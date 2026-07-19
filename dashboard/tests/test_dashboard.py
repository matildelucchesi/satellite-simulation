"""Test dell'aggregatore e delle route della Dashboard."""

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
            "/state": {"topology": {}, "routing_table": {}},
            "/health": {"status": "ok"},
        }

        def fetcher(url):
            for suffix, payload in responses.items():
                if url.endswith(suffix):
                    return payload
            raise AssertionError(url)

        with TemporaryDirectory() as directory:
            service = DashboardDataService(
                "http://simulator:5000",
                "http://controller:5000",
                directory,
                fetcher=fetcher,
            )
            snapshot = service.collect()

        self.assertIn("constellation", snapshot)
        self.assertIn("controller_state", snapshot)
        self.assertEqual(
            snapshot["startup_controller"]["selected_satellite_id"], "SAT-2"
        )
        self.assertEqual(snapshot["errors"], [])


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
        self.assertIn(b"migrationTransfer", response.data)
        self.assertIn(b"migrationTimeline", response.data)
        self.assertIn(b"migrationTimelineStatus", response.data)

    def test_dashboard_api_returns_json(self):
        response = self.client.get("/api/dashboard")

        self.assertEqual(response.status_code, 200)
        self.assertIn("generated_at", response.get_json())


if __name__ == "__main__":
    unittest.main()
