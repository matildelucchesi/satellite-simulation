"""Paired continuous sessions on one immutable, conservatively admitted schedule."""
import copy
import csv
import hashlib
import html
import json
import uuid
from dataclasses import replace
from pathlib import Path

from .artifacts import canonical_bytes, describe, file_digest
from .planner import Planner, OrbitIndex, ScenarioRejected, validate_parameters as session_parameters
from .preconditions import calibration_inputs
from .results import requires_recovery, summary_metrics
from .simulation import Simulation
from .storage import atomic_json, utc_now

POLICY = 'continuous-paired-service-v3'
METRICS = ('controller_downtime_s', 'total_operation_s', 'service_verification_s', 'ping_recovery_s', 'attempt')


def bundle_identity(item):
    evidence=item if 'sha256' in item and 'bytes' in item else describe(Path(item['path']))
    return {key:evidence[key] for key in ('sha256','bytes')}


def validate_parameters(parameters):
    defaults = {'duration_s':3600, 'rate_bps':1000000000, 'start_orbital_s':None,
                'initial_satellite_id':None, 'max_migrations':None,
                'migration_count':None, 'additional_data_bytes':0,
                'selection_rates':None,'selection_id':None}
    if set(parameters)-set(defaults):
        raise ValueError('Unsupported continuous comparison parameter')
    defaults.update(parameters)
    if not any(key in parameters for key in ('migration_count','duration_s')):defaults['migration_count']=3
    rates=defaults.pop('selection_rates');identifier=defaults.pop('selection_id')
    if rates is not None and (not isinstance(rates,list) or not rates or
            any(isinstance(rate,bool) or rate not in (100000000,1000000000,10000000000) for rate in rates)
            or defaults['rate_bps'] not in rates):raise ValueError('Invalid selection rates')
    if identifier is not None and (not isinstance(identifier,str) or len(identifier)!=37 or
            not identifier.startswith('pair-') or any(c not in '0123456789abcdef' for c in identifier[5:])):
        raise ValueError('Invalid selection identity')
    count=defaults.pop('migration_count')
    if count is not None and (isinstance(count,bool) or not isinstance(count,int) or not 1 <= count <= 100):
        raise ValueError('Invalid migration count')
    if count is not None and defaults['max_migrations'] not in (None,count):
        raise ValueError('Conflicting migration limits')
    checked = session_parameters({**defaults,'duration_s':1} if count is not None else defaults)
    result={key:checked[key] for key in defaults}
    result['migration_count']=count
    if rates is not None:result['selection_rates']=sorted(set(rates))
    if identifier is not None:result['selection_id']=identifier
    if count is not None:result['duration_s']=None
    return result


def comparison_directory(root, identifier):
    if (len(identifier) != 37 or not identifier.startswith('pair-')
            or any(c not in '0123456789abcdef' for c in identifier[5:])):
        raise ValueError('Invalid continuous comparison identifier')
    directory = root/'results/continuous-comparisons'/identifier
    if not (directory/'metadata.json').is_file():
        raise FileNotFoundError(identifier)
    return directory


class SharedPlanner(Planner):
    def additional_opportunities(self):
        return (start for start,end in self.index.service_periods())

    def ranked(self, source, tick, operation_s, end):
        self.check()
        if self.index.service_contact_end(tick)<tick+operation_s:
            self.rejections['service_path_window']=self.rejections.get('service_path_window',0)+1
            return [],[{'reason':'service_path_window','orbital_s':tick}]
        return super().ranked(source,tick,operation_s,end)

    def estimate(self, method, rate):
        estimates = [super(SharedPlanner,self).estimate(mode,rate) for mode in ('hot','cold')]
        recovery = max(row[1] for row in estimates)
        # A shared arrival includes the 30 s service gate and source cleanup reserve.
        # This deliberately rejects sequences that are feasible for only one mode.
        return max(row[0] for row in estimates)+30+recovery, recovery


