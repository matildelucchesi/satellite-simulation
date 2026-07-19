"""Test della formula di score e delle notifiche di migrazione."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.migration_manager import MigrationManager
from app.score_manager import ScoreManager, ScoreManagerConfig, ScoreWeights


def config(weights=None, threshold=10.0, cooldown=60.0):
    return ScoreManagerConfig(
        weights=weights or ScoreWeights(w1=1.0, w2=10.0, w3=0.1, w4=1.0),
        heartbeat_ttl_seconds=60.0,
        minimum_score_improvement=threshold,
        migration_cooldown_seconds=cooldown,
    )


def heartbeat(satellite_id, eclipse, cpu, controller=False):
    return {
        "id": satellite_id,
        "time_to_eclipse": eclipse,
        "neighbors": 2,
        "cpu": cpu,
        "controller": controller,
    }


def constellation():
    return {
        "distances_km": {
            "SAT-1": {"SAT-1": 0, "SAT-2": 100, "SAT-3": 200},
            "SAT-2": {"SAT-1": 100, "SAT-2": 0, "SAT-3": 100},
            "SAT-3": {"SAT-1": 200, "SAT-2": 100, "SAT-3": 0},
        }
    }


class ScoreManagerTests(unittest.TestCase):
    def setUp(self):
        self.migrations = MigrationManager()
        self.manager = ScoreManager(
            ["SAT-1", "SAT-2", "SAT-3"],
            config(),
            self.migrations.notify_migration,
        )
        self.manager.update_constellation(constellation())

    def test_waits_for_all_heartbeats(self):
        self.manager.record_heartbeat(heartbeat(1, 100, 10, controller=True))

        evaluation = self.manager.snapshot()["evaluation"]

        self.assertFalse(evaluation["ready"])
        self.assertEqual(evaluation["missing_heartbeats"], ["SAT-2", "SAT-3"])
        self.assertEqual(self.migrations.snapshot()["count"], 0)

    def test_calculates_formula_and_notifies_migration_manager(self):
        self.manager.record_heartbeat(heartbeat(1, 100, 10, controller=True))
        self.manager.record_heartbeat(heartbeat(2, 200, 20))
        self.manager.record_heartbeat(heartbeat(3, 150, 30))

        evaluation = self.manager.snapshot()["evaluation"]

        self.assertEqual(evaluation["scores"]["SAT-1"]["score"], 95.0)
        self.assertEqual(evaluation["scores"]["SAT-2"]["score"], 190.0)
        self.assertEqual(evaluation["selected_satellite_id"], "SAT-2")
        self.assertTrue(evaluation["migration_required"])
        latest = self.migrations.snapshot()["latest"]
        self.assertEqual(latest["source_satellite_id"], "SAT-1")
        self.assertEqual(latest["target_satellite_id"], "SAT-2")

    def test_weights_are_loaded_from_json_file(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "scoring.json"
            path.write_text(
                json.dumps(
                    {
                        "weights": {"w1": 2, "w2": 3, "w3": 4, "w4": 5},
                        "heartbeat_ttl_seconds": 10,
                        "migration": {
                            "minimum_score_improvement": 6,
                            "cooldown_seconds": 7,
                        },
                    }
                ),
                encoding="utf-8",
            )

            loaded = ScoreManagerConfig.from_file(path)

        self.assertEqual(loaded.weights.w1, 2.0)
        self.assertEqual(loaded.minimum_score_improvement, 6.0)


if __name__ == "__main__":
    unittest.main()
