"""One durable lab job at a time; worker lifetime is independent of the browser."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path
from .storage import atomic_json, append_json, utc_now, read_json
from .results import requires_recovery
from .checkpoints import ActiveCheckpoint

OPERATIONS = {'resource_diagnostic','simulate','functional','continuous_validation','environment','run','calibrate','select','campaign','faults','sensitivity','report','recover','diagnostic','complete'}
OPERATIONS.add('compare_continuous')
OPERATIONS.add('expand_constellation')


def process_running(pid):
    if not pid:return False
    if os.name=='nt':
        import csv
        output=subprocess.check_output(['tasklist','/FI',f'PID eq {int(pid)}','/FO','CSV','/NH'],text=True,timeout=10)
        # An unavailable process listing must not certify that the lab owner died.
        if output is None:return True
        return any(len(row)>1 and row[1]==str(pid) for row in csv.reader(output.splitlines()))
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False
    except PermissionError:return True


class BusyError(RuntimeError): pass


class JobManager:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.directory = self.root/'results/jobs'
        self.directory.mkdir(parents=True,exist_ok=True)
        self.guard = self.directory/'lab.lock'

    def validate(self, operation, parameters):
        if operation not in OPERATIONS: raise ValueError('Unknown application operation')
        if operation=='expand_constellation':
            selection=read_json(self.root/'config/selected_constellation.json')
            if len(selection['satellites']) not in (17,42):
                raise ValueError('Espansione già completata; nessun ulteriore aggiornamento automatico previsto')
        if operation == 'compare_continuous':
            if any(key in parameters for key in ('initial_satellite_id','start_orbital_s')):
                raise ValueError('La partenza è esclusivamente automatica')
            from .continuous_comparison import validate_parameters
            validate_parameters(parameters)
            return
        if operation == 'simulate':
            from .planner import validate_parameters
            validate_parameters(parameters)
            return
        allowed = {'method','rate_bps','event_id'} if operation == 'run' else set()
        if set(parameters)-allowed: raise ValueError('Unsupported job parameter')
        if operation == 'run':
            if parameters.get('method') not in ('cold','hot'): raise ValueError('Choose cold or hot')
            if parameters.get('rate_bps') not in (100000000,1000000000,10000000000): raise ValueError('Unapproved rate')

    def start(self, operation, parameters=None):
        parameters = parameters or {}
        self.validate(operation,parameters)
        if operation=='recover':
            return self.start_recovery()
        # History may have been cleared while this server remained running.
        self.directory.mkdir(parents=True, exist_ok=True)
        job_id = 'job-'+uuid.uuid4().hex
        try: descriptor = os.open(self.guard,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
        except FileExistsError: raise BusyError('A laboratory job or recovery-required checkpoint already holds the lock')
        with os.fdopen(descriptor,'w') as handle:
            json.dump({'job_id':job_id,'created_utc':utc_now(),'launcher_pid':os.getpid()},handle)
            handle.flush();os.fsync(handle.fileno())
        directory = self.directory/job_id
        directory.mkdir()
        atomic_json(directory/'job.json',{'job_id':job_id,'operation':operation,'parameters':parameters,
                    'status':'queued','created_utc':utc_now(),'worker_pid':None})
        try:
            with (directory/'worker.log').open('w',encoding='utf-8') as log:
                kwargs = {'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}
                process=subprocess.Popen([sys.executable,str(self.root/'tools/experiment.py'),'--worker',job_id],
                                         cwd=self.root,stdout=log,stderr=subprocess.STDOUT,**kwargs)
                atomic_json(self.guard,{'job_id':job_id,'created_utc':utc_now(),'worker_pid':process.pid})
        except Exception as exc:
            atomic_json(directory/'job.json',{'job_id':job_id,'status':'failed','error':str(exc)})
            self.guard.unlink()
            raise
        return self.get(job_id)

    def start_recovery(self):
        if not self.guard.exists():raise ValueError('No interrupted laboratory job to recover')
        guard=json.loads(self.guard.read_text())
        if process_running(guard.get('worker_pid',guard.get('launcher_pid'))):
            raise BusyError('Worker is alive; request interruption and wait for its recovery')
        target=self.recovery_target(guard['job_id'])
        claim=self.directory/'recovery.lock'
        if claim.exists():
            owner=json.loads(claim.read_text())
            if process_running(owner['pid']):raise BusyError('Recovery already claimed')
            claim.unlink()
        try:descriptor=os.open(claim,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
        except FileExistsError:raise BusyError('Recovery already claimed')
        with os.fdopen(descriptor,'w') as stream:json.dump({'pid':os.getpid()},stream)
        try:
            # Retain previous lock as evidence, then acquire normal exclusivity.
            previous=target
            atomic_json(self.directory/guard['job_id']/'interrupted-lock.json',guard)
            job_id='job-'+uuid.uuid4().hex
            directory=self.directory/job_id;directory.mkdir()
            atomic_json(self.guard,{'job_id':job_id,'launcher_pid':os.getpid(),'created_utc':utc_now()})
            atomic_json(directory/'job.json',{'job_id':job_id,'operation':'recover','parameters':{},
                'previous_job_id':previous,'status':'queued','created_utc':utc_now(),'worker_pid':None})
            with (directory/'worker.log').open('w') as log:
                kwargs={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}
                process=subprocess.Popen([sys.executable,str(self.root/'tools/experiment.py'),'--worker',job_id],
                    cwd=self.root,stdout=log,stderr=subprocess.STDOUT,**kwargs)
                atomic_json(self.guard,{'job_id':job_id,'created_utc':utc_now(),'worker_pid':process.pid})
            return self.get(job_id)
        finally:claim.unlink(missing_ok=True)

    def recovery_target(self, identifier):
        """Retries recover the original operation and its checkpoint, never another recovery."""
        seen=set()
        while identifier not in seen:
            seen.add(identifier)
            job=self.get(identifier)
            if job['operation']!='recover':return identifier
            identifier=job.get('previous_job_id')
            if not identifier:raise ValueError('Recovery has no original operation')
        raise ValueError('Cyclic recovery history')

    def get(self, job_id):
        if not job_id.startswith('job-') or len(job_id)!=36 or any(c not in '0123456789abcdef' for c in job_id[4:]):
            raise ValueError('Invalid job identifier')
        return self.with_progress(read_json(self.directory/job_id/'job.json'))

    def with_progress(self, job):
        job['cancellation_requested'] = (self.directory/job['job_id']/'cancel.json').exists()
        for name in ('progress', 'worker-heartbeat'):
            path = self.directory/job['job_id']/(name+'.json')
            if path.exists(): job[name.replace('-', '_')] = read_json(path)
        return job

    def list(self):
        return sorted([self.with_progress(read_json(p)) for p in self.directory.glob('job-*/job.json')],
                      key=lambda row:row.get('created_utc',''),reverse=True)

    def stop(self, job_id):
        job=self.get(job_id)
        if job['status'] not in ('queued','running'): raise ValueError('Job is not running')
        atomic_json(self.directory/job_id/'cancel.json',{'requested_utc':utc_now()})

    def work(self, job_id):
        from .experiment import Experiment
        job=self.get(job_id)
        guard=json.loads(self.guard.read_text())
        if guard['job_id']!=job_id: raise BusyError('Worker does not own laboratory lock')
        directory=self.directory/job_id
        job.update(status='running',worker_pid=os.getpid(),started_utc=utc_now())
        atomic_json(directory/'job.json',job)
        guard['worker_pid']=os.getpid();atomic_json(self.guard,guard)
        cancel=threading.Event();finished=threading.Event()
        def watch():
            last_heartbeat = 0
            while not finished.wait(.1):
                if (directory/'cancel.json').exists(): cancel.set()
                if time.monotonic()-last_heartbeat >= 2:
                    try: atomic_json(directory/'worker-heartbeat.json', {'timestamp_utc': utc_now()})
                    except OSError:
                        # Liveness reporting must never disable cancellation.
                        pass
                    last_heartbeat = time.monotonic()
        threading.Thread(target=watch,daemon=True).start()
        sequence=[0]
        event_lock=threading.Lock()
        def publish(event):
            with event_lock:
                from .progress import advance
                progress_path = directory/'progress.json'
                previous = read_json(progress_path) if progress_path.exists() else {}
                atomic_json(progress_path, advance(previous, event))
                checkpoint=directory/'active-checkpoint.json'
                if checkpoint.exists():
                    active=json.loads(checkpoint.read_text())
                    if active.get('kind') in ('run','simulation'):
                        active.update({key:event[key] for key in ('phase','orbital_s','source_slot','target_slot','migration_id') if key in event})
                        active['timestamp_utc']=utc_now()
                        atomic_json(checkpoint,active)
                sequence[0]+=1
                append_json(directory/'events.jsonl',{**event,'id':sequence[0],'job_id':job_id,'timestamp_utc':utc_now()})
        application=Experiment(self.root,cancel,publish)
        application.job_id=job_id
        application.checkpoint=ActiveCheckpoint(directory/'active-checkpoint.json')
        recovery_required=False
        try:
            operation=job['operation'];parameters=job['parameters']
            if operation=='run':
                event=None
                if parameters.get('event_id'):
                    events=json.loads((self.root/'config/selected_events.json').read_text())['events']
                    event=next(row for row in events if row['event_id']==parameters['event_id'])
                output=application.run(parameters['method'],parameters['rate_bps'],event)
            elif operation=='recover':
                output=application.recover(job['previous_job_id'])
                from .continuous_comparison import reconcile_recovery
                reconcile_recovery(application,job['previous_job_id'],output)
            elif operation=='simulate':output=application.simulate(**parameters)
            elif operation=='compare_continuous':output=application.compare_continuous(**parameters)
            else: output=getattr(application,operation)()
            output['recovery_required']=requires_recovery(output)
            atomic_json(directory/'result.json',output)
            recovery_required=requires_recovery(output)
            job['status']='recovery_required' if recovery_required else 'interrupted' if cancel.is_set() else 'completed'
            job['result_path']=str(directory/'result.json')
            job['application_success']=output.get('complete',output.get('success',False))
        except Exception as exc:
            job.update(status='failed',error=str(exc),traceback=traceback.format_exc())
            # An unknown failure of a mutating operation leaves the durable lock.
            recovery_required=job['operation'] not in ('environment','report','select','sensitivity')
            if recovery_required: job['status']='recovery_required'
        finally:
            finished.set()
            job['finished_utc']=utc_now();atomic_json(directory/'job.json',job)
            publish({'phase':'job_finished','status':job['status']})
            if not recovery_required and self.guard.exists():
                if json.loads(self.guard.read_text())['job_id']==job_id:self.guard.unlink()