def shared_plan(planner, parameters):
    resources={**planner.resources,'disk_gib':planner.resources['disk_gib']+parameters.get('additional_data_bytes',0)/1024**3}
    common = SharedPlanner(planner.orbit,planner.index,planner.scenario,
        {'horizon_s':planner.horizon,'manifest_resources':resources},
        replace(planner.workload,image_bytes=planner.workload.image_bytes+parameters.get('additional_data_bytes',0)),
        cancel=planner.cancel,publish=planner.publish)
    planner.rejections = common.rejections
    common.check = planner.check
    count=parameters.get('migration_count')
    session={key:value for key,value in parameters.items() if key not in ('migration_count','selection_rates','selection_id')}
    if count is not None:
        start=session['start_orbital_s'] if session['start_orbital_s'] is not None else 0
        session.update(start_orbital_s=start,duration_s=planner.orbit.duration-start)
    plan = common.plan({**session,'method':'hot','max_migrations':count},minimum_migrations=count or 1)
    if count is not None:
        last=plan['migrations'][-1]
        operation,recovery=common.estimate('hot',parameters['rate_bps'])
        plan.update(end_s=min(last['deadline_s'],last['trigger_s']+operation+recovery),
                    stop_after_schedule=True,target_migrations=count)
    if parameters.get('max_migrations') is not None and len(plan['migrations'])>parameters['max_migrations']:
        raise ScenarioRejected('Shared duration requires more migrations than the requested limit')
    plan['policy_version'] = POLICY
    plan['methods'] = ['hot','cold']
    plan['service_verification_reserve_s'] = 30
    plan['trigger_tolerance_s'] = 1
    plan['service_path_policy'] = 'continuous geometric path during each planned operation, including service verification'
    plan['service_endpoints'] = [53848,53913]
    for index,event in enumerate(plan['migrations']):
        event['service_path_end_s']=common.index.service_contact_end(event['trigger_s'])
        following = plan['migrations'][index+1]['trigger_s'] if index+1<len(plan['migrations']) else plan['end_s']
        # LiveBackend subtracts the source rollback reserve from this deadline.
        # Successful work must finish by the next trigger; a failed comparison
        # may use the source reserve without executing that next event.
        limit = following+event['recovery_reserve_s'] if index+1<len(plan['migrations']) else following
        event['deadline_s'] = min(event['deadline_s'], limit)
    return plan


def reconcile_recovery(app, previous_job_id, recovery):
    """Conclude a composite record when its active child was recovered after a crash."""
    for path in (app.root/'results/continuous-comparisons').glob('pair-*/metadata.json'):
        document=json.loads(path.read_text())
        if document.get('job_id') != previous_job_id:
            continue
        coordinator=ContinuousComparison(app)
        coordinator.result=document
        coordinator.directory=path.parent
        for method,identifier in document['sessions'].items():
            child=app.root/'results/simulations'/identifier/'metadata.json'
            if child.exists():
                coordinator.collect(method,json.loads(child.read_text()))
        document.update(phase='finished',outcome='recovery_required' if requires_recovery(recovery) else 'interrupted',
            complete=False,success=False,current_method=None,finished_utc=utc_now(),
            recovery_required=requires_recovery(recovery),recovery=recovery,
            reason='Esecuzione interrotta; recupero del laboratorio eseguito. Avviare un nuovo confronto.')
        coordinator.save()


