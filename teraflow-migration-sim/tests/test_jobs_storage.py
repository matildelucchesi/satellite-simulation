import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from src.authority import Authority
from src.jobs import JobManager, BusyError
from src.measurements import size_bytes
from src.storage import atomic_json


class DurableStateTests(unittest.TestCase):
    def test_missing_windows_process_output_keeps_owner_unconfirmed(self):
        from src.jobs import process_running
        with patch('src.jobs.os.name','nt'),patch('src.jobs.subprocess.check_output',return_value=None):
            self.assertTrue(process_running(12345))

    def test_explicit_recovery_fences_run_without_clock_instead_of_restoring_source(self):
        from src.experiment import Experiment
        with tempfile.TemporaryDirectory() as tmp,patch('src.live_backend.Compose.stop') as stop,patch('src.experiment.http'):
            root=Path(tmp);atomic_json(root/'config/scenario.json',{})
            job='job-'+'a'*32;run='run-'+'b'*32
            atomic_json(root/'results/jobs'/job/'job.json',{'job_id':job,'status':'recovery_required'})
            atomic_json(root/'results/jobs'/job/'active-checkpoint.json',{'kind':'run','run_id':run})
            directory=root/'results/runs'/run
            atomic_json(directory/'inputs.json',{'event':{'deadline_s':100}})
            atomic_json(directory/'metadata.json',{'run_id':run,'outcome':'recovery_required','success':False})
            output=Experiment(root).recover(job)
            self.assertTrue(output['complete']);self.assertFalse(output['clock_resumed'])
            self.assertFalse(output['source_restored']);self.assertEqual(stop.call_count,2)
            metadata=json.loads((directory/'metadata.json').read_text())
            self.assertFalse(metadata['success']);self.assertTrue(metadata['controllers_fenced'])
            self.assertEqual(json.loads((directory/'pre-fenced-recovery.json').read_text())['outcome'],'recovery_required')

    def test_recovery_retry_resolves_original_checkpoint_owner(self):
        with tempfile.TemporaryDirectory() as tmp,patch('src.jobs.process_running',return_value=False),patch('src.jobs.subprocess.Popen') as launch:
            launch.return_value.pid=12345;manager=JobManager(Path(tmp))
            original='job-'+'a'*32;first='job-'+'b'*32;second='job-'+'c'*32
            for identifier,operation,previous in ((original,'compare_continuous',None),(first,'recover',original),(second,'recover',first)):
                atomic_json(manager.directory/identifier/'job.json',{'job_id':identifier,'operation':operation,
                    'previous_job_id':previous,'status':'recovery_required'})
            atomic_json(manager.guard,{'job_id':second,'worker_pid':99999})
            job=manager.start_recovery()
            self.assertEqual(job['previous_job_id'],original)
            self.assertTrue((manager.directory/second/'interrupted-lock.json').exists())
            self.assertEqual(manager.get(original)['status'],'recovery_required')

    def test_recovery_cycle_is_rejected_without_replacing_lock(self):
        with tempfile.TemporaryDirectory() as tmp,patch('src.jobs.process_running',return_value=False):
            manager=JobManager(Path(tmp));identifier='job-'+'a'*32
            atomic_json(manager.directory/identifier/'job.json',{'job_id':identifier,'operation':'recover','previous_job_id':identifier})
            atomic_json(manager.guard,{'job_id':identifier,'worker_pid':99999})
            with self.assertRaises(ValueError):manager.start_recovery()
            self.assertEqual(json.loads(manager.guard.read_text())['job_id'],identifier)

    def test_continuous_comparison_worker_dispatches_one_composite_job(self):
        with tempfile.TemporaryDirectory() as tmp, patch('src.jobs.subprocess.Popen') as launch, patch('src.experiment.Experiment') as factory:
            launch.return_value.pid=12345
            application=factory.return_value
            application.compare_continuous.return_value={'complete':True,'success':True,'events':[]}
            manager=JobManager(Path(tmp))
            job=manager.start('compare_continuous',{'duration_s':600,'rate_bps':1000000000})
            manager.work(job['job_id'])
            application.compare_continuous.assert_called_once_with(duration_s=600,rate_bps=1000000000)
            self.assertEqual(application.job_id,job['job_id'])
            self.assertTrue(manager.get(job['job_id'])['application_success'])
            self.assertFalse(manager.guard.exists())

    def test_job_start_recreates_history_directory_removed_after_server_start(self):
        with tempfile.TemporaryDirectory() as tmp, patch('src.jobs.subprocess.Popen') as launch:
            launch.return_value.pid=12345
            manager=JobManager(Path(tmp))
            manager.directory.rmdir()
            job=manager.start('environment')
            self.assertEqual(job['status'],'queued')
            self.assertEqual(json.loads(manager.guard.read_text())['job_id'],job['job_id'])

    def test_restart_requires_explicit_reconciliation(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp)/'authority.json'
            first = Authority(journal=journal)
            first.freeze()
            self.assertTrue(first.ready(images=True, api=True, staged=True))
            first.cutover('sat-b', lambda: None)
            restarted = Authority(journal=journal)
            self.assertIsNone(restarted.active)
            self.assertFalse(restarted.ack)
            self.assertFalse(restarted.writable('sat-a'))
            self.assertFalse(restarted.writable('sat-b'))
            restarted.recover('sat-a', lambda: None)
            self.assertTrue(restarted.writable('sat-a'))

    def test_second_job_refused_and_cancellation_is_durable(self):
        with tempfile.TemporaryDirectory() as tmp, patch('src.jobs.subprocess.Popen') as launch:
            launch.return_value.pid=12345
            manager = JobManager(Path(tmp))
            job = manager.start('environment')
            with self.assertRaises(BusyError): manager.start('environment')
            manager.stop(job['job_id'])
            self.assertTrue((manager.directory/job['job_id']/'cancel.json').is_file())
            self.assertEqual(json.loads(manager.guard.read_text())['job_id'],job['job_id'])

    def test_validation_precedes_lock_and_paths_are_restricted(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = JobManager(Path(tmp))
            with self.assertRaises(ValueError): manager.start('run',{'method':'hot','rate_bps':1})
            self.assertFalse(manager.guard.exists())
            with self.assertRaises(ValueError): manager.get('../escape')

    def test_atomic_json_rejects_nonfinite_without_replacing_previous(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'state.json'
            atomic_json(path, {'value':1})
            with self.assertRaises(ValueError): atomic_json(path, {'value':float('nan')})
            self.assertEqual(json.loads(path.read_text()),{'value':1})

    def test_docker_units(self):
        self.assertEqual(size_bytes('12.5kB'),12500)
        self.assertEqual(size_bytes('1GiB'),1024**3)
        with self.assertRaises(ValueError):size_bytes('unavailable')
