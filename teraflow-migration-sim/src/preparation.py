"""Measured calibration and frozen, reproducible campaign preparation."""
import copy
import json
import math
import subprocess
from dataclasses import asdict
from pathlib import Path
from .artifacts import canonical_bytes, describe, file_digest
from .events import generate_events
from .event_sampling import select_percentile_events
from .migration_model import Workload, evaluate
from .probes import json_lines
from .storage import atomic_json, utc_now


class Preparation:
    def calibrate(self):
        if (self.root/'config/campaign-manifest.json').exists():
            raise ValueError('Campaign is frozen; archive it explicitly before recalibration')
        runs=[]
        for method in ('cold','hot'):
            for replica in range(3):
                self.publish({'phase':'calibration','method':method,'replica':replica+1})
                result=self.run(method,1000000000,purpose='calibration')
                runs.append(result)
                atomic_json(self.root/'results/calibration-progress.json',{'runs':[r['run_id'] for r in runs]})
                if not result['success']:
                    return {'complete':False,'reason':result['outcome'],'runs':[r['run_id'] for r in runs]}
        manifest=self.calibration_manifest(runs)
        from tools.validate_artifact_manifest import validate
        issues=validate(manifest)
        if issues: raise ValueError('Incomplete measurements: '+str(issues))
        atomic_json(self.root/'config/artifact_manifest.json',manifest)
        workload=self.workload(manifest)
        estimates=[asdict(evaluate(workload,mode,rate,self.scenario['fso']['alignment_s'],1e12,1e12))
            for mode in ('cold','hot') for rate in self.scenario['fso']['useful_throughput_bps']]
        horizon=math.ceil(max(row['total_operation_s'] for row in estimates)*1.2)
        output={'complete':True,'execution_kind':'live-calibration','runs':[r['run_id'] for r in runs],
                'estimates':estimates,'horizon_s':horizon,'manifest':describe(self.root/'config/artifact_manifest.json')}
        atomic_json(self.root/'results/calibration.json',output)
        return output

    @staticmethod
    def workload(manifest):
        state=manifest['operational_state'];times=manifest['timing_measurements_s']
        return Workload(manifest['image_bundle']['bytes'],state['cold_snapshot_bytes'],
            state['hot_initial_state_bytes'],state['hot_final_delta_bytes'],times['cold_snapshot'],
            times['hot_freeze'],times['hot_delta_apply'],times['controller_startup'],times['api_restore'],
            times['api_verification'],times['ack_cutover'])

    def calibration_manifest(self,runs):
        bundle=self.bundle()
        doc=json.loads((self.root/'config/artifact_manifest.template.json').read_text())
        doc.update(status='measured',image_bundle=bundle['image_bundle'],measurement_date_utc=utc_now(),
            measurement_method='Three full functional runs per mode; maxima of measured phases and host resources. Shared Docker daemon layer reuse explicitly retained.')
        doc['controller'].update(source_commit=bundle['source_commit'],
            dependency_policy=self.scenario['controller']['dependency_policy'],
            images={name:{'image':row['reference'],'digest':row['image_id']} for name,row in bundle['images'].items()})
        rows=json.loads(subprocess.check_output(['docker','container','inspect','sat-b-cockroachdb-1',
            'sat-b-nats-1','sat-b-kafka-1'],cwd=self.root,text=True,timeout=30))
        doc['controller']['dependencies']=[{'image':row['Config']['Image'],'digest':row['Image']} for row in rows]
        cold=[r for r in runs if r['method']=='cold'];hot=[r for r in runs if r['method']=='hot']
        def maximum(group,name):
            values=[sum(x['elapsed_s'] for x in r['operations'] if x['operation']==name) for r in group]
            return max(values)
        def payloads(group,prefix):
            return [p for r in group for p in (Path(r['directory'])/'operation').glob(prefix)]
        snapshots=payloads(runs,'snapshot-*.json')
        state=max(snapshots,key=lambda p:p.stat().st_size)
        entities=json.loads(state.read_text())['entities']
        doc['operational_state'].update({name+'_bytes':len(canonical_bytes(entities[name]))
            for name in ('contexts','topologies','devices','links')})
        doc['operational_state'].update(services_connections_policies_bytes=len(canonical_bytes(
            {name:entities.get(name,[]) for name in ('services','connections','policies')})),
            cold_snapshot_bytes=max(p.stat().st_size for p in payloads(cold,'snapshot-*.json')),
            hot_initial_state_bytes=max(p.stat().st_size for p in payloads(hot,'snapshot-*.json')),
            hot_final_delta_bytes=max(p.stat().st_size for p in payloads(hot,'delta-*.json')),
            export_format='versioned ordered JSON UTF-8',sha256=file_digest(state))
        doc['timing_measurements_s'].update(cold_snapshot=maximum(cold,'snapshot')+maximum(cold,'source_stop'),
            hot_freeze=maximum(hot,'freeze')+maximum(hot,'snapshot'),hot_delta_apply=maximum(hot,'delta_apply'),
            controller_startup=maximum(runs,'image_load_shared_daemon')+maximum(runs,'controller_startup'),
            api_restore=maximum(runs,'api_restore'),api_verification=maximum(runs,'api_verification'),
            ack_cutover=maximum(runs,'queued_topology_apply')+maximum(runs,'cutover'))
        overhead=max(max(0,r['total_operation_s']-self.scenario['fso']['alignment_s']
            -sum(row['receipt']['elapsed_s'] for row in r['events'] if row['phase']=='transfer_verified')
            -sum(row['elapsed_s'] for row in r['operations'])) for r in runs)
        doc['timing_measurements_s']['measured_protocol_overhead']=overhead
        doc['timing_measurements_s']['ack_cutover']+=overhead
        samples=[host for r in runs for row in json_lines(Path(r['directory'])/'resources.jsonl')
            for host in row['hosts'].values() if host['running_containers']>=9]
        if not samples:raise ValueError('Missing complete workload/dependency resource samples')
        doc['resources']={'measured_controller_cpu_cores':max(row['cpu_cores'] for row in samples),
            'measured_controller_ram_gib':max(row['ram_gib'] for row in samples),
            'measured_controller_disk_gib':max(r['disk_accounting']['disk_gib'] for r in runs)}
        doc['calibration_run_ids']=[r['run_id'] for r in runs]
        doc['timing_accounting']='Maxima per phase; cold snapshot includes stop, hot freeze includes both snapshots; startup includes shared-daemon load; cutover includes queued topology reconciliation. Conservative estimates.'
        return doc

    def select(self):
        if (self.root/'config/campaign-manifest.json').exists():raise ValueError('Campaign already frozen')
        calibration=json.loads((self.root/'results/calibration.json').read_text())
        if not calibration['complete']:raise ValueError('Six functional calibrations required')
        manifest=json.loads((self.root/'config/artifact_manifest.json').read_text())
        resources={key:manifest['resources']['measured_controller_'+key] for key in ('cpu_cores','ram_gib','disk_gib')}
        events=generate_events(self.orbit,self.scenario,calibration['horizon_s'],resources)
        atomic_json(self.root/'results/events.json',{'execution_kind':'calibrated-model','events':events})
        eligible=[row for row in events if row['migrable']]
        if len(eligible)<3:return {'complete':False,'reason':'fewer_than_three_selectable_events','event_count':len(events),'eligible':len(eligible)}
        selected=select_percentile_events(eligible)
        atomic_json(self.root/'config/selected_events.json',{'schema_version':1,'events':selected})
        multiple=next((row for row in events if len(row['candidates'])>=2),None)
        atomic_json(self.root/'results/ranking-diagnostic.json',{'event':multiple,
            'reason':None if multiple else 'No trigger has two eligible candidates'})
        files=['config/scenario.json','config/fixture.json','config/selected_constellation.json',
            'config/artifact_manifest.json','config/selected_events.json','artifacts/orbit/replay.npz',
            'artifacts/orbit/replay.json','artifacts/images-l2-patched-v2/bundle.json',
            'deploy/patches/manifest.json','deploy/patches/device-manifest.json',
            'results/calibration.json','results/events.json']
        files.extend(str(p.relative_to(self.root)) for p in (self.root/'src').glob('*.py'))
        for directory in ('deploy','tools','web'):
            files.extend(str(p.relative_to(self.root)) for p in (self.root/directory).rglob('*')
                if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
        files.append('artifacts/resource-image-accounting.json')
        files = sorted(set(files))
        artifacts=[describe(self.root/path) for path in files]
        artifacts.append(self.bundle()['image_bundle'])
        frozen={'schema_version':1,'created_utc':utc_now(),'artifacts':artifacts,
            'horizon_s':calibration['horizon_s'],'expected_primary_runs':18,
            'provenance':'Frozen orbital replay, actual authorized patched images, six measured calibration runs',
            'event_ids':[row['event_id'] for row in selected]}
        atomic_json(self.root/'config/campaign-manifest.json',frozen)
        return {'complete':True,'events':selected,'event_count':len(events),'eligible':len(eligible)}
