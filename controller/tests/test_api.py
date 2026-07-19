"""Test delle API REST pubbliche del Controller."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app import create_app
from test_service import heartbeat


class ControllerApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        checkpoint_path = Path(self.temporary_directory.name) / "checkpoint.json"
        self.app = create_app(
            {
                "TESTING": True,
                "CHECKPOINT_PATH": str(checkpoint_path),
            }
        )
        self.client = self.app.test_client()

    def test_receives_and_returns_heartbeat(self):
        received = self.client.post("/heartbeat", json=heartbeat())
        listed = self.client.get("/heartbeat?id=SAT-3")

        self.assertEqual(received.status_code, 202)
        self.assertEqual(listed.status_code, 200)
        self.assertIn("SAT-3", listed.get_json()["heartbeats"])

    def test_state_contains_required_fields(self):
        state = self.client.get("/state").get_json()

        self.assertEqual(
            set(state),
            {
                "topology",
                "routing_table",
                "heartbeats",
                "sequence_number",
                "timestamp",
            },
        )

    def test_checkpoint_restore_and_shutdown(self):
        self.client.post("/heartbeat", json=heartbeat())
        checkpoint_response = self.client.post("/checkpoint")
        checkpoint = checkpoint_response.get_json()["checkpoint"]
        shutdown = self.client.post("/shutdown")
        rejected = self.client.post("/heartbeat", json=heartbeat(4))
        restored = self.client.post("/restore", json={"checkpoint": checkpoint})

        self.assertEqual(checkpoint_response.status_code, 201)
        self.assertEqual(shutdown.status_code, 202)
        self.assertEqual(rejected.status_code, 503)
        self.assertEqual(restored.status_code, 200)


if __name__ == "__main__":
    unittest.main()

