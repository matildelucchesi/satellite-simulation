"""Test dell'aggregatore e delle route della Dashboard."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app import create_app
from app.service import DashboardDataService


class DashboardDataServiceTests(unittest.TestCase):
    def test_collects_all_upstreams_into_one_snapshot(self):
        responses = {
            "/api/v1/constellation": {"satellites": {"SAT-1": {}}},
            "/api/v1/scores": {"evaluation": {"scores": {}}},
            "/api/v1/heartbeats": {"heartbeats": {}},
            "/api/v1/migrations": {"migrations": []},
            "/api/v1/startup-controller": {
                "status": "active",
                "selected_satellite_id": "SAT-2",
            },
            "/api/v1/experiment": {
                "status": "awaiting_configuration",
                "completed_migrations": 0,
            },
            "/state": {"topology": {}, "routing_table": {}},
            "/health": {"status": "ok"},
        }

        def fetcher(url):
            for suffix, payload in responses.items():
                if url.endswith(suffix):
                    return payload
            raise AssertionError(url)

        with TemporaryDirectory() as directory:
            export = Path(directory, "metrics-hot-20260721T120000Z.json")
            pdf = Path(directory, "metrics-hot-20260721T120000Z.pdf")
            csv = Path(directory, "metrics-hot-20260721T120000Z.csv")
            export.write_text('{"migration_count": 3}', encoding="utf-8")
            pdf.write_bytes(b"%PDF-1.4")
            csv.write_text("legacy,csv", encoding="utf-8")
            service = DashboardDataService(
                "http://simulator:5000",
                "http://controller:5000",
                directory,
                fetcher=fetcher,
            )
            snapshot = service.collect()
            export_path = service.export_path(export.name)

        self.assertIn("constellation", snapshot)
        self.assertIn("controller_state", snapshot)
        self.assertEqual(
            snapshot["startup_controller"]["selected_satellite_id"], "SAT-2"
        )
        self.assertEqual(snapshot["errors"], [])
        self.assertEqual({item["filename"] for item in snapshot["exports"]}, {export.name, pdf.name})
        self.assertEqual(export_path, export)
        self.assertIsNone(service.export_path("../metrics-hot-20260721T120000Z.json"))
        self.assertIsNone(service.export_path(csv.name))


class DashboardApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "SIMULATOR_URL": "http://simulator",
                "CONTROLLER_URL": "http://controller",
                "LOG_DIR": ".",
                "DASHBOARD_FETCHER": lambda _url: {},
            }
        )
        self.client = self.app.test_client()

    def test_index_renders_dashboard(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Starlink Simulation", response.data)
        self.assertIn(b"networkSvg", response.data)
        self.assertIn(b"transitionRows", response.data)
        self.assertIn(b"migrationRoute", response.data)
        self.assertIn(b"migration-reason", response.data)
        self.assertIn(b"migrationTransfer", response.data)
        self.assertIn(b"migrationTimeline", response.data)
        self.assertIn(b"migrationTimelineStatus", response.data)
        self.assertIn(b"experimentModal", response.data)
        self.assertIn(b"migrationLimit", response.data)
        self.assertIn(b"newSimulationButton", response.data)
        self.assertIn(b"exportRows", response.data)
        self.assertIn(b"exportPreviewModal", response.data)

    def test_dashboard_api_returns_json(self):
        response = self.client.get("/api/dashboard")

        self.assertEqual(response.status_code, 200)
        self.assertIn("generated_at", response.get_json())

    def test_migration_arrow_exposes_final_update_phase(self):
        response = self.client.get("/static/app.js")
        self.addCleanup(response.close)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"UPDATE FINALE", response.data)
        self.assertIn(b"CANALE STABILITO", response.data)
        self.assertIn(b"ACTIVE_MIGRATION_STATUSES", response.data)


if __name__ == "__main__":
    unittest.main()
