"""Test delle sequenze Cold/Hot e delle metriche di migrazione."""

from copy import deepcopy
import unittest

from app.migration_manager import (
    MigrationConfig,
    MigrationManager,
    RestResponse,
)


CHECKPOINT = {
    "topology": {"nodes": {}, "links": []},
    "routing_table": {},
    "heartbeats": {},
    "sequence_number": 4,
    "timestamp": "2026-07-19T10:00:00Z",
}


class FakeTransport:
    def __init__(self, target_ack_status=200):
        self.calls = []
        self.target_ack_status = target_ack_status
        self.checkpoint_count = 0

    def request(self, method, url, payload, timeout):
        self.calls.append((method, url, deepcopy(payload)))
        if url.endswith("/checkpoint"):
            self.checkpoint_count += 1
            checkpoint = deepcopy(CHECKPOINT)
            if self.checkpoint_count > 1:
                checkpoint["sequence_number"] = 7
                checkpoint["timestamp"] = "2026-07-19T10:00:05Z"
            return RestResponse(201, {"checkpoint": checkpoint}, 256)
        if url.endswith("/restore"):
            return RestResponse(200, {"status": "restored"}, 32)
        if url.endswith("/shutdown"):
            return RestResponse(202, {"status": "shutdown"}, 16)
        if url.endswith("/migration_request"):
            return RestResponse(202, {"status": "accepted"}, 16)
        if url.endswith("/receive_controller_state"):
            sequence = payload["controller_state"]["sequence_number"]
            return RestResponse(
                self.target_ack_status,
                {"status": "ack", "sequence_number": sequence},
                32,
            )
        return RestResponse(200, {"status": "ok"}, 16)


def config():
    return MigrationConfig(
        default_mode="hot",
        controller_url="http://controller:5000",
        agent_url_template="http://satellite-{satellite_number}:5000",
        request_timeout_seconds=1.0,
        max_retries=0,
        retry_delay_seconds=0.0,
    )


class MigrationManagerTests(unittest.TestCase):
    def test_hot_migration_syncs_final_state_before_stopping_source(self):
        transport = FakeTransport()
        manager = MigrationManager(config(), ["SAT-1", "SAT-2"], transport)
        migration_id = manager.enqueue("SAT-1", "SAT-2", "hot")

        manager.process_next()

        migration = manager.migration_snapshot(migration_id)
        urls = [call[1] for call in transport.calls]
        checkpoint_indices = [
            index
            for index, url in enumerate(urls)
            if url == "http://controller:5000/checkpoint"
        ]
        quiesce_index = urls.index("http://controller:5000/quiesce")
        ack_index = urls.index("http://satellite-2:5000/receive_controller_state")
        stop_index = urls.index("http://satellite-1:5000/stop_controller")
        restore_index = urls.index("http://controller:5000/restore")
        start_index = urls.index("http://satellite-2:5000/start_controller")
        self.assertEqual(migration["status"], "completed")
        self.assertTrue(migration["metrics"]["ack_received"])
        self.assertLess(quiesce_index, checkpoint_indices[1])
        self.assertLess(checkpoint_indices[1], ack_index)
        self.assertLess(ack_index, stop_index)
        self.assertLess(stop_index, restore_index)
        self.assertLess(restore_index, start_index)
        self.assertEqual(urls.count("http://controller:5000/checkpoint"), 2)
        self.assertEqual(migration["metrics"]["initial_sequence_number"], 4)
        self.assertEqual(migration["metrics"]["final_sequence_number"], 7)
        self.assertEqual(migration["metrics"]["updates_during_transfer"], 3)
        self.assertTrue(migration["metrics"]["controller_restore_ack"])
        self.assertIsNotNone(migration["metrics"]["downtime_ms"])

    def test_cold_migration_transfers_frozen_state_and_waits_for_ack(self):
        transport = FakeTransport()
        manager = MigrationManager(config(), ["SAT-1", "SAT-2"], transport)
        migration_id = manager.enqueue("SAT-1", "SAT-2", "cold")

        manager.process_next()

        migration = manager.migration_snapshot(migration_id)
        urls = [call[1] for call in transport.calls]
        quiesce_index = urls.index("http://controller:5000/quiesce")
        stop_index = urls.index("http://satellite-1:5000/stop_controller")
        checkpoint_index = urls.index("http://controller:5000/checkpoint")
        shutdown_index = urls.index("http://controller:5000/shutdown")
        ack_index = urls.index("http://satellite-2:5000/receive_controller_state")
        restore_index = urls.index("http://controller:5000/restore")
        start_index = urls.index("http://satellite-2:5000/start_controller")
        self.assertEqual(migration["status"], "completed")
        self.assertLess(quiesce_index, stop_index)
        self.assertLess(stop_index, checkpoint_index)
        self.assertLess(checkpoint_index, shutdown_index)
        self.assertLess(shutdown_index, ack_index)
        self.assertLess(ack_index, restore_index)
        self.assertLess(restore_index, start_index)
        self.assertTrue(migration["metrics"]["ack_received"])
        self.assertEqual(migration["metrics"]["final_sequence_number"], 4)
        self.assertIsNotNone(migration["metrics"]["downtime_ms"])
        self.assertGreater(migration["metrics"]["state_bytes"], 0)

    def test_cold_migration_rolls_back_when_target_ack_is_missing(self):
        transport = FakeTransport(target_ack_status=202)
        manager = MigrationManager(config(), ["SAT-1", "SAT-2"], transport)
        migration_id = manager.enqueue("SAT-1", "SAT-2", "cold")

        manager.process_next()

        migration = manager.migration_snapshot(migration_id)
        urls = [call[1] for call in transport.calls]
        self.assertEqual(migration["status"], "failed")
        self.assertFalse(migration["metrics"]["ack_received"])
        self.assertTrue(migration["metrics"]["rollback_succeeded"])
        self.assertIn("http://controller:5000/restore", urls)
        self.assertIn("http://satellite-1:5000/start_controller", urls)

    def test_missing_http_200_ack_fails_and_records_rollback(self):
        transport = FakeTransport(target_ack_status=202)
        manager = MigrationManager(config(), ["SAT-1", "SAT-2"], transport)
        migration_id = manager.enqueue("SAT-1", "SAT-2", "hot")

        manager.process_next()

        migration = manager.migration_snapshot(migration_id)
        self.assertEqual(migration["status"], "failed")
        self.assertFalse(migration["metrics"]["ack_received"])
        self.assertTrue(migration["metrics"]["rollback_attempted"])
        urls = [call[1] for call in transport.calls]
        self.assertIn("http://controller:5000/resume", urls)


if __name__ == "__main__":
    unittest.main()
