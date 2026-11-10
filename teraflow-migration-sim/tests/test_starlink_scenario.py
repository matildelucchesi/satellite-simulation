import math
import unittest

import numpy as np

from src import starlink_scenario as model


def ring_positions(count_per_plane=12, ticks=200, node_offset_deg=2.0, phase_offset_deg=0.0):
    """Two circular rings at ~463 km, 53 deg inclination, nodes ``node_offset_deg`` apart."""
    radius, inclination = 6841.0, math.radians(53.0)
    omega = 2 * math.pi / 5640.0
    columns, planes, ids = [], [], []
    for plane, node in enumerate((0.0, math.radians(node_offset_deg))):
        e1 = np.array([math.cos(node), math.sin(node), 0.0])
        e2 = np.array([-math.sin(node) * math.cos(inclination), math.cos(node) * math.cos(inclination), math.sin(inclination)])
        for k in range(count_per_plane):
            theta0 = 2 * math.pi * k / count_per_plane + math.radians(phase_offset_deg) * plane
            angles = theta0 + omega * np.arange(ticks)
            columns.append(radius * (np.cos(angles)[:, None] * e1 + np.sin(angles)[:, None] * e2))
            planes.append(plane)
            ids.append(1000 * (plane + 1) + k)
    return np.stack(columns, axis=1), ids, planes


class LaserLinkTests(unittest.TestCase):
    def setUp(self):
        self.positions, self.ids, self.planes = ring_positions()
        self.links = model.laser_links(self.positions, self.ids, self.planes, max_range_km=4000, alignment_s=60)

    def test_three_terminal_rule_holds(self):
        self.assertTrue(model.terminal_usage_ok(self.links, self.ids, self.planes))

    def test_rings_have_two_intra_links_per_satellite_after_alignment(self):
        intra = [row for row in self.links if row['kind'] == 'intra']
        self.assertEqual(len(intra), 24)
        degree = {sid: 0 for sid in self.ids}
        for row in intra:
            self.assertEqual((row['assigned_start_s'], row['start_s'], row['end_s']), (0, 0, 200))
            degree[row['sat_a']] += 1
            degree[row['sat_b']] += 1
        self.assertEqual(set(degree.values()), {2})

    def test_each_satellite_has_one_stable_inter_plane_partner(self):
        inter = [row for row in self.links if row['kind'] == 'inter']
        self.assertEqual(len(inter), 12)
        partners = {}
        for row in inter:
            self.assertNotEqual(self.planes[self.ids.index(row['sat_a'])], self.planes[self.ids.index(row['sat_b'])])
            for sid in (row['sat_a'], row['sat_b']):
                self.assertNotIn(sid, partners)
                partners[sid] = row
        self.assertEqual(len(partners), 24)

    def test_links_formed_during_replay_pay_alignment(self):
        radius, omega, ticks = 6841.0, 2 * math.pi / 5640.0, 400
        t = np.arange(ticks)
        leader = omega * t
        trailer = leader - np.radians(30.0) + np.radians(0.1) * t  # closes the gap by 0.1 deg/s
        positions = np.stack([np.stack([radius * np.cos(a), radius * np.sin(a), np.zeros(ticks)], -1)
                              for a in (leader, trailer)], axis=1)
        links = model.laser_links(positions, [1, 2], [0, 1], max_range_km=2000, alignment_s=60)
        self.assertEqual(len(links), 1)
        link = links[0]
        self.assertGreater(link['assigned_start_s'], 0)
        self.assertEqual(link['start_s'], link['assigned_start_s'] + 60)
        short = model.laser_links(positions[:link['assigned_start_s'] + 30], [1, 2], [0, 1], max_range_km=2000, alignment_s=60)
        self.assertEqual(short, [])

    def test_out_of_range_rings_have_no_links(self):
        links = model.laser_links(self.positions, self.ids, self.planes, max_range_km=1000, alignment_s=60)
        self.assertEqual([row for row in links if row['kind'] == 'intra'], [])