class ContinuousComparison:
    def __init__(self, app, *, planner=None, session_factory=None):
        self.app, self.root, self.planner = app, app.root, planner
        self.session_factory = session_factory or (lambda:Simulation(app,planner=self.planner))
        self.calibration = self.manifest = None

    def check(self):
        if self.app.cancel and self.app.cancel.is_set():
            raise InterruptedError('Confronto interrotto')

    def selection_identity(self):
        from .simulation import engine_fingerprint
        return {'scenario_sha256':hashlib.sha256(canonical_bytes(self.app.scenario)).hexdigest(),
            'calibration_sha256':hashlib.sha256(canonical_bytes(self.calibration)).hexdigest(),
            'manifest_sha256':hashlib.sha256(canonical_bytes(self.manifest)).hexdigest(),
            'engine_sha256':engine_fingerprint(self.root) if (self.root/'config/scenario.json').exists() else None,
            'frozen_files':{name:file_digest(self.root/name) for name in
                ('results/calibration.json','config/artifact_manifest.json','results/direct_link_windows.json',
                 'artifacts/orbit/replay.npz') if (self.root/name).exists()},
            'image_bundle_identity':bundle_identity(self.app.bundle()['image_bundle'])}

    def automatic_plan(self, parameters):
        from .automatic_start import select_start, SelectionInvalidated
        identity=self.selection_identity()
        if parameters.get('selection_id'):
            origin=comparison_directory(self.root,parameters['selection_id'])
            selection=json.loads((origin/'selection.json').read_text())
            if selection['identity']!=identity:raise SelectionInvalidated('La selezione congelata non è compatibile con gli input correnti')
            if selection['migration_count']!=parameters['migration_count'] or selection['additional_data_bytes']!=parameters['additional_data_bytes']:
                raise SelectionInvalidated('I parametri non coincidono con la selezione congelata')
        else:
            evidence,plans=select_start(self.planner,parameters,parameters.get('selection_rates'),
                budget_s=self.app.scenario.get('live',{}).get('departure_search_budget_s',600))
            selection={**evidence,'identity':identity,'migration_count':parameters['migration_count'],
                'additional_data_bytes':parameters['additional_data_bytes'],'plans':plans,
                'plan_hashes':{rate:hashlib.sha256(canonical_bytes(plan)).hexdigest() for rate,plan in plans.items()}}
        rate=str(parameters['rate_bps'])
        if rate not in selection['plans']:raise SelectionInvalidated('Velocità non inclusa nella selezione congelata')
        plan=copy.deepcopy(selection['plans'][rate])
        if hashlib.sha256(canonical_bytes(plan)).hexdigest()!=selection['plan_hashes'][rate]:
            raise SelectionInvalidated('Piano della selezione alterato')
        if (selection['selected']['initial_satellite_id']!=plan['initial_satellite_id'] or
                selection['selected']['start_orbital_s']!=plan['start_s']):
            raise SelectionInvalidated('La configurazione risolta non coincide con il piano congelato')
        self.selection_context=identity
        self.result['selection']={key:value for key,value in selection.items() if key!='plans'}
        self.result['resolved_configuration']=selection['selected']
        atomic_json(self.directory/'selection.json',selection)
        self.save()
        return plan

    def save(self):
        job_id = self.result.get('job_id')
        progress = self.root/'results/jobs'/job_id/'progress.json' if job_id else None
        if progress and progress.exists(): self.result['progress'] = json.loads(progress.read_text())
        atomic_json(self.directory/'metadata.json',self.result)
        self.write_report()

    def stage(self, phase, method=None):
        self.result.update(phase=phase,current_method=method)
        self.save()
        self.app.publish({'phase':'continuous_comparison','comparison_phase':phase,
                          'comparison_id':self.identifier,'method':method})

    def prepare(self):
        if self.planner:
            return
        try:
            self.calibration,self.manifest = calibration_inputs(self.root,full=True)
        except (ValueError,FileNotFoundError):
            self.stage('preparation')
            functional = self.root/'results/functional-gate.json'
            if not functional.exists() or not json.loads(functional.read_text()).get('complete'):
                self.check()
                gate = self.app.functional()
                self.result['preparation'].append({'stage':'functional','complete':gate.get('complete',False),
                    'recovery_required':requires_recovery(gate),'reason':gate.get('reason')})
                if not gate.get('complete') or requires_recovery(gate):
                    self.result['error'] = gate.get('error')
                    raise ScenarioRejected('Verifica iniziale Hot/Cold non riuscita: '+str(gate.get('reason','servizio non valido')))
            self.check()
            self.stage('calibration')
            calibration = self.app.calibrate()
            self.result['preparation'].append({'stage':'calibration','complete':calibration.get('complete',False),
                'recovery_required':requires_recovery(calibration),'reason':calibration.get('reason')})
            if not calibration.get('complete') or requires_recovery(calibration):
                self.result['error'] = calibration.get('error')
                self.result['cleanup_verified'] = calibration.get('cleanup_verified',False)
                raise ScenarioRejected('Calibrazione non riuscita: '+str(calibration.get('reason','misure incomplete')))
            self.check()
            self.calibration,self.manifest = calibration_inputs(self.root,full=True)
        atomic_json(self.directory/'calibration.json',self.calibration)
        atomic_json(self.directory/'artifact-manifest.json',self.manifest)
        calibration = copy.deepcopy(self.calibration)
        calibration['manifest_resources'] = {key:self.manifest['resources']['measured_controller_'+key]
                                             for key in ('cpu_cores','ram_gib','disk_gib')}
        windows = json.loads((self.root/'results/direct_link_windows.json').read_text())['windows']
        self.planner = Planner(self.app.orbit,OrbitIndex(self.app.orbit,windows),self.app.scenario,
            calibration,self.app.workload(self.manifest),cancel=self.app.cancel,publish=self.app.publish)

    def child_created(self, method, identifier):
        self.result['sessions'][method] = identifier
        directory = self.root/'results/simulations'/identifier
        if self.calibration is not None:
            atomic_json(directory/'calibration.json',self.calibration)
            atomic_json(directory/'artifact-manifest.json',self.manifest)
        self.save()
        self.app.publish({'phase':'comparison_session','comparison_id':self.identifier,
                          'simulation_id':identifier,'method':method})

    def collect(self, method, result):
        self.result['session_results'][method] = {'simulation_id':result['simulation_id'],
            'success':result.get('success',False),'outcome':result.get('outcome'),
            'real_elapsed_s':result.get('real_elapsed_s'),'recovery_required':requires_recovery(result),
            'failure_reason':result.get('failure_reason')}
        if result.get('report_error'):self.result['session_results'][method]['report_error']=result['report_error']
        if result.get('error'): self.result['error'] = result['error']
        report_file = self.root/'results/simulations'/result['simulation_id']/'report.json'
        report = json.loads(report_file.read_text()) if report_file.exists() else {}
        summaries = {row['migration_id']:row for row in report.get('migration_summary',[])}
        by_event = {row['event']['event_id']:row for row in result['migrations']}
        for row in self.result['events']:
            migration = by_event.get(row['event_id'])
            if migration is None:
                continue
            metrics = {**summary_metrics(migration),**summaries.get(migration['migration_id'],{})}
            row[method] = {'success':migration.get('success',False),'outcome':migration.get('outcome'),
                'migration_id':migration.get('migration_id'),
                'simulation_id':result.get('simulation_id'),
                'experimental_valid':migration.get('experimental_valid'),
                'observation_complete':migration.get('observation_complete'),
                'plan_verified':result.get('shared_plan_sha256') == self.result['shared_plan_sha256'],
                'failure_reason':migration.get('failure_reason'),
                **{key:metrics.get(key) for key in METRICS}}
            hot,cold = row.get('hot'),row.get('cold')
            row['comparable'] = bool(hot and cold and all(item['success'] and item['plan_verified']
                and item['experimental_valid'] is True and item['observation_complete'] is True for item in (hot,cold)))
            row['exclusion_reason'] = None if row['comparable'] else 'Misure valide e piano identico richiesti per entrambe le modalità'
            row['cold_minus_hot'] = {key:cold[key]-hot[key]
                if row['comparable'] and hot[key] is not None and cold[key] is not None else None
                for key in METRICS} if hot and cold else None
        accepted = self.result['session_results'][method]['success']
        rows = [row[method] for row in self.result['events'] if row.get(method)]
        self.result['totals'][method] = {'completed_migrations':sum(row['success'] for row in rows),
            'attempted_migrations':len(result['migrations']),
            'real_elapsed_s':result.get('real_elapsed_s'),
            **{key:sum(row[key] for row in rows) if accepted and len(rows)==len(self.result['events'])
                and all(row[key] is not None for row in rows) else None
                for key in ('controller_downtime_s','total_operation_s')}}
        if (all(self.result['session_results'].get(mode,{}).get('success') for mode in ('hot','cold'))
                and all(row.get('comparable') for row in self.result['events'])):
            self.result['totals']['cold_minus_hot'] = {key:
                self.result['totals']['cold'][key]-self.result['totals']['hot'][key]
                if self.result['totals']['hot'][key] is not None and self.result['totals']['cold'][key] is not None else None
                for key in ('controller_downtime_s','total_operation_s','real_elapsed_s')}

    def capture_unreturned_children(self):
        """A reporting/worker exception must not erase an active child's recovery flag."""
        safe_children=set()
        for method,identifier in self.result['sessions'].items():
            try:
                child=json.loads((self.root/'results/simulations'/identifier/'metadata.json').read_text())
                if method not in self.result['session_results']:
                    self.collect(method,child)
                safe=(child.get('phase')=='finished' and
                      (child.get('controllers_fenced') is True or child.get('outcome')=='rejected')
                      and not requires_recovery(child))
                if safe:
                    safe_children.add(identifier)
                else:
                    self.result['recovery_required']=True
            except (OSError,ValueError,KeyError):
                self.result['recovery_required']=True
        checkpoint_path=getattr(getattr(self.app,'checkpoint',None),'path',None)
        if self.result['sessions'] and len(safe_children)==len(self.result['sessions']):
            self.result['cleanup_verified']=True
        if checkpoint_path and checkpoint_path.exists():
            checkpoint=json.loads(checkpoint_path.read_text())
            if checkpoint.get('kind') in ('run','simulation') and checkpoint.get('simulation_id') not in safe_children:
                self.result['recovery_required']=True

    def run(self, parameters):
        parameters = validate_parameters(parameters)
        self.identifier = 'pair-'+uuid.uuid4().hex
        self.directory = self.root/'results/continuous-comparisons'/self.identifier
        self.directory.mkdir(parents=True)
        self.result = {'schema_version':1,'comparison_id':self.identifier,
            'job_id':getattr(self.app,'job_id',None),'created_utc':utc_now(),'parameters':parameters,
            'policy_version':POLICY,'phase':'planning','current_method':None,'outcome':'running',
            'success':False,'complete':False,'sessions':{},'session_results':{},'preparation':[],
            'events':[],'totals':{},'shared_plan_sha256':None,'reason':None}
        self.save()
        try:
            self.check()
            self.prepare()
            self.check()
            self.stage('planning')
            # Explicit coordinates remain internal for historical fixtures only;
            # all public entrypoints reject them before creating a job.
            plan = (shared_plan(self.planner,parameters) if parameters['initial_satellite_id'] is not None
                    or parameters['start_orbital_s'] is not None else self.automatic_plan(parameters))
            plan['image_bundle_identity']=bundle_identity(self.app.bundle()['image_bundle'])
            plan['scenario_sha256']=hashlib.sha256(canonical_bytes(self.app.scenario)).hexdigest()
            fixture=self.root/'config/fixture.json'
            plan['fixture_sha256']=file_digest(fixture) if fixture.exists() else None
            digest = hashlib.sha256(canonical_bytes(plan)).hexdigest()
            atomic_json(self.directory/'plan.json',plan)
            self.result.update(shared_plan_sha256=digest,start_s=plan['start_s'],end_s=plan['end_s'],
                events=[{key:event[key] for key in ('event_id','sat_a','sat_b','trigger_s')}
                        for event in plan['migrations']])
            for method in ('hot','cold'):
                self.check()
                if hasattr(self,'selection_context') and self.selection_identity()!=self.selection_context:
                    from .automatic_start import SelectionInvalidated
                    raise SelectionInvalidated('Gli input della selezione sono cambiati; confronto fermato')
                self.stage(method,method)
                session = self.session_factory()
                session_parameters={key:value for key,value in parameters.items() if key not in ('migration_count','selection_rates','selection_id')}
                child = session.run({**session_parameters,'duration_s':plan['end_s']-plan['start_s'],
                    'method':method,'start_orbital_s':plan['start_s'],
                    'initial_satellite_id':plan['initial_satellite_id']}, fixed_plan=copy.deepcopy(plan),
                    comparison_id=self.identifier,plan_sha256=digest,
                    on_created=lambda identifier,mode=method:self.child_created(mode,identifier))
                self.collect(method,child)
                self.save()
                if not child.get('success') or not child.get('complete') or requires_recovery(child):
                    raise ScenarioRejected(method.upper()+': '+str(child.get('failure_reason') or child.get('outcome')))
                if method == 'hot':
                    self.stage('resetting')
            self.check()
            if not all(row.get('comparable') for row in self.result['events']):
                raise ScenarioRejected('Confronto privo di misure valide sullo stesso piano per tutti gli eventi')
            if any(row.get('report_error') for row in self.result['session_results'].values()):
                raise RuntimeError('Misure conservate, ma esportazione di una sessione incompleta')
            self.result.update(success=True,complete=True,outcome='success')
        except Exception as exc:
            self.capture_unreturned_children()
            from .automatic_start import SelectionRejected, SelectionInvalidated
            if isinstance(exc,SelectionRejected):
                self.result['selection']=exc.evidence
                atomic_json(self.directory/'selection.json',exc.evidence)
            if self.result['phase']=='planning' and not self.result['sessions'] and isinstance(exc,ScenarioRejected):
                self.result['error']={'code':('selection_invalidated' if isinstance(exc,SelectionInvalidated) else 'departure_search_incomplete' if isinstance(exc,SelectionRejected) and not exc.evidence['exhaustive'] else 'plan_not_admissible'),'phase':'planning',
                    'message':str(exc) if isinstance(exc,(SelectionRejected,SelectionInvalidated)) else 'Non esiste una sequenza sicura per il confronto con la configurazione richiesta.',
                    'rejections':dict(self.planner.rejections) if self.planner else {},
                    'parameters':dict(parameters),'technical_detail':str(exc)}
                self.result['session_execution_started']=False
            self.result.update(reason=str(exc),outcome='interrupted' if self.app.cancel and self.app.cancel.is_set()
                               or isinstance(exc,InterruptedError) else 'failed')
        finally:
            self.result['recovery_required'] = requires_recovery(self.result)
            if self.result['recovery_required']:
                self.result.update(outcome='recovery_required',success=False,complete=False)
            self.result.update(phase='finished',finished_utc=utc_now(),current_method=None)
            self.app.publish({'phase':'comparison_finished','comparison_id':self.identifier,
                              'outcome':self.result['outcome']})
            self.save()
        return self.result

    def write_report(self):
        fields = ['event_id','sat_a','sat_b','trigger_s','hot_success','cold_success',
                  'hot_controller_downtime_s','cold_controller_downtime_s','cold_minus_hot_s',
                  'comparable','exclusion_reason','shared_plan_sha256',
                  'hot_service_verification_s','cold_service_verification_s','hot_ping_recovery_s','cold_ping_recovery_s']
        with (self.directory/'events.csv').open('w',encoding='utf-8',newline='') as handle:
            writer = csv.DictWriter(handle,fields)
            writer.writeheader()
            for row in self.result['events']:
                hot,cold = row.get('hot') or {},row.get('cold') or {}
                writer.writerow({**{key:row[key] for key in fields[:4]},'hot_success':hot.get('success'),
                    'cold_success':cold.get('success'),'hot_controller_downtime_s':hot.get('controller_downtime_s'),
                    'cold_controller_downtime_s':cold.get('controller_downtime_s'),
                    'comparable':row.get('comparable',False),'exclusion_reason':row.get('exclusion_reason'),
                    'shared_plan_sha256':self.result['shared_plan_sha256'],
                    **{mode+'_'+metric:(row.get(mode) or {}).get(metric) for mode in ('hot','cold')
                       for metric in ('service_verification_s','ping_recovery_s')},
                    'cold_minus_hot_s':(row.get('cold_minus_hot') or {}).get('controller_downtime_s')})
        def value(item):
            return html.escape(str(item)) if item is not None else '—'
        rows = ''.join('<tr>'+''.join('<td>'+value(item)+'</td>' for item in (
            row['event_id'],row['sat_a'],row['sat_b'],row['trigger_s'],
            (row.get('hot') or {}).get('controller_downtime_s'),
            (row.get('cold') or {}).get('controller_downtime_s'),
            (row.get('cold_minus_hot') or {}).get('controller_downtime_s'),
            (row.get('hot') or {}).get('ping_recovery_s'),(row.get('cold') or {}).get('ping_recovery_s'),
            row.get('comparable',False),row.get('exclusion_reason')) )+'</tr>'
            for row in self.result['events'])
        termination=(str(self.result['parameters']['migration_count'])+' migrazioni verificate per modalità'
                     if self.result['parameters'].get('migration_count') else
                     'Durata per modalità: '+value(self.result['parameters']['duration_s'])+' s')
        document = ('<!doctype html><html lang="it"><meta charset="utf-8"><title>Confronto continuo Hot/Cold</title>'
            '<h1>Confronto continuo Hot/Cold</h1><p>Esito: '+value(self.result['outcome'])+
            '</p><p>'+value(self.result.get('reason'))+'</p><p>Piano condiviso SHA-256: '+
            value(self.result['shared_plan_sha256'])+'</p><p>'+termination+
            '. Sequenza fissa, senza ripianificazione.</p><p>Dati aggiuntivi per migrazione: '+
            value(self.result['parameters'].get('additional_data_bytes',0))+' byte.</p>'
            '<table border="1"><tr><th>Evento</th><th>Sorgente</th><th>Destinazione</th><th>Trigger (s)</th>'
            '<th>Downtime Hot (s)</th><th>Downtime Cold (s)</th><th>Cold − Hot (s)</th>'
            '<th>Ripristino forwarding Hot (s)</th><th>Ripristino forwarding Cold (s)</th>'
            '<th>Confrontabile</th><th>Esclusione</th></tr>'+rows+
            '</table><p>Valori mancanti: —. Differenze solo per eventi validi in entrambe le modalità. '
            'Il downtime del controller è distinto dal ripristino del forwarding misurato dalle sonde.</p>'
            '<h2>Totali</h2><pre>'+html.escape(json.dumps(self.result['totals'],indent=2))+'</pre></html>')
        document = document.replace('</html>', '<h2>Provenienza e diagnostica</h2><pre>'+html.escape(json.dumps(
            {key:self.result.get(key) for key in ('comparison_id','parameters','resolved_configuration','selection','sessions','progress','error','preparation')},
            indent=2,ensure_ascii=False))+'</pre><p>Orbite e FSO modellati; API, TCP, P4 e sonde misurati live. '
            'Le calibrazioni sono stime conservative, non i risultati di questo confronto.</p></html>')
        error=self.result.get('error') or {}
        if error:
            document=document.replace('<h2>Provenienza e diagnostica</h2>',
                '<h2>Diagnosi</h2><p>'+value(error.get('message'))+'</p><p>'+value(error.get('label'))+
                ': '+value(error.get('elapsed_s'))+' s; limite '+value(error.get('limit_s'))+' s.</p><p>'+
                value(error.get('recovery_hint'))+'</p><h2>Provenienza e diagnostica</h2>')
        (self.directory/'report.html').write_text(document,encoding='utf-8')
