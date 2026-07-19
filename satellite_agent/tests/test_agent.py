"""Test dello stato e degli heartbeat del Satellite Agent."""

import json
import unittest
from unittest.mock import MagicMock, patch

from app.agent import AgentValidationError, SatelliteAgent


def orbital_state(satellite_id: str = "SAT-3"):
    return {
        "id": satellite_id,
        "position_km": {"x": 1.0, "y": 2.0, "z": 3.0},
        "geodetic": {"latitude_deg": 1.0, "longitude_deg": 2.0},
        "velocity_km_s": {"x": 4.0, "y": 5.0, "z": 6.0},
        "speed_km_s": 7.5,
        "illumination": {
            "state": "sunlight",
            "seconds_until_eclipse": 540.4,
        },
        "distances_km": {
            "SAT-1": 100.0,
            "SAT-2": 200.0,
            "SAT-3": 0.0,
            "SAT-4": 300.0,
            "SAT-5": 400.0,
        },
    }


class SatelliteAgentTests(unittest.TestCase):
    def setUp(self):
        self.agent = SatelliteAgent("SAT-3")

    def test_receives_own_orbital_state(self):
        state = self.agent.receive_state(orbital_state())

        self.assertEqual(state["id"], "SAT-3")
        self.assertEqual(self.agent.position_state()["position_km"]["x"], 1.0)

    def test_extracts_state_from_constellation_snapshot(self):
        self.agent.receive_state(
            {
                "generated_at": "2026-07-19T10:00:00Z",
                "satellites": {"SAT-3": orbital_state()},
            }
        )

        self.assertEqual(
            self.agent.status()["orbital_state"]["source_generated_at"],
            "2026-07-19T10:00:00Z",
        )

    def test_rejects_state_for_another_satellite(self):
        with self.assertRaises(AgentValidationError):
            self.agent.receive_state(orbital_state("SAT-2"))

    @patch("app.agent.psutil.cpu_percent", return_value=28.0)
    def test_builds_expected_heartbeat(self, _cpu_percent):
        self.agent.receive_state(orbital_state())

        heartbeat = self.agent.build_heartbeat()

        self.assertEqual(
            heartbeat,
            {
                "id": 3,
                "time_to_eclipse": 540,
                "neighbors": 4,
                "cpu": 28,
                "controller": False,
            },
        )

    def test_controller_lifecycle_is_idempotent(self):
        first = self.agent.start_controller()
        second = self.agent.start_controller()
        stopped = self.agent.stop_controller()

        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertFalse(stopped["controller"])

    def test_accepts_controller_migration(self):
        migration = self.agent.accept_migration(
            {
                "source_satellite_id": "SAT-1",
                "target_satellite_id": "SAT-3",
            }
        )

        self.assertEqual(migration["status"], "accepted")
        self.assertEqual(migration["target_satellite_id"], "SAT-3")

    @patch("app.agent.psutil.cpu_percent", return_value=28.0)
    @patch("app.agent.urlopen")
    def test_sends_heartbeat_as_json(self, mocked_urlopen, _cpu_percent):
        response = MagicMock(status=202)
        mocked_urlopen.return_value.__enter__.return_value = response
        agent = SatelliteAgent(
            "SAT-3", heartbeat_url="http://controller:5000/heartbeat"
        )
        agent.receive_state(orbital_state())

        agent.send_heartbeat()

        sent_request = mocked_urlopen.call_args.args[0]
        self.assertEqual(json.loads(sent_request.data)["neighbors"], 4)
        self.assertEqual(sent_request.get_method(), "POST")
        self.assertIsNotNone(agent.status()["heartbeat"]["last_sent_at"])

    @patch("app.agent.urlopen")
    def test_synchronizes_state_from_simulator(self, mocked_urlopen):
        response = MagicMock()
        response.read.return_value = json.dumps(orbital_state()).encode("utf-8")
        mocked_urlopen.return_value.__enter__.return_value = response
        agent = SatelliteAgent("SAT-3", simulator_url="http://simulator:5000")

        agent.sync_from_simulator()

        sent_request = mocked_urlopen.call_args.args[0]
        self.assertTrue(sent_request.full_url.endswith("/api/v1/satellites/SAT-3"))
        self.assertIsNotNone(agent.orbital_state())


if __name__ == "__main__":
    unittest.main()
