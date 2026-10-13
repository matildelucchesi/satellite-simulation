import tempfile
import unittest
from pathlib import Path
from src.authority import Authority
from src.clock import ManualClock
from src.orchestrator import Migration
from src.snapshot import snapshot


class Backend:
    def __init__(self, clock, failure=None): self.clock, self.failure, self.calls = clock, failure, []
    def contact(self, tick): return True
    def prepare_target(self): pass
    def export_source(self): return snapshot({})
    def transfer(self, path, event):
        from src.artifacts import describe
        if self.failure == "copy": raise ConnectionError("link lost")
        item = describe(path); self.clock.sleep(1)
        return {"sent_bytes": item["bytes"], "received_bytes": item["bytes"], "sha256": item["sha256"]}
    def start_target(self, receipt): self.calls.append("start")
    def stop_source(self): self.calls.append("stop")
    def freeze_source(self): self.calls.append("freeze")
    def restore_target(self, state): self.calls.append("restore")
    def apply_target_delta(self, *args): self.calls.append("delta")
    def verify_target(self, expected): return {"equivalent": self.failure != "verify"}
    def staged_ready(self): return self.failure != "staged"
    def ack(self, **checks): self.calls.append("ack")
    def cutover(self): self.calls.append("cutover")
    def abort_target(self): self.calls.append("abort")
    def recover_source(self): self.calls.append("recover")


class AuthorityOrchestratorTests(unittest.TestCase):
    def test_deadline_during_alignment_has_no_transfer_or_ack(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = ManualClock(); backend = Backend(clock)
            image = Path(tmp)/"images.tar"; image.write_bytes(b"image")
            migration = Migration(backend, clock, Path(tmp)/"run", {"fso": {"alignment_s": 60, "max_attempts": 3}})
            result = migration.run("hot", {"deadline_s": 30, "trigger_causes": ["shadow"]}, image)
            self.assertFalse(result["ack"])
            self.assertEqual(result["attempt"], 1)
            self.assertEqual(result["bytes_sent"], 0)
            self.assertNotIn("recover", backend.calls)
            self.assertEqual(clock.now(), 30)

    def test_recovery_failure_preserves_metadata_and_stops_retries(self):
        import json
        for operation in ("abort_target", "recover_source"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as tmp:
                clock = ManualClock(); backend = Backend(clock, "copy")
                def fail(): raise RuntimeError("recovery unavailable")
                setattr(backend, operation, fail)
                image = Path(tmp)/"images.tar"; image.write_bytes(b"image")
                directory = Path(tmp)/"run"
                migration = Migration(backend, clock, directory, {"fso": {"alignment_s": 60, "max_attempts": 3}})
                result = migration.run("cold", {"deadline_s": 1000, "trigger_causes": ["resources"]}, image)
                self.assertEqual(result["attempt"], 1)
                self.assertTrue(result["recovery_required"])
                self.assertFalse(result["ack"])
                self.assertTrue(json.loads((directory/'checkpoint.json').read_text())['requires_fenced_recovery_after_crash'])
                self.assertEqual(json.loads((directory/"metadata.json").read_text())["recovery_failure"], "recovery unavailable")
                if operation == "abort_target": self.assertNotIn("recover", backend.calls)

    def test_failed_reconcile_leaves_both_sides_fenced(self):
        authority = Authority(); authority.freeze()
        self.assertTrue(authority.ready(images=True, api=True, staged=True))
        def fail(): raise RuntimeError("hardware error")
        with self.assertRaises(RuntimeError): authority.cutover("sat-b", fail)
        self.assertIsNone(authority.active)
        self.assertFalse(authority.ack)

    def test_historical_ack_survives_failed_cutover_with_current_ack_revoked(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = ManualClock();backend = Backend(clock)
            def fail():raise RuntimeError('Hardware readback failed')
            backend.cutover = fail
            image=Path(tmp)/'images.tar';image.write_bytes(b'image')
            migration=Migration(backend,clock,Path(tmp)/'run',{'fso':{'alignment_s':60,'max_attempts':3}})
            result=migration.run('hot',{'deadline_s':1000,'trigger_causes':['resources']},image)
            self.assertFalse(result['success']);self.assertFalse(result['ack'])
            self.assertEqual(result['attempt'],3)
            self.assertEqual(sum(row['phase']=='ack' for row in result['events']),3)
            self.assertEqual(backend.calls.count('recover'),3)

    def test_ack_cannot_bypass_readiness_or_freeze(self):
        authority = Authority()
        self.assertFalse(authority.ready(images=False, api=True, staged=True))
        with self.assertRaises(RuntimeError): authority.cutover("sat-b", lambda: None)
        self.assertTrue(authority.writable("sat-a"))
        self.assertFalse(authority.writable("sat-b"))

    def test_modes_and_failure_never_ack(self):
        for method in ("hot", "cold"):
            for failure in (None, "copy", "verify", "staged"):
                with self.subTest(method=method, failure=failure), tempfile.TemporaryDirectory() as tmp:
                    clock = ManualClock(); backend = Backend(clock, failure)
                    image = Path(tmp)/"images.tar"; image.write_bytes(b"image")
                    migration = Migration(backend, clock, Path(tmp)/"run", {"fso": {"alignment_s": 60, "max_attempts": 3}})
                    result = migration.run(method, {"deadline_s": 1000, "trigger_causes": ["resources"]}, image)
                    self.assertEqual(result["success"], failure is None)
                    if failure:
                        self.assertNotIn("ack", backend.calls)
                        self.assertNotIn("cutover", backend.calls)
                        self.assertEqual(result["attempt"], 3)
                    else:
                        self.assertLess(backend.calls.index("ack"), backend.calls.index("cutover"))
                        self.assertEqual(len([e for e in result["events"] if e["phase"] == "alignment"]), 1)


if __name__ == "__main__": unittest.main()
