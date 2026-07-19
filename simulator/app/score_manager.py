"""Raccolta heartbeat, calcolo degli score e selezione del candidato."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Any, Callable
from uuid import uuid4


class ScoreManagerError(ValueError):
    """Errore di configurazione o heartbeat non valido."""


@dataclass(frozen=True, slots=True)
class ScoreWeights:
    w1: float
    w2: float
    w3: float
    w4: float

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScoreWeights":
        if not isinstance(payload, dict):
            raise ScoreManagerError("weights deve essere un oggetto JSON")
        missing = {"w1", "w2", "w3", "w4"} - payload.keys()
        if missing:
            raise ScoreManagerError(
                "Pesi mancanti: " + ", ".join(sorted(missing))
            )
        values: dict[str, float] = {}
        for name in ("w1", "w2", "w3", "w4"):
            value = payload[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ScoreManagerError(f"{name} deve essere numerico")
            value = float(value)
            if not math.isfinite(value) or value < 0:
                raise ScoreManagerError(f"{name} deve essere finito e non negativo")
            values[name] = value
        return cls(**values)

    def to_dict(self) -> dict[str, float]:
        return {"w1": self.w1, "w2": self.w2, "w3": self.w3, "w4": self.w4}


@dataclass(frozen=True, slots=True)
class ScoreManagerConfig:
    weights: ScoreWeights
    heartbeat_ttl_seconds: float
    minimum_score_improvement: float
    migration_cooldown_seconds: float

    @classmethod
    def from_file(cls, path: str | Path) -> "ScoreManagerConfig":
        config_path = Path(path)
        if not config_path.is_file():
            raise FileNotFoundError(f"Configurazione scoring non trovata: {config_path}")
        with config_path.open(encoding="utf-8") as stream:
            payload = json.load(stream)
        migration = payload.get("migration", {})
        return cls(
            weights=ScoreWeights.from_dict(payload.get("weights")),
            heartbeat_ttl_seconds=_positive_number(
                payload.get("heartbeat_ttl_seconds"), "heartbeat_ttl_seconds"
            ),
            minimum_score_improvement=_non_negative_number(
                migration.get("minimum_score_improvement"),
                "minimum_score_improvement",
            ),
            migration_cooldown_seconds=_non_negative_number(
                migration.get("cooldown_seconds"), "cooldown_seconds"
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "weights": self.weights.to_dict(),
            "heartbeat_ttl_seconds": self.heartbeat_ttl_seconds,
            "migration": {
                "minimum_score_improvement": self.minimum_score_improvement,
                "cooldown_seconds": self.migration_cooldown_seconds,
            },
        }


class ScoreManager:
    """Mantiene la vista globale usata per scegliere l'host del Controller."""

    def __init__(
        self,
        satellite_ids: list[str],
        config: ScoreManagerConfig,
        migration_notifier: Callable[[dict[str, Any]], None],
        evaluation_listener: Callable[[dict[str, Any], float], None] | None = None,
    ) -> None:
        normalized_ids = [_canonical_satellite_id(value) for value in satellite_ids]
        if not normalized_ids or len(set(normalized_ids)) != len(normalized_ids):
            raise ScoreManagerError("Gli ID dei satelliti devono essere unici")
        self.satellite_ids = normalized_ids
        self.config = config
        self._migration_notifier = migration_notifier
        self._evaluation_listener = evaluation_listener
        self._lock = RLock()
        self._heartbeats: dict[str, dict[str, Any]] = {}
        self._heartbeat_times: dict[str, datetime] = {}
        self._constellation_state: dict[str, Any] = {}
        self._evaluation: dict[str, Any] = self._empty_evaluation(
            "waiting_for_data"
        )
        self._last_notification_at: datetime | None = None
        self._last_notification_pair: tuple[str, str] | None = None

    def record_heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        heartbeat = _validate_heartbeat(payload)
        satellite_id = _canonical_satellite_id(heartbeat["id"])
        if satellite_id not in self.satellite_ids:
            raise ScoreManagerError(f"Satellite non appartenente alla costellazione: {satellite_id}")

        now = datetime.now(timezone.utc)
        record = deepcopy(heartbeat)
        record["satellite_id"] = satellite_id
        record["received_at"] = _isoformat(now)
        with self._lock:
            self._heartbeats[satellite_id] = record
            self._heartbeat_times[satellite_id] = now
            self._evaluate_locked(now)
            return deepcopy(record)

    def update_constellation(self, snapshot: dict[str, Any]) -> None:
        with self._lock:
            self._constellation_state = deepcopy(snapshot)
            self._evaluate_locked(datetime.now(timezone.utc))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "config": self.config.to_dict(),
                "heartbeats": deepcopy(self._heartbeats),
                "evaluation": deepcopy(self._evaluation),
            }

    def heartbeat_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "count": len(self._heartbeats),
                "heartbeats": deepcopy(self._heartbeats),
            }

    def _evaluate_locked(self, now: datetime) -> None:
        evaluation_started = monotonic()
        missing = [item for item in self.satellite_ids if item not in self._heartbeats]
        stale = [
            item
            for item in self.satellite_ids
            if item in self._heartbeat_times
            and now - self._heartbeat_times[item]
            > timedelta(seconds=self.config.heartbeat_ttl_seconds)
        ]
        if missing or stale:
            self._evaluation = self._empty_evaluation(
                "waiting_for_heartbeats", missing=missing, stale=stale
            )
            return

        controller_ids = [
            satellite_id
            for satellite_id in self.satellite_ids
            if self._heartbeats[satellite_id]["controller"]
        ]
        if len(controller_ids) != 1:
            reason = (
                "controller_not_reported"
                if not controller_ids
                else "multiple_controllers_reported"
            )
            self._evaluation = self._empty_evaluation(
                reason,
                reported_controllers=controller_ids,
            )
            return
        current_controller = controller_ids[0]

        distances = self._constellation_state.get("distances_km", {})
        if not isinstance(distances, dict) or not distances:
            self._evaluation = self._empty_evaluation("waiting_for_constellation")
            return
        controller_distances = distances.get(current_controller)
        if not isinstance(controller_distances, dict):
            self._evaluation = self._empty_evaluation(
                "waiting_for_distances",
                missing_distances=list(self.satellite_ids),
                current_controller=current_controller,
            )
            return

        scores: dict[str, dict[str, Any]] = {}
        missing_distances: list[str] = []
        for satellite_id in self.satellite_ids:
            distance_from_controller = controller_distances.get(satellite_id)
            if (
                isinstance(distance_from_controller, bool)
                or not isinstance(distance_from_controller, (int, float))
                or not math.isfinite(distance_from_controller)
                or distance_from_controller < 0
            ):
                missing_distances.append(satellite_id)
                continue

            heartbeat = self._heartbeats[satellite_id]
            time_to_eclipse = heartbeat["time_to_eclipse"]
            t_value = float(time_to_eclipse) if time_to_eclipse is not None else 0.0
            n_value = int(heartbeat["neighbors"])
            d_value = float(distance_from_controller)
            l_value = float(heartbeat["cpu"])
            weights = self.config.weights
            score = (
                weights.w1 * t_value
                + weights.w2 * n_value
                - weights.w3 * d_value
                - weights.w4 * l_value
            )
            scores[satellite_id] = {
                "T": round(t_value, 3),
                "N": n_value,
                "D": round(d_value, 3),
                "L": round(l_value, 3),
                "score": round(score, 6),
            }

        if missing_distances:
            self._evaluation = self._empty_evaluation(
                "waiting_for_distances",
                missing_distances=missing_distances,
                current_controller=current_controller,
            )
            return

        selected_id = sorted(
            scores, key=lambda item: (-scores[item]["score"], item)
        )[0]
        migration_required = False
        score_delta: float | None = None
        reason = "best_candidate_is_current_controller"

        if selected_id != current_controller:
            score_delta = scores[selected_id]["score"] - scores[current_controller]["score"]
            if score_delta < self.config.minimum_score_improvement:
                reason = "improvement_below_threshold"
            elif self._cooldown_active(now, current_controller, selected_id):
                reason = "migration_cooldown"
            else:
                migration_required = True
                reason = "higher_score"

        self._evaluation = {
            "ready": True,
            "reason": reason,
            "evaluated_at": _isoformat(now),
            "scores": scores,
            "selected_satellite_id": selected_id,
            "current_controller_satellite_id": current_controller,
            "distance_reference_satellite_id": current_controller,
            "reported_controller_satellite_ids": [current_controller],
            "score_delta": round(score_delta, 6) if score_delta is not None else None,
            "migration_required": migration_required,
            "missing_heartbeats": [],
            "stale_heartbeats": [],
            "missing_distances": [],
        }

        if migration_required and current_controller is not None:
            notification = {
                "migration_id": str(uuid4()),
                "source_satellite_id": current_controller,
                "target_satellite_id": selected_id,
                "reason": reason,
                "score_delta": round(score_delta or 0.0, 6),
                "source_score": scores[current_controller]["score"],
                "target_score": scores[selected_id]["score"],
                "timestamp": _isoformat(now),
            }
            self._migration_notifier(notification)
            self._last_notification_at = now
            self._last_notification_pair = (current_controller, selected_id)

        if self._evaluation_listener is not None:
            self._evaluation_listener(
                deepcopy(self._evaluation),
                (monotonic() - evaluation_started) * 1000,
            )

    def _cooldown_active(self, now: datetime, source: str, target: str) -> bool:
        if self._last_notification_at is None:
            return False
        if self._last_notification_pair != (source, target):
            return False
        return now - self._last_notification_at < timedelta(
            seconds=self.config.migration_cooldown_seconds
        )

    def _empty_evaluation(self, reason: str, **details: Any) -> dict[str, Any]:
        return {
            "ready": False,
            "reason": reason,
            "evaluated_at": _isoformat(datetime.now(timezone.utc)),
            "scores": {},
            "selected_satellite_id": None,
            "current_controller_satellite_id": details.get("current_controller"),
            "distance_reference_satellite_id": details.get("current_controller"),
            "reported_controller_satellite_ids": details.get(
                "reported_controllers", []
            ),
            "score_delta": None,
            "migration_required": False,
            "missing_heartbeats": details.get("missing", []),
            "stale_heartbeats": details.get("stale", []),
            "missing_distances": details.get("missing_distances", []),
        }