class LinkIndexTests(unittest.TestCase):
    def setUp(self):
        chain = [(1, 2, 0, 1000), (2, 3, 0, 1000), (3, 4, 0, 600), (4, 5, 0, 1000)]
        self.links = [{'sat_a': a, 'sat_b': b, 'kind': 'intra', 'assigned_start_s': s, 'start_s': s, 'end_s': e}
                      for a, b, s, e in chain]
        self.index = model.LinkIndex(self.links, [1, 2, 3, 4, 5], 1000)

    def test_hops_and_paths(self):
        depth, paths = self.index.hops(1, 100)
        self.assertEqual(depth, {1: 0, 2: 1, 3: 2, 4: 3, 5: 4})
        self.assertEqual(paths[5], [1, 2, 3, 4, 5])
        depth, _ = self.index.hops(1, 700)
        self.assertNotIn(4, depth)

    def test_path_end_and_limit(self):
        self.assertEqual(self.index.path_end(1, 5, 100), 600)
        self.assertEqual(self.index.path_end(1, 3, 100), 1000)
        self.assertEqual(self.index.path_end(1, 5, 100, limit_s=200), 300)
        self.assertEqual(self.index.path_end(1, 5, 650), 650)

    def test_component(self):
        graph = self.index.segment(700)[2]
        self.assertEqual(model.component(graph, 1), {1, 2, 3})


class EventTests(unittest.TestCase):
    def setUp(self):
        chain = [(1, 2), (2, 3), (3, 4)]
        links = [{'sat_a': a, 'sat_b': b, 'kind': 'intra', 'assigned_start_s': 0, 'start_s': 0, 'end_s': 3000}
                 for a, b in chain]
        self.index = model.LinkIndex(links, [1, 2, 3, 4], 3000)
        self.periods = {1: [(0, 1000), (1500, 2500)], 2: [(0, 1100)], 3: [(0, 2900)], 4: [(0, 2950)]}

    def test_fewest_hops_with_enough_light_and_infeasible_kept(self):
        events = model.migration_events(self.index, self.periods, [1], trigger_lead_s=200,
                                        minimum_destination_light_s=1000, minimum_path_persistence_s=300)
        self.assertEqual([e['trigger_s'] for e in events], [800, 2300])
        first, second = events
        self.assertEqual((first['destination'], first['hops'], first['path']), (3, 2, [1, 2, 3]))
        self.assertEqual(first['destination_light_remaining_s'], 2100)
        self.assertEqual(first['light_gained_s'], 1900)
        self.assertIsNone(second['destination'])
        self.assertEqual(second['lit_candidates'], 0)

    def test_shadow_entry_outside_replay_is_ignored(self):
        periods = {**self.periods, 1: [(0, 3000)]}
        events = model.migration_events(self.index, periods, [1], trigger_lead_s=200,
                                        minimum_destination_light_s=100, minimum_path_persistence_s=100)
        self.assertEqual(events, [])


class PlaneSelectionTests(unittest.TestCase):
    def rows(self):
        out = []
        for center, base in ((80.8, 100), (82.8, 200), (90.0, 300)):
            for k in range(5):
                out.append({'norad_id': base + k, 'raan_deg': center + 0.05 * k, 'argument_of_latitude_deg': (72 * k + base) % 360})
        return out

    def test_select_planes_by_center(self):
        first, second = model.select_planes(self.rows(), [80.9, 82.9])
        self.assertEqual({r['norad_id'] for r in first}, set(range(100, 105)))
        self.assertEqual({r['norad_id'] for r in second}, set(range(200, 205)))
        self.assertEqual([r['argument_of_latitude_deg'] for r in first], sorted(r['argument_of_latitude_deg'] for r in first))

    def test_missing_center_fails(self):
        with self.assertRaises(ValueError):
            model.select_planes(self.rows(), [80.9, 85.0])

    def test_domain_arc(self):
        planes = [sorted(({'norad_id': i, 'argument_of_latitude_deg': 30.0 * i} for i in range(12)), key=lambda r: r['argument_of_latitude_deg']),
                  sorted(({'norad_id': 100 + i, 'argument_of_latitude_deg': (30.0 * i + 5) % 360} for i in range(12)), key=lambda r: r['argument_of_latitude_deg'])]
        first, second = model.choose_domain(planes, 3)
        self.assertEqual(first, [0, 1, 2])
        self.assertEqual(second, [100, 101, 102])
        self.assertEqual(model.max_ring_gap_deg(planes[0]), 30.0)


