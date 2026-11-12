import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.fixture import build, connection_path, endpoint_id, hop_distances, hosts, service_endpoints, state
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


def ladder_fixture():
    """Square 1-2-4 / 1-3-4 with a spur 4-5: two fewest-hop paths between the hosts on 1 and 4."""
    pairs = [(1, 2), (1, 3), (2, 4), (3, 4), (4, 5)]
    devices = []
    for index, sid in enumerate([1, 2, 3, 4, 5]):
        neighbors = sorted(b if a == sid else a for a, b in pairs if sid in (a, b))
        ports = {str(neighbor): port + 1 for port, neighbor in enumerate(neighbors)}
        if sid == 1: ports['h1'] = len(neighbors) + 1
        if sid == 4: ports['h2'] = len(neighbors) + 1
        devices.append({'norad': sid, 'dpid': index + 1, 'name': f's{index + 1}', 'grpc_port': 50001 + index,
                        'proxy_port': 51001 + index, 'ports': ports})
    hosts_ = [{'name': 'h1', 'ip': '10.0.0.1/24', 'mac': '00:00:00:00:00:01', 'satellite': 1},
              {'name': 'h2', 'ip': '10.0.0.2/24', 'mac': '00:00:00:00:00:02', 'satellite': 4}]
    fixture = {'schema_version': 1, 'context': 'migration-lab', 'topology': 'starlink-5', 'forwarding': 'service-path-only',
               'service': 'migration-l2', 'emulator': {'devices': devices, 'pairs': pairs, 'hosts': hosts_},
               'controller_proxy': 'p4-proxy', 'pipeline_binary': 'b', 'pipeline_info': 'i'}
    graph = {sid: {} for sid in range(1, 6)}
    for a, b in pairs:
        graph[a][b] = graph[b][a] = 100.0
    return fixture, graph


class TeraFlowPathForwardingTests(unittest.TestCase):
    def settings(self, fixture, graph):
        document = state(fixture, graph)
        rules = document['entities']['services'][0]['service_config']['config_rules']
        return {name: info for row in json.loads(rules[0]['custom']['resource_value'])['switch_info'] for name, info in row.items()}

    def test_every_fewest_hop_path_is_covered_and_nothing_else(self):
        fixture, graph = ladder_fixture()
        settings = self.settings(fixture, graph)
        # 5 hangs off the destination switch, on no fewest-hop path
        self.assertEqual(sorted(settings), ['sat-1', 'sat-2', 'sat-3', 'sat-4'])
        ports = {row['norad']: row['ports'] for row in fixture['emulator']['devices']}
        h1, h2 = '00:00:00:00:00:01', '00:00:00:00:00:02'
        entries = lambda sid: sorted((row['host_mac'], row['port_id']) for row in settings[f'sat-{sid}']['fwd_list'])
        # The source switch sends h2 to both of its next hops, whichever TeraFlow takes
        self.assertEqual(entries(1), sorted([(h1, ports[1]['h1']), (h2, ports[1]['2']), (h2, ports[1]['3'])]))
        self.assertEqual(entries(2), sorted([(h1, ports[2]['1']), (h2, ports[2]['4'])]))
        self.assertEqual(entries(4), sorted([(h1, ports[4]['2']), (h1, ports[4]['3']), (h2, ports[4]['h2'])]))
        # On any one of the two paths every switch has exactly one port per host on that path
        for path in ([1, 2, 4], [1, 3, 4]):
            for position, sid in enumerate(path):
                used = {ports[sid]['h1'] if sid == 1 else ports[sid][str(path[position - 1])],
                        ports[sid]['h2'] if sid == 4 else ports[sid][str(path[position + 1])]}
                macs = {}
                for mac, port in entries(sid):
                    if port in used: macs.setdefault(mac, []).append(port)
                self.assertEqual({mac: len(found) for mac, found in macs.items()}, {h1: 1, h2: 1})

    def test_a_unique_path_gives_one_port_per_host(self):
        fixture, graph = ladder_fixture()
        del graph[1][3], graph[3][1]
        settings = self.settings(fixture, graph)
        self.assertEqual(sorted(settings), ['sat-1', 'sat-2', 'sat-4'])
        self.assertTrue(all(len(info['fwd_list']) == 2 for info in settings.values()))

    def test_without_a_path_no_switch_is_described(self):
        fixture, graph = ladder_fixture()
        for a, b in ((2, 4), (3, 4)):
            del graph[a][b], graph[b][a]
        self.assertEqual(self.settings(fixture, graph), {})

    def test_hop_distances_ignore_link_length(self):
        graph = {1: {2: 1.0, 3: 900.0}, 2: {1: 1.0, 3: 1.0}, 3: {1: 900.0, 2: 1.0}}
        self.assertEqual(hop_distances(graph, 1), {1: 0, 2: 1, 3: 1})
        self.assertEqual(hop_distances(graph, 9), {})

    def test_connection_path_reads_satellites_in_order(self):
        fixture, graph = ladder_fixture()
        document = state(fixture, graph)
        hop = lambda sid, port: endpoint_id(sid, port)
        connection = {'path_hops_endpoint_ids': [hop(1, 3), hop(1, 2), hop(3, 1), hop(3, 2), hop(4, 2), hop(4, 4)]}
        self.assertEqual(connection_path(document, connection), [1, 3, 4])


if __name__ == '__main__':
    unittest.main()
