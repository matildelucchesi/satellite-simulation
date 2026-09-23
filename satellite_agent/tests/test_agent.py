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
                "neighbor_ids": [
                    "SAT-1",
                    "SAT-2",
                    "SAT-4",
                    "SAT-5",
                    "SAT-6",
                    "SAT-7",
                ],
                "cpu": 28,
                "controller": False,
            },
        )

    @patch("app.agent.psutil.cpu_percent", return_value=28.0)
    def test_heartbeat_uses_only_physical_neighbors_when_available(
        self, _cpu_percent
    ):
        state = orbital_state()
        state["physical_neighbors"] = ["SAT-1", "SAT-6"]
        self.agent.receive_state(state)

        heartbeat = self.agent.build_heartbeat()

        self.assertEqual(heartbeat["neighbors"], 2)
        self.assertEqual(heartbeat["neighbor_ids"], ["SAT-1", "SAT-6"])

    def test_controller_lifecycle_is_idempotent(self):
        first = self.agent.start_controller()
        second = self.agent.start_controller()
        stopped = self.agent.stop_controller()

        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertFalse(stopped["controller"])

    def test_controller_requests_outbound_migration(self):
        self.agent.start_controller()
        migration = self.agent.request_migration(
            {
                "source_satellite_id": "SAT-3",
                "target_satellite_id": "SAT-7",
            }
        )

        self.assertEqual(migration["status"], "requested")
        self.assertEqual(migration["direction"], "outbound")
        self.assertEqual(migration["target_satellite_id"], "SAT-7")

    def test_non_controller_cannot_request_outbound_migration(self):
        with self.assertRaisesRegex(
            Exception, "solo dal satellite che ospita il Controller"
        ):
            self.agent.request_migration(
                {
                    "source_satellite_id": "SAT-3",
                    "target_satellite_id": "SAT-7",
                }
            )

    def test_acknowledges_final_controller_state(self):
        migration = self.agent.prepare_migration(
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

    def test_target_cannot_start_controller_before_final_update(self):
        self.agent.prepare_migration(
            {
                "migration_id": "migration-early-start",
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

        with self.assertRaisesRegex(Exception, "update finale"):
            self.agent.start_controller()
        self.assertFalse(self.agent.status()["controller"])

    def test_target_activation_rewrites_migrated_controller_flags(self):
        initial = {
            "topology": {"nodes": {}, "links": []},
            "routing_table": {},
            "heartbeats": {},
            "sequence_number": 4,
            "timestamp": "2026-07-19T10:00:00Z",
        }
        self.agent.prepare_migration(
            {
                "migration_id": "migration-1",
                "source_satellite_id": "SAT-1",
                "target_satellite_id": "SAT-3",
                "controller_state": initial,
            }
        )
        final_state = {
            "topology": {
                "nodes": {
                    "SAT-1": {"controller": True},
                    "SAT-3": {"controller": False},
                },
                "links": [],
            },
            "routing_table": {},
            "heartbeats": {
                "SAT-1": {"controller": True},
                "SAT-3": {"controller": False},
            },
            "sequence_number": 7,
            "timestamp": "2026-07-19T10:00:05Z",
        }
        self.agent.receive_controller_state(
            {"migration_id": "migration-1", "controller_state": final_state}
        )

        self.agent.start_controller()
        migrated = self.agent.status()["migration"]["controller_state"]

        self.assertFalse(migrated["heartbeats"]["SAT-1"]["controller"])
        self.assertTrue(migrated["heartbeats"]["SAT-3"]["controller"])
        self.assertFalse(migrated["topology"]["nodes"]["SAT-1"]["controller"])
        self.assertTrue(migrated["topology"]["nodes"]["SAT-3"]["controller"])
        self.assertTrue(self.agent.controller_service.active)
        local_state = self.agent.controller_service.snapshot()
        self.assertFalse(local_state["heartbeats"]["SAT-1"]["controller"])
        self.assertTrue(local_state["heartbeats"]["SAT-3"]["controller"])
        self.assertEqual(self.agent.controller_service.host_satellite_id, "SAT-3")

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

    @patch("app.agent.psutil.cpu_percent", return_value=28.0)
    def test_sends_heartbeat_to_simulator_and_controller(self, _cpu_percent):
        transport = FakeTransport()
        agent = SatelliteAgent(
            "SAT-3",
            heartbeat_url="http://simulator:5000/api/v1/heartbeats",
            controller_heartbeat_url="http://controller:5000/heartbeat",
            transport=transport,
        )
        state = orbital_state()
        state["physical_neighbors"] = ["SAT-1", "SAT-6"]
        agent.receive_state(state)

        agent.send_heartbeat()

        calls = [call for call in transport.calls if call[0] == "POST"]
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            {call[1] for call in calls},
            {
                "http://simulator:5000/api/v1/heartbeats",
                "http://controller:5000/heartbeat",
            },
        )
        self.assertTrue(all(call[2]["neighbor_ids"] == ["SAT-1", "SAT-6"] for call in calls))

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