if __name__ == '__main__':
    unittest.main()


class DesignedEventTests(unittest.TestCase):
    def setUp(self):
        # Two parallel rails 1-2-3-4 (plane 0) and 5-6-7-8 (plane 1), rungs 1-5 and 3-7
        chain = [(1, 2), (2, 3), (3, 4), (5, 6), (6, 7), (7, 8), (1, 5), (3, 7)]
        links = [{'sat_a': a, 'sat_b': b, 'kind': 'intra', 'assigned_start_s': 0, 'start_s': 0, 'end_s': 4000}
                 for a, b in chain]
        self.index = model.LinkIndex(links, list(range(1, 9)), 4000)
        # Source 1 enters shadow at 1000, 2500 and 3600: three events, triggers 800, 2300 and 3400
        light = {1: [(0, 1000), (1500, 2500), (2700, 3600)], 5: [(0, 1100), (1200, 2600)], 2: [(0, 1300)], 3: [(0, 3800)],
                 4: [(0, 3900)], 6: [(0, 1200)], 7: [(0, 3200)], 8: [(0, 3900)]}
        self.periods = light
        self.plane = {1: 0, 2: 0, 3: 0, 4: 0, 5: 1, 6: 1, 7: 1, 8: 1}

    def test_one_event_per_hop_and_plane_specification(self):
        events = model.designed_events(self.index, self.periods, [1], self.plane, ((1, False), (1, True), (2, False)),
                                       trigger_lead_s=200, minimum_destination_light_s=150, minimum_path_persistence_s=100,
                                       within_domain=False)
        self.assertEqual([(e['hops'], e['other_plane'], e['destination']) for e in events], [(1, False, 2), (1, True, 5), (2, False, 3)])
        self.assertEqual(events[0]['path'], [1, 2])
        self.assertEqual(len({(e['source'], e['trigger_s']) for e in events}), 3)

    def test_destination_about_to_enter_shadow_is_excluded(self):
        with self.assertRaises(ValueError):
            model.designed_events(self.index, {**self.periods, 5: [(0, 850)], 6: [(0, 850)]}, [1], self.plane, ((1, True),),
                                  trigger_lead_s=200, minimum_destination_light_s=600, minimum_path_persistence_s=100,
                                  within_domain=False)


class PinnedEventTests(DesignedEventTests):
    def test_slot_and_source_pin_an_event(self):
        periods = {**self.periods, 1: [(0, 1500), (2000, 2500), (2700, 3600)]}
        events = model.designed_events(self.index, periods, [1, 5], self.plane, ((1, True, 0, 5),), slots=3,
                                       trigger_lead_s=200, minimum_destination_light_s=150, minimum_path_persistence_s=100)
        self.assertEqual((events[0]['source'], events[0]['destination']), (5, 1))

    def test_destination_and_path_stay_in_the_domain(self):
        # Domain {1, 2}: 3 is reachable in 2 hops but outside, so no 2-hop event exists inside it
        with self.assertRaises(ValueError):
            model.designed_events(self.index, self.periods, [1, 2], self.plane, ((2, False),),
                                  trigger_lead_s=200, minimum_destination_light_s=150, minimum_path_persistence_s=100)
        events = model.designed_events(self.index, self.periods, [1, 2], self.plane, ((1, False),),
                                       trigger_lead_s=200, minimum_destination_light_s=150, minimum_path_persistence_s=100)
        self.assertEqual(events[0]['path'], [1, 2])

    def test_the_destination_must_outlast_the_source(self):
        periods = {**self.periods, 2: [(0, 950)]}
        with self.assertRaises(ValueError):
            model.designed_events(self.index, periods, [1, 2], self.plane, ((1, False, 0, 1),),
                                  trigger_lead_s=200, minimum_destination_light_s=100, minimum_path_persistence_s=100)
