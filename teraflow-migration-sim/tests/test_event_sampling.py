import unittest

from src.event_sampling import linear_quantile, select_percentile_events


class EventSamplingTests(unittest.TestCase):
    def test_type7_percentile_interpolation(self):
        self.assertEqual(linear_quantile([0, 10, 20, 30, 40], 50), 20)
        self.assertEqual(linear_quantile([0, 10, 20, 30, 40], 10), 4)

    def test_selects_distinct_events_nearest_each_percentile(self):
        events = [{"event_id": f"e{i}", "orbital_margin_s": value}
                  for i, value in enumerate([5, 10, 15, 20, 40, 60, 80, 100, 120, 160])]
        selected = select_percentile_events(events)
        self.assertEqual([event["percentile_case"] for event in selected], ["P10", "P50", "P90"])
        self.assertEqual(len({event["event_id"] for event in selected}), 3)

    def test_requires_enough_trigger_qualified_events(self):
        with self.assertRaises(ValueError):
            select_percentile_events([{"event_id": "e1", "orbital_margin_s": 1}])


if __name__ == "__main__":
    unittest.main()
