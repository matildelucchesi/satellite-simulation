"""Opt-in resource evidence; never changes scientific admission inputs."""
import contextlib
import csv
import json
import re
import statistics
import subprocess
import threading
import time
import uuid
from pathlib import Path

from .deployment import PROJECT, ROLE_LABEL, ROLES
from .measurements import size_bytes
from .storage import append_json, atomic_json, utc_now

WORKLOAD = {'nbiservice','serviceservice','deviceservice','pathcompservice','pathcomp-backend','contextservice'}


class DiagnosticClock:
    """Wall-time protocol clock with explicitly suspended orbital progression."""
    def __init__(self, orbital_start_s):
        self.start=time.monotonic(); self.offset=orbital_start_s
        self.paused_at=self.start; self.excluded=0

    def now(self): return time.monotonic()-self.start

    def orbital(self):
        return self.offset+(self.paused_at or time.monotonic())-self.start-self.excluded

    def freeze(self):
        if self.paused_at is None: self.paused_at=time.monotonic()

    def resume(self):
        if self.paused_at is not None:
            self.excluded+=time.monotonic()-self.paused_at; self.paused_at=None

    def sleep(self, seconds): time.sleep(seconds)


def window(backend, collector, phase, duration):
    collector.set_phase(phase)
    backend.notify({'phase':phase,'run_id':backend.probe_id,'duration_s':duration})
    started=time.time()
    end=time.monotonic()+duration
    while time.monotonic()<end:
        backend.check()
        if backend.cancel.wait(min(.2,max(0,end-time.monotonic()))): backend.check()
    if phase in ('source_stable','target_stable'):
        from .live_backend import http
        from .probes import ping_observations, baseline_ready
        path=backend.root/'results/lab'/backend.probe_id/'ping.log'
        rows=ping_observations(path.read_text(encoding='utf-8'))
        fresh=[r for r in rows if r['unix_s']>=started]
        role=backend.source_slot if phase=='source_stable' else backend.target_slot
        status=http(18091)
        if not baseline_ready(fresh,[],status,started,role,now=time.time()):
            raise RuntimeError('Stable resource window lost verified service: '+phase)
        adapter=backend.source if phase=='source_stable' else backend.target
        adapter.export()
        collector.event('stable_service_verified',phase=phase,slot=role,
            criteria='API+authority+10_fresh_consecutive_pings',started_unix_s=started,verified_unix_s=time.time())


def run_pair(application):
    from .simulation import engine_fingerprint
    identifier='resource-'+uuid.uuid4().hex
    directory=application.root/'results/resource-diagnostics'/identifier
    directory.mkdir(parents=True)
    event=application.functional_event()
    output={'schema_version':1,'diagnostic_id':identifier,'created_utc':utc_now(),
        'engine_fingerprint':engine_fingerprint(application.root),'scenario':application.scenario,
        'bundle':application.bundle(),'event':event,'configuration':{'settling_s':60,'stable_s':120,
        'rate_bps':1000000000,'order':['hot','cold']},'runs':[],'complete':False}
    atomic_json(directory/'inputs.json',output)
    output['directory']=str(directory)
    for method in ('hot','cold'):
        run=application.run(method,1000000000,event,purpose='resource-diagnostic',resource_diagnostic=True)
        output['runs'].append(run)
        atomic_json(directory/'result.json',output)
        if not run.get('success') or run.get('recovery_required'): break
    output['migration_success']=len(output['runs'])==2 and all(r.get('success') for r in output['runs'])
    output['complete']=output['migration_success'] and all(r.get('resource_diagnosis',{}).get('complete') for r in output['runs'])
    output['recovery_required']=any(r.get('recovery_required') for r in output['runs'])
    report=['# Diagnosi CPU TeraFlow', '',f"ID: {identifier}",
        f"Migrazioni riuscite: {output['migration_success']}. Diagnosi completa: {output['complete']}.",
        '', 'Planner, risorse e calibrazioni non modificati. Percentili empirici floor(0.95*(N-1)).',
        'Le coincidenze temporali non dimostrano causalità; i campioni non misurano la durata esatta dei picchi.', '']
    for r in output['runs']:
        report += [f"## {r['method']} — {r['run_id']}", '',
            '### Totali per slot e finestra', '',
            '| Slot | Finestra | Mediana | P95 | Massimo | Campioni >2,4 |',
            '|---|---|---:|---:|---:|---:|']
        diagnosis=r.get('resource_diagnosis',{})
        for s in diagnosis.get('slot_summaries',[]):
            report.append(f"| {s['slot']} | {s['phase']} | {s['median']} | {s['p95']} | {s['maximum']} | {s['above_2_4']} |")
        stable=[s for s in diagnosis.get('slot_summaries',[]) if
            (s['phase'],s['slot']) in [('source_stable','sat-a'),('target_stable','sat-b')]]
        exceeded=any(s['above_2_4'] for s in stable)
        report += ['', f"Superamenti campionati in regime stabile: {exceeded}. Completezza delle risorse: {diagnosis.get('complete',False)}.",
            'Campioni mancanti o totali incompleti non sono consumi nulli.', '', '### Componenti', '',
            '| Slot | Finestra | Servizio | Mediana | P95 | Massimo | Campioni >2,4 |',
            '|---|---|---|---:|---:|---:|---:|']
        for s in r.get('resource_diagnosis',{}).get('container_summaries',[]):
            report.append(f"| {s['slot']} | {s['phase']} | {s['service']} | {s['median']} | {s['p95']} | {s['maximum']} | {s['above_2_4']} |")
        report += ['',f"Evidenze: {r['directory']}", '']
    (directory/'report.md').write_text('\n'.join(report),encoding='utf-8')
    output['report_path']=str(directory/'report.md')
    atomic_json(directory/'result.json',output)
    return output


