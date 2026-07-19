"""Test della geometria usata per autorizzare una migrazione."""

import unittest

from app.contact_window import ContactWindowConfig, evaluate_contact


def snapshot(target):
    return {
        "generated_at": "2026-07-19T10:00:00Z",
        "satellites": {
            "SAT-1": {"position_km": {"x": 7000.0, "y": 0.0, "z": 0.0}},
            "SAT-2": {
                "position_km": {
                    "x": target[0],
                    "y": target[1],
                    "z": target[2],
                }
            },
        },
    }


class ContactWindowTests(unittest.TestCase):
    def test_accepts_nearby_satellites_with_clear_line_of_sight(self):
        config = ContactWindowConfig.from_dict({"max_distance_km": 5500})

        observation = evaluate_contact(
            snapshot((7000.0, 1000.0, 0.0)), "SAT-1", "SAT-2", config
        )

        self.assertTrue(observation.eligible)
        self.assertTrue(observation.line_of_sight)
        self.assertEqual(observation.reason, "in_contact")

    def test_rejects_a_link_occluded_by_earth(self):
        config = ContactWindowConfig.from_dict({"max_distance_km": 20000})

        observation = evaluate_contact(
            snapshot((-7000.0, 0.0, 0.0)), "SAT-1", "SAT-2", config
        )

        self.assertFalse(observation.eligible)
        self.assertFalse(observation.line_of_sight)
        self.assertEqual(observation.reason, "earth_occlusion")

    def test_rejects_a_link_beyond_the_configured_distance(self):
        config = ContactWindowConfig.from_dict({"max_distance_km": 5500})

        observation = evaluate_contact(
            snapshot((7000.0, 6000.0, 0.0)), "SAT-1", "SAT-2", config
        )

        self.assertFalse(observation.eligible)
        self.assertEqual(observation.reason, "distance_exceeded")


if __name__ == "__main__":
    unittest.main()
