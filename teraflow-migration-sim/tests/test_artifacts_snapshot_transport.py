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

    def test_path_delay_adds_handshake_slow_start_and_final_receipt(self):
        from src.transport import latency_offset_s, INITIAL_WINDOW_BYTES
        self.assertEqual(latency_offset_s(1000, 0), 0)
        self.assertAlmostEqual(latency_offset_s(INITIAL_WINDOW_BYTES, .01), .02)
        self.assertAlmostEqual(latency_offset_s(3 * INITIAL_WINDOW_BYTES, .01), .04)

    def test_modelled_transfer_counts_the_crossings_of_the_path(self):
        from src.transport import modelled_transfer
        # The state snapshot (about 250 kB) over a 24 ms path: handshake, 4 slow-start rounds and the
        # final receipt cross the path 11 times; the rate (2 ms at 1 Gbit/s) does not bound it
        model = modelled_transfer(247360, .024, 1_000_000_000)
        self.assertEqual((model['bound'], model['crossings'], model['slow_start_rounds']), ('latency', 11, 4))
        self.assertAlmostEqual(model['modelled_s'], 11 * .024)
        # A small delta: one round trip and the receipt
        self.assertEqual(modelled_transfer(505, .024, 1_000_000_000)['crossings'], 3)
        self.assertAlmostEqual(modelled_transfer(505, .024, 1_000_000_000)['modelled_s'], 3 * .024)
        # 100 MB at 1 Gbit/s over 1 ms: the rate bounds it
        large = modelled_transfer(100_000_000, .001, 1_000_000_000)
        self.assertEqual(large['bound'], 'rate')
        self.assertAlmostEqual(large['modelled_s'], .8 + .001)

    def test_deadline_terminates_paced_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "payload.bin"
            path.write_bytes(b"x" * 100000)
            with Receiver(Path(directory) / "received", progress_timeout_s=1) as receiver:
                with self.assertRaises(TimeoutError):
                    transfer(path, receiver.address, 1000, deadline_monotonic=time.monotonic()+0.05,
                             progress_timeout_s=1)


if __name__ == "__main__": unittest.main()
