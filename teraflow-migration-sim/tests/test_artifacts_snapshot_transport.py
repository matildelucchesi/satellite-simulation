import hashlib
import tempfile
import time
import unittest
from pathlib import Path

from src.artifacts import HostInventory, describe
from src.snapshot import apply_delta, delta, snapshot
from src.transport import Receiver, transfer


class ArtifactSnapshotTransportTests(unittest.TestCase):
    def test_delta_roundtrip_including_deletion_and_empty_changes(self):
        first = snapshot({"contexts": [{"context_id": {"context_uuid": {"uuid": "a"}}, "name": "old"}],
                          "devices": [{"device_id": {"device_uuid": {"uuid": "gone"}}}]})
        second = snapshot({"contexts": [{"context_id": {"context_uuid": {"uuid": "a"}}, "name": "new"}]})
        self.assertEqual(apply_delta(first, delta(first, second)), second)
        self.assertEqual(apply_delta(first, delta(first, first)), first)

    def test_tcp_receiver_checksum_and_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "payload.bin"
            path.write_bytes(bytes(range(256)) * 4096)
            with Receiver(Path(directory) / "received", progress_timeout_s=2) as receiver:
                result = transfer(path, receiver.address, 100_000_000, progress_timeout_s=2)
                self.assertEqual(Path(result["path"]).read_bytes(), path.read_bytes())
                inventory = HostInventory()
                inventory.accept("sat-b", describe(path), result)
                inventory.require("sat-b")
                with self.assertRaises(RuntimeError): inventory.require("sat-a")

    def test_corrupt_copy_is_discarded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "payload.bin"
            path.write_bytes(b"valid bytes" * 100)
            destination = Path(directory) / "received"
            with Receiver(destination, progress_timeout_s=1) as receiver:
                with self.assertRaises(ConnectionError):
                    transfer(path, receiver.address, 100_000_000, corrupt_checksum=True, progress_timeout_s=1)
            self.assertFalse((destination / path.name).exists())
            self.assertFalse(list(destination.glob("*.partial")))

    def test_deadline_terminates_paced_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "payload.bin"
            path.write_bytes(b"x" * 100000)
            with Receiver(Path(directory) / "received", progress_timeout_s=1) as receiver:
                with self.assertRaises(TimeoutError):
                    transfer(path, receiver.address, 1000, deadline_monotonic=time.monotonic()+0.05,
                             progress_timeout_s=1)


if __name__ == "__main__": unittest.main()
