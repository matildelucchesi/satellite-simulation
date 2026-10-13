"""Immutable, byte-accurate experiment artifacts (never Docker inspect sizes)."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

SOURCE_COMMIT = "fb8707871eba26806cac7ac373c70b2bb5bd26fc"
COMPONENTS = ("context", "device", "pathcomp-frontend", "pathcomp-backend", "service", "nbi")


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def describe(path: Path) -> dict:
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": file_digest(path)}


def verify_artifact(item: dict) -> Path:
    path = Path(item["path"])
    if not path.is_file() or path.stat().st_size != item["bytes"] or file_digest(path) != item["sha256"]:
        raise ValueError(f"Artifact missing or changed: {path}")
    return path


def nonnegative(value: object, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field}: a finite number is required")
    if value < 0 or (positive and value == 0):
        raise ValueError(f"{field}: invalid magnitude")
    return float(value)


class HostInventory:
    """Availability in the experiment is independent of the lab Docker cache."""
    def __init__(self):
        self.receipts: dict[str, dict] = {}

    def accept(self, host: str, artifact: dict, receipt: dict) -> None:
        if (receipt.get("received_bytes") != artifact["bytes"] or
                receipt.get("sha256") != artifact["sha256"]):
            raise ValueError("Incomplete or corrupt receipt cannot make images available")
        self.receipts[host] = dict(receipt)

    def require(self, host: str) -> None:
        if host not in self.receipts:
            raise RuntimeError(f"No verified image delivery for {host}")
