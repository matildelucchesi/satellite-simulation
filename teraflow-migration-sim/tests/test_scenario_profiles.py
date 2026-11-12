import json
import tempfile
import unittest
from pathlib import Path

from src.web import scenario_profiles


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


class ScenarioProfileApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        write(self.root / 'config/scenario.json', {'orbital': {'constellation_profile': 'old'}})
        self.profile = self.root / 'artifacts/constellation-profiles/new'
        write(self.profile / 'scenario.json', {'orbital': {'constellation_profile': 'new'},
                                               'fso': {'useful_throughput_bps': [1000000000],
                                                       'laser_terminals': {'intra_plane': 2, 'inter_plane': 1}}})
        event = {'event_id': 'a-1', 'source': 1, 'destination': 5, 'hops': 4, 'path': [1, 2, 3, 4, 5], 'trigger_s': 10,
                 'source_shadow_entry_s': 910, 'source_light_remaining_s': 900, 'destination_light_remaining_s': 1800,
                 'light_gained_s': 900, 'reachable_satellites': 9}
        write(self.profile / 'events.json', {'parameters': {'trigger_lead_s': 900}, 'hops_histogram': {'4': 1},
                                             'selected': [event], 'events': [event]})
        write(self.profile / 'domain.json', {'plane_1': [1, 2], 'plane_2': [3, 4]})
        outputs = {name: {'bytes': (self.profile / name).stat().st_size} for name in ('scenario.json', 'events.json', 'domain.json')}
        write(self.profile / 'manifest.json', {'profile': 'new', 'created_utc': 'now', 'outputs': outputs,
                                               'summary': {'satellites': 4}, 'statistics': {'path_segments': 2}})
        # Archived profiles without a manifest are ignored.
        write(self.root / 'artifacts/constellation-profiles/legacy/archive.json', {})

    def tearDown(self):
        self.directory.cleanup()

    def test_summary_lists_profile_selected_events_and_integrity(self):
        profiles = scenario_profiles(self.root)['profiles']
        self.assertEqual(len(profiles), 1)
        profile = profiles[0]
        self.assertEqual(profile['profile'], 'new')
        self.assertFalse(profile['installed'])
        self.assertEqual(profile['integrity'], 'sizes_match')
        self.assertEqual(profile['rate_bps'], [1000000000])
        self.assertEqual(profile['domain'], {'plane_1': [1, 2], 'plane_2': [3, 4]})
        self.assertEqual(profile['selected_events'][0]['path'], [1, 2, 3, 4, 5])
        self.assertNotIn('reachable_satellites', profile['selected_events'][0])
        self.assertEqual((profile['policy_events'], profile['destination_policy']), ([], None))

    def test_policy_events_are_listed_when_built(self):
        events = json.loads((self.profile / 'events.json').read_text(encoding='utf-8'))
        pick = {**events['selected'][0], 'event_id': 'a-1-cost', 'destination': 3, 'hops': 2, 'designed_event_id': 'a-1',
                'replaces_designed_entry': False, 'stay_s': 300, 'control_latency_ms': 12.5}
        events.update(policy_selected=[pick], destination_policy={'parameters': {'availability_min': 0.95}, 'events': []})
        write(self.profile / 'events.json', events)
        manifest = json.loads((self.profile / 'manifest.json').read_text(encoding='utf-8'))
        manifest['outputs']['events.json']['bytes'] = (self.profile / 'events.json').stat().st_size
        write(self.profile / 'manifest.json', manifest)
        profile = scenario_profiles(self.root)['profiles'][0]
        self.assertEqual(profile['integrity'], 'sizes_match')
        [row] = profile['policy_events']
        self.assertEqual((row['event_id'], row['destination'], row['designed_event_id'], row['stay_s']), ('a-1-cost', 3, 'a-1', 300))
        self.assertNotIn('reachable_satellites', row)
        self.assertEqual(profile['destination_policy'], {'availability_min': 0.95})

    def test_changed_output_and_installed_profile_are_reported(self):
        (self.profile / 'domain.json').write_text('{"plane_1": [1], "plane_2": [3, 4, 5, 6]}', encoding='utf-8')
        write(self.root / 'config/scenario.json', {'orbital': {'constellation_profile': 'new'}})
        profile = scenario_profiles(self.root)['profiles'][0]
        self.assertEqual(profile['integrity'], 'changed')
        self.assertEqual(profile['changed_files'], ['domain.json'])
        self.assertTrue(profile['installed'])

    def test_unreadable_profile_is_flagged(self):
        (self.profile / 'events.json').write_text('{', encoding='utf-8')
        self.assertEqual(scenario_profiles(self.root)['profiles'], [{'profile': 'new', 'integrity': 'unreadable'}])


if __name__ == '__main__':
    unittest.main()
