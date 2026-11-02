import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import validate_guided_flow as validation
from src.storage import atomic_json


class GuidedValidationTests(unittest.TestCase):
    def test_terminal_job_uses_experimental_result_without_probing_dead_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identifier = 'job-' + 'a' * 32
            pair = 'pair-' + 'b' * 32
            queued = {'job_id': identifier, 'status': 'running', 'worker_pid': 123}
            terminal = {**queued, 'status': 'completed'}
            manager = Mock(directory=root / 'results/jobs')
            manager.start.return_value = queued
            manager.get.return_value = terminal
            atomic_json(manager.directory / identifier / 'result.json', {'comparison_id': pair})
            with patch.object(validation, 'ROOT', root), \
                    patch.object(validation, 'JobManager', return_value=manager), \
                    patch.object(validation.time, 'sleep'), \
                    patch.object(validation, 'process_running', side_effect=AssertionError('Unnecessary process query')) as probe, \
                    patch.object(validation, 'check_comparison', side_effect=AssertionError('No feasible sequence')), \
                    patch('sys.argv', ['validate', '--live']), patch('builtins.print'):
                self.assertEqual(validation.main(), 2)
            probe.assert_not_called()
            manager.start.assert_called_once()
            self.assertEqual(manager.start.call_args.args[1]['selection_rates'],[100000000,1000000000,10000000000])
            self.assertNotIn('initial_satellite_id',manager.start.call_args.args[1])
            summary = json.loads(next((root / 'results/guided-validation').glob('*/summary.json')).read_text())
            self.assertFalse(summary['complete'])
            self.assertEqual(summary['failure'], 'No feasible sequence')
            self.assertEqual(summary['failure_type'], 'AssertionError')
            self.assertEqual(summary['runs'][0]['comparison_id'], pair)
            self.assertIn('No feasible sequence', summary['traceback'])


if __name__ == '__main__':
    unittest.main()