def _validate_heartbeat(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ScoreManagerError("L'heartbeat deve essere un oggetto JSON")
    required = {"id", "time_to_eclipse", "neighbors", "cpu", "controller"}
    missing = required - payload.keys()
    if missing:
        raise ScoreManagerError(
            "Campi heartbeat mancanti: " + ", ".join(sorted(missing))
        )
    _canonical_satellite_id(payload["id"])
    if (
        isinstance(payload["neighbors"], bool)
        or not isinstance(payload["neighbors"], int)
        or payload["neighbors"] < 0
    ):
        raise ScoreManagerError("neighbors deve essere un intero non negativo")
    if not isinstance(payload["controller"], bool):
        raise ScoreManagerError("controller deve essere booleano")
    for field in ("time_to_eclipse", "cpu"):
        value = payload[field]
        if field == "time_to_eclipse" and value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ScoreManagerError(f"{field} deve essere numerico")
        if not math.isfinite(value) or value < 0:
            raise ScoreManagerError(f"{field} deve essere finito e non negativo")
    if float(payload["cpu"]) > 100:
        raise ScoreManagerError("cpu deve essere compreso tra 0 e 100")
    return deepcopy(payload)


def _canonical_satellite_id(value: int | str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ScoreManagerError("id deve essere un numero o una stringa")
    text = str(value).strip().upper()
    if not text:
        raise ScoreManagerError("id non può essere vuoto")
    return text if text.startswith("SAT-") else f"SAT-{text}"


def _positive_number(value: Any, name: str) -> float:
    result = _non_negative_number(value, name)
    if result == 0:
        raise ScoreManagerError(f"{name} deve essere maggiore di zero")
    return result


def _non_negative_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScoreManagerError(f"{name} deve essere numerico")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ScoreManagerError(f"{name} deve essere finito e non negativo")
    return result


def _isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
