import csv
import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

from src import event_comparison as module
from src.experiment import Experiment


def entry(index, trigger):
    return {'event_id': f'e{index}', 'source': 10 + index, 'destination': 20 + index, 'hops': 5,
            'path': [10 + index, 20 + index], 'trigger_s': trigger, 'source_shadow_entry_s': trigger + 900,
            'source_light_remaining_s': 900, 'destination_light_remaining_s': 1800, 'path_end_s': 86400}


class FakeOrbit:
    duration = 86400
    def contact(self, a, b, tick): return False
    def migration_link(self, a, b, tick): return True


class EventComparisonTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        (self.root / 'config').mkdir()
        (self.root / 'config/migration_events.json').write_text(json.dumps({'selected': [entry(1, 1000), entry(2, 5000)]}))
        (self.root / 'config/scenario.json').write_text('{}')
        (self.root / 'config/fixture.json').write_text('{}')
        self.calls, self.fail, self.recovery = [], set(), set()
        app = SimpleNamespace(root=self.root, orbit=FakeOrbit(), cancel=threading.Event(), publish=lambda event: None,
                              scenario={'fso': {'useful_throughput_bps': [1000000000]}, 'migration': {'software_on_board': True},
                                        'orbital': {'constellation_profile': 'p'},
                                        'experiment': {'replicas': 2, 'warmup_runs': 1, 'seed': 7}})
        app.catalog_event = lambda selected, prefix, causes, purpose: Experiment.catalog_event(app, selected, prefix, causes, purpose)
        app.run = self.run_migration
        self.app = app

    def tearDown(self):
        self.directory.cleanup()

    def run_migration(self, method, rate, event, *, purpose):
        self.calls.append((event['catalog_event_id'], method))
        run_id = f'run-{len(self.calls)}-{uuid.uuid4().hex[:6]}'
        directory = self.root / 'results/runs' / run_id
        directory.mkdir(parents=True)
        (directory / 'operations.jsonl').write_text('\n'.join(json.dumps(row) for row in [
            {'name': 'controller_startup', 'elapsed_s': 60.0}, {'name': 'api_restore', 'elapsed_s': 30.0},
            {'name': 'queued_topology_apply', 'elapsed_s': 5.0}, {'name': 'queued_topology_apply', 'elapsed_s': 6.0}]))
        failed = len(self.calls) in self.fail
        downtime = (120.0 if method == 'cold' else 20.0) + len(self.calls) / 10
        return {'run_id': run_id, 'method': method, 'success': not failed, 'outcome': 'failed' if failed else 'success',
                'baseline': {'success': True}, 'service_verification': {'success': not failed},
                'controller_downtime_s': downtime, 'total_operation_s': 190.0 if method == 'hot' else 1000.0,
                'probes': {'ping': {'observed_probes': 2000, 'lost_probes': 0, 'time_to_stable_recovery_s': None}},
                'software_on_board': True, 'recovery_required': len(self.calls) in self.recovery}

    def test_warmup_then_replicas_over_all_events_with_random_pair_order(self):
        output = module.compare(self.app)
        self.assertTrue(output['complete'])
        plan = output['design']['schedule']
        self.assertEqual(len(plan), 1 + 2 * 2 * 2)
        self.assertTrue(plan[0]['warmup'])
        self.assertEqual([(item['replica'], item['event']) for item in plan[1:]][::2], [(1, 1), (1, 2), (2, 1), (2, 2)])
        for first, second in zip(plan[1::2], plan[2::2]):
            self.assertEqual({first['method'], second['method']}, {'hot', 'cold'})
        self.assertEqual(module.schedule([1, 2], 2, 1, 7), plan)
        self.assertEqual(len(self.calls), len(plan))
        self.assertIn('run', output['warmup'])
        event = output['events'][0]
        self.assertEqual(len(event['replicas']), 2)
        self.assertEqual(event['statistics']['controller_downtime_s']['hot']['n'], 2)
        difference = event['statistics']['controller_downtime_s']['cold_minus_hot']
        self.assertEqual(difference['n'], 2)
        self.assertTrue(99 < difference['median'] < 101)
        self.assertEqual(len(difference['ci95']), 2)
        hot = event['replicas'][0]['runs']['hot']
        self.assertEqual(hot['phases']['seconds']['queued_topology_apply'], 11.0)
        self.assertTrue(hot['feasibility']['fits_before_shadow'])
        self.assertFalse(event['replicas'][0]['runs']['cold']['feasibility']['fits_before_shadow'])
        directory = self.root / 'results/event-comparisons' / output['comparison_id']
        with open(directory / 'summary.csv', encoding='utf-8') as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), len(plan))
        self.assertEqual(rows[0]['warmup'], 'True')
        self.assertEqual(module.list_comparisons(self.root)[0]['comparison_id'], output['comparison_id'])

    def test_a_failed_run_stays_missing_and_the_experiment_continues(self):
        self.fail = {3}
        output = module.compare(self.app)
        self.assertTrue(output['complete'])
        self.assertEqual(output['failed_runs'], 1)
        self.assertEqual(len(self.calls), 9)

    def test_stops_when_recovery_is_required_or_after_three_failures(self):
        self.recovery = {2}
        output = module.compare(self.app)
        self.assertEqual(output['reason'], 'recovery_required')
        self.assertEqual(len(self.calls), 2)
        self.calls, self.recovery, self.fail = [], set(), {2, 3, 4}
        output = module.compare(self.app)
        self.assertEqual(output['reason'], 'too_many_failures')
        self.assertEqual(len(self.calls), 4)

    def test_cancellation_before_next_run(self):
        self.app.cancel.set()
        output = module.compare(self.app)
        self.assertEqual(output['reason'], 'interrupted')
        self.assertEqual(self.calls, [])

    def test_statistics_keep_missing_values_out(self):
        self.assertEqual(module.describe_values([None, 3, 1, 2])['median'], 2)
        self.assertEqual(module.describe_values([])['n'], 0)
        single = module.paired_difference([(1, 5), (2, None)], seed=1)
        self.assertEqual((single['n'], single['median'], single['ci95']), (1, 4, None))

    def test_requires_single_rate_and_catalogue(self):
        self.app.scenario['fso']['useful_throughput_bps'] = [1, 2]
        with self.assertRaises(ValueError):
            module.compare(self.app)
        (self.root / 'config/migration_events.json').unlink()
        with self.assertRaises(ValueError):
            module.compare(self.app)

    def test_differences_need_both_values(self):
        self.assertEqual(module.differences({'hot': {'controller_downtime_s': 1}}), {})
        result = module.differences({'hot': {'controller_downtime_s': 1, 'total_operation_s': None},
                                     'cold': {'controller_downtime_s': 4, 'total_operation_s': 2}})
        self.assertEqual(result['controller_downtime_s'], 3)
        self.assertIsNone(result['total_operation_s'])


if __name__ == '__main__':
    unittest.main()
