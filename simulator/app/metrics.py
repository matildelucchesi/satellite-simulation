"""Raccolta ed esportazione delle metriche globali della simulazione."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from io import StringIO
from threading import RLock
from time import monotonic
from typing import Any, Callable


class MetricsManager:
    """Mantiene contatori runtime e aggrega le metriche delle migrazioni."""

    def __init__(
        self,
        migration_provider: Callable[[], dict[str, Any]],
    ) -> None:
        self._migration_provider = migration_provider
        self._lock = RLock()
        self._started_monotonic = monotonic()
        self._started_at = _utc_now()
        self._heartbeat_count = 0
        self._election_times_ms: list[float] = []
        self._last_selected_satellite_id: str | None = None

    def record_heartbeat(self) -> None:
        """Registra un heartbeat validato e accettato dal Simulator."""

        with self._lock:
            self._heartbeat_count += 1

    def record_election(
        self, evaluation: dict[str, Any], duration_ms: float
    ) -> None:
        """Registra la latenza quando viene eletto un candidato differente."""

        selected = evaluation.get("selected_satellite_id")
        if not evaluation.get("ready") or not isinstance(selected, str):
            return
        with self._lock:
            if selected == self._last_selected_satellite_id:
                return
            self._last_selected_satellite_id = selected
            self._election_times_ms.append(max(0.0, float(duration_ms)))

    def snapshot(self) -> dict[str, Any]:
        migration_state = self._migration_provider()
        migrations = migration_state.get("migrations", [])
        if not isinstance(migrations, list):
            migrations = []

        completed = [item for item in migrations if item.get("status") == "completed"]
        failed = [item for item in migrations if item.get("status") == "failed"]
        handover_times = _numeric_metrics(completed, "duration_ms")
        downtime_times = _numeric_metrics(completed, "downtime_ms")
        alignment_times = _numeric_metrics(completed, "alignment_wait_ms")
        ack_count = sum(
            int(bool(item.get("metrics", {}).get(field)))
            for item in migrations
            for field in ("ack_received", "controller_restore_ack")
        )

        with self._lock:
            heartbeat_count = self._heartbeat_count
            election_times = list(self._election_times_ms)
            selected = self._last_selected_satellite_id
            elapsed = monotonic() - self._started_monotonic

        return {
            "simulation_started_at": self._started_at,
            "generated_at": _utc_now(),
            "simulation_time_seconds": round(elapsed, 3),
            "migration_count": len(migrations),
            "completed_migration_count": len(completed),
            "failed_migration_count": len(failed),
            "heartbeat_count": heartbeat_count,
            "ack_count": ack_count,
            "total_downtime_ms": _total(downtime_times),
            "average_downtime_ms": _average(downtime_times),
            "average_handover_time_ms": _average(handover_times),
            "average_alignment_wait_ms": _average(alignment_times),
            "controller_election_count": len(election_times),
            "average_controller_election_time_ms": _average(election_times),
            "last_selected_controller_satellite_id": selected,
        }

    def to_csv(self) -> str:
        """Serializza lo snapshot corrente come CSV a singola riga."""

        snapshot = self.snapshot()
        output = StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=list(snapshot))
        writer.writeheader()
        writer.writerow(snapshot)
        return output.getvalue()


def _numeric_metrics(
    migrations: list[dict[str, Any]], field: str
) -> list[float]:
    values: list[float] = []
    for migration in migrations:
        value = migration.get("metrics", {}).get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values.append(float(value))
    return values


def _total(values: list[float]) -> float:
    return round(sum(values), 3)


def _average(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
