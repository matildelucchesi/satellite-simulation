"""Test della formula di score e delle notifiche di migrazione."""

import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.migration_manager import MigrationConfig, MigrationManager
from app.contact_window import ContactWindowConfig
from app.score_manager import ScoreManager, ScoreManagerConfig, ScoreWeights


def config(weights=None, threshold=10.0, cooldown=60.0):
    return ScoreManagerConfig(
        weights=weights or ScoreWeights(w1=1.0, w2=10.0, w3=0.1, w4=1.0),
        heartbeat_ttl_seconds=60.0,
        minimum_score_improvement=threshold,
        migration_cooldown_seconds=cooldown,
    )


def migration_config():
    return MigrationConfig(
        default_mode="hot",
        controller_url="http://controller:5000",
        agent_url_template="http://satellite-{satellite_number}:5000",
        request_timeout_seconds=1.0,
        max_retries=0,
        retry_delay_seconds=0.0,
        contact_window=ContactWindowConfig(
            required_alignment_seconds=0.0,
            max_distance_km=5500.0,
            require_line_of_sight=True,
            earth_radius_km=6378.137,
            max_sample_gap_seconds=2.5,
        ),
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
        self.migrations = MigrationManager(
            migration_config(), ["SAT-1", "SAT-2", "SAT-3"]
        )
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

    def test_handover_immediately_replaces_stale_controller_heartbeat(self):
        self.manager.record_heartbeat(heartbeat(1, 100, 10, controller=True))
        self.manager.record_heartbeat(heartbeat(2, 300, 20))
        self.manager.record_heartbeat(heartbeat(3, 250, 30))

        self.manager.record_controller_handover("SAT-1", "SAT-2")
        self.manager.record_heartbeat(heartbeat(1, 90, 10, controller=True))
        state = self.manager.snapshot()

        self.assertEqual(
            state["authoritative_controller_satellite_id"], "SAT-2"
        )
        self.assertFalse(state["heartbeats"]["SAT-1"]["controller"])
        self.assertTrue(state["heartbeats"]["SAT-2"]["controller"])
        self.assertEqual(
            state["evaluation"]["current_controller_satellite_id"], "SAT-2"
        )

    def test_calculates_formula_and_notifies_migration_manager(self):
        self.manager.record_heartbeat(heartbeat(1, 100, 10, controller=True))
        self.manager.record_heartbeat(heartbeat(2, 300, 20))
        self.manager.record_heartbeat(heartbeat(3, 250, 30))

        evaluation = self.manager.snapshot()["evaluation"]

        self.assertEqual(evaluation["scores"]["SAT-1"]["score"], 110.0)
        self.assertEqual(evaluation["scores"]["SAT-2"]["score"], 290.0)
        self.assertEqual(evaluation["scores"]["SAT-1"]["D"], 0.0)
        self.assertEqual(evaluation["scores"]["SAT-3"]["D"], 200.0)
        self.assertEqual(evaluation["distance_reference_satellite_id"], "SAT-1")
        self.assertEqual(evaluation["selected_satellite_id"], "SAT-2")
        self.assertTrue(evaluation["migration_required"])
        latest = self.migrations.snapshot()["latest"]
        self.assertEqual(latest["source_satellite_id"], "SAT-1")
        self.assertEqual(latest["target_satellite_id"], "SAT-2")
        self.assertEqual(latest["mode"], "hot")

    def test_waits_when_there_is_no_unique_controller_reference(self):
        self.manager.record_heartbeat(heartbeat(1, 100, 10))
        self.manager.record_heartbeat(heartbeat(2, 200, 20))
        self.manager.record_heartbeat(heartbeat(3, 150, 30))

        evaluation = self.manager.snapshot()["evaluation"]

        self.assertFalse(evaluation["ready"])
        self.assertEqual(evaluation["reason"], "controller_not_reported")
        self.assertEqual(evaluation["scores"], {})

    def test_recalculates_distances_from_the_new_controller(self):
        self.manager.record_heartbeat(heartbeat(1, 100, 10))
        self.manager.record_heartbeat(heartbeat(2, 200, 20, controller=True))
        self.manager.record_heartbeat(heartbeat(3, 150, 30))

        evaluation = self.manager.snapshot()["evaluation"]

        self.assertEqual(evaluation["distance_reference_satellite_id"], "SAT-2")
        self.assertEqual(evaluation["scores"]["SAT-1"]["D"], 100.0)
        self.assertEqual(evaluation["scores"]["SAT-2"]["D"], 0.0)
        self.assertEqual(evaluation["scores"]["SAT-3"]["D"], 100.0)

    def test_does_not_migrate_until_controller_eclipse_is_approaching(self):
        self.manager.record_heartbeat(heartbeat(1, 500, 10, controller=True))
        self.manager.record_heartbeat(heartbeat(2, 600, 20))
        self.manager.record_heartbeat(heartbeat(3, 700, 30))

        evaluation = self.manager.snapshot()["evaluation"]

        self.assertFalse(evaluation["migration_required"])
        self.assertFalse(evaluation["handover_due"])
        self.assertEqual(evaluation["reason"], "controller_eclipse_not_imminent")
        self.assertEqual(self.migrations.snapshot()["count"], 0)

    def test_starts_handover_early_enough_for_alignment_protocol_and_margin(self):
        self.manager.record_heartbeat(heartbeat(1, 150, 10, controller=True))
        self.manager.record_heartbeat(heartbeat(2, 300, 20))
        self.manager.record_heartbeat(heartbeat(3, 300, 30))

        evaluation = self.manager.snapshot()["evaluation"]
        recommendation = self.migrations.snapshot()["latest"]["recommendation"]

        self.assertTrue(evaluation["handover_due"])
        self.assertEqual(evaluation["handover_trigger_seconds"], 210.0)
        self.assertEqual(evaluation["migration_execution_budget_seconds"], 90.0)
        self.assertEqual(recommendation["migration_execution_budget_seconds"], 90.0)
        self.assertIsNotNone(recommendation["completion_deadline_at"])

    def test_retries_with_a_new_deadline_when_controller_is_already_in_eclipse(self):
        notifications = []
        manager = ScoreManager(
            ["SAT-1", "SAT-2", "SAT-3"],
            config(cooldown=0),
            notifications.append,
            required_contact_seconds=60,
            migration_execution_budget_seconds=90,
            migration_state_provider=lambda: {
                "migrations": [{"status": "failed"}]
            },
        )
        manager.update_constellation(constellation())
        manager.record_heartbeat(heartbeat(1, 0, 10, controller=True))
        manager.record_heartbeat(heartbeat(2, 500, 20))
        manager.record_heartbeat(heartbeat(3, 400, 30))

        evaluation = manager.snapshot()["evaluation"]
        recommendation = notifications[0]

        self.assertTrue(evaluation["migration_required"])
        self.assertTrue(evaluation["controller_in_eclipse"])
        self.assertEqual(evaluation["reason"], "controller_in_eclipse_recovery")
        self.assertTrue(recommendation["emergency_recovery"])
        self.assertGreater(
            datetime.fromisoformat(
                recommendation["completion_deadline_at"].replace("Z", "+00:00")
            ),
            datetime.fromisoformat(
                recommendation["alignment_complete_not_before"].replace(
                    "Z", "+00:00"
                )
            ),
        )

    def test_selects_only_a_target_with_direct_contact(self):
        contact_config = ContactWindowConfig(
            required_alignment_seconds=60,
            max_distance_km=5500,
            require_line_of_sight=True,
            earth_radius_km=6378.137,
            max_sample_gap_seconds=2.5,
        )
        migrations = MigrationManager(
            migration_config(), ["SAT-1", "SAT-2", "SAT-3"]
        )
        manager = ScoreManager(
            ["SAT-1", "SAT-2", "SAT-3"],
            config(),
            migrations.notify_migration,
            contact_window_config=contact_config,
        )
        snapshot = constellation()
        snapshot.update(
            {
                "generated_at": "2026-07-19T10:00:00Z",
                "satellites": {
                    "SAT-1": {
                        "position_km": {"x": 7000.0, "y": 0.0, "z": 0.0}
                    },
                    "SAT-2": {
                        "position_km": {"x": 7000.0, "y": 1000.0, "z": 0.0}
                    },
                    "SAT-3": {
                        "position_km": {"x": -7000.0, "y": 0.0, "z": 0.0}
                    },
                },
            }
        )
        manager.update_constellation(snapshot)
        manager.record_heartbeat(heartbeat(1, 100, 10, controller=True))
        manager.record_heartbeat(heartbeat(2, 300, 20))
        manager.record_heartbeat(heartbeat(3, 1000, 0))

        evaluation = manager.snapshot()["evaluation"]

        self.assertEqual(evaluation["selected_satellite_id"], "SAT-2")
        self.assertTrue(evaluation["candidate_eligibility"]["SAT-2"]["eligible"])
        self.assertFalse(evaluation["candidate_eligibility"]["SAT-3"]["eligible"])
        self.assertEqual(
            evaluation["candidate_eligibility"]["SAT-3"]["contact"]["reason"],
            "distance_exceeded",
        )

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
