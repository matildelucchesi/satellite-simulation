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

from .contact_window import ContactWindowConfig, evaluate_contact


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
    handover_safety_margin_seconds: float = 60.0
    minimum_target_sunlight_seconds: float = 120.0

    @classmethod
    def from_file(cls, path: str | Path) -> "ScoreManagerConfig":
        config_path = Path(path)
        if not config_path.is_file():
            raise FileNotFoundError(f"Configurazione scoring non trovata: {config_path}")
        with config_path.open(encoding="utf-8") as stream:
            payload = json.load(stream)
        migration = payload.get("migration", {})
        eclipse_handover = migration.get("eclipse_handover", {})
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
            handover_safety_margin_seconds=_non_negative_number(
                eclipse_handover.get("safety_margin_seconds", 60),
                "safety_margin_seconds",
            ),
            minimum_target_sunlight_seconds=_non_negative_number(
                eclipse_handover.get("minimum_target_sunlight_seconds", 120),
                "minimum_target_sunlight_seconds",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "weights": self.weights.to_dict(),
            "heartbeat_ttl_seconds": self.heartbeat_ttl_seconds,
            "migration": {
                "minimum_score_improvement": self.minimum_score_improvement,
                "cooldown_seconds": self.migration_cooldown_seconds,
                "eclipse_handover": {
                    "safety_margin_seconds": self.handover_safety_margin_seconds,
                    "minimum_target_sunlight_seconds": (
                        self.minimum_target_sunlight_seconds
                    ),
                },
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
        required_contact_seconds: float = 60.0,
        migration_execution_budget_seconds: float = 90.0,
        contact_window_config: ContactWindowConfig | None = None,
        migration_state_provider: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        normalized_ids = [_canonical_satellite_id(value) for value in satellite_ids]
        if not normalized_ids or len(set(normalized_ids)) != len(normalized_ids):
            raise ScoreManagerError("Gli ID dei satelliti devono essere unici")
        self.satellite_ids = normalized_ids
        self.config = config
        self._migration_notifier = migration_notifier
        self._evaluation_listener = evaluation_listener
        self.required_contact_seconds = _non_negative_number(
            required_contact_seconds, "required_contact_seconds"
        )
        self.migration_execution_budget_seconds = _positive_number(
            migration_execution_budget_seconds,
            "migration_execution_budget_seconds",
        )
        self.contact_window_config = contact_window_config
        self._migration_state_provider = migration_state_provider
        self._lock = RLock()
        self._heartbeats: dict[str, dict[str, Any]] = {}
        self._heartbeat_times: dict[str, datetime] = {}
        self._constellation_state: dict[str, Any] = {}
        self._evaluation: dict[str, Any] = self._empty_evaluation(
            "waiting_for_data"
        )
        self._last_notification_at: datetime | None = None
        self._last_notification_pair: tuple[str, str] | None = None
        self._enabled = True
        self._authoritative_controller_id: str | None = None

    def reset(self, enabled: bool = False) -> None:
        """Azzera heartbeat, valutazioni e memoria delle elezioni."""

        with self._lock:
            self._heartbeats = {}
            self._heartbeat_times = {}
            self._constellation_state = {}
            self._evaluation = self._empty_evaluation("waiting_for_data")
            self._last_notification_at = None
            self._last_notification_pair = None
            self._enabled = enabled
            self._authoritative_controller_id = None

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = bool(enabled)

    def record_controller_handover(
        self, source_satellite_id: str, target_satellite_id: str
    ) -> None:
        """Rende immediato il cambio host senza attendere il prossimo heartbeat."""

        source = _canonical_satellite_id(source_satellite_id)
        target = _canonical_satellite_id(target_satellite_id)
        if source not in self.satellite_ids or target not in self.satellite_ids:
            raise ScoreManagerError("Handover fuori dalla costellazione")
        with self._lock:
            self._authoritative_controller_id = target
            for satellite_id, heartbeat in self._heartbeats.items():
                heartbeat["controller"] = satellite_id == target
            self._evaluate_locked(datetime.now(timezone.utc))

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
            if self._authoritative_controller_id is not None:
                record["controller"] = (
                    satellite_id == self._authoritative_controller_id
                )
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
                "authoritative_controller_satellite_id": (
                    self._authoritative_controller_id
                ),
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

        handover_trigger_seconds = (
            self.required_contact_seconds
            + self.migration_execution_budget_seconds
            + self.config.handover_safety_margin_seconds
        )
        controller_time_to_eclipse = scores[current_controller]["T"]
        controller_in_eclipse = controller_time_to_eclipse <= 0
        handover_due = controller_time_to_eclipse <= handover_trigger_seconds
        candidate_eligibility: dict[str, dict[str, Any]] = {}
        eligible_targets: list[str] = []
        target_required_sunlight = max(
            self.config.minimum_target_sunlight_seconds,
            handover_trigger_seconds,
        )
        for satellite_id in self.satellite_ids:
            if satellite_id == current_controller:
                continue
            reasons: list[str] = []
            target_sunlight = scores[satellite_id]["T"]
            if target_sunlight < target_required_sunlight:
                reasons.append("insufficient_target_sunlight")

            contact_payload: dict[str, Any] = {
                "eligible": None,
                "reason": "not_evaluated",
                "distance_km": scores[satellite_id]["D"],
                "line_of_sight": None,
            }
            if self.contact_window_config is not None:
                observation = evaluate_contact(
                    self._constellation_state,
                    current_controller,
                    satellite_id,
                    self.contact_window_config,
                )
                contact_payload = {
                    "eligible": observation.eligible,
                    "reason": observation.reason,
                    "distance_km": (
                        round(observation.distance_km, 3)
                        if observation.distance_km is not None
                        else None
                    ),
                    "line_of_sight": observation.line_of_sight,
                }
            if contact_payload["eligible"] is False:
                reasons.append(str(contact_payload["reason"]))
            eligible = not reasons
            candidate_eligibility[satellite_id] = {
                "eligible": eligible,
                "reasons": reasons,
                "target_sunlight_seconds": target_sunlight,
                "required_target_sunlight_seconds": target_required_sunlight,
                "contact": contact_payload,
            }
            if eligible:
                eligible_targets.append(satellite_id)

        ranked_targets = sorted(
            eligible_targets,
            key=lambda item: (-scores[item]["score"], item),
        )
        selected_id = ranked_targets[0] if ranked_targets else None
        migration_required = False
        score_delta: float | None = None
        reason = "controller_eclipse_not_imminent"

        if selected_id is None:
            reason = (
                "waiting_for_contact_candidate"
                if handover_due
                else "no_eligible_target"
            )
        else:
            score_delta = scores[selected_id]["score"] - scores[current_controller]["score"]
            if not handover_due:
                reason = "controller_eclipse_not_imminent"
            elif self._handover_open():
                reason = "handover_already_pending"
            elif self._cooldown_active(now):
                reason = "migration_cooldown"
            else:
                migration_required = True
                reason = (
                    "controller_in_eclipse_recovery"
                    if controller_in_eclipse
                    else "controller_eclipse_approaching"
                )

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
            "handover_due": handover_due,
            "handover_trigger_seconds": round(handover_trigger_seconds, 3),
            "required_contact_seconds": round(self.required_contact_seconds, 3),
            "migration_execution_budget_seconds": round(
                self.migration_execution_budget_seconds, 3
            ),
            "controller_time_to_eclipse_seconds": controller_time_to_eclipse,
            "controller_in_eclipse": controller_in_eclipse,
            "candidate_eligibility": candidate_eligibility,
            "missing_heartbeats": [],
            "stale_heartbeats": [],
            "missing_distances": [],
        }

        if migration_required and current_controller is not None and self._enabled:
            completion_window_seconds = (
                self.required_contact_seconds
                + self.migration_execution_budget_seconds
                + self.config.handover_safety_margin_seconds
                if controller_in_eclipse
                else controller_time_to_eclipse
                - self.config.handover_safety_margin_seconds
            )
            notification = {
                "migration_id": str(uuid4()),
                "source_satellite_id": current_controller,
                "target_satellite_id": selected_id,
                "reason": reason,
                "score_delta": round(score_delta or 0.0, 6),
                "source_score": scores[current_controller]["score"],
                "target_score": scores[selected_id]["score"],
                "source_time_to_eclipse_seconds": controller_time_to_eclipse,
                "target_time_to_eclipse_seconds": scores[selected_id]["T"],
                "required_contact_seconds": self.required_contact_seconds,
                "handover_safety_margin_seconds": (
                    self.config.handover_safety_margin_seconds
                ),
                "migration_execution_budget_seconds": (
                    self.migration_execution_budget_seconds
                ),
                "source_eclipse_at": _isoformat(
                    now + timedelta(seconds=controller_time_to_eclipse)
                ),
                "completion_deadline_at": _isoformat(
                    now + timedelta(seconds=completion_window_seconds)
                ),
                "alignment_complete_not_before": _isoformat(
                    now + timedelta(seconds=self.required_contact_seconds)
                ),
                "estimated_margin_after_alignment_seconds": round(
                    (
                        self.config.handover_safety_margin_seconds
                        if controller_in_eclipse
                        else controller_time_to_eclipse
                        - self.required_contact_seconds
                        - self.migration_execution_budget_seconds
                    ),
                    3,
                ),
                "emergency_recovery": controller_in_eclipse,
                "contact": deepcopy(
                    candidate_eligibility[selected_id]["contact"]
                ),
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

    def _cooldown_active(self, now: datetime) -> bool:
        if self._last_notification_at is None:
            return False
        return now - self._last_notification_at < timedelta(
            seconds=self.config.migration_cooldown_seconds
        )

    def _handover_open(self) -> bool:
        if self._migration_state_provider is None:
            return False
        state = self._migration_state_provider()
        return any(
            migration.get("status")
            in {"waiting_for_contact", "queued", "in_progress"}
            for migration in state.get("migrations", [])
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
            "handover_due": False,
            "handover_trigger_seconds": round(
                self.required_contact_seconds
                + self.migration_execution_budget_seconds
                + self.config.handover_safety_margin_seconds,
                3,
            ),
            "required_contact_seconds": round(self.required_contact_seconds, 3),
            "migration_execution_budget_seconds": round(
                self.migration_execution_budget_seconds, 3
            ),
            "controller_time_to_eclipse_seconds": None,
            "candidate_eligibility": {},
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
