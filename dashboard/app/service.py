"""Aggregazione resiliente dei dati esposti dai microservizi."""

from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen


class DashboardDataService:
    """Costruisce un unico snapshot per il frontend della dashboard."""

    def __init__(
        self,
        simulator_url: str,
        controller_url: str,
        log_dir: str | Path,
        request_timeout_seconds: float = 2.0,
        fetcher: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self.simulator_url = simulator_url.rstrip("/")
        self.controller_url = controller_url.rstrip("/")
        self.log_dir = Path(log_dir)
        self.request_timeout_seconds = request_timeout_seconds
        self.fetcher = fetcher or self._fetch_json

    def collect(self) -> dict[str, Any]:
        endpoints = {
            "constellation": f"{self.simulator_url}/api/v1/constellation",
            "scores": f"{self.simulator_url}/api/v1/scores",
            "heartbeats": f"{self.simulator_url}/api/v1/heartbeats",
            "migrations": f"{self.simulator_url}/api/v1/migrations",
            "startup_controller": (
                f"{self.simulator_url}/api/v1/startup-controller"
            ),
            "controller_state": f"{self.controller_url}/state",
            "controller_health": f"{self.controller_url}/health",
        }
        results: dict[str, Any] = {}
        errors: list[dict[str, str]] = []

        with ThreadPoolExecutor(max_workers=len(endpoints)) as executor:
            pending = {
                executor.submit(self.fetcher, url): (name, url)
                for name, url in endpoints.items()
            }
            for future in as_completed(pending):
                name, url = pending[future]
                try:
                    results[name] = future.result()
                except Exception as exc:
                    results[name] = {}
                    errors.append({"source": name, "url": url, "message": str(exc)})

        logs = self._collect_logs(results, errors)
        return {
            "generated_at": _utc_now(),
            **results,
            "logs": logs,
            "errors": errors,
        }

    def _fetch_json(self, url: str) -> dict[str, Any]:
        request = Request(url, headers={"Accept": "application/json"}, method="GET")
        with urlopen(request, timeout=self.request_timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Risposta non valida da {url}")
        return payload

    def _collect_logs(
        self, results: dict[str, Any], errors: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        events: list[dict[str, str]] = []
        for migration in results.get("migrations", {}).get("migrations", []):
            events.append(
                {
                    "timestamp": migration.get("completed_at")
                    or migration.get("started_at")
                    or migration.get("created_at")
                    or _utc_now(),
                    "level": "error" if migration.get("status") == "failed" else "info",
                    "source": "migration_manager",
                    "message": (
                        f"{migration.get('mode', '').upper()} "
                        f"{migration.get('source_satellite_id')} → "
                        f"{migration.get('target_satellite_id')}: "
                        f"{migration.get('status')}"
                    ),
                }
            )
            for step in migration.get("metrics", {}).get("steps", []):
                events.append(
                    {
                        "timestamp": step.get("timestamp") or _utc_now(),
                        "level": "error" if step.get("status") == "failed" else "debug",
                        "source": "migration_manager",
                        "message": (
                            f"{step.get('name')}: {step.get('status')} "
                            f"(HTTP {step.get('http_status', '—')}, "
                            f"{step.get('duration_ms', 0)} ms)"
                        ),
                    }
                )

        for satellite_id, heartbeat in results.get("heartbeats", {}).get(
            "heartbeats", {}
        ).items():
            events.append(
                {
                    "timestamp": heartbeat.get("received_at") or _utc_now(),
                    "level": "debug",
                    "source": satellite_id,
                    "message": (
                        f"Heartbeat · CPU {heartbeat.get('cpu', '—')}% · "
                        f"vicini {heartbeat.get('neighbors', '—')} · "
                        f"controller {heartbeat.get('controller', False)}"
                    ),
                }
            )

        for error in errors:
            events.append(
                {
                    "timestamp": _utc_now(),
                    "level": "error",
                    "source": error["source"],
                    "message": error["message"],
                }
            )

        events.extend(self._read_log_files(limit=80))
        events.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
        return events[:100]

    def _read_log_files(self, limit: int) -> list[dict[str, str]]:
        if not self.log_dir.is_dir():
            return []
        entries: list[dict[str, str]] = []
        for path in sorted(self.log_dir.glob("*.log")):
            try:
                with path.open(encoding="utf-8", errors="replace") as stream:
                    lines = deque(stream, maxlen=limit)
            except OSError:
                continue
            timestamp = datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            ).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            for line in lines:
                text = line.strip()
                if text:
                    entries.append(
                        {
                            "timestamp": timestamp,
                            "level": "info",
                            "source": path.stem,
                            "message": text,
                        }
                    )
        return entries[-limit:]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
