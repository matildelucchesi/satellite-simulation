import json
import unittest
from pathlib import Path
from src.events import operational_periods, generate_events
from src.orbit import cylindrical_eclipse


class EventTests(unittest.TestCase):
    def test_sunlight_periods_start_after_initial_shadow(self):
        self.assertEqual(list(operational_periods([True, True, False, False, True, False])),
                         [(2, 4), (5, 6)])

    def test_all_sources_keep_one_nonmigrable_event_per_period(self):
        scenario = json.loads((Path(__file__).parents[1]/'config/scenario.json').read_text())
        class Shadows:
            def __getitem__(self, item):
                return [True, True, False, False, False, True, True, False, False, True][item[0]]
        class Orbit:
            ids = list(range(17)); index = {sid: sid for sid in ids}; duration = 10
            eclipsed = Shadows()
            def graph(self, tick):
                return {sid: {} for sid in self.ids + [53848, 53913]}
        events = generate_events(Orbit(), scenario, 3,
                                 {'cpu_cores': 0, 'ram_gib': 0, 'disk_gib': 0})
        self.assertEqual(len(events), 34)
        self.assertEqual(len({e['event_id'] for e in events}), 34)
        self.assertEqual({e['period_start_s'] for e in events}, {2, 7})
        self.assertTrue(all(not e['migrable'] for e in events))
        self.assertTrue(all(e['trigger_causes'] == ['eclipse'] for e in events))

    def test_cylindrical_shadow_is_on_antisolar_side(self):
        self.assertTrue(cylindrical_eclipse((-7000, 0, 0), (1, 0, 0)))
        self.assertFalse(cylindrical_eclipse((7000, 0, 0), (1, 0, 0)))
        self.assertFalse(cylindrical_eclipse((-7000, 7000, 0), (1, 0, 0)))
        with self.assertRaises(ValueError): cylindrical_eclipse((-7000, 0, 0), (0, 0, 0))
