"""Paced TCP with receiver-confirmed progress and discard-on-failure semantics."""
from __future__ import annotations

import hashlib
import json
import math
import socket
import struct
import threading
import time
from pathlib import Path

from .artifacts import canonical_bytes, describe

BLOCK = 256 * 1024


def exact(sock, size):
    result = bytearray()
    while len(result) < size:
        block = sock.recv(size - len(result))
        if not block:
            raise ConnectionError("TCP peer closed before completing message")
        result.extend(block)
    return bytes(result)


def send_json(sock, document):
    data = canonical_bytes(document)
    sock.sendall(struct.pack("!I", len(data)) + data)


def read_json(sock):
    size = struct.unpack("!I", exact(sock, 4))[0]
    if size > 65536:
        raise ValueError("Oversized transfer control message")
    return json.loads(exact(sock, size))


class Receiver:
    """One connection per payload, operating in its own disposable run directory."""
    def __init__(self, directory: Path, host="127.0.0.1", port=0, progress_timeout_s=120):
        self.directory = directory
        self.timeout = progress_timeout_s
        directory.mkdir(parents=True, exist_ok=True)
        self.server = socket.socket()
        self.server.bind((host, port))
        self.server.listen()
        self.server.settimeout(0.2)
        self.address = self.server.getsockname()
        self.stop = threading.Event()
        self.errors = []
        self.receipts = []
        self.thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join(timeout=self.timeout + 1)
        self.server.close()
        if self.thread.is_alive():
            raise RuntimeError("Receiver failed to stop")

    def _serve(self):
        while not self.stop.is_set():
            try:
                connection, _ = self.server.accept()
            except socket.timeout:
                continue
            temporary = None
            try:
                with connection:
                    connection.settimeout(self.timeout)
                    header = read_json(connection)
                    name = header["name"]
                    if Path(name).name != name or name in {"", ".", ".."}:
                        raise ValueError("Invalid artifact name")
                    size = header["bytes"]
                    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                        raise ValueError("Invalid byte count")
                    temporary = self.directory / (name + ".partial")
                    digest, received = hashlib.sha256(), 0
                    started = time.monotonic()
                    with temporary.open("wb") as output:
                        while received < size:
                            block = connection.recv(min(BLOCK, size - received))
                            if not block:
                                raise ConnectionError("Interrupted payload")
                            output.write(block)
                            digest.update(block)
                            received += len(block)
                            send_json(connection, {"received_bytes": received})
                    checksum = digest.hexdigest()
                    if checksum != header["sha256"]:
                        raise ValueError("Payload checksum mismatch")
                    final = self.directory / name
                    temporary.replace(final)
                    receipt = {"received_bytes": received, "sha256": checksum,
                               "receiver_elapsed_s": time.monotonic() - started, "path": str(final.resolve())}
                    self.receipts.append(receipt)
                    send_json(connection, receipt)
            except Exception as exc:
                self.errors.append(str(exc))
                if temporary is not None:
                    temporary.unlink(missing_ok=True)


def transfer(path: Path, address: tuple, useful_rate_bps: int, *, link=lambda: True,
             deadline_monotonic=math.inf, progress_timeout_s=120, corrupt_checksum=False) -> dict:
    if useful_rate_bps <= 0 or progress_timeout_s <= 0:
        raise ValueError("Rate and timeout must be positive")
    artifact = describe(path)
    confirmed = [0]
    last_progress = [time.monotonic()]
    receipt = []
    errors = []
    started = time.monotonic()
    sent = 0
    with socket.create_connection(address, timeout=progress_timeout_s) as sock:
        sock.settimeout(min(0.2, progress_timeout_s))
        send_json(sock, {"name": path.name, "bytes": artifact["bytes"],
                         "sha256": "0" * 64 if corrupt_checksum else artifact["sha256"]})
        # Framed receipt reader uses a separate blocking socket timeout; sender's
        # watchdog shuts down the socket on link loss/deadline/stall.
        sock.settimeout(None)
        def read_progress():
            try:
                while not receipt:
                    response = read_json(sock)
                    confirmed[0] = response["received_bytes"]
                    last_progress[0] = time.monotonic()
                    if "sha256" in response:
                        receipt.append(response)
            except Exception as exc:
                errors.append(exc)
        reader = threading.Thread(target=read_progress, daemon=True)
        reader.start()
        stopped = threading.Event()
        def watchdog():
            while not stopped.wait(0.02):
                now = time.monotonic()
                reason = None
                if not link(): reason = "FSO contact lost"
                elif now >= deadline_monotonic: reason = "Operational deadline reached"
                elif now - last_progress[0] >= progress_timeout_s: reason = "No receiver progress"
                if reason:
                    errors.append(TimeoutError(reason))
                    try: sock.shutdown(socket.SHUT_RDWR)
                    except OSError: pass
                    return
        guard = threading.Thread(target=watchdog, daemon=True)
        guard.start()
        try:
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(BLOCK), b""):
                    target = started + (sent + len(block)) * 8 / useful_rate_bps
                    while time.monotonic() < target:
                        if errors: raise errors[0]
                        time.sleep(max(0.0,min(0.01,target-time.monotonic())))
                    if errors: raise errors[0]
                    sock.sendall(block)
                    sent += len(block)
            while not receipt:
                if errors: raise errors[0]
                time.sleep(0.01)
            elapsed = time.monotonic() - started
            return {**receipt[0], "sent_bytes": sent, "elapsed_s": elapsed,
                    "useful_throughput_bps": sent * 8 / elapsed,
                    "configured_rate_bps": useful_rate_bps}
        except Exception as exc:
            setattr(exc, "sent_bytes", sent)
            setattr(exc, "received_bytes", confirmed[0])
            raise
        finally:
            stopped.set()
            try: sock.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            reader.join(timeout=1)
            guard.join(timeout=1)
