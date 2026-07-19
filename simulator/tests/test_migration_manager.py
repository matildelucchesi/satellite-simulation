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
    def __init__(self, restore_status=200):
        self.calls = []
        self.restore_status = restore_status

    def request(self, method, url, payload, timeout):
        self.calls.append((method, url, deepcopy(payload)))
        if url.endswith("/checkpoint"):
            return RestResponse(201, {"checkpoint": deepcopy(CHECKPOINT)}, 256)
        if url.endswith("/restore"):
            return RestResponse(self.restore_status, {"status": "restored"}, 32)
        if url.endswith("/shutdown"):
            return RestResponse(202, {"status": "shutdown"}, 16)
        if url.endswith("/migration_request"):
            return RestResponse(202, {"status": "accepted"}, 16)
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
    def test_hot_migration_waits_for_ack_before_stopping_source(self):
        transport = FakeTransport()
        manager = MigrationManager(config(), ["SAT-1", "SAT-2"], transport)
        migration_id = manager.enqueue("SAT-1", "SAT-2", "hot")

        manager.process_next()

        migration = manager.migration_snapshot(migration_id)
        urls = [call[1] for call in transport.calls]
        self.assertEqual(migration["status"], "completed")
        self.assertTrue(migration["metrics"]["ack_received"])
        self.assertLess(urls.index("http://controller:5000/restore"), urls.index("http://satellite-1:5000/stop_controller"))
        self.assertEqual(migration["metrics"]["downtime_ms"], 0.0)

    def test_cold_migration_stops_controller_before_transfer(self):
        transport = FakeTransport()
        manager = MigrationManager(config(), ["SAT-1", "SAT-2"], transport)
        migration_id = manager.enqueue("SAT-1", "SAT-2", "cold")

        manager.process_next()

        migration = manager.migration_snapshot(migration_id)
        urls = [call[1] for call in transport.calls]
        self.assertEqual(migration["status"], "completed")
        self.assertLess(urls.index("http://controller:5000/shutdown"), urls.index("http://controller:5000/restore"))
        self.assertIsNotNone(migration["metrics"]["downtime_ms"])
        self.assertGreater(migration["metrics"]["state_bytes"], 0)

    def test_missing_http_200_ack_fails_and_records_rollback(self):
        transport = FakeTransport(restore_status=202)
        manager = MigrationManager(config(), ["SAT-1", "SAT-2"], transport)
        migration_id = manager.enqueue("SAT-1", "SAT-2", "hot")

        manager.process_next()

        migration = manager.migration_snapshot(migration_id)
        self.assertEqual(migration["status"], "failed")
        self.assertFalse(migration["metrics"]["ack_received"])
        self.assertTrue(migration["metrics"]["rollback_attempted"])


if __name__ == "__main__":
    unittest.main()
