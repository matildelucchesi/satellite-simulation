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
from .orbit import Orbit, shortest_paths
from .orchestrator import Migration
from .probes import analyze_directory, classify_observations, json_lines, ping_observations
from .storage import append_json, atomic_json, utc_now
from .preparation import Preparation
from .analysis import Analysis


class Experiment(Preparation, Analysis):
    def __init__(self, root, cancel=None, publish=None):
        self.root = Path(root).resolve()
        self.cancel = cancel
        self.publish = publish or (lambda event: None)
        self.scenario = json.loads((self.root/'config/scenario.json').read_text())
        self._orbit = None

    @property
    def orbit(self):
        if self._orbit is None: self._orbit = Orbit(self.root/'artifacts/orbit/replay.npz')
        return self._orbit

    def bundle(self):
        path = self.root/'artifacts/images-l2-patched-v2/bundle.json'
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
        from .fixture import for_destination
        directory=self.root/'results/jobs'/previous_job_id
        events=list(json_lines(directory/'events.jsonl'))
        run_id=next((row.get('run_id') for row in events if row.get('run_id')),None)
        http(18091,'/revoke',{})
        compose=Compose(self.root)
        compose.stop('sat-b')
        if not run_id:raise RuntimeError('No run evidence; controllers fenced, manual perimeter inspection required')
        run_dir=self.root/'results/runs'/run_id
        event=json.loads((run_dir/'inputs.json').read_text())['event']
        timed=[row for row in events if 'orbital_s' in row]
        if timed:
            latest=timed[-1]
            orbital=latest['orbital_s']+(datetime.now(timezone.utc)-datetime.fromisoformat(latest['timestamp_utc'])).total_seconds()
        else:orbital=event['trigger_s']-30
        if orbital>=event['deadline_s']:
            compose.stop('sat-a')
            output={'complete':True,'recovered':False,'source_expired':True,'controllers_fenced':True,
                'previous_job_id':previous_job_id,'orbital_s':orbital}
        else:
            from .tfs_adapter import TfsAdapter
            paths=sorted((run_dir/'operation').glob('snapshot-*.json'))
            if not paths:raise RuntimeError('No verified source snapshot; explicit fixture reconstruction required')
            snapshot=json.loads(paths[-1].read_text())
            compose.start('sat-a')
            # Restore confirmed saved A hardware state before accepting A writes.
            http(18091,'/recover',{})
            adapter=TfsAdapter('http://127.0.0.1:18080')
            try:
                adapter.reconcile(snapshot)
                verification=adapter.verify(snapshot)
                if not verification['equivalent']:raise RuntimeError('Recovery API equivalence failed')
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
            status['success'] = (status['mininet']['switch_count'] == 17 and status['mininet']['switches_alive']
                and all(status['controllers'].values())
                and all(row['upstream_master'] for row in status['proxy']['states']))
        except Exception as exc: status['error'] = str(exc)
        atomic_json(self.root/'results/environment.json',status)
        return status

    def functional_event(self):
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

    def run(self, method, rate, event=None, *, fault=None, purpose='diagnostic'):
        if method not in ('cold','hot') or rate not in self.scenario['fso']['useful_throughput_bps']:
            raise ValueError('Unapproved method or throughput')
        event = event or self.functional_event()
        bundle = self.bundle()
        run_id = 'run-'+uuid.uuid4().hex
        directory = self.root/'results/runs'/run_id
        directory.mkdir(parents=True)
        atomic_json(directory/'inputs.json', {'event':event,'method':method,'rate_bps':rate,
            'scenario':self.scenario,'bundle':bundle,'purpose':purpose,'fault':fault})
        result = {'schema_version':3,'run_id':run_id,'created_utc':utc_now(), 'execution_kind':'live-hybrid',
            'purpose':purpose,'method':method,'configured_rate_bps':rate,'event':event,'fault':fault,
            'success':False,'ack':False,'outcome':'recovery_required','directory':str(directory),
            'shared_docker_daemon':True,'images_inventory':'per-host verified receipts; not Docker cache'}
        backend = None
        try:
            backend = LiveBackend(self.root,directory,event,rate,self.orbit,self.scenario,
                                  self.cancel,fault,self.publish)
            self.publish({'phase':'prepare','run_id':run_id,'timestamp_utc':utc_now()})
            backend.reset()
            clock = LiveClock(max(0,event['trigger_s']-30))
            backend.start_observation(clock,run_id)
            while clock.orbital() < event['trigger_s']:
                backend.check(); time.sleep(max(0,min(.1,event['trigger_s']-clock.orbital())))
            migration_start = time.time()
            migration = Migration(backend,clock,directory/'operation',self.scenario)
            result.update(migration.run(method,event,Path(bundle['image_bundle']['path'])))
            result['migration_start_unix_s'] = migration_start
            until = min(self.orbit.duration,clock.orbital()+30)
            while clock.orbital() < until and not backend.cancelled:
                time.sleep(max(0,min(.1,until-clock.orbital())))
            result['operations'] = backend.measurements
            if result['success']:
                result['disk_accounting'] = disk_content(self.root,'sat-b',bundle['image_bundle']['path'])
            result['outcome'] = ('success' if result['success'] else
                'recovery_required' if result.get('recovery_required') else
                'interrupted' if result.get('interrupted') else 'experimental_failure')
        except InterruptedError as exc:
            result.update(outcome='interrupted',failure_reason=str(exc))
            if backend:
                try:
                    backend.quiesce_source()
                    backend.abort_target()
                    backend.recover_source()
                    result['source_recovered'] = True
                except Exception as recovery:
                    result.update(outcome='recovery_required',recovery_failure=str(recovery))
        except Exception as exc:
            result.update(failure_reason=str(exc),outcome='recovery_required')
            if backend:
                try:
                    backend.abort_target()
                    if backend.source_snapshot and (not backend.clock or backend.clock.orbital() < event['deadline_s']):
                        backend.recover_source()
                        result.update(source_recovered=True,outcome='experimental_failure')
                except Exception as recovery: result['recovery_failure'] = str(recovery)
        finally:
            if backend:
                try: backend.close()
                except Exception as exc: result.update(outcome='recovery_required',close_failure=str(exc))
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
                started = result.get('migration_start_unix_s',float('inf'))
                baseline_rows = [row for row in rows if row['unix_s'] < started]
                baseline_service = any(row['success'] for row in baseline_rows)
                baseline_graph = self.orbit.graph(max(0,event['trigger_s']-1))
                baseline_path = 53913 in shortest_paths(baseline_graph,53848)
                result['probes'] = analyze_directory(probe_dir,migration_start_unix_s=result.get('migration_start_unix_s'),
                    baseline_path_available=baseline_path and baseline_service)
                result['baseline_service_available'] = baseline_service
                result['baseline_path_available'] = baseline_path
                result['raw_probes_directory'] = str(probe_dir)
                result['baseline_observation_s'] = min(30,event['trigger_s'])
            image_copies = [row for row in result.get('events',[]) if row['phase']=='transfer_verified'
                            and row.get('payload')==Path(bundle['image_bundle']['path']).name]
            if image_copies:
                measured = min(row['receipt']['useful_throughput_bps'] for row in image_copies)
                result['image_throughput_bps'] = measured
                if measured < .90*rate and purpose == 'primary':
                    result.update(outcome='invalid_lab',invalid_reason='Measured bundle throughput below 90% of configured useful rate')
            delivered = {}
            for row in result.get('events',[]):
                if row['phase']=='transfer_verified':
                    receipt=row['receipt'];delivered[receipt['sha256']]=receipt['received_bytes']
            result['useful_payload_bytes'] = sum(delivered.values())
            result['restarted_payload_bytes'] = max(0,result.get('bytes_sent',0)-result['useful_payload_bytes'])
            result['tcp_retransmissions'] = None
            result['schema_version'] = 3
            atomic_json(directory/'metadata.json',result)
            row = {key:result.get(key) for key in ('run_id','purpose','execution_kind','method','configured_rate_bps',
                'outcome','success','ack','controller_downtime_s','total_operation_s','bytes_sent','bytes_received','failure_reason')}
            with (directory/'summary.csv').open('w',newline='',encoding='utf-8') as handle:
                writer=csv.DictWriter(handle,fieldnames=list(row));writer.writeheader();writer.writerow(row)
            # Frozen source bundle and receipt remain; discard only the delivered
            # duplicate after Docker load to bound campaign disk consumption.
            copied = directory/'received'/Path(bundle['image_bundle']['path']).name
            if copied.exists(): copied.unlink()
            self.publish({'phase':'run_finished','run_id':run_id,'outcome':result['outcome'],'timestamp_utc':utc_now()})
        return result

    def campaign(self):
        manifest = json.loads((self.root/'config/campaign-manifest.json').read_text())
        for artifact in manifest['artifacts']: verify_artifact(artifact)
        events = json.loads((self.root/'config/selected_events.json').read_text())['events']
        runs=[]
        for event in events:
            for method in ('cold','hot'):
                for rate in self.scenario['fso']['useful_throughput_bps']:
                    if self.cancel and self.cancel.is_set(): return {'complete':False,'runs':runs,'reason':'interrupted'}
                    result=self.run(method,rate,event,purpose='primary')
                    runs.append(result['run_id'])
                    atomic_json(self.root/'results/campaign.json',{'complete':len(runs)==18,'runs':runs})
                    if result['outcome']=='recovery_required': return {'complete':False,'runs':runs,'reason':'recovery_required'}
        return {'complete':len(runs)==18,'runs':runs}

    def diagnostic(self):
        diagnostic=json.loads((self.root/'results/ranking-diagnostic.json').read_text())
        if diagnostic['event'] is None:return {'complete':True,'performed':False,'reason':diagnostic['reason']}
        result=self.run('hot',1000000000,diagnostic['event'],purpose='ranking-diagnostic')
        return {'complete':result['success'],'run_id':result['run_id'],'outcome':result['outcome']}

    def complete(self):
        stages={}
        for name in ('environment','calibrate','select','faults','campaign','diagnostic','sensitivity','report'):
            if self.cancel and self.cancel.is_set():return {'complete':False,'reason':'interrupted','stages':stages}
            self.publish({'phase':'workflow_stage','stage':name})
            stages[name]=getattr(self,name)()
            atomic_json(self.root/'results/workflow.json',{'complete':False,'stages':stages})
            passed=stages[name].get('complete',stages[name].get('success',False))
            if not passed:
                reason=stages[name].get('reason',stages[name].get('outcome','gate_failed'))
                self.report()
                return {'complete':False,'reason':reason,'failed_stage':name,'stages':stages}
        result={'complete':True,'stages':stages}
        atomic_json(self.root/'results/workflow.json',result)
        return result

    def faults(self):
        runs=[]
        for method in ('cold','hot'):
            for fault in ('fso_loss','no_progress','checksum','target_start','restore_api'):
                if self.cancel and self.cancel.is_set(): break
                result=self.run(method,1000000000,fault=fault,purpose='fault')
                result['fault_assertions_passed'] = (not result['success'] and not result.get('ack') and
                    result.get('attempt',0)<=3 and result['outcome']!='recovery_required')
                try:
                    authority=http(18091)
                    result['fault_authority_status']=authority.get('authority',authority.get('active'))
                    result['fault_assertions_passed'] &= authority.get('active')=='sat-a'
                except Exception:
                    result['fault_assertions_passed']=False
                atomic_json(Path(result['directory'])/'metadata.json',result)
                runs.append({'run_id':result['run_id'],'fault':fault,'method':method,'passed':result['fault_assertions_passed']})
                if result['outcome']=='recovery_required':
                    output={'complete':False,'reason':'recovery_required','runs':runs}
                    atomic_json(self.root/'results/fault-campaign.json',output)
                    return output
        output={'complete':len(runs)==10 and all(row['passed'] for row in runs),'runs':runs}
        atomic_json(self.root/'results/fault-campaign.json',output)
        return output
