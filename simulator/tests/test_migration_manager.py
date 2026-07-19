"""Test delle sequenze Cold/Hot e delle metriche di migrazione."""

from copy import deepcopy
import unittest

from app.migration_manager import (
    MigrationConfig,
    MigrationManager,
    RestResponse,
)
from app.contact_window import ContactWindowConfig


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


def config(alignment_seconds=0.0):
    return MigrationConfig(
        default_mode="hot",
        controller_url="http://controller:5000",
        agent_url_template="http://satellite-{satellite_number}:5000",
        request_timeout_seconds=1.0,
        max_retries=0,
        retry_delay_seconds=0.0,
        contact_window=ContactWindowConfig(
            required_alignment_seconds=alignment_seconds,
            max_distance_km=5500.0,
            require_line_of_sight=True,
            earth_radius_km=6378.137,
            max_sample_gap_seconds=2.5,
        ),
    )


def constellation(second, in_contact=True):
    target = {"x": 7000.0, "y": 1000.0, "z": 0.0}
    if not in_contact:
        target = {"x": -7000.0, "y": 0.0, "z": 0.0}
    return {
        "generated_at": f"2026-07-19T10:00:{second:02d}Z"
        if second < 60
        else f"2026-07-19T10:01:{second - 60:02d}Z",
        "satellites": {
            "SAT-1": {"position_km": {"x": 7000.0, "y": 0.0, "z": 0.0}},
            "SAT-2": {"position_km": target},
        },
    }


class MigrationManagerTests(unittest.TestCase):
    def test_repeated_recommendation_reuses_pending_alignment(self):
        manager = MigrationManager(
            config(alignment_seconds=60), ["SAT-1", "SAT-2"], FakeTransport()
        )

        first = manager.enqueue("SAT-1", "SAT-2", "hot")
        second = manager.enqueue("SAT-1", "SAT-2", "hot")

        self.assertEqual(second, first)
        self.assertEqual(manager.snapshot()["count"], 1)

    def test_requires_sixty_seconds_of_continuous_contact_before_queueing(self):
        manager = MigrationManager(
            config(alignment_seconds=60), ["SAT-1", "SAT-2"], FakeTransport()
        )
        migration_id = manager.enqueue("SAT-1", "SAT-2", "hot")

        for second in range(60):
            manager.update_constellation(constellation(second))

        waiting = manager.migration_snapshot(migration_id)
        self.assertEqual(waiting["status"], "waiting_for_contact")
        self.assertEqual(
            waiting["contact_window"]["continuous_alignment_seconds"], 59.0
        )
        self.assertFalse(manager.process_next())

        manager.update_constellation(constellation(60))

        ready = manager.migration_snapshot(migration_id)
        self.assertEqual(ready["status"], "queued")
        self.assertEqual(ready["metrics"]["alignment_wait_ms"], 60000.0)
        self.assertEqual(
            [event["name"] for event in ready["events"]],
            [
                "target_selected",
                "contact_alignment_started",
                "contact_window_ready",
            ],
        )

    def test_contact_interruption_resets_the_sixty_second_alignment(self):
        manager = MigrationManager(
            config(alignment_seconds=60), ["SAT-1", "SAT-2"], FakeTransport()
        )
        migration_id = manager.enqueue("SAT-1", "SAT-2", "cold")
        for second in range(31):
            manager.update_constellation(constellation(second))
        manager.update_constellation(constellation(31, in_contact=False))
        for second in range(32, 92):
            manager.update_constellation(constellation(second))

        waiting = manager.migration_snapshot(migration_id)
        self.assertEqual(waiting["status"], "waiting_for_contact")
        self.assertEqual(waiting["contact_window"]["reset_count"], 1)
        self.assertIn(
            "contact_alignment_reset",
            [event["name"] for event in waiting["events"]],
        )

        manager.update_constellation(constellation(92))

        self.assertEqual(manager.migration_snapshot(migration_id)["status"], "queued")

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
        ack_step = next(
            step
            for step in migration["metrics"]["steps"]
            if step["name"] == "transfer_final_state_and_wait_target_ack"
        )
        self.assertIsNotNone(ack_step["started_at"])
        self.assertIsNotNone(ack_step["completed_at"])
        self.assertEqual(ack_step["http_status"], 200)

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
