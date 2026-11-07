import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.fixture import build, hosts, service_endpoints, state
from src.orbit import Orbit, load_orbit
from tools.install_scenario import service_endpoints as choose_endpoints, unique_shortest_path, windows_from_links

IDS = [1, 2, 3, 4, 5]
LINKS = [  # chain 1-2-3-4-5; link 3-4 only usable in [0, 50)
    {'sat_a': 1, 'sat_b': 2, 'start_s': 0, 'end_s': 100, 'kind': 'intra', 'assigned_start_s': 0},
    {'sat_a': 2, 'sat_b': 3, 'start_s': 0, 'end_s': 100, 'kind': 'intra', 'assigned_start_s': 0},
    {'sat_a': 3, 'sat_b': 4, 'start_s': 0, 'end_s': 50, 'kind': 'inter', 'assigned_start_s': 0},
    {'sat_a': 4, 'sat_b': 5, 'start_s': 0, 'end_s': 100, 'kind': 'intra', 'assigned_start_s': 0},
]


def replay(directory):
    positions = np.zeros((100, len(IDS), 3))
    for column in range(len(IDS)):
        positions[:, column] = [7000.0 + 100.0 * column, 0.0, 0.0]
    path = Path(directory) / 'replay.npz'
    np.savez_compressed(path, ids=np.array(IDS), positions=positions, eclipsed=np.zeros((100, len(IDS)), dtype=bool))
    return path


class LaserOrbitTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.orbit = Orbit(replay(self.directory.name), links=LINKS, domain=[1, 2, 3])

    def tearDown(self):
        self.directory.cleanup()

    def test_graph_follows_link_intervals_with_distances(self):
        graph = self.orbit.graph(10)
        self.assertEqual(graph[3], {2: 100.0, 4: 100.0})
        self.assertNotIn(4, self.orbit.graph(60)[3])

    def test_lab_graph_keeps_only_domain(self):
        self.assertEqual(self.orbit.lab_graph(10), {1: {2: 100.0}, 2: {1: 100.0, 3: 100.0}, 3: {2: 100.0}})

    def test_migration_link_is_multi_hop_and_breaks_with_the_path(self):
        self.assertTrue(self.orbit.migration_link(1, 5, 10))
        self.assertFalse(self.orbit.contact(1, 5, 10))
        self.assertFalse(self.orbit.migration_link(1, 5, 60))
        self.assertFalse(self.orbit.migration_link(1, 5, 100))
        self.assertEqual(self.orbit.migration_path(1, 5, 10), [1, 2, 3, 4, 5])
        self.assertIsNone(self.orbit.migration_path(1, 5, 60))

    def test_domain_must_belong_to_replay(self):
        with self.assertRaises(ValueError):
            Orbit(replay(self.directory.name), links=LINKS, domain=[1, 9])

    def test_without_domain_the_lab_sees_every_link(self):
        orbit = Orbit(replay(self.directory.name), links=LINKS)
        self.assertEqual(orbit.lab_graph(10), orbit.graph(10))


class DomainFixtureTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        (self.root / 'config').mkdir()
        (self.root / 'results').mkdir()
        (self.root / 'artifacts/orbit').mkdir(parents=True)
        selection = {'satellites': [{'norad_id': sid, 'plane': 1 if sid < 4 else 2, 'phase_rank': sid} for sid in IDS]}
        (self.root / 'config/selected_constellation.json').write_text(json.dumps(selection))
        windows = windows_from_links({'inputs': {'duration_s': 100, 'range_km': 1700, 'alignment_s': 60,
                                                 'terminals': {'intra_plane': 2, 'inter_plane': 1}}, 'links': LINKS})
        (self.root / 'results/direct_link_windows.json').write_text(json.dumps(windows))
        domain = {'plane_1': [1, 2, 3], 'plane_2': [4]}
        domain['service_endpoints'] = choose_endpoints(domain)
        (self.root / 'config/domain.json').write_text(json.dumps(domain))
        (self.root / 'config/scenario.json').write_text(json.dumps({'fso': {'laser_terminals': {'intra_plane': 2}, 'max_range_km': 1700}}))
        replay_path = replay(self.directory.name)
        (self.root / 'artifacts/orbit/replay.npz').write_bytes(replay_path.read_bytes())

    def tearDown(self):
        self.directory.cleanup()

    def test_windows_schema_matches_direct_link_windows(self):
        windows = json.loads((self.root / 'results/direct_link_windows.json').read_text())
        self.assertEqual(windows['window_count'], 4)
        self.assertEqual(windows['windows_at_least_alignment_count'], 3)
        self.assertTrue(all(row['duration_s'] == row['end_s'] - row['start_s'] for row in windows['windows']))

    def test_fixture_emulates_only_domain_with_domain_service_hosts(self):
        fixture = build(self.root)
        self.assertEqual([row['norad'] for row in fixture['emulator']['devices']], [1, 2, 3, 4])
        self.assertEqual(fixture['emulator']['pairs'], [(1, 2), (2, 3), (3, 4)])
        self.assertEqual(fixture['forwarding'], 'service-path-only')
        self.assertEqual(service_endpoints(fixture), (1, 3))
        self.assertEqual(choose_endpoints({'plane_1': [7, 8, 9], 'plane_2': [1, 2]}), [7, 9])
        self.assertEqual([host['name'] for host in hosts(fixture)], ['h1', 'h2'])
        self.assertIn('h1', fixture['emulator']['devices'][0]['ports'])

    def test_load_orbit_applies_links_and_domain_and_state_uses_lab_graph(self):
        orbit = load_orbit(self.root)
        self.assertEqual(orbit.domain, [1, 2, 3, 4])
        fixture = build(self.root)
        document = state(fixture, orbit.lab_graph(10))
        self.assertEqual(len(document['entities']['devices']), 4)
        self.assertEqual(len(document['entities']['links']), 6)
        self.assertEqual(len(document['entities']['services']), 1)
        settings = json.loads(document['entities']['services'][0]['service_config']['config_rules'][0]['custom']['resource_value'])
        # Satellite 4 is reachable but off the service path: TeraFlow would not program it.
        self.assertEqual(sorted(key for row in settings['switch_info'] for key in row), ['sat-1', 'sat-2', 'sat-3'])

    def test_unique_shortest_path_rejects_ladder_ties(self):
        rail = {1: {2}, 2: {1, 3}, 3: {2}}
        self.assertEqual(unique_shortest_path(rail, 1, 3), [1, 2, 3])
        ladder = {1: {2, 3}, 2: {1, 4}, 3: {1, 4}, 4: {2, 3}}
        self.assertIsNone(unique_shortest_path(ladder, 1, 4))
        self.assertIsNone(unique_shortest_path({1: set(), 2: set()}, 1, 2))

    def test_load_orbit_requires_the_laser_model(self):
        (self.root / 'config/scenario.json').write_text(json.dumps({'fso': {}}))
        with self.assertRaises(ValueError):
            load_orbit(self.root)


if __name__ == '__main__':
    unittest.main()
