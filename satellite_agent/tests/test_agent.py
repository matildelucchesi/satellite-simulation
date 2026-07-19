"""Test dello stato e degli heartbeat del Satellite Agent."""

import unittest
from unittest.mock import patch

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
            **{
                f"SAT-{index}": float(index * 100)
                for index in range(1, 8)
                if index != 3
            },
            "SAT-3": 0.0,
        },
    }


class FakeTransport:
    def __init__(self, get_payload=None, post_status=202):
        self.get_payload = get_payload
        self.post_status = post_status
        self.calls = []

    def get_json(self, url, timeout):
        self.calls.append(("GET", url, None, timeout))
        return self.get_payload

    def post_json(self, url, payload, timeout):
        self.calls.append(("POST", url, payload, timeout))
        return self.post_status


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
                "neighbors": 6,
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

    def test_acknowledges_final_controller_state(self):
        migration = self.agent.accept_migration(
            {
                "migration_id": "migration-1",
                "source_satellite_id": "SAT-1",
                "target_satellite_id": "SAT-3",
                "controller_state": {
                    "topology": {"nodes": {}, "links": []},
                    "routing_table": {},
                    "heartbeats": {},
                    "sequence_number": 4,
                    "timestamp": "2026-07-19T10:00:00Z",
                },
            }
        )
        acknowledgement = self.agent.receive_controller_state(
            {
                "migration_id": migration["migration_id"],
                "controller_state": {
                    "topology": {"nodes": {}, "links": []},
                    "routing_table": {},
                    "heartbeats": {},
                    "sequence_number": 7,
                    "timestamp": "2026-07-19T10:00:05Z",
                },
            }
        )

        self.assertEqual(acknowledgement["status"], "ack")
        self.assertEqual(acknowledgement["sequence_number"], 7)
        self.assertEqual(
            self.agent.status()["migration"]["status"], "final_state_received"
        )

    @patch("app.agent.psutil.cpu_percent", return_value=28.0)
    def test_sends_heartbeat_as_json(self, _cpu_percent):
        transport = FakeTransport()
        agent = SatelliteAgent(
            "SAT-3",
            heartbeat_url="http://controller:5000/heartbeat",
            transport=transport,
        )
        agent.receive_state(orbital_state())

        agent.send_heartbeat()

        method, _url, payload, _timeout = transport.calls[0]
        self.assertEqual(payload["neighbors"], 6)
        self.assertEqual(method, "POST")
        self.assertIsNotNone(agent.status()["heartbeat"]["last_sent_at"])

    def test_synchronizes_state_from_simulator(self):
        transport = FakeTransport(get_payload=orbital_state())
        agent = SatelliteAgent(
            "SAT-3",
            simulator_url="http://simulator:5000",
            transport=transport,
        )

        agent.sync_from_simulator()

        _method, url, _payload, _timeout = transport.calls[0]
        self.assertTrue(url.endswith("/api/v1/satellites/SAT-3"))
        self.assertIsNotNone(agent.orbital_state())


if __name__ == "__main__":
    unittest.main()
