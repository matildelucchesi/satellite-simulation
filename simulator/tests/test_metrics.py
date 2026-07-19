"""Test delle metriche aggregate ed esportabili."""

import csv
from io import StringIO
import unittest

from app.metrics import MetricsManager


class MetricsManagerTests(unittest.TestCase):
    def setUp(self):
        self.migrations = {
            "migrations": [
                {
                    "status": "completed",
                    "metrics": {
                        "duration_ms": 120.0,
                        "downtime_ms": 30.0,
                        "ack_received": True,
                        "controller_restore_ack": True,
                    },
                },
                {
                    "status": "completed",
                    "metrics": {
                        "duration_ms": 80.0,
                        "downtime_ms": 10.0,
                        "ack_received": True,
                        "controller_restore_ack": False,
                    },
                },
                {
                    "status": "failed",
                    "metrics": {
                        "duration_ms": 50.0,
                        "downtime_ms": None,
                        "ack_received": False,
                        "controller_restore_ack": False,
                    },
                },
            ]
        }
        self.manager = MetricsManager(lambda: self.migrations)

    def test_aggregates_runtime_and_migration_metrics(self):
        self.manager.record_heartbeat()
        self.manager.record_heartbeat()
        self.manager.record_election(
            {"ready": True, "selected_satellite_id": "SAT-1"}, 4.0
        )
        self.manager.record_election(
            {"ready": True, "selected_satellite_id": "SAT-1"}, 99.0
        )
        self.manager.record_election(
            {"ready": True, "selected_satellite_id": "SAT-2"}, 6.0
        )

        metrics = self.manager.snapshot()

        self.assertEqual(metrics["migration_count"], 3)
        self.assertEqual(metrics["completed_migration_count"], 2)
        self.assertEqual(metrics["heartbeat_count"], 2)
        self.assertEqual(metrics["ack_count"], 3)
        self.assertEqual(metrics["total_downtime_ms"], 40.0)
        self.assertEqual(metrics["average_downtime_ms"], 20.0)
        self.assertEqual(metrics["average_handover_time_ms"], 100.0)
        self.assertEqual(metrics["controller_election_count"], 2)
        self.assertEqual(metrics["average_controller_election_time_ms"], 5.0)
        self.assertGreaterEqual(metrics["simulation_time_seconds"], 0)

    def test_exports_a_valid_csv_row(self):
        rows = list(csv.DictReader(StringIO(self.manager.to_csv())))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["migration_count"], "3")
        self.assertIn("simulation_time_seconds", rows[0])
