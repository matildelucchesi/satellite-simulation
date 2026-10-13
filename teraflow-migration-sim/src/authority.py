"""Fail-closed ownership and standby state, independent of gRPC mechanics."""
from __future__ import annotations
import threading
import json
from pathlib import Path
from .storage import atomic_json


class Authority:
    def __init__(self, active="sat-a", journal=None):
        self.journal = Path(journal) if journal else None
        self.active = active
        self.generation = 0
        self.verified = False
        self.ack = False
        self.frozen = False
        self.lock = threading.RLock()
        if self.journal and self.journal.exists():
            previous = json.loads(self.journal.read_text())
            self.active = None
            self.frozen = True
            self.generation = previous['generation'] + 1
        self.persist()

    def persist(self):
        if self.journal:
            atomic_json(self.journal, {'active': self.active, 'generation': self.generation,
                'frozen': self.frozen, 'ack': self.ack, 'verified': self.verified})

    def freeze(self):
        with self.lock:
            self.frozen = True
            self.persist()

    def ready(self, *, images: bool, api: bool, staged: bool):
        with self.lock:
            self.verified = self.active is not None and images and api and staged
            self.ack = self.verified
            self.persist()
            return self.ack

    def cutover(self, destination, reconcile):
        with self.lock:
            if not self.ack or not self.frozen:
                raise RuntimeError("Cutover requires ACK and source fencing")
            previous = self.active
            self.active = None
            self.generation += 1
            self.persist()
            try:
                reconcile()
            except Exception:
                # Reconciliation might have partially changed hardware. Recovery
                # must explicitly restore it before either side regains ownership.
                self.ack = self.verified = False
                self.persist()
                raise
            self.active = destination
            self.frozen = False
            self.persist()
            return previous

    def recover(self, source, restore):
        with self.lock:
            self.active = None
            self.ack = self.verified = False
            self.persist()
            restore()
            self.active = source
            self.frozen = self.verified = self.ack = False
            self.persist()

    def writable(self, role):
        return role == self.active and not self.frozen
