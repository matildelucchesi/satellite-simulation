import json
import os
import sys
import time
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace

from src.live_backend import Compose
from src.preparation_budget import PreparationBudget, DEFAULTS
from src.progress import advance
from src.results import finalize, read_result
from src.processes import run_process
from src.jobs import process_running
from src.storage import read_json
from src.preparation import Preparation
from src.storage import atomic_json


class PreparationProgressTests(unittest.TestCase):
    def test_stages_have_independent_budgets_and_a_bounded_total(self):
        with tempfile.TemporaryDirectory() as directory:
            clock=[100.0];events=[]
            with patch('src.preparation_budget.time.monotonic',side_effect=lambda:clock[0]):
                budget=PreparationBudget(Path(directory),{},events.append)
                with budget.stage('start_source'):
                    clock[0]+=179
                    self.assertAlmostEqual(budget.remaining(),1)
                with budget.stage('start_target'):
                    self.assertAlmostEqual(budget.remaining(),180)
                self.assertEqual(budget.total_limit,sum(DEFAULTS.values()))
            rows=[json.loads(line) for line in (Path(directory)/'preparation-operations.jsonl').read_text().splitlines()]
            self.assertEqual(rows[0]['elapsed_s'],179)
            self.assertEqual(events[0]['operation_status'],'running')

    def test_startup_timeout_preserves_operation_and_elapsed_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            budget=PreparationBudget(Path(directory),{},Mock())
            with self.assertRaises(subprocess.TimeoutExpired):
                with budget.stage('start_source'):
                    raise subprocess.TimeoutExpired(['docker'],180)
            error=json.loads((Path(directory)/'preparation-error.json').read_text())
            self.assertEqual(error['code'],'startup_timeout')
            self.assertEqual(error['operation'],'start_source')
            self.assertEqual(error['limit_s'],180)

    def test_exhausted_budget_does_not_launch_docker(self):
        command=Compose('.')
        command.remaining=lambda:0
        with patch('src.live_backend.run_process') as run:
            with self.assertRaises(TimeoutError):command.start('sat-a')
            run.assert_not_called()

    def test_invalid_baseline_is_never_valid_even_without_baseline_file(self):
        result=finalize({'run_id':'run-test','outcome':'invalid_baseline'})
        self.assertFalse(result['experimental_valid'])
        self.assertFalse(result['measurement_valid'])
        self.assertFalse(result['success'])
        self.assertIsNone(read_result({'success':True})['experimental_valid'])

    def test_replica_and_operation_progress_survive_terminal_event(self):
        p=advance({}, {'phase':'calibration','method':'hot','replica':2})
        self.assertEqual(p['calibration_index'],5)
        p=advance(p,{'phase':'preparation_operation','operation':'start_source','label':'Avvio',
                     'operation_status':'failed','error':{'code':'startup_timeout'}})
        p=advance(p,{'phase':'comparison_finished','outcome':'failed'})
        self.assertEqual(p['error']['code'],'startup_timeout')
        self.assertEqual(p['phase'],'finished')

    def test_repeated_baseline_samples_do_not_fake_progress(self):
        sample={'phase':'baseline_check','fresh_ping_successes':0,'udp_packets':0,'active_slot':None}
        p=advance({},sample)
        with patch('src.progress.utc_now',return_value='later'):
            self.assertEqual(advance(p,sample)['last_progress_utc'],p['last_progress_utc'])

    def test_unknown_or_unbounded_budgets_are_rejected(self):
        for values in ({'baseline':0},{'baseline':float('inf')},{'wrong':10}):
            with self.assertRaises(ValueError):PreparationBudget(Path('.'),{'live':{'preparation_budgets_s':values}},Mock())

    @unittest.skipUnless(os.name == 'nt', 'Windows snapshot replacement race')
    def test_state_reader_recovers_from_transient_access_denial(self):
        with patch('pathlib.Path.read_text',side_effect=[PermissionError('sharing'),'{"phase":"running"}']), patch('src.storage.time.sleep'):
            self.assertEqual(read_json('state.json'),{'phase':'running'})

    def test_cancellation_is_not_relabelled_as_an_unrelated_unhealthy_service(self):
        with tempfile.TemporaryDirectory() as directory:
            budget=PreparationBudget(Path(directory),{},Mock(),lambda:{'containers':[{'name':'other','health':'unhealthy'}]})
            with self.assertRaises(InterruptedError):
                with budget.stage('start_source'):raise InterruptedError('cancel')
            self.assertEqual(budget.error['code'],'interrupted')

    def test_calibration_rejects_implementation_changes_before_publishing_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            atomic_json(root/'results/functional-gate.json',{'complete':True})
            app=SimpleNamespace(root=root,prepare_calibration_network=Mock(),publish=Mock(),calibration_manifest=Mock(),
                run=Mock(side_effect=[{'run_id':str(i),'success':True,'baseline':{'success':True}} for i in range(6)]))
            with patch('src.simulation.engine_fingerprint',side_effect=['before','after']):
                result=Preparation.calibrate(app)
            self.assertFalse(result['complete'])
            self.assertEqual(result['reason'],'implementation_changed_during_calibration')
            app.calibration_manifest.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Windows Compose process-tree regression')
    def test_cancellation_stops_descendants_that_hold_output_pipes(self):
        with tempfile.TemporaryDirectory() as directory:
            marker=Path(directory)/'child.pid'
            child="import os,time;from pathlib import Path;Path("+repr(str(marker))+").write_text(str(os.getpid()));time.sleep(60)"
            parent="import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',"+repr(child)+"]);time.sleep(60)"
            def check():
                if marker.exists(): raise InterruptedError('cancel')
            started=time.monotonic()
            with self.assertRaises(InterruptedError):run_process([sys.executable,'-c',parent],check=check,timeout=10)
            self.assertLess(time.monotonic()-started,8)
            self.assertFalse(process_running(int(marker.read_text())))
