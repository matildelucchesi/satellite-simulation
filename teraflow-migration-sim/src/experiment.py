"""Shared application operations. No modeled operation is labeled live."""
from __future__ import annotations
import csv
import json
import time
import uuid
from pathlib import Path

from .artifacts import canonical_bytes, describe, file_digest, verify_artifact
from .clock import LiveClock
from .live_backend import LiveBackend, http
from .measurements import disk_content
from .orbit import Orbit, lab_graph, load_orbit, shortest_paths
from .fixture import service_endpoints
from .orchestrator import Migration
from .probes import analyze_directory, classify_observations, json_lines, ping_observations
from .storage import append_json, atomic_json, utc_now
from .preparation import Preparation
from .analysis import Analysis
from .results import finalize, requires_recovery, summary_metrics, transfer_metrics
from .handover import execute as execute_handover


class Experiment(Preparation, Analysis):
    def prepare_base(self):
        """One explicit scenario-creation job owns preliminary measurements and base planning."""
        from .common_base import prepare
        from .preconditions import calibration_inputs
        try:calibration_inputs(self.root,full=False)
        except (ValueError,OSError):
            self.prepare_calibration_network()
            path=self.root/'results/functional-gate.json'
            try:gate=json.loads(path.read_text(encoding='utf-8'))
            except (ValueError,OSError):gate={}
            valid=gate.get('complete') and len(gate.get('runs',[]))==2 and all(
                (self.root/'results/runs'/row['run_id']/'metadata.json').exists() for row in gate['runs'])
            if not valid:
                self.publish({'phase':'scenario_creation','label':'Verifica preliminare del laboratorio'})
                gate=self.functional()
                if not gate.get('complete') or requires_recovery(gate):return {**gate,'complete':False}
            if self.cancel and self.cancel.is_set():raise InterruptedError('Creazione scenario interrotta')
            self.publish({'phase':'scenario_creation','label':'Calibrazione Cold/Hot sulla rete predisposta'})
            calibration=self.calibrate()
            if not calibration.get('complete') or requires_recovery(calibration):return {**calibration,'complete':False}
        if self.cancel and self.cancel.is_set():raise InterruptedError('Creazione scenario interrotta')
        self.publish({'phase':'scenario_creation','label':'Preparazione della base comune'})
        from .prepared_source import prepare as prepare_source
        return prepare_source(self, prepare(self))

    def expand_constellation(self):
        from .constellation import expand
        return expand(self)

    def prepare_calibration_network(self):
        """Build the full inventory once, before functional/calibration trials."""
        if getattr(self, '_calibration_network_ready', False):
            return
        if (self.root/'config/campaign-manifest.json').exists():
            raise ValueError('Campaign is frozen; archive it explicitly before recalibration')
        directory = self.root/'results/network-preparations'/('network-'+uuid.uuid4().hex)
        backend = LiveBackend(self.root, directory, self.functional_event(), 1000000000,
                              self.orbit, self.scenario, self.cancel, notify=self.publish)
        self.checkpoint(kind='between_runs', phase='network_preparation')
        self.publish({'phase':'scenario_creation','label':'Creazione della rete completa prima della calibrazione'})
        try:
            backend.reset()
            baseline = backend.establish_baseline(directory.name)
            if not baseline.get('success'):
                raise RuntimeError('Baseline della rete di calibrazione non valida')
            backend.check()
            atomic_json(directory/'ready.json', {'ready':True, 'baseline':baseline})
        except Exception:
            backend.shutdown()
            raise
        finally:
            backend.close()
        self._calibration_network_ready = True

    def __init__(self, root, cancel=None, publish=None):
        self.root = Path(root).resolve()
        self.cancel = cancel
        self.publish = publish or (lambda event: None)
        self.scenario = json.loads((self.root/'config/scenario.json').read_text())
        self._orbit = None
        self.checkpoint = lambda **context: None

    @property
    def orbit(self):
        if self._orbit is None: self._orbit = load_orbit(self.root, self.scenario)
        return self._orbit

    def bundle(self):
        path = self.root/'artifacts/images-l2-patched-v3/bundle.json'
        manifest = json.loads(path.read_text())
        verify_artifact(manifest['image_bundle'])
        for name in ('local_patch','device_patch'):
            patch = manifest.get(name)
            if patch: verify_artifact(patch['manifest'])
        return manifest

    def recover(self, previous_job_id):
        """Explicit recovery of a dead worker, never automatic reassignment."""
        from datetime import datetime, timezone
        from .live_backend import Compose
        directory=self.root/'results/jobs'/previous_job_id
        events=list(json_lines(directory/'events.jsonl'))
        checkpoint_path=directory/'active-checkpoint.json'
        checkpoint=json.loads(checkpoint_path.read_text()) if checkpoint_path.exists() else None
        identifiers={(('simulation' if row.get('simulation_id') else 'run'),
            row.get('simulation_id') or row.get('run_id')) for row in events
            if row.get('simulation_id') or row.get('run_id')}
        if checkpoint is None and len(identifiers)==1:
            kind,identifier=next(iter(identifiers))
            checkpoint={'kind':kind,kind+'_id':identifier}
        http(18091,'/revoke',{})
        compose=Compose(self.root)
        http(18090,'/probes/stop',{})
        if checkpoint and checkpoint.get('kind')=='between_runs':
            compose.stop('sat-a');compose.stop('sat-b')
            output={'complete':True,'recovery_required':False,'controllers_fenced':True,'between_runs':True}
            job=json.loads((directory/'job.json').read_text());job.update(status='recovered',recovery=output)
            atomic_json(directory/'job.json',job)
            return output
        if not checkpoint or checkpoint.get('kind') not in ('run','simulation'):
            compose.stop('sat-a');compose.stop('sat-b')
            return {'complete':False,'recovery_required':True,'outcome':'recovery_required',
                'controllers_fenced':True,'reason':'No unambiguous active child checkpoint; inspect the laboratory explicitly'}
        simulation_id=checkpoint.get('simulation_id') if checkpoint['kind']=='simulation' else None
        if simulation_id:
            from .simulation import simulation_directory
            from .simulation_report import report
            simulation=simulation_directory(self.root,simulation_id)
            compose.stop('sat-a');compose.stop('sat-b')
            metadata=json.loads((simulation/'metadata.json').read_text())
            metadata.update(phase='finished',outcome='worker_lost',success=False,complete=False,
                controllers_fenced=True,finished_utc=utc_now(),
                failure_reason='Worker lost; authority revoked and both workloads stopped. Clock was not resumed.')
            atomic_json(simulation/'metadata.json',metadata)
            report(simulation,self.root)
            output={'complete':True,'controllers_fenced':True,'simulation_id':simulation_id,'clock_resumed':False}
            job=json.loads((directory/'job.json').read_text());job.update(status='recovered',recovery=output)
            atomic_json(directory/'job.json',job)
            return output
        run_id=checkpoint.get('run_id')
        compose.stop('sat-b')
        if not run_id:raise RuntimeError('No run evidence; controllers fenced, manual perimeter inspection required')
        run_dir=self.root/'results/runs'/run_id
        event=json.loads((run_dir/'inputs.json').read_text())['event']
        timed=[row for row in events if row.get('run_id')==run_id and row.get('orbital_s') is not None]
        if checkpoint.get('orbital_s') is not None: timed.append(checkpoint)
        if not timed:
            timed=list(json_lines(run_dir/'geometry.jsonl'))
        if timed:
            latest=timed[-1]
            elapsed=(time.time()-latest['unix_s']) if 'unix_s' in latest else (datetime.now(timezone.utc)-datetime.fromisoformat(latest['timestamp_utc'])).total_seconds()
            orbital=latest['orbital_s']+max(0,elapsed)
        else:
            compose.stop('sat-a')
            # Without a trustworthy clock, terminate the old run; never restore an expired source.
            metadata_path=run_dir/'metadata.json'
            metadata=json.loads(metadata_path.read_text()) if metadata_path.exists() else {'run_id':run_id}
            atomic_json(run_dir/'pre-fenced-recovery.json',metadata)
            metadata.update(success=False,outcome='interrupted',interrupted=True,recovery_required=False,
                controllers_fenced=True,finished_utc=utc_now(),
                failure_reason='Explicit recovery terminated the run without resuming an untrusted clock')
            atomic_json(metadata_path,metadata)
            output={'complete':True,'recovery_required':False,'controllers_fenced':True,
                'run_id':run_id,'clock_resumed':False,'source_restored':False,'aborted_without_clock':True}
            job=json.loads((directory/'job.json').read_text());job.update(status='recovered',recovery=output)
            atomic_json(directory/'job.json',job)
            return output
        if orbital>=event['deadline_s']:
            compose.stop('sat-a')
            output={'complete':True,'recovered':False,'source_expired':True,'controllers_fenced':True,
                'previous_job_id':previous_job_id,'orbital_s':orbital}
        else:
            from .tfs_adapter import TfsAdapter
            paths=sorted((run_dir/'operation').glob('snapshot-*.json'))
            if not paths and (run_dir/'prepared-snapshot.json').exists():paths=[run_dir/'prepared-snapshot.json']
            if not paths:raise RuntimeError('No verified source snapshot; explicit fixture reconstruction required')
            snapshot=json.loads(paths[-1].read_text())
            compose.start('sat-a')
            # Keep hardware fenced while restoring the saved NBI state.
            adapter=TfsAdapter('http://127.0.0.1:18080')
            try:
                adapter.reconcile(snapshot)
                verification=adapter.verify(snapshot)
                if not verification['equivalent']:raise RuntimeError('Recovery API equivalence failed')
                http(18091,'/recover',{})
            except Exception:
                http(18091,'/revoke',{});raise
            output={'complete':True,'recovered':True,'previous_job_id':previous_job_id,'orbital_s':orbital,
                'verification':verification,'authority':http(18091)}
        job=json.loads((directory/'job.json').read_text());job.update(status='recovered',recovery=output)
        atomic_json(directory/'job.json',job)
        return output

    def environment(self):
        status = {'timestamp_utc': utc_now(), 'success': False, 'execution_kind': 'live'}
        try:
            from .live_backend import Compose
            from .transport import Receiver, transfer
            import subprocess, shutil, platform
            compose=Compose(self.root)
            compose.start('sat-a');compose.start('sat-b')
            status['mininet'] = http(18090)
            status['proxy'] = http(18091)
            status['controllers'] = {}
            from urllib.request import urlopen
            for role, port in [('sat-a',18080),('sat-b',18081)]:
                with urlopen(f'http://127.0.0.1:{port}/healthz',timeout=5) as response:
                    status['controllers'][role] = response.status == 200
            status['bundle'] = self.bundle()['image_bundle']
            status['docker_info']=json.loads(subprocess.check_output(['docker','info','--format','{{json .}}'],
                cwd=self.root,text=True,timeout=30))
            status['host']={'platform':platform.platform(),'python':platform.python_version(),
                'disk_free_bytes':shutil.disk_usage(self.root).free}
            capacity_directory=self.root/'results/capacity'
            status['transport_capacity']=[]
            with Receiver(capacity_directory) as receiver:
                for rate in self.scenario['fso']['useful_throughput_bps']:
                    if self.cancel and self.cancel.is_set():raise InterruptedError('Capacity check interrupted')
                    self.publish({'phase':'transport_capacity','configured_rate_bps':rate})
                    receipt=transfer(Path(status['bundle']['path']),receiver.address,rate,
                        link=lambda:not(self.cancel and self.cancel.is_set()))
                    receipt['supported']=receipt['useful_throughput_bps']>=.9*rate
                    status['transport_capacity'].append(receipt)
                    Path(receipt['path']).unlink()
            status['capacity_checked']=True
            status['success'] = (status['mininet']['switch_count'] == len(json.loads((self.root/'config/fixture.json').read_text())['emulator']['devices']) and status['mininet']['switches_alive']
                and all(status['controllers'].values())
                and all(row['upstream_master'] for row in status['proxy']['states']))
        except Exception as exc: status['error'] = str(exc)
        atomic_json(self.root/'results/environment.json',status)
        return status

    def catalog_event(self, selected, prefix, causes, purpose):
        """Live event from a frozen catalogue entry: shadow entry is the deadline, the multi-hop path the link."""
        source, target, tick = selected['source'], selected['destination'], selected['trigger_s']
        path_end = selected.get('path_end_s') or self.orbit.duration
        return {'event_id':f'{prefix}-{source}-{target}-{tick}', 'sat_a':source, 'sat_b':target, 'trigger_s':tick,
            'deadline_s':selected['source_shadow_entry_s'], 'trigger_causes':causes,
            'contact_window_s':path_end-tick, 'deadline_window_s':selected['source_shadow_entry_s']-tick,
            'contact_end_s':path_end, 'path':selected['path'], 'hops':selected['hops'],
            'catalog_event_id':selected['event_id'], 'execution_purpose':purpose}

    def compare_events(self):
        """Phase 3: Hot and Cold on each selected catalogue event, order alternated between events.

        Every run starts from the same orbital instant of its event. The comparison stops at the
        first run that fails or needs recovery; missing measures stay missing."""
        from .event_comparison import compare
        return compare(self)

    def functional_event(self):
        catalog = self.root/'config/migration_events.json'
        if catalog.exists():
            # Laser profile: the first selected event of the frozen catalogue (multi-hop path).
            selected = json.loads(catalog.read_text())['selected'][0]
            return self.catalog_event(selected, 'functional', ['functional_diagnostic','source_shadow'], 'functional-calibration')
        windows = json.loads((self.root/'results/direct_link_windows.json').read_text())['windows']
        # Calibration/fault diagnostics deliberately use a long real contact,
        # separately identified from the percentile-selected primary events.
        windows = sorted(windows, key=lambda w: (set((w['sat_a'],w['sat_b'])) != {53848,53913}, w['start_s']))
        for window in windows:
            tick = max(30,window['start_s']+30)
            if window['end_s']-tick < 600: continue
            a,b = window['sat_a'],window['sat_b']
            if not (self.orbit.operational(a,tick) and self.orbit.operational(b,tick)): continue
            deadline = tick
            while deadline < self.orbit.duration and self.orbit.operational(a,deadline): deadline += 1
            if min(deadline,window['end_s'])-tick < 600: continue
            return {'event_id':f'functional-{a}-{b}-{tick}', 'sat_a':a,'sat_b':b,'trigger_s':tick,
                'deadline_s':deadline,'trigger_causes':['functional_diagnostic'],
                'contact_window_s':window['end_s']-tick,'deadline_window_s':deadline-tick,
                'contact_end_s':window['end_s'],'execution_purpose':'functional-calibration'}
        raise RuntimeError('No sufficiently long illuminated functional contact in frozen observation')

    def resource_diagnostic(self):
        from .resource_diagnostic import run_pair
        return run_pair(self)

    def run(self, method, rate, event=None, *, fault=None, purpose='diagnostic', resource_diagnostic=False):
        if method not in ('cold','hot') or rate not in self.scenario['fso']['useful_throughput_bps']:
            raise ValueError('Unapproved method or throughput')
        event = event or self.functional_event()
        bundle = self.bundle()
        run_id = 'run-'+uuid.uuid4().hex
        directory = self.root/'results/runs'/run_id
        directory.mkdir(parents=True)
        atomic_json(directory/'inputs.json', {'event':event,'method':method,'rate_bps':rate,
            'scenario':self.scenario,'bundle':bundle,'purpose':purpose,'fault':fault,
            'resource_diagnostic':resource_diagnostic})
        self.checkpoint(kind='run', run_id=run_id, phase='preparation', source_slot='sat-a',
            target_slot='sat-b', inputs_path=str(directory/'inputs.json'))
        result = {'schema_version':3,'run_id':run_id,'created_utc':utc_now(), 'execution_kind':'live-hybrid',
            'purpose':purpose,'method':method,'configured_rate_bps':rate,'event':event,'fault':fault,
            'success':False,'ack':False,'outcome':'recovery_required','directory':str(directory),
            'shared_docker_daemon':True,'images_inventory':'per-host verified receipts; not Docker cache'}
        backend = None
        collector = None
        try:
            backend = LiveBackend(self.root,directory,event,rate,self.orbit,self.scenario,
                                  self.cancel,fault,self.publish)
            if resource_diagnostic:
                from .resource_diagnostic import Collector
                collector=Collector(self.root,directory)
                backend.resource_collector=collector
                collector.start()
            self.publish({'phase':'prepare','run_id':run_id,'timestamp_utc':utc_now()})
            if getattr(self, '_calibration_network_ready', False):
                backend.reset(reuse_inventory=True)
            else:
                backend.reset()
            baseline_started = True
            result['baseline'] = backend.establish_baseline(run_id)
            if resource_diagnostic:
                from .resource_diagnostic import DiagnosticClock, window
                clock=DiagnosticClock(max(0,event['trigger_s']-30))
            else:
                clock = LiveClock(max(0,event['trigger_s']-30))
            backend.start_observation(clock,run_id)
            if collector:
                window(backend,collector,'settling',60)
                window(backend,collector,'source_stable',120)
                collector.set_phase('dynamic_baseline')
                clock.resume()
            while clock.orbital() < event['trigger_s']:
                backend.check(); time.sleep(max(0,min(.1,event['trigger_s']-clock.orbital())))
            migration_start = time.time()
            if collector: collector.set_phase('migration')
            migration = Migration(backend,clock,directory/'operation',self.scenario)
            execute_handover(migration,backend,method,event,Path(bundle['image_bundle']['path']),result,directory)
            result['migration_start_unix_s'] = migration_start
            until = min(self.orbit.duration,clock.orbital()+30)
            if result.get('service_failure'):
                if result.get('interrupted'): raise InterruptedError(result['failure_reason'])
                raise RuntimeError(result['failure_reason'])
            observation_start = clock.now()
            if collector: collector.set_phase('dynamic_observation')
            while clock.orbital() < until:
                backend.check()
                time.sleep(max(0,min(.1,until-clock.orbital())))
            backend.check()
            result['observation_s'] = clock.now()-observation_start
            result['observation_complete'] = True
            if collector:
                clock.freeze()
                # Finish queued reconciliation before the fixed destination window.
                collector.set_phase('target_reconciliation')
                end=time.monotonic()+60
                expected_signature=backend.signature(lab_graph(self.orbit, int(clock.orbital())))
                while backend.pending_graph is not None or backend.graph_signature != expected_signature:
                    backend.check()
                    if time.monotonic()>end: raise TimeoutError('Target reconciliation did not settle')
                    time.sleep(.1)
                window(backend,collector,'target_stable',120)
                collector.set_phase('cleanup')
            result['operations'] = backend.measurements
            if result.get('migration_completed') and result.get('service_verification',{}).get('success'):
                result['disk_accounting'] = disk_content(self.root,'sat-b',bundle['image_bundle']['path'])
        except InterruptedError as exc:
            result.update(success=False,interrupted=True,outcome='interrupted',failure_reason=str(exc))
            if backend and not result.get('service_verification',{}).get('success'):
                try:
                    backend.quiesce_source()
                    backend.abort_target()
                    backend.recover_source()
                    result['source_recovered'] = True
                except Exception as recovery:
                    result.update(outcome='recovery_required',recovery_required=True,recovery_failure=str(recovery))
        except Exception as exc:
            result.update(success=False,ack=False,failure_reason=str(exc),outcome='recovery_required',recovery_required=True)
            error_file=directory/'preparation-error.json'
            if error_file.exists(): result['error']=json.loads(error_file.read_text())
            if backend:
                try:
                    backend.abort_target()
                    if backend.source_snapshot and (not backend.clock or backend.clock.orbital() < event['deadline_s']):
                        backend.recover_source()
                        result.update(source_recovered=True,outcome='experimental_failure',recovery_required=False)
                except Exception as recovery: result['recovery_failure'] = str(recovery)
        finally:
            service_file=directory/'service-verification.json'
            if service_file.exists():result['service_verification']=json.loads(service_file.read_text())
            if backend:
                if backend.clock and ((self.cancel and self.cancel.is_set()) or result.get('failure_reason')):
                    try:
                        backend.shutdown()
                        result.update(controllers_fenced=True,recovery_required=False)
                    except Exception as exc:
                        result.update(outcome='recovery_required',recovery_required=True,cleanup_failure=str(exc))
                if not backend.clock:
                    preparation_error = result.get('error') or {}
                    result.update(success=False,outcome='interrupted' if result.get('interrupted') else
                        'invalid_baseline' if preparation_error.get('operation')=='baseline' or locals().get('baseline_started',False) or (directory/'baseline.json').exists()
                        else 'preparation_failed')
                    try:
                        backend.shutdown()
                        result['controllers_fenced']=True
                        result['recovery_required']=False
                    except Exception as exc:result.update(outcome='recovery_required',recovery_required=True,cleanup_failure=str(exc))
                    baseline=directory/'baseline.json'
                    if baseline.exists():result['baseline']=json.loads(baseline.read_text())
                try: backend.close()
                except Exception as exc: result.update(success=False,outcome='recovery_required',recovery_required=True,close_failure=str(exc))
                result['api_calls'] = {'sat-a':backend.a.calls,'sat-b':backend.b.calls}
                result['operations'] = backend.measurements
            if collector:
                try:
                    collector.close()
                    from .resource_diagnostic import analyze
                    result['resource_diagnosis']=analyze(directory)
                except Exception as exc:
                    result['resource_diagnosis']={'complete':False,'error':str(exc)}
                    if ((collector.thread and collector.thread.is_alive()) or
                            (collector.inventory_thread and collector.inventory_thread.is_alive())):
                        result.update(recovery_required=True,close_failure=str(exc))
            probe_dir = self.root/'results/lab'/run_id
            if probe_dir.exists():
                rows = ping_observations((probe_dir/'ping.log').read_text())
                classified = classify_observations(rows,list(json_lines(directory/'geometry.jsonl')),
                    list(json_lines(directory/'heartbeat.jsonl')))
                for observation in classified:
                    append_json(directory/'classified-probes.jsonl',observation)
                result['probe_classifications'] = {category:sum(row['classification']==category for row in classified)
                    for category in ('service_available','no_geometric_path','loss_with_path','unknown_geometry')}
                started = result.get('migration_start_unix_s',float('inf'))
                baseline_rows = [row for row in rows if row['unix_s'] < started]
                baseline_service = result.get('baseline',{}).get('success',False)
                baseline_graph = lab_graph(self.orbit, max(0,event['trigger_s']-1))
                source_host,target_host = service_endpoints(backend.fixture)
                baseline_path = source_host in baseline_graph and target_host in shortest_paths(baseline_graph,source_host)
                result['probe_window_end_unix_s']=time.time()
                result['probes'] = analyze_directory(probe_dir,migration_start_unix_s=result.get('migration_start_unix_s'),
                    observation_end_unix_s=result['probe_window_end_unix_s'],
                    baseline_path_available=baseline_path and baseline_service)
                result['baseline_service_available'] = baseline_service
                result['baseline_path_available'] = baseline_path
                result['raw_probes_directory'] = str(probe_dir)
                result['baseline_observation_s'] = min(30,event['trigger_s'])
            result.update(transfer_metrics(result,Path(bundle['image_bundle']['path']).name))
            if 'observation_start' in locals() and not collector:result['observation_s']=clock.now()-observation_start
            finalize(result)
            atomic_json(directory/'metadata.json',result)
            row = {key:result.get(key) for key in ('run_id','purpose','execution_kind','method','configured_rate_bps',
                'outcome','success','ack','controller_downtime_s','total_operation_s','bytes_sent','bytes_received','failure_reason',
                'migration_completed','experimental_valid','observation_complete','recovery_required','service_verification_s','observation_s','retries')}
            with (directory/'summary.csv').open('w',newline='',encoding='utf-8') as handle:
                writer=csv.DictWriter(handle,fieldnames=list(row));writer.writeheader();writer.writerow(row)
            # Frozen source bundle and receipt remain; discard only the delivered
            # duplicate after Docker load to bound campaign disk consumption.
            for copied in directory.glob('attempts/*/received/'+Path(bundle['image_bundle']['path']).name):
                copied.unlink(missing_ok=True)
            self.publish({'phase':'run_finished','run_id':run_id,'outcome':result['outcome'],'timestamp_utc':utc_now()})
            if not result['recovery_required']:
                self.checkpoint(kind='between_runs',phase='idle',last_run_id=run_id)
        return result

    def simulate(self, **parameters):
        from .simulation import Simulation
        return Simulation(self).run(parameters)

    def compare_continuous(self, **parameters):
        from .continuous_comparison import ContinuousComparison
        return ContinuousComparison(self).run(parameters)

    def campaign(self):
        gate=self.frozen_gate()
        if gate:return gate
        events = json.loads((self.root/'config/selected_events.json').read_text())['events']
        runs=[]
        campaign_id='campaign-'+uuid.uuid4().hex
        expected=[[e['event_id'],m,r] for e in events for m in ('cold','hot') for r in self.scenario['fso']['useful_throughput_bps']]
        execution={'schema_version':2,'campaign_id':campaign_id,'expected_cases':expected,'runs':runs,'complete':False,'recovery_required':False}
        atomic_json(self.root/'results/campaigns'/campaign_id/'metadata.json',execution)
        def save_campaign():
            atomic_json(self.root/'results/campaign.json',execution)
            atomic_json(self.root/'results/campaigns'/campaign_id/'metadata.json',execution)
        save_campaign()
        for event in events:
            for method in ('cold','hot'):
                for rate in self.scenario['fso']['useful_throughput_bps']:
                    if self.cancel and self.cancel.is_set(): return {'complete':False,'runs':runs,'reason':'interrupted'}
                    result=self.run(method,rate,event,purpose='primary')
                    runs.append(result['run_id'])
                    result['campaign_id']=campaign_id
                    atomic_json(Path(result['directory'])/'metadata.json',result)
                    execution.update(complete=len(runs)==len(expected),recovery_required=requires_recovery(result))
                    save_campaign()
                    if result['outcome'] in ('recovery_required','invalid_baseline','invalid_lab','interrupted'):
                        output={**execution,'complete':False,'reason':result['outcome']}
                        execution.update(output);save_campaign()
                        return output
        return execution

    def diagnostic(self):
        gate=self.frozen_gate()
        if gate:return gate
        diagnostic=json.loads((self.root/'results/ranking-diagnostic.json').read_text())
        if diagnostic['event'] is None:return {'complete':True,'performed':False,'reason':diagnostic['reason']}
        result=self.run('hot',1000000000,diagnostic['event'],purpose='ranking-diagnostic')
        return {'complete':result['success'],'run_id':result['run_id'],'outcome':result['outcome']}

    def complete(self):
        stages={}
        for name in ('functional','calibrate','continuous_validation','environment','select','faults','campaign','diagnostic','sensitivity','report'):
            if self.cancel and self.cancel.is_set():return {'complete':False,'reason':'interrupted','stages':stages}
            self.publish({'phase':'workflow_stage','stage':name})
            try: stages[name]=getattr(self,name)()
            except Exception as exc:
                stages[name]={'complete':False,'reason':str(exc),
                    'recovery_required':name not in ('sensitivity','report','select')}
            atomic_json(self.root/'results/workflow.json',{'complete':False,'stages':stages})
            passed=stages[name].get('complete',stages[name].get('success',False)) and not requires_recovery(stages[name])
            if not passed:
                reason=stages[name].get('reason',stages[name].get('outcome','gate_failed'))
                self.report()
                result={'complete':False,'reason':reason,'failed_stage':name,'stages':stages,'recovery_required':requires_recovery(stages)}
                atomic_json(self.root/'results/workflow.json',result)
                return result
        result={'complete':True,'stages':stages}
        atomic_json(self.root/'results/workflow.json',result)
        return result

    def functional(self):
        import copy
        event=self.functional_event()
        runs=[]
        output={'schema_version':2,'comparison_id':'compare-'+uuid.uuid4().hex,'event':event,
            'created_utc':utc_now(),'current_method':None,
            'configured_rate_bps':1000000000,'order':['hot','cold'],
            'acceptance':'api_equivalence+target_authority+10_fresh_consecutive_pings',
            'complete':False,'runs':runs,'cold_minus_hot':{},'purpose':'functional-validation'}
        def save():
            atomic_json(self.root/'results/functional-gate.json',output)
            atomic_json(self.root/'results/comparisons'/output['comparison_id']/'metadata.json',output)
        save()
        for method in ('hot','cold'):
            if self.cancel and self.cancel.is_set():
                output['reason']='interrupted';save();return output
            output['current_method']=method
            save()
            self.publish({'phase':'comparison_run','comparison_id':output['comparison_id'],'method':method})
            result=self.run(method,1000000000,copy.deepcopy(event),purpose='functional-gate')
            if result.get('error'): output['error'] = result['error']
            runs.append({**summary_metrics(result), **{key:result.get(key) for key in ('run_id','method','outcome','failure_reason')},
                'recovery_required':requires_recovery(result),'success':result['success'],'baseline_valid':result.get('baseline',{}).get('success',False),
                'service_verified':result.get('service_verification',{}).get('success',False)})
            output['current_method']=None
            output['schema_version']=3
            output['recovery_required']=requires_recovery(runs)
            output['complete']=len(runs)==2 and all(r['success'] and r['baseline_valid'] and r['service_verified'] for r in runs)
            if not runs[-1]['success'] or not runs[-1]['baseline_valid'] or not runs[-1]['service_verified']:
                output['reason']=result['outcome'] if not result['success'] else 'service_not_verified'
                save();return output
            if output['complete']:
                hot,cold=runs
                for field in ('controller_downtime_s','ping_recovery_s','total_operation_s','attempt'):
                    output['cold_minus_hot'][field]=cold[field]-hot[field] if hot[field] is not None and cold[field] is not None else None
            save()
        return output

    def continuous_validation(self):
        from .simulation import Simulation
        runs=[]
        for method in ('hot','cold'):
            session=Simulation(self)
            attempted_live=False
            # Admission needs at least three planned handovers, with unchanged
            # scientific inputs. Failure here ends the workflow before freezing.
            session.identifier='validation-planning'
            session.directory=self.root/'results/continuous-validation-planning'
            session.directory.mkdir(parents=True,exist_ok=True)
            try:
                planner=session.prepare_planner()
                plan=planner.plan({'method':method,'duration_s':3600,'max_migrations':3},minimum_migrations=3)
                attempted_live=True
                result=self.simulate(method=method,duration_s=3600,max_migrations=3,
                    start_orbital_s=plan['start_s'],initial_satellite_id=plan['initial_satellite_id'])
                passed=(result['success'] and len(result['migrations'])>=3 and
                    {r['source_slot'] for r in result['migrations']}=={'sat-a','sat-b'})
                runs.append({'simulation_id':result['simulation_id'],'method':method,'passed':passed,
                    'outcome':result['outcome'],'recovery_required':requires_recovery(result),
                    'reason':result.get('failure_reason')})
            except Exception as exc:
                runs.append({'method':method,'passed':False,'reason':str(exc),'recovery_required':attempted_live})
            output={'schema_version':2,'complete':len(runs)==2 and all(r['passed'] for r in runs),
                'sessions':runs,'recovery_required':requires_recovery(runs)}
            atomic_json(self.root/'results/continuous-validation.json',output)
            if not runs[-1]['passed']:return output
        return output

    def faults(self):
        gate=self.frozen_gate()
        if gate:return gate
        runs=[]
        for method in ('cold','hot'):
            for fault in ('fso_loss','no_progress','checksum','target_start','restore_api'):
                if self.cancel and self.cancel.is_set(): break
                result=self.run(method,1000000000,fault=fault,purpose='fault')
                result['fault_assertions_passed'] = (result.get('baseline',{}).get('success',False) and not result['success'] and not result.get('ack') and
                    result.get('attempt',0)<=3 and result['outcome']!='recovery_required')
                try:
                    authority=http(18091)
                    result['fault_authority_status']=authority.get('authority',authority.get('active'))
                    result['fault_assertions_passed'] &= authority.get('active')=='sat-a'
                except Exception:
                    result['fault_assertions_passed']=False
                atomic_json(Path(result['directory'])/'metadata.json',result)
                runs.append({'run_id':result['run_id'],'fault':fault,'method':method,'passed':result['fault_assertions_passed']})
                if result['outcome'] in ('recovery_required','invalid_baseline','invalid_lab','interrupted'):
                    output={'complete':False,'reason':result['outcome'],'runs':runs}
                    atomic_json(self.root/'results/fault-campaign.json',output)
                    return output
        output={'complete':len(runs)==10 and all(row['passed'] for row in runs),'runs':runs}
        atomic_json(self.root/'results/fault-campaign.json',output)
        return output

    def frozen_gate(self):
        """A rejected checksum gate has not changed the laboratory."""
        try:
            manifest=json.loads((self.root/'config/campaign-manifest.json').read_text())
            for artifact in manifest['artifacts']:verify_artifact(artifact)
        except Exception as exc:
            return {'complete':False,'reason':'Frozen campaign gate failed: '+str(exc)}
        return None