def number(value, memory=False):
    try:
        return size_bytes(value.split('/')[0])/1024**3 if memory else float(value.rstrip('%'))/100
    except (ValueError, TypeError, AttributeError):
        return None


def parse_stats_line(line):
    cleaned=re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', line).strip()
    return json.loads(cleaned) if cleaned else None


def identity(row):
    labels = row.get('Config', {}).get('Labels') or {}
    role = labels.get(ROLE_LABEL)
    if labels.get('com.docker.compose.project') != PROJECT or role not in ROLES:
        return None
    service = labels.get('com.docker.compose.service', '')
    name = service.removeprefix(role+'-')
    return {'container_id':row['Id'], 'slot':role, 'service':service,
            'category':'workload' if name in WORKLOAD else 'dependency'}


class Collector:
    def __init__(self, root, directory):
        self.root, self.directory = root, Path(directory)
        self.phase = 'preparation'
        self.active = {}
        self.lock = threading.RLock()
        self.errors = []
        self.identities = {}
        self.process = None
        self.thread = None
        self.inventory_thread = None
        self.inventory_stop = threading.Event()
        self.batch = 0
        self.seen = set()

    def event(self, kind, **data):
        append_json(self.directory/'resource-phases.jsonl', dict(schema_version=1,
            timestamp_utc=utc_now(), monotonic_s=time.monotonic(), kind=kind, **data))

    def set_phase(self, phase):
        with self.lock:
            self.event('phase_end', phase=self.phase)
            self.phase = phase
            self.event('phase_start', phase=phase)

    @contextlib.contextmanager
    def operation(self, operation, slot):
        key = uuid.uuid4().hex
        with self.lock:
            self.active[key] = {'operation':operation,'slot':slot}
            self.event('operation_start', operation_id=key, **self.active[key])
        try:
            yield
        finally:
            with self.lock:
                self.event('operation_end', operation_id=key, **self.active.pop(key))

    def refresh(self):
        ids = subprocess.check_output(['docker','ps','-q','--no-trunc','--filter',
            'label=com.docker.compose.project='+PROJECT], cwd=self.root,text=True,timeout=10).split()
        if not ids:
            self.identities = {}; return
        rows = json.loads(subprocess.check_output(['docker','inspect',*ids],cwd=self.root,text=True,timeout=10))
        identities = {r['Id']:identity(r) for r in rows if identity(r)}
        with self.lock:
            if identities != self.identities:
                self.event('inventory',containers=list(identities.values()))
            self.identities = identities

    def accept(self, row):
        cid = row.get('ID','')
        info = next((v for k,v in self.identities.items() if k.startswith(cid) and cid), None)
        if not info:
            return
        with self.lock:
            if info['container_id'] in self.seen:
                self.batch+=1; self.seen.clear()
            self.seen.add(info['container_id'])
            sample = dict(schema_version=1,timestamp_utc=utc_now(),monotonic_s=time.monotonic(),
                batch=self.batch,expected_container_ids=sorted(self.identities),
                expected_slots={k:v['slot'] for k,v in self.identities.items()},
                phase=self.phase,operations=list(self.active.values()), **info,
                cpu_cores=number(row.get('CPUPerc')),ram_gib=number(row.get('MemUsage'),True))
            if sample['cpu_cores'] is None or sample['ram_gib'] is None:
                self.errors.append('Missing or malformed resource value')
            append_json(self.directory/'container-resources.jsonl',sample)

    def start(self):
        self.event('phase_start',phase=self.phase)
        try:
            self.refresh()
            self.process = subprocess.Popen(['docker','stats','--no-trunc','--format','{{json .}}'],
                cwd=self.root,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1)
            def inventory():
                while not self.inventory_stop.wait(2):
                    try: self.refresh()
                    except Exception as exc: self.errors.append('Inventory: '+str(exc))
            def collect():
                try:
                    for line in self.process.stdout:
                        try:
                            row=parse_stats_line(line)
                            if row is not None: self.accept(row)
                        except (ValueError,KeyError) as exc: self.errors.append(str(exc))
                    if not getattr(self,'closing',False): self.errors.append('Docker stats ended unexpectedly')
                except Exception as exc: self.errors.append(str(exc))
            self.thread = threading.Thread(target=collect,daemon=True)
            self.inventory_thread = threading.Thread(target=inventory,daemon=True)
            self.thread.start()
            self.inventory_thread.start()
        except Exception as exc:
            self.errors.append(str(exc))

    def close(self):
        self.closing = True
        self.inventory_stop.set()
        if self.process:
            if self.process.poll() is None: self.process.terminate()
            try: self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait(timeout=5)
            if self.thread: self.thread.join(timeout=15)
            if self.thread and self.thread.is_alive(): raise RuntimeError('Resource collector did not stop')
            self.process.stdout.close()
        if self.inventory_thread:
            self.inventory_thread.join(timeout=25)
            if self.inventory_thread.is_alive(): raise RuntimeError('Resource inventory did not stop')
        self.event('phase_end',phase=self.phase)
        atomic_json(self.directory/'resource-collection.json',{'schema_version':1,'errors':self.errors})


