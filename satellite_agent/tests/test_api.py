"""Test delle API REST richieste per ogni Satellite Agent."""

import unittest

from app import create_app
from test_agent import orbital_state


class SatelliteAgentApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "SATELLITE_ID": "SAT-3",
                "CONTROLLER_ENABLED": False,
                "SIMULATOR_URL": "",
                "HEARTBEAT_URL": "",
                "AGENT_AUTOSTART": False,
            }
        )
        self.client = self.app.test_client()

    def test_position_is_unavailable_before_first_state(self):
        self.assertEqual(self.client.get("/position").status_code, 503)

    def test_receive_state_and_position(self):
        accepted = self.client.post("/receive_state", json=orbital_state())
        position = self.client.get("/position")

        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(position.status_code, 200)
        self.assertEqual(position.get_json()["id"], "SAT-3")

    def test_controller_endpoints(self):
        started = self.client.post("/start_controller")
        stopped = self.client.post("/stop_controller")

        self.assertTrue(started.get_json()["controller"])
        self.assertFalse(stopped.get_json()["controller"])

    def test_migration_endpoint(self):
        response = self.client.post(
            "/migration_request",
            json={
                "source_satellite_id": "SAT-1",
                "target_satellite_id": "SAT-3",
            },
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json()["status"], "accepted")


if __name__ == "__main__":
    unittest.main()

