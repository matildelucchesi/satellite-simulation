"""Test dell'elezione e dell'attivazione iniziale del Controller."""

import unittest

from app.migration_manager import RestResponse
from app.startup_controller import StartupControllerConfig, StartupControllerManager


class FakeTransport:
    def __init__(self):
        self.calls = []

    def request(self, method, url, payload, timeout_seconds):
        self.calls.append((method, url, payload, timeout_seconds))
        return RestResponse(status=200, payload={"status": "ok"}, bytes_received=0)


def constellation_snapshot():
    return {
        "generated_at": "2026-07-19T10:00:00.000Z",
        "satellites": {
            "SAT-1": {
                "illumination": {
                    "state": "sunlight",
                    "seconds_until_eclipse": 500,
                }
            },
            "SAT-2": {
                "illumination": {
                    "state": "sunlight",
                    "seconds_until_eclipse": 121,
                }
            },
            "SAT-3": {
                "illumination": {
                    "state": "sunlight",
                    "seconds_until_eclipse": 120,
                }
            },
            "SAT-4": {
                "illumination": {
                    "state": "shadow",
                    "seconds_until_eclipse": 900,
                }
            },
        },
    }


class StartupControllerManagerTests(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()
        self.manager = StartupControllerManager(
            satellite_ids=["SAT-1", "SAT-2", "SAT-3", "SAT-4"],
            config=StartupControllerConfig(
                strategy="minimum_remaining_sunlight",
                minimum_sunlight_seconds=120,
                retry_seconds=1,
            ),
            agent_url=lambda satellite_id: f"http://{satellite_id.lower()}:5000",
            controller_url="http://controller:5000",
            transport=self.transport,
        )

    def test_selects_smallest_remaining_sunlight_strictly_above_limit(self):
        self.manager.update_constellation(constellation_snapshot())

        state = self.manager.snapshot()

        self.assertEqual(state["selected_satellite_id"], "SAT-2")
        self.assertEqual(state["selected_time_to_eclipse_seconds"], 121)
        self.assertEqual(
            [item["satellite_id"] for item in state["eligible_candidates"]],
            ["SAT-2", "SAT-1"],
        )

    def test_activation_starts_selected_agent_and_stops_all_others(self):
        self.manager.update_constellation(constellation_snapshot())

        activated = self.manager.activate_once()
        calls = {(method, url): payload for method, url, payload, _ in self.transport.calls}

        self.assertTrue(activated)
        self.assertIn(("POST", "http://sat-2:5000/start_controller"), calls)
        self.assertIn(("POST", "http://sat-1:5000/stop_controller"), calls)
        self.assertIn(("POST", "http://sat-3:5000/stop_controller"), calls)
        self.assertIn(("POST", "http://sat-4:5000/stop_controller"), calls)
        self.assertEqual(
            calls[("POST", "http://controller:5000/host")],
            {"satellite_id": "SAT-2"},
        )
        self.assertEqual(self.manager.snapshot()["status"], "active")

    def test_waits_when_no_satellite_is_eligible(self):
        snapshot = constellation_snapshot()
        for satellite in snapshot["satellites"].values():
            satellite["illumination"]["state"] = "shadow"

        self.manager.update_constellation(snapshot)

        self.assertEqual(
            self.manager.snapshot()["status"], "waiting_for_eligible_satellite"
        )
        self.assertIsNone(self.manager.snapshot()["selected_satellite_id"])


if __name__ == "__main__":
    unittest.main()
