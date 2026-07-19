"""Test di stato, routing e serializzazione del Controller."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.service import ControllerService, ControllerState


def heartbeat(satellite_id=3, neighbor_ids=None):
    payload = {
        "id": satellite_id,
        "time_to_eclipse": 540,
        "neighbors": 4,
        "cpu": 28,
        "controller": satellite_id == 1,
    }
    if neighbor_ids is not None:
        payload["neighbor_ids"] = neighbor_ids
    return payload


class ControllerStateTests(unittest.TestCase):
    def test_state_round_trip_json(self):
        state = ControllerState.empty()

        restored = ControllerState.from_json(state.to_json())

        self.assertEqual(restored.to_dict(), state.to_dict())


class ControllerServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.path = Path(self.temporary_directory.name) / "checkpoint.json"
        self.controller = ControllerService(self.path)

    def test_heartbeat_updates_state_and_sequence(self):
        self.controller.record_heartbeat(heartbeat())
        state = self.controller.snapshot()

        self.assertEqual(state["sequence_number"], 1)
        self.assertIn("SAT-3", state["heartbeats"])
        self.assertIn("SAT-3", state["topology"]["nodes"])

    def test_routing_table_is_built_from_neighbor_ids(self):
        self.controller.record_heartbeat(heartbeat(1, [2]))
        self.controller.record_heartbeat(heartbeat(2, [1, 3]))
        self.controller.record_heartbeat(heartbeat(3, [2]))

        routes = self.controller.snapshot()["routing_table"]

        self.assertEqual(routes["SAT-1"]["SAT-3"]["next_hop"], "SAT-2")
        self.assertEqual(routes["SAT-1"]["SAT-3"]["hops"], 2)

    def test_checkpoint_and_restore_from_file(self):
        self.controller.record_heartbeat(heartbeat())
        expected = self.controller.checkpoint()
        self.assertTrue(self.path.is_file())
        self.assertEqual(json.loads(self.path.read_text()), expected)

        another_controller = ControllerService(self.path)
        restored = another_controller.restore()

        self.assertEqual(restored, expected)

    def test_shutdown_blocks_heartbeats_until_restore(self):
        self.controller.record_heartbeat(heartbeat())
        self.controller.shutdown()

        with self.assertRaises(RuntimeError):
            self.controller.record_heartbeat(heartbeat(4))

        self.controller.restore()
        self.controller.record_heartbeat(heartbeat(4))
        self.assertIn("SAT-4", self.controller.snapshot()["heartbeats"])


if __name__ == "__main__":
    unittest.main()