def lines(path):
    return [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []


def stats(values):
    values = sorted(v for v in values if v is not None)
    return {'samples':len(values),'median':statistics.median(values) if values else None,
        'p95':values[int(.95*(len(values)-1))] if values else None,
        'maximum':max(values) if values else None,'above_2_4':sum(v>2.4 for v in values)}


def plot_points(rows, origin):
    """Break traces across unavailable samples, stops and replacements."""
    xs,ys=[],[]
    previous=None
    for row in rows:
        if previous is not None and (row['monotonic_s']-previous['monotonic_s']>5 or
                row.get('container_id')!=previous.get('container_id')):
            xs.append(row['monotonic_s']-origin);ys.append(None)
        xs.append(row['monotonic_s']-origin);ys.append(row['cpu_cores'])
        previous=row
    return xs,ys


def analyze(directory, *, output_directory=None):
    directory = Path(directory)
    rows = lines(directory/'container-resources.jsonl')
    events = lines(directory/'resource-phases.jsonl')
    collection_path=directory/'resource-collection.json'
    collection = json.loads(collection_path.read_text()) if collection_path.exists() else {'errors':['Container detail unavailable']}
    groups = {}
    known_slots={r['container_id']:r['slot'] for r in rows}
    # Bucket by monotonic second, phase and slot; aggregate each container once.
    buckets = {}
    for r in rows:
        key=(r['slot'],r['phase'],r['batch'])
        buckets.setdefault(key,{})[r['container_id']]=r
        groups.setdefault((r['slot'],r['phase'],r['service']),[]).append(r)
    totals=[]
    for (slot,phase,bucket), members in buckets.items():
        vals=list(members.values())
        expected={cid for r in vals for cid in r['expected_container_ids']
                  if r.get('expected_slots',known_slots).get(cid)==slot}
        totals.append(dict(slot=slot,phase=phase,monotonic_s=max(r['monotonic_s'] for r in vals),
            cpu_cores=sum(r['cpu_cores'] for r in vals) if set(members)==expected and all(r['cpu_cores'] is not None for r in vals) else None,
            services=sorted(r['service'] for r in vals)))
    summaries=[]
    for (slot,phase,service), values in groups.items():
        times=sorted(r['monotonic_s'] for r in values)
        gaps=[b-a for a,b in zip(times,times[1:])]
        summaries.append(dict(slot=slot,phase=phase,service=service,**stats(r['cpu_cores'] for r in values),
            median_interval_s=statistics.median(gaps) if gaps else None,maximum_gap_s=max(gaps,default=None)))
    complete=bool(rows) and not collection['errors']
    coverage=[]
    for phase,slot in [('source_stable','sat-a'),('target_stable','sat-b')]:
        starts=[e['monotonic_s'] for e in events if e['kind']=='phase_start' and e.get('phase')==phase]
        ends=[e['monotonic_s'] for e in events if e['kind']=='phase_end' and e.get('phase')==phase]
        relevant=[s for s in summaries if s['slot']==slot and s['phase']==phase]
        valid=bool(starts and ends and ends[-1]-starts[0]>=119.9 and relevant)
        for s in relevant:
            times=sorted(r['monotonic_s'] for r in groups[(slot,phase,s['service'])])
            gap=max([times[0]-starts[0],ends[-1]-times[-1],s['maximum_gap_s'] or 0])
            valid=valid and gap<=5
        valid=valid and len(relevant)>=9
        total_times=sorted(r['monotonic_s'] for r in totals if r['slot']==slot and r['phase']==phase and r['cpu_cores'] is not None)
        if valid and total_times:
            total_gaps=[b-a for a,b in zip(total_times,total_times[1:])]
            valid=max([total_times[0]-starts[0],ends[-1]-total_times[-1],*total_gaps])<=5
        else: valid=False
        coverage.append({'phase':phase,'slot':slot,'complete':valid})
        complete=complete and valid
    # Container downtime is not a collector gap: check only while still running.
    inventories=[e for e in events if e['kind']=='inventory']
    gaps=[]
    by_id={}
    for r in rows: by_id.setdefault(r['container_id'],[]).append(r)
    for cid,seq in by_id.items():
        seq=sorted(seq,key=lambda r:r['monotonic_s'])
        for a,b in zip(seq,seq[1:]):
            if b['monotonic_s']-a['monotonic_s']<=5: continue
            stopped=any(a['monotonic_s']<=e['monotonic_s']<=b['monotonic_s'] and
                cid not in {c['container_id'] for c in e['containers']} for e in inventories)
            if not stopped: gaps.append({'container_id':cid,'start':a['monotonic_s'],'end':b['monotonic_s']})
    complete=complete and not gaps
    output={'schema_version':1,'complete':bool(complete),'percentile_method':'floor(0.95*(N-1))',
        'source_directory':str(directory.resolve()),
        'container_summaries':summaries,'slot_samples':totals,'coverage':coverage,'errors':collection['errors'],'gaps':gaps,
        'slot_summaries':[dict(slot=slot,phase=phase,**stats(r['cpu_cores'] for r in totals
            if r['slot']==slot and r['phase']==phase)) for slot,phase in sorted({(r['slot'],r['phase']) for r in totals})],
        'detail_available':bool(rows),'limitations':['Docker interval samples, not continuous coverage',
        'Concurrent operations do not establish causality','Shared daemon costs outside containers are excluded']}
    if output_directory is not None:
        directory=Path(output_directory)
        directory.mkdir(parents=True,exist_ok=False)
    atomic_json(directory/'resource-analysis.json',output)
    with (directory/'resource-summary.csv').open('w',newline='',encoding='utf-8') as f:
        fields=['slot','phase','service','samples','median','p95','maximum','above_2_4','median_interval_s','maximum_gap_s']
        w=csv.DictWriter(f,fields); w.writeheader();w.writerows(summaries)
    with (directory/'resource-samples.csv').open('w',newline='',encoding='utf-8') as f:
        fields=['timestamp_utc','monotonic_s','batch','slot','phase','container_id','service','category','cpu_cores','ram_gib']
        w=csv.DictWriter(f,fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
    with (directory/'resource-slot-summary.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,['slot','phase','samples','median','p95','maximum','above_2_4'])
        w.writeheader();w.writerows(output['slot_summaries'])
    if rows:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        origin=min(r['monotonic_s'] for r in rows)
        fig,axes=plt.subplots(2,1,figsize=(14,9),sharex=True)
        for slot,ax in zip(ROLES,axes):
            for service in sorted({r['service'] for r in rows if r['slot']==slot}):
                seq=[r for r in rows if r['slot']==slot and r['service']==service]
                ax.plot(*plot_points(seq,origin),label=service,alpha=.65)
            seq=sorted([r for r in totals if r['slot']==slot],key=lambda r:r['monotonic_s'])
            ax.plot(*plot_points(seq,origin),label='slot total (stream batches)',color='black')
            ax.axhline(2.4,color='red',linestyle='--',label='2.4 cores')
            for e in events:
                if e['kind']=='phase_start':
                    x=e['monotonic_s']-origin;ax.axvline(x,color='grey',alpha=.25)
                    ax.text(x,.98,e['phase'],transform=ax.get_xaxis_transform(),rotation=90,va='top',fontsize=6)
                elif e['kind']=='operation_start' and e.get('operation')=='topology_update' and e.get('slot')==slot:
                    ax.axvline(e['monotonic_s']-origin,color='orange',alpha=.2)
            ax.set_ylabel(slot+' CPU cores'); ax.legend(fontsize=6,ncol=3)
        axes[-1].set_xlabel('Wall seconds from first sample');fig.tight_layout()
        fig.savefig(directory/'resource-timeline.svg');fig.savefig(directory/'resource-timeline.png');plt.close(fig)
    return output
