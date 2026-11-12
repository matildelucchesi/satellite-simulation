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


class DestinationPolicyTests(DesignedEventTests):
    """Domain = rail 1-2-3-4, links of 3000 km (≈10 ms each). From source 1 at trigger 800, with a
    lead of 200 s and a longest migration of 100 s, the stays from the end of the migration are:
    2 (1 hop, 200 s), 3 (2 hops, 2700 s) and 4 (3 hops, 2800 s)."""
    LIMITS = {'trigger_lead_s': 200, 'minimum_destination_light_s': 150, 'minimum_path_persistence_s': 100}
    DOWNTIME = {'hot': 7.0, 'cold': 100.0}
    DURATION = {'hot': 50.0, 'cold': 100.0}
    SELECTION = {'availability_min': 0.9, 'selection_mode': 'cold'}

    def candidates(self, domain=(1, 2, 3, 4), **options):
        return model.policy_candidates(self.index, self.periods, list(domain), self.plane, 1, 1000,
                                       lambda a, b, tick: 3000.0, **self.LIMITS,
                                       **({'downtime_s': self.DOWNTIME, 'duration_s': self.DURATION} | self.SELECTION | options))

    def options(self):
        return {**self.LIMITS, 'downtime_s': self.DOWNTIME, 'duration_s': self.DURATION}

    def test_availability_threshold_then_lowest_latency(self):
        trigger, rows = self.candidates()
        self.assertEqual(trigger, 800)
        hop_ms = 3000.0 / model.LIGHT_SPEED_KM_S * 1000.0
        by = {row['destination']: row for row in rows}
        # 2 is as central as 3 but its 200 s of stay give half of Cold downtime: excluded
        self.assertNotIn(2, by)
        self.assertEqual([row['destination'] for row in rows], [3, 4])
        self.assertAlmostEqual(by[3]['control_latency_ms'], 4 / 3 * hop_ms)
        self.assertAlmostEqual(by[4]['control_latency_ms'], 2 * hop_ms)
        self.assertEqual((by[3]['stay_s'], by[3]['stay_from_trigger_s']), (2700, 2800))
        self.assertAlmostEqual(by[3]['downtime_fraction']['cold'], 100.0 / 2700)
        self.assertAlmostEqual(by[3]['downtime_fraction']['hot'], 7.0 / 2700)
        # A stricter threshold leaves only the longest stay, a stricter one still nothing
        self.assertEqual([row['destination'] for row in self.candidates(availability_min=0.963)[1]], [4])
        self.assertEqual(self.candidates(availability_min=0.97)[1], [])
        # With a loose threshold the tie on latency goes to fewer hops
        self.assertEqual(self.candidates(availability_min=0.5)[1][0]['destination'], 2)

    def test_the_stay_starts_at_the_end_of_the_longest_migration(self):
        # With a 350 s migration the trigger of 2 (300 s after this one) comes before its end
        rows = self.candidates(availability_min=0.01, duration_s={'hot': 50.0, 'cold': 350.0})[1]
        self.assertEqual([row['destination'] for row in rows], [3, 4])
        self.assertEqual(rows[0]['stay_s'], 2450)
        # Without durations the stay is counted from the trigger
        rows = self.candidates(availability_min=0.01, duration_s={})[1]
        self.assertEqual({row['destination']: row['stay_s'] for row in rows}, {2: 300, 3: 2800, 4: 2900})

    def test_the_selection_mode_decides_the_destination_of_both_modes(self):
        # With Hot downtime the short stay of 2 passes, with Cold it does not
        self.assertEqual(self.candidates(selection_mode='hot')[1][0]['destination'], 2)
        self.assertEqual(self.candidates()[1][0]['destination'], 3)
        self.assertEqual((model.DESTINATION_POLICY['selection_mode'], model.DESTINATION_POLICY['availability_min']), ('hot', 0.95))

    def test_measured_overhead_shifts_latency_but_not_the_order(self):
        plain = self.candidates()[1]
        shifted = self.candidates(overhead_ms=5.0)[1]
        self.assertEqual([row['destination'] for row in plain], [row['destination'] for row in shifted])
        self.assertAlmostEqual(shifted[0]['control_latency_ms'] - plain[0]['control_latency_ms'], 5.0)

    def test_the_controller_must_reach_the_whole_domain(self):
        # 8 hangs off 7, outside the domain: no controller inside reaches it
        self.assertEqual(self.candidates(domain=(1, 2, 3, 8))[1], [])
        self.assertIsNone(model.control_latency_ms(self.index.segment(800)[2], [1, 2, 3, 8], 2, lambda a, b: 1.0))

    def test_policy_events_summary_sensitivity_and_comparison_with_a_designed_event(self):
        distance = lambda a, b, tick: 3000.0
        options = self.options()
        events = model.policy_events(self.index, self.periods, [1, 2, 3, 4], self.plane, distance, **options, **self.SELECTION)
        first = next(event for event in events if event['event_id'] == '1-800')
        self.assertEqual((first['destination'], first['hops'], first['candidates'], first['constrained_candidates']), (3, 2, 2, 3))
        self.assertIsNotNone(first['source_control_latency_ms'])
        summary = model.policy_summary(events, 'cold')
        self.assertEqual(summary['shadow_entries'], len(events))
        served = [event for event in events if event['destination'] is not None]
        self.assertEqual(summary['served'], len(served))
        self.assertAlmostEqual(summary['downtime_share']['cold'], 100.0 * len(served) / sum(event['stay_s'] for event in served))
        sensitivity = model.policy_sensitivity(self.index, self.periods, [1, 2, 3, 4], self.plane, distance, **options,
                                               selection_mode='cold', thresholds=(0.5, 0.9, 0.97))
        self.assertEqual([row['availability_min'] for row in sensitivity], [0.5, 0.9, 0.97])
        self.assertGreaterEqual(sensitivity[0]['served'], sensitivity[1]['served'])
        self.assertGreaterEqual(sensitivity[1]['served'], sensitivity[2]['served'])
        self.assertEqual(sensitivity[1]['served'], summary['served'])
        designed = [{'event_id': '1-800', 'source': 1, 'trigger_s': 800, 'source_shadow_entry_s': 1000, 'destination': 2, 'hops': 1}]
        [row] = model.compare_with_policy(designed, self.index, self.periods, [1, 2, 3, 4], self.plane, distance,
                                          **options, **self.SELECTION)
        self.assertEqual((row['policy']['destination'], row['designed']['destination']), (3, 2))
        self.assertEqual((row['designed']['feasible'], row['designed']['admissible']), (True, False))
        self.assertIsNone(row['rank_of_designed'])
        self.assertFalse(row['same_destination'])
        # With a 350 s migration the designed destination is no longer feasible at all
        [late] = model.compare_with_policy(designed, self.index, self.periods, [1, 2, 3, 4], self.plane, distance,
                                           **(options | {'duration_s': {'cold': 350.0}}), **self.SELECTION)
        self.assertEqual((late['designed']['feasible'], late['designed']['admissible']), (False, False))
        report = model.destination_policy_report(designed, self.index, self.periods, [1, 2, 3, 4], self.plane, distance,
                                                 **options, **self.SELECTION, thresholds=(0.9,))
        self.assertEqual(report['parameters']['selection_mode'], 'cold')
        self.assertEqual(report['parameters']['duration_s'], self.DURATION)
        self.assertEqual(report['summary'], summary)
        with self.assertRaises(ValueError):
            model.destination_policy_report(designed, self.index, self.periods, [1, 2, 3, 4], self.plane, distance,
                                            **options, selection_mode='cold', availability_min=1.0)
        [pick] = model.policy_selected_events([row], events, self.index, 100)
        self.assertEqual((pick['event_id'], pick['designed_event_id'], pick['source'], pick['trigger_s']), ('1-800-cost', '1-800', 1, 800))
        self.assertEqual((pick['destination'], pick['hops'], pick['path'], pick['source_shadow_entry_s']), (3, 2, [1, 2, 3], 1000))
        self.assertEqual(pick['light_gained_s'], pick['destination_light_remaining_s'] - 200)
        self.assertGreaterEqual(pick['path_end_s'] - 800, 100)
        self.assertFalse(pick['replaces_designed_entry'])

    def test_an_unserved_designed_entry_is_replaced_by_the_nearest_served_one(self):
        distance = lambda a, b, tick: 3000.0
        events = model.policy_events(self.index, self.periods, [1, 2, 3, 4], self.plane, distance, **self.options(),
                                     **self.SELECTION)
        others = [event for event in events if event['event_id'] != '1-800']
        unserved = {'event_id': '1-800', 'source': 1, 'trigger_s': 800, 'source_shadow_entry_s': 1000,
                    'policy': None, 'same_destination': False}
        [pick] = model.policy_selected_events([unserved], others, self.index, 100)
        nearest = min((event for event in others if event['destination'] is not None),
                      key=lambda event: (abs(event['trigger_s'] - 800), event['source']))
        self.assertEqual((pick['source'], pick['trigger_s'], pick['destination']),
                         (nearest['source'], nearest['trigger_s'], nearest['destination']))
        self.assertTrue(pick['replaces_designed_entry'])
        self.assertEqual(pick['designed_event_id'], '1-800')
        self.assertIn('replacement_reason', pick)
        # An entry already used by another designed event is not taken twice
        served_row = {'event_id': nearest['event_id'], 'source': nearest['source'], 'trigger_s': nearest['trigger_s'],
                      'source_shadow_entry_s': nearest['source_shadow_entry_s'], 'policy': nearest, 'same_destination': True}
        picks = model.policy_selected_events([served_row, unserved], others, self.index, 100)
        self.assertNotEqual((picks[1]['source'], picks[1]['trigger_s']), (nearest['source'], nearest['trigger_s']))
        with self.assertRaises(ValueError):
            model.policy_selected_events([unserved], [], self.index, 100)
