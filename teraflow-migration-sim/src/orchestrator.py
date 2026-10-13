"""Migration state machine with explicit ACK gates and bounded recovery.

Backends implement real operations. Unit tests inject a deterministic backend;
the state machine never substitutes modeled timings for live measurements.
"""
from __future__ import annotations
import json
from pathlib import Path
from .artifacts import HostInventory, describe, canonical_bytes
from .snapshot import delta
from .storage import atomic_json, append_json, utc_now


class Migration:
    def __init__(self, backend, clock, directory: Path, scenario: dict):
        self.backend, self.clock, self.directory, self.scenario = backend, clock, directory, scenario
        directory.mkdir(parents=True, exist_ok=False)
        self.events = []
        self.phase = "created"
        self.inventory = HostInventory()
        self.bytes_sent = self.bytes_received = 0
        self.downtime_start = None
        self.ack = False
        self.trigger_time = None

    def transition(self, phase, **details):
        self.phase = phase
        event = {"id": len(self.events)+1, "timestamp_utc": utc_now(), "phase": phase,
                 "elapsed_s": self.clock.now(), "orbital_s": self.clock.orbital(), **details}
        self.events.append(event)
        append_json(self.directory / 'events.jsonl', event)
        atomic_json(self.directory / 'checkpoint.json', {"phase": phase, "ack": self.ack,
            "requires_fenced_recovery_after_crash": phase not in {"created", "completed", "failed"}})
        if hasattr(self.backend, 'notify'): self.backend.notify(event)

    def require_time(self, event):
        if hasattr(self.backend, 'check'): self.backend.check()
        if self.clock.orbital() >= event["deadline_s"]:
            raise TimeoutError("Operational deadline or observation boundary")

    def alignment(self, event):
        self.transition("alignment")
        continuous = 0.0
        while continuous < self.scenario["fso"]["alignment_s"]:
            self.require_time(event)
            if self.backend.contact(self.clock.orbital()):
                continuous += 1
            else:
                continuous = 0
            self.clock.sleep(1)
        self.require_time(event)

    def payload(self, path, event):
        self.transition("transfer", payload=path.name, artifact=describe(path))
        try:
            receipt = self.backend.transfer(path, event)
        except Exception as exc:
            self.bytes_sent += getattr(exc, "sent_bytes", 0)
            self.bytes_received += getattr(exc, "received_bytes", 0)
            raise
        self.bytes_sent += receipt["sent_bytes"]
        self.bytes_received += receipt["received_bytes"]
        self.transition("transfer_verified", payload=path.name, receipt=receipt)
        self.require_time(event)
        return receipt

    def save(self, name, value):
        path = self.directory / name
        atomic_json(path, value)
        return path

    def run(self, method, event, image_bundle: Path):
        if method not in {"cold", "hot"}: raise ValueError("Invalid migration protocol")
        result = {"schema_version": 2, "execution_kind": "live-hybrid", "event": event,
                  "method": method, "success": False, "ack": False}
        self.transition("trigger", causes=event["trigger_causes"])
        self.trigger_time = self.clock.now()
        for attempt in range(1, self.scenario["fso"]["max_attempts"]+1):
            try:
                self.require_time(event)
                self.backend.prepare_target()
                self.alignment(event)
                if method == 'cold' and hasattr(self.backend, 'quiesce_source'):
                    self.transition('quiescence')
                    self.backend.quiesce_source()
                self.transition("snapshot_initial")
                initial = self.backend.export_source()
                snapshot_path = self.save(f"snapshot-{attempt}.json", initial)
                if method == "cold":
                    self.transition("source_stop")
                    self.downtime_start = self.clock.now()
                    self.backend.stop_source()
                    self.transition('source_stopped')
                self.payload(image_bundle, event)
                # Host inventory is accepted only from the verified receiver receipt.
                image_receipt = self.events[-1]["receipt"]
                self.inventory.accept("sat-b", describe(image_bundle), image_receipt)
                state_receipt = self.payload(snapshot_path, event)
                self.inventory.require("sat-b")
                self.transition("target_start")
                self.backend.start_target(image_receipt)
                self.require_time(event)
                self.transition("restore_initial")
                self.backend.restore_target(initial)
                self.require_time(event)
                expected = initial
                if method == "hot":
                    self.transition("freeze")
                    self.downtime_start = self.clock.now()
                    self.backend.freeze_source()
                    self.transition('source_frozen')
                    expected = self.backend.export_source()
                    changes = delta(initial, expected)
                    change_path = self.save(f"delta-{attempt}.json", changes)
                    self.payload(change_path, event)
                    self.transition("restore_delta")
                    self.backend.apply_target_delta(initial, changes)
                self.transition("verify")
                verification = self.backend.verify_target(expected)
                if not verification["equivalent"]:
                    self.save(f'verification-failed-{attempt}.json',verification)
                    raise RuntimeError("API state equivalence failed: " + str(verification.get('mismatched_entity_types')))
                self.require_time(event)
                if not self.backend.staged_ready():
                    raise RuntimeError("Standby P4 state not ready")
                self.backend.ack(images=True, api=True)
                self.ack = True
                self.transition("ack")
                self.require_time(event)
                self.transition("cutover")
                self.backend.cutover()
                self.require_time(event)
                self.transition("completed", attempt=attempt)
                result.update(success=True, ack=True, attempt=attempt,
                              controller_downtime_s=self.clock.now()-self.downtime_start,
                              total_operation_s=self.clock.now()-self.trigger_time)
                break
            except Exception as exc:
                self.ack = False
                self.transition("attempt_failed", attempt=attempt, reason=str(exc))
                result.update(attempt=attempt, failure_phase=self.events[-2]["phase"], failure_reason=str(exc))
                interrupted = isinstance(exc, InterruptedError) or getattr(self.backend, 'cancelled', False)
                try:
                    self.backend.abort_target()
                except Exception as recovery_error:
                    self.transition("recovery_failed", operation="abort_target", reason=str(recovery_error))
                    result.update(recovery_required=True, recovery_failure=str(recovery_error))
                    # Ownership cannot safely be restored while target fencing is
                    # unconfirmed. Preserve evidence and stop the retry loop.
                    break
                if self.clock.orbital() < event["deadline_s"]:
                    self.transition("rollback")
                    try:
                        self.backend.recover_source()
                    except Exception as recovery_error:
                        self.transition("recovery_failed", operation="recover_source", reason=str(recovery_error))
                        result.update(recovery_required=True, recovery_failure=str(recovery_error))
                        break
                    if interrupted:
                        result['interrupted'] = True
                        break
                else:
                    break
        if not result["success"]:
            self.transition("recovery_required" if result.get('recovery_required') else "failed")
        result.update(bytes_sent=self.bytes_sent, bytes_received=self.bytes_received, events=self.events)
        self.save("metadata.json", result)
        return result
