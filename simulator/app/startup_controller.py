"""Elezione e attivazione del Controller iniziale della simulazione."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from threading import Event, RLock, Thread
from typing import Any, Callable

from .migration_manager import RestTransport, UrllibRestTransport


@dataclass(frozen=True, slots=True)
class StartupControllerConfig:
    strategy: str
    minimum_sunlight_seconds: float
    retry_seconds: float

    @classmethod
    def from_dict(cls, payload: Any) -> "StartupControllerConfig":
        if not isinstance(payload, dict):
            raise ValueError("initial_controller deve essere un oggetto JSON")
        strategy = str(payload.get("strategy", "")).strip().lower()
        if strategy != "minimum_remaining_sunlight":
            raise ValueError(
                "initial_controller.strategy deve essere minimum_remaining_sunlight"
            )
        minimum = _non_negative_number(
            payload.get("minimum_sunlight_seconds"),
            "minimum_sunlight_seconds",
        )
        retry = _positive_number(payload.get("retry_seconds", 1), "retry_seconds")
        return cls(strategy, minimum, retry)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "minimum_sunlight_seconds": self.minimum_sunlight_seconds,
            "retry_seconds": self.retry_seconds,
        }


class StartupControllerManager:
    """Seleziona una sola volta il target iniziale e ne attiva l'agente."""

    def __init__(
        self,
        satellite_ids: list[str],
        config: StartupControllerConfig,
        agent_url: Callable[[str], str],
        controller_url: str,
        transport: RestTransport | None = None,
        request_timeout_seconds: float = 2.0,
    ) -> None:
        if not satellite_ids or len(set(satellite_ids)) != len(satellite_ids):
            raise ValueError("Gli ID dei satelliti iniziali devono essere unici")
        self.satellite_ids = list(satellite_ids)
        self.config = config
        self.agent_url = agent_url
        self.controller_url = controller_url.rstrip("/")
        self.transport = transport or UrllibRestTransport()
        self.request_timeout_seconds = request_timeout_seconds
        self._lock = RLock()
        self._wake_event = Event()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._state: dict[str, Any] = {
            "strategy": config.strategy,
            "minimum_sunlight_seconds": config.minimum_sunlight_seconds,
            "status": "waiting_for_orbital_state",
            "selected_satellite_id": None,
            "selected_time_to_eclipse_seconds": None,
            "eligible_candidates": [],
            "selected_at": None,
            "activated_at": None,
            "activation_attempts": 0,
            "last_error": None,
        }

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._thread = Thread(
            target=self._worker,
            name="startup-controller-election",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def update_constellation(self, snapshot: dict[str, Any]) -> None:
        with self._lock:
            if self._state["selected_satellite_id"] is not None:
                return
            candidates = _eligible_candidates(
                snapshot,
                self.satellite_ids,
                self.config.minimum_sunlight_seconds,
            )
            self._state["eligible_candidates"] = deepcopy(candidates)
            if not candidates:
                self._state["status"] = "waiting_for_eligible_satellite"
                return
            selected = candidates[0]
            self._state.update(
                {
                    "status": "selected",
                    "selected_satellite_id": selected["satellite_id"],
                    "selected_time_to_eclipse_seconds": selected[
                        "seconds_until_eclipse"
                    ],
                    "selected_at": snapshot.get("generated_at") or _utc_now(),
                }
            )
        self._wake_event.set()

    def activate_once(self) -> bool:
        """Esegue un tentativo sincrono, utile anche per i test."""

        with self._lock:
            selected = self._state["selected_satellite_id"]
            if selected is None or self._state["status"] == "active":
                return self._state["status"] == "active"
            self._state["status"] = "activating"
            self._state["activation_attempts"] += 1

        try:
            for satellite_id in self.satellite_ids:
                if satellite_id == selected:
                    continue
                response = self.transport.request(
                    "POST",
                    f"{self.agent_url(satellite_id)}/stop_controller",
                    None,
                    self.request_timeout_seconds,
                )
                if response.status != 200:
                    raise RuntimeError(
                        f"stop_controller su {satellite_id}: HTTP {response.status}"
                    )
            response = self.transport.request(
                "POST",
                f"{self.agent_url(selected)}/start_controller",
                None,
                self.request_timeout_seconds,
            )
            if response.status != 200:
                raise RuntimeError(
                    f"start_controller su {selected}: HTTP {response.status}"
                )
            response = self.transport.request(
                "POST",
                f"{self.controller_url}/host",
                {"satellite_id": selected},
                self.request_timeout_seconds,
            )
            if response.status != 200:
                raise RuntimeError(f"Aggiornamento host: HTTP {response.status}")
        except Exception as exc:
            with self._lock:
                self._state["status"] = "activation_retry"
                self._state["last_error"] = str(exc)
            return False

        with self._lock:
            self._state["status"] = "active"
            self._state["activated_at"] = _utc_now()
            self._state["last_error"] = None
        return True

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._state)

    def _worker(self) -> None:
        while not self._stop_event.is_set():
            self._wake_event.wait(timeout=self.config.retry_seconds)
            self._wake_event.clear()
            if self._stop_event.is_set():
                return
            with self._lock:
                should_activate = (
                    self._state["selected_satellite_id"] is not None
                    and self._state["status"] != "active"
                )
            if should_activate:
                self.activate_once()


def _eligible_candidates(
    snapshot: dict[str, Any],
    satellite_ids: list[str],
    minimum_sunlight_seconds: float,
) -> list[dict[str, Any]]:
    satellites = snapshot.get("satellites", {})
    candidates: list[dict[str, Any]] = []
    for order, satellite_id in enumerate(satellite_ids):
        satellite = satellites.get(satellite_id, {}) if isinstance(satellites, dict) else {}
        illumination = satellite.get("illumination", {})
        seconds = illumination.get("seconds_until_eclipse")
        if (
            illumination.get("state") != "sunlight"
            or isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds)
            or float(seconds) <= minimum_sunlight_seconds
        ):
            continue
        candidates.append(
            {
                "satellite_id": satellite_id,
                "seconds_until_eclipse": round(float(seconds), 3),
                "constellation_order": order,
            }
        )
    candidates.sort(
        key=lambda candidate: (
            candidate["seconds_until_eclipse"],
            candidate["constellation_order"],
        )
    )
    for candidate in candidates:
        candidate.pop("constellation_order", None)
    return candidates


def _positive_number(value: Any, name: str) -> float:
    result = _non_negative_number(value, name)
    if result == 0:
        raise ValueError(f"{name} deve essere maggiore di zero")
    return result


def _non_negative_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} deve essere numerico")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} deve essere finito e non negativo")
    return result


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
