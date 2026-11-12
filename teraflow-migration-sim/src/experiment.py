"""Laboratory operations: single migration run, verification, event experiment, recovery, environment.

Geometry is modeled from the installed scenario; every migration step is executed live.
"""
from __future__ import annotations
import copy
import csv
import json
import time
import uuid
from pathlib import Path

from .artifacts import verify_artifact
from .clock import LiveClock
from .fixture import service_endpoints
from .handover import execute as execute_handover
from .live_backend import LiveBackend, http
from .measurements import disk_content
from .orbit import lab_graph, load_orbit, shortest_paths
from .orchestrator import Migration
from .probes import analyze_directory, classify_observations, json_lines, ping_observations
from .results import finalize, requires_recovery, summary_metrics, transfer_metrics
from .storage import append_json, atomic_json, utc_now


class Experiment:
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
        identifiers={row['run_id'] for row in events if row.get('run_id')}
        if checkpoint is None and len(identifiers)==1:
            checkpoint={'kind':'run','run_id':next(iter(identifiers))}
        http(18091,'/revoke',{})
        compose=Compose(self.root)
        http(18090,'/probes/stop',{})
        if checkpoint and checkpoint.get('kind')=='between_runs':
            compose.stop('sat-a');compose.stop('sat-b')
            output={'complete':True,'recovery_required':False,'controllers_fenced':True,'between_runs':True}
            job=json.loads((directory/'job.json').read_text());job.update(status='recovered',recovery=output)
            atomic_json(directory/'job.json',job)
            return output
        if not checkpoint or checkpoint.get('kind')!='run':
            compose.stop('sat-a');compose.stop('sat-b')
            return {'complete':False,'recovery_required':True,'outcome':'recovery_required',
                'controllers_fenced':True,'reason':'No unambiguous active child checkpoint; inspect the laboratory explicitly'}
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

    def functional_event(self):
        """The first selected event of the installed catalogue."""
        selected = json.loads((self.root/'config/migration_events.json').read_text())['selected'][0]
        return self.catalog_event(selected, 'functional', ['functional_diagnostic','source_shadow'], 'functional-verification')

    def compare_events(self, policy='designed'):
        """Hot and Cold on each catalogue event of ``policy`` (designed events or the destination
        policy's), order drawn in each pair.

        Every run starts from the same orbital instant of its event. A failed run stays missing and
        the experiment goes on; it stops when recovery is needed or after repeated failures."""
        from .event_comparison import compare
        return compare(self, policy)

    def run(self, method, rate, event=None, *, purpose='diagnostic'):
        if method not in ('cold','hot') or rate not in self.scenario['fso']['useful_throughput_bps']:
            raise ValueError('Unapproved method or throughput')
        event = event or self.functional_event()
        bundle = self.bundle()
        run_id = 'run-'+uuid.uuid4().hex
        directory = self.root/'results/runs'/run_id
        directory.mkdir(parents=True)
        atomic_json(directory/'inputs.json', {'event':event,'method':method,'rate_bps':rate,
            'scenario':self.scenario,'bundle':bundle,'purpose':purpose})
        self.checkpoint(kind='run', run_id=run_id, phase='preparation', source_slot='sat-a',
            target_slot='sat-b', inputs_path=str(directory/'inputs.json'))
        result = {'schema_version':3,'run_id':run_id,'created_utc':utc_now(), 'execution_kind':'live-hybrid',
            'purpose':purpose,'method':method,'configured_rate_bps':rate,'event':event,
            'success':False,'ack':False,'outcome':'recovery_required','directory':str(directory),
            'shared_docker_daemon':True,'images_inventory':'per-host verified receipts; not Docker cache'}
        backend = None
        try:
            backend = LiveBackend(self.root,directory,event,rate,self.orbit,self.scenario,
                                  self.cancel,None,self.publish)
            self.publish({'phase':'prepare','run_id':run_id,'timestamp_utc':utc_now()})
            backend.reset()
            baseline_started = True
            result['baseline'] = backend.establish_baseline(run_id)
            clock = LiveClock(max(0,event['trigger_s']-30))
            backend.start_observation(clock,run_id)
            while clock.orbital() < event['trigger_s']:
                backend.check(); time.sleep(max(0,min(.1,event['trigger_s']-clock.orbital())))
            migration_start = time.time()
            migration = Migration(backend,clock,directory/'operation',self.scenario)
            execute_handover(migration,backend,method,event,Path(bundle['image_bundle']['path']),result,directory)
            result['migration_start_unix_s'] = migration_start
            until = min(self.orbit.duration,clock.orbital()+30)
            if result.get('service_failure'):
                if result.get('interrupted'): raise InterruptedError(result['failure_reason'])
                raise RuntimeError(result['failure_reason'])
            observation_start = clock.now()
            while clock.orbital() < until:
                backend.check()
                time.sleep(max(0,min(.1,until-clock.orbital())))
            backend.check()
            result['observation_s'] = clock.now()-observation_start
            result['observation_complete'] = True
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
            probe_dir = self.root/'results/lab'/run_id
            if probe_dir.exists():
                rows = ping_observations((probe_dir/'ping.log').read_text())
                classified = classify_observations(rows,list(json_lines(directory/'geometry.jsonl')),
                    list(json_lines(directory/'heartbeat.jsonl')))
                for observation in classified:
                    append_json(directory/'classified-probes.jsonl',observation)
                result['probe_classifications'] = {category:sum(row['classification']==category for row in classified)
                    for category in ('service_available','no_geometric_path','loss_with_path','unknown_geometry')}
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
            if 'observation_start' in locals():result['observation_s']=clock.now()-observation_start
            finalize(result)
            atomic_json(directory/'metadata.json',result)
            row = {key:result.get(key) for key in ('run_id','purpose','execution_kind','method','configured_rate_bps',
                'outcome','success','ack','controller_downtime_s','total_operation_s','bytes_sent','bytes_received','failure_reason',
                'migration_completed','experimental_valid','observation_complete','recovery_required','service_verification_s','observation_s','retries')}
            with (directory/'summary.csv').open('w',newline='',encoding='utf-8') as handle:
                writer=csv.DictWriter(handle,fieldnames=list(row));writer.writeheader();writer.writerow(row)
            # Frozen source bundle and receipt remain; discard only a delivered duplicate.
            for copied in directory.glob('attempts/*/received/'+Path(bundle['image_bundle']['path']).name):
                copied.unlink(missing_ok=True)
            self.publish({'phase':'run_finished','run_id':run_id,'outcome':result['outcome'],'timestamp_utc':utc_now()})
            if not result['recovery_required']:
                self.checkpoint(kind='between_runs',phase='idle',last_run_id=run_id)
        return result

    def functional(self):
        """Verification: one Hot and one Cold migration on the first catalogue event."""
        event=self.functional_event()
        runs=[]
        rate=self.scenario['fso']['useful_throughput_bps'][0]
        output={'schema_version':3,'comparison_id':'compare-'+uuid.uuid4().hex,'event':event,
            'created_utc':utc_now(),'current_method':None,
            'configured_rate_bps':rate,'order':['hot','cold'],
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
            self.publish({'phase':'comparison_run','comparison_id':output['comparison_id'],'method':method,
                          'label':f'Verifica · {method.upper()}'})
            result=self.run(method,rate,copy.deepcopy(event),purpose='functional-gate')
            if result.get('error'): output['error'] = result['error']
            runs.append({**summary_metrics(result), **{key:result.get(key) for key in ('run_id','method','outcome','failure_reason')},
                'recovery_required':requires_recovery(result),'success':result['success'],'baseline_valid':result.get('baseline',{}).get('success',False),
                'service_verified':result.get('service_verification',{}).get('success',False)})
            output['current_method']=None
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
