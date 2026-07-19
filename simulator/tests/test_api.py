"""Test dell'API REST del Simulator."""

from pathlib import Path
import unittest

from app import create_app


ROOT = Path(__file__).resolve().parents[2]


class SimulatorApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "SIMULATOR_AUTOSTART": False,
                "CONFIG_PATH": str(ROOT / "config" / "constellation.json"),
                "TLE_PATH": str(ROOT / "config" / "starlink.tle"),
            }
        )
        self.simulator = self.app.extensions["constellation_simulator"]
        self.addCleanup(self.simulator.close)
        self.simulator.update()
        self.client = self.app.test_client()

    def test_constellation_endpoint(self):
        response = self.client.get("/api/v1/constellation")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["satellite_count"], 7)

    def test_unknown_satellite_returns_404(self):
        response = self.client.get("/api/v1/satellites/SAT-99")

        self.assertEqual(response.status_code, 404)

    def test_startup_controller_is_minimum_sunlight_above_two_minutes(self):
        response = self.client.get("/api/v1/startup-controller")
        startup = response.get_json()
        constellation = self.simulator.snapshot()["satellites"]
        eligible = {
            satellite_id: satellite["illumination"]["seconds_until_eclipse"]
            for satellite_id, satellite in constellation.items()
            if satellite["illumination"]["state"] == "sunlight"
            and satellite["illumination"]["seconds_until_eclipse"] > 120
        }

        self.assertEqual(response.status_code, 200)
        self.assertTrue(eligible)
        self.assertEqual(
            startup["selected_satellite_id"],
            min(eligible, key=lambda satellite_id: eligible[satellite_id]),
        )
        self.assertGreater(startup["selected_time_to_eclipse_seconds"], 120)

    def test_heartbeats_produce_scores_for_all_satellites(self):
        for satellite_id in range(1, 8):
            response = self.client.post(
                "/api/v1/heartbeats",
                json={
                    "id": satellite_id,
                    "time_to_eclipse": satellite_id * 100,
                    "neighbors": 6,
                    "cpu": satellite_id * 5,
                    "controller": satellite_id == 1,
                },
            )
            self.assertEqual(response.status_code, 202)

        score_state = self.client.get("/api/v1/scores").get_json()
        heartbeat_state = self.client.get("/api/v1/heartbeats").get_json()
        metrics_state = self.client.get("/api/v1/metrics").get_json()

        self.assertTrue(score_state["evaluation"]["ready"])
        self.assertEqual(len(score_state["evaluation"]["scores"]), 7)
        self.assertEqual(heartbeat_state["count"], 7)
        self.assertEqual(metrics_state["heartbeat_count"], 7)
        self.assertEqual(metrics_state["controller_election_count"], 1)
        self.assertIsNotNone(
            metrics_state["last_selected_controller_satellite_id"]
        )

    def test_manual_migration_waits_for_contact_and_can_be_inspected(self):
        queued = self.client.post(
            "/api/v1/migrations",
            json={
                "source_satellite_id": "SAT-1",
                "target_satellite_id": "SAT-2",
                "mode": "cold",
            },
        )
        migration_id = queued.get_json()["migration_id"]
        migration = self.client.get(f"/api/v1/migrations/{migration_id}")

        self.assertEqual(queued.status_code, 202)
        self.assertEqual(migration.status_code, 200)
        self.assertEqual(migration.get_json()["mode"], "cold")
        self.assertEqual(queued.get_json()["status"], "waiting_for_contact")
        self.assertEqual(migration.get_json()["status"], "waiting_for_contact")

    def test_metrics_count_heartbeats_and_export_json_and_csv(self):
        for satellite_id in range(1, 3):
            response = self.client.post(
                "/api/v1/heartbeats",
                json={
                    "id": satellite_id,
                    "time_to_eclipse": 300,
                    "neighbors": 4,
                    "cpu": 20,
                    "controller": satellite_id == 1,
                },
            )
            self.assertEqual(response.status_code, 202)

        metrics = self.client.get("/api/v1/metrics")
        json_export = self.client.get("/api/v1/metrics/export.json")
        csv_export = self.client.get("/api/v1/metrics/export.csv")

        self.assertEqual(metrics.status_code, 200)
        self.assertEqual(metrics.get_json()["heartbeat_count"], 2)
        self.assertEqual(json_export.status_code, 200)
        self.assertIn("simulation-metrics.json", json_export.headers["Content-Disposition"])
        self.assertEqual(csv_export.status_code, 200)
        self.assertTrue(csv_export.mimetype.startswith("text/csv"))
        self.assertIn(b"average_handover_time_ms", csv_export.data)

    def test_metrics_reject_unsupported_export_format(self):
        response = self.client.get("/api/v1/metrics/export.xml")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "unsupported_format")


if __name__ == "__main__":
    unittest.main()
