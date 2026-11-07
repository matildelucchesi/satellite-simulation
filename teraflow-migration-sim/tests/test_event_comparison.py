import csv
import json
import tempfile
import threading
import unittest
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
        self.calls, self.fail = [], None
        app = SimpleNamespace(root=self.root, orbit=FakeOrbit(), cancel=threading.Event(), publish=lambda event: None,
                              scenario={'fso': {'useful_throughput_bps': [1000000000]}, 'migration': {'software_on_board': True},
                                        'orbital': {'constellation_profile': 'p'}})
        app.catalog_event = lambda selected, prefix, causes, purpose: Experiment.catalog_event(app, selected, prefix, causes, purpose)
        app.run = self.run_migration
        self.app = app

    def tearDown(self):
        self.directory.cleanup()

    def run_migration(self, method, rate, event, *, purpose):
        self.calls.append((event['catalog_event_id'], method))
        run_id = f'run-{len(self.calls)}'
        directory = self.root / 'results/runs' / run_id
        directory.mkdir(parents=True)
        (directory / 'operations.jsonl').write_text('\n'.join(json.dumps(row) for row in [
            {'name': 'controller_startup', 'elapsed_s': 60.0}, {'name': 'api_restore', 'elapsed_s': 30.0},
            {'name': 'queued_topology_apply', 'elapsed_s': 5.0}, {'name': 'queued_topology_apply', 'elapsed_s': 6.0}]))
        failed = self.fail == (event['catalog_event_id'], method)
        downtime = 120.0 if method == 'cold' else 20.0
        return {'run_id': run_id, 'method': method, 'success': not failed, 'outcome': 'failed' if failed else 'success',
                'baseline': {'success': True}, 'service_verification': {'success': not failed},
                'controller_downtime_s': downtime, 'total_operation_s': 190.0 if method == 'hot' else 1000.0,
                'probes': {'ping': {'observed_probes': 2000, 'lost_probes': 0, 'time_to_stable_recovery_s': None}},
                'software_on_board': True}

    def test_alternates_order_and_reports_differences_phases_and_feasibility(self):
        output = module.compare(self.app)
        self.assertTrue(output['complete'])
        self.assertEqual(self.calls, [('e1', 'hot'), ('e1', 'cold'), ('e2', 'cold'), ('e2', 'hot')])
        first = output['events'][0]
        self.assertEqual(first['cold_minus_hot']['controller_downtime_s'], 100.0)
        self.assertEqual(first['cold_minus_hot']['lost_pings'], 0)
        self.assertIsNone(first['cold_minus_hot']['ping_recovery_s'])
        hot, cold = first['runs']['hot'], first['runs']['cold']
        self.assertEqual(hot['phases']['seconds']['queued_topology_apply'], 11.0)
        self.assertEqual(hot['phases']['counts']['queued_topology_apply'], 2)
        self.assertTrue(hot['feasibility']['fits_before_shadow'])
        self.assertFalse(cold['feasibility']['fits_before_shadow'])
        self.assertTrue(hot['feasibility']['multi_hop_path_whole_operation'])
        self.assertFalse(hot['feasibility']['direct_contact_whole_operation'])
        directory = self.root / 'results/event-comparisons' / output['comparison_id']
        saved = json.loads((directory / 'metadata.json').read_text())
        self.assertEqual(saved['comparison_id'], output['comparison_id'])
        with open(directory / 'summary.csv', encoding='utf-8') as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([row['method'] for row in rows], ['hot', 'cold', 'cold', 'hot'])
        self.assertEqual(module.list_comparisons(self.root)[0]['comparison_id'], output['comparison_id'])

    def test_stops_at_first_failed_run_without_difference(self):
        self.fail = ('e2', 'cold')
        output = module.compare(self.app)
        self.assertFalse(output['complete'])
        self.assertEqual(output['reason'], 'failed')
        self.assertEqual(self.calls[-1], ('e2', 'cold'))
        self.assertNotIn('cold_minus_hot', output['events'][1])

    def test_cancellation_before_next_run(self):
        self.app.cancel.set()
        output = module.compare(self.app)
        self.assertEqual(output['reason'], 'interrupted')
        self.assertEqual(self.calls, [])

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
