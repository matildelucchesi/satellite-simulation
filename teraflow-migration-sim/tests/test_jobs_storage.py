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
