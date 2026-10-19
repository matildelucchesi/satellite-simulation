import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.storage import append_json, atomic_json
from src.topology_state import presentation


class TopologyEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        (self.directory/'operation').mkdir()
        (self.directory/'migrations/migration-one/operation').mkdir(parents=True)
        atomic_json(self.directory/'inputs.json', {'event': {'sat_a': 11, 'sat_b': 22}})

    def tearDown(self):
        self.temp.cleanup()

    def event(self, tick, phase, **extra):
        append_json(self.directory/'operation/events.jsonl',
                    {'orbital_s': tick, 'phase': phase, **extra})

    def confirm(self, tick, slot='sat-a', **proxy):
        append_json(self.directory/'heartbeat.jsonl',
                    {'orbital_s': tick, 'controllers': {slot: True}})
        append_json(self.directory/'authority.jsonl',
                    {'orbital_s': tick+.01, 'proxy': {'active': slot, 'frozen': False, **proxy}})

    def view(self, tick=100, **kwargs):
        return presentation(self.directory, tick, replay=True, **kwargs)

    def test_pair_and_planned_target_do_not_confirm_controller(self):
        view = self.view(context={'placement_status': 'planned', 'controller_satellite': 11,
                                 'next_migration': {'sat_b': 22}})
        self.assertIsNone(view['controller_satellite'])
        self.assertEqual(view['migration_status'], 'planned')
        self.assertEqual(view['target_satellite'], 22)

    def test_authority_requires_healthy_unfrozen_controller(self):
        append_json(self.directory/'authority.jsonl', {'orbital_s': 1, 'proxy': {'active': 'sat-a'}})
        self.assertIsNone(self.view()['controller_satellite'])
        self.confirm(2)
        self.assertEqual(self.view()['controller_satellite'], 11)
        self.confirm(3, frozen=True)
        self.assertIsNone(self.view()['controller_satellite'])

    def test_transfer_and_cutover_use_confirmations_not_phase_names(self):
        self.confirm(1)
        self.event(2, 'transfer')
        self.assertEqual(self.view(2)['controller_satellite'], 11)
        self.assertEqual(self.view(2)['migration_status'], 'transferring')
        self.event(3, 'transfer_verified')
        self.assertEqual(self.view(3)['migration_status'], 'in_progress')
        self.event(4, 'cutover')
        self.assertIsNone(self.view(4)['controller_satellite'])
        self.event(5, 'completed')
        self.assertEqual(self.view(5)['controller_satellite'], 22)

    def test_cold_stop_invalidates_previous_health_until_new_evidence(self):
        self.confirm(1)
        self.event(2, 'source_stopped')
        append_json(self.directory/'authority.jsonl', {'orbital_s': 3, 'proxy': {'active': 'sat-a'}})
        self.assertIsNone(self.view()['controller_satellite'])
        self.event(4, 'rollback')
        self.assertIsNone(self.view()['controller_satellite'])
        self.confirm(5)
        self.assertEqual(self.view()['controller_satellite'], 11)

    def test_replay_does_not_leak_future_completion_or_failure(self):
        self.confirm(1)
        self.event(2, 'transfer')
        self.event(3, 'completed')
        self.event(4, 'recovery_failed')
        self.assertEqual(self.view(2)['controller_satellite'], 11)
        self.assertEqual(self.view(3)['controller_satellite'], 22)
        self.assertIsNone(self.view(4)['controller_satellite'])

    def test_simulation_alternating_slots_and_next_passage(self):
        append_json(self.directory/'observations.jsonl', {'orbital_s': 1,
                    'controller_satellite': 22, 'active_slot': 'sat-b',
                    'next_migration': {'sat_a': 22, 'sat_b': 33},
                    'service_state': {'forwarding_observed': False}})
        append_json(self.directory/'migrations/migration-one/operation/events.jsonl',
                    {'orbital_s': 2, 'phase': 'transfer', 'source_slot': 'sat-b',
                     'target_slot': 'sat-a', 'source_satellite': 22, 'target_satellite': 33})
        self.confirm(3, slot='sat-b')
        view = self.view()
        self.assertEqual(view['controller_satellite'], 22)
        self.assertEqual(view['target_satellite'], 33)
        self.assertFalse(view['forwarding_observed'])

    def test_stale_live_evidence_and_historical_mode(self):
        stamp = (datetime.now(timezone.utc)-timedelta(seconds=60)).isoformat()
        self.event(1, 'transfer', timestamp_utc=stamp)
        self.assertTrue(presentation(self.directory, 2)['stale'])
        self.assertFalse(self.view(2)['stale'])
        self.assertEqual(self.view(2)['mode'], 'replay')

    def test_service_path_does_not_imply_forwarding(self):
        self.event(1, 'completed')
        self.assertIsNone(self.view()['forwarding_observed'])
        self.event(2, 'service_verified')
        self.assertTrue(self.view()['forwarding_observed'])

    def test_geometry_carries_probe_result_without_confirming_logical_host(self):
        append_json(self.directory/'geometry.jsonl', {'orbital_s': 2,
                    'controller_satellite': 11, 'active_slot': 'sat-a',
                    'service_path_available': True, 'forwarding_observed': None})
        self.assertIsNone(self.view()['controller_satellite'])
        self.assertIsNone(self.view()['forwarding_observed'])
        append_json(self.directory/'geometry.jsonl', {'orbital_s': 3,
                    'forwarding_observed': False})
        self.assertFalse(self.view()['forwarding_observed'])

    def test_terminal_fencing_is_visible_in_replay_without_leaking_into_earlier_samples(self):
        append_json(self.directory/'observations.jsonl',{'orbital_s':1,'controller_satellite':11,'active_slot':'sat-a'})
        append_json(self.directory/'observations.jsonl',{'orbital_s':2,'controller_satellite':11,'active_slot':'sat-a','controllers_fenced':True})
        self.assertEqual(self.view(1)['controller_satellite'],11)
        self.assertIsNone(self.view(2)['controller_satellite'])


if __name__ == '__main__':
    unittest.main()
