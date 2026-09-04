"""Coordinamento REST completo delle migrazioni Cold e Hot del Controller."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
from queue import Empty, Queue
from threading import Event, RLock, Thread
from time import monotonic, sleep
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from .contact_window import ContactWindowConfig, evaluate_contact
from .timing_model import MigrationTimingConfig, MigrationTimingModel


class MigrationManagerError(ValueError):
    """Errore di configurazione o richiesta di migrazione non valida."""


class MigrationProtocolError(RuntimeError):
    """Errore durante uno dei passi REST del protocollo."""


@dataclass(frozen=True, slots=True)
class MigrationConfig:
    default_mode: str
    controller_url: str
    agent_url_template: str
    request_timeout_seconds: float
    max_retries: int
    retry_delay_seconds: float
    contact_window: ContactWindowConfig
    phase_delay_seconds: float = 0.0
    execution_budget_seconds: float = 90.0
    timing_model: MigrationTimingConfig = field(
        default_factory=MigrationTimingConfig
    )

    @classmethod
    def from_file(cls, path: str | Path) -> "MigrationConfig":
        config_path = Path(path)
        if not config_path.is_file():
            raise FileNotFoundError(
                f"Configurazione migrazione non trovata: {config_path}"
            )
        with config_path.open(encoding="utf-8") as stream:
            payload = json.load(stream)
        return cls.from_dict(payload)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MigrationConfig":
        if not isinstance(payload, dict):
            raise MigrationManagerError("La configurazione deve essere un oggetto JSON")
        default_mode = str(payload.get("default_mode", "")).lower()
        if default_mode not in {"cold", "hot"}:
            raise MigrationManagerError("default_mode deve essere cold oppure hot")
        controller_url = _required_url(payload.get("controller_url"), "controller_url")
        agent_url_template = _required_url(
            payload.get("agent_url_template"), "agent_url_template"
        )
        if "{satellite_number}" not in agent_url_template:
            raise MigrationManagerError(
                "agent_url_template deve contenere {satellite_number}"
            )
        max_retries = payload.get("max_retries")
        if isinstance(max_retries, bool) or not isinstance(max_retries, int):
            raise MigrationManagerError("max_retries deve essere un intero")
        if max_retries < 0:
            raise MigrationManagerError("max_retries non può essere negativo")
        return cls(
            default_mode=default_mode,
            controller_url=controller_url.rstrip("/"),
            agent_url_template=agent_url_template.rstrip("/"),
            request_timeout_seconds=_positive_number(
                payload.get("request_timeout_seconds"), "request_timeout_seconds"
            ),
            max_retries=max_retries,
            retry_delay_seconds=_non_negative_number(
                payload.get("retry_delay_seconds"), "retry_delay_seconds"
            ),
            contact_window=ContactWindowConfig.from_dict(
                payload.get("contact_window")
            ),
            phase_delay_seconds=_non_negative_number(
                payload.get("protocol_phase_delay_seconds", 0),
                "protocol_phase_delay_seconds",
            ),
            execution_budget_seconds=_positive_number(
                payload.get("execution_budget_seconds", 90),
                "execution_budget_seconds",
            ),
            timing_model=MigrationTimingConfig.from_dict(
                payload.get("timing_model")
            ),
        )

    def agent_url(self, satellite_id: str) -> str:
        number = satellite_id.removeprefix("SAT-")
        return self.agent_url_template.format(satellite_number=number)

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_mode": self.default_mode,
            "controller_url": self.controller_url,
            "agent_url_template": self.agent_url_template,
            "request_timeout_seconds": self.request_timeout_seconds,
            "max_retries": self.max_retries,
            "retry_delay_seconds": self.retry_delay_seconds,
            "contact_window": self.contact_window.to_dict(),
            "protocol_phase_delay_seconds": self.phase_delay_seconds,
            "execution_budget_seconds": self.execution_budget_seconds,
            "timing_model": self.timing_model.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class RestResponse:
    status: int
    payload: dict[str, Any]
    bytes_received: int


class RestTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None,
        timeout: float,
    ) -> RestResponse: ...


class UrllibRestTransport:
    """Client REST minimale che non introduce dipendenze esterne."""

    def request(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None,
        timeout: float,
    ) -> RestResponse:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
                decoded = json.loads(raw.decode("utf-8")) if raw else {}
                if not isinstance(decoded, dict):
                    raise MigrationProtocolError(
                        f"Risposta non JSON-object ricevuta da {url}"
                    )
                return RestResponse(response.status, decoded, len(raw))
        except HTTPError as exc:
            raw = exc.read()
            detail = raw.decode("utf-8", errors="replace") if raw else str(exc)
            raise MigrationProtocolError(f"HTTP {exc.code} da {url}: {detail}") from exc
        except (URLError, OSError, json.JSONDecodeError) as exc:
            raise MigrationProtocolError(f"Errore REST verso {url}: {exc}") from exc


class MigrationManager:
    """Accoda ed esegue in ordine le migrazioni richieste dallo score manager."""

    def __init__(
        self,
        config: MigrationConfig,
        satellite_ids: list[str],
        transport: RestTransport | None = None,
    ) -> None:
        self.config = config
        self.satellite_ids = [_canonical_satellite_id(value) for value in satellite_ids]
        if len(set(self.satellite_ids)) != len(self.satellite_ids):
            raise MigrationManagerError("Gli ID dei satelliti devono essere unici")
        self.transport = transport or UrllibRestTransport()
        self._lock = RLock()
        self._queue: Queue[str] = Queue()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._migrations: dict[str, dict[str, Any]] = {}
        self._migration_order: list[str] = []
        self._active_migration_id: str | None = None
        self._latest_constellation_state: dict[str, Any] = {}
        self._default_mode = config.default_mode
        self._handover_listener: Callable[[str, str], None] | None = None
        self._timing_model = MigrationTimingModel(config.timing_model)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._thread = Thread(
            target=self._worker,
            name="controller-migration-manager",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None

    @property
    def default_mode(self) -> str:
        with self._lock:
            return self._default_mode

    def set_handover_listener(
        self, listener: Callable[[str, str], None] | None
    ) -> None:
        """Registra l'osservatore aggiornato atomicamente dopo il cutover."""

        with self._lock:
            self._handover_listener = listener

    def reset(self, default_mode: str | None = None) -> None:
        """Svuota coda e storico, predisponendo una nuova prova."""

        selected_mode = str(default_mode or self.config.default_mode).lower()
        if selected_mode not in {"cold", "hot"}:
            raise MigrationManagerError("default_mode deve essere cold oppure hot")
        self.stop()
        with self._lock:
            self._queue = Queue()
            self._migrations = {}
            self._migration_order = []
            self._active_migration_id = None
            self._latest_constellation_state = {}
            self._default_mode = selected_mode

    def notify_migration(self, recommendation: dict[str, Any]) -> str:
        """Riceve la selezione dello score manager e accoda il protocollo."""

        return self.enqueue(
            source_satellite_id=recommendation.get("source_satellite_id"),
            target_satellite_id=recommendation.get("target_satellite_id"),
            mode=recommendation.get("mode", self.default_mode),
            recommendation=recommendation,
            migration_id=recommendation.get("migration_id"),
        )

    def enqueue(
        self,
        source_satellite_id: Any,
        target_satellite_id: Any,
        mode: str | None = None,
        recommendation: dict[str, Any] | None = None,
        migration_id: str | None = None,
    ) -> str:
        source = _canonical_satellite_id(source_satellite_id)
        target = _canonical_satellite_id(target_satellite_id)
        selected_mode = str(mode or self.default_mode).lower()
        if source not in self.satellite_ids or target not in self.satellite_ids:
            raise MigrationManagerError("Sorgente o destinazione fuori costellazione")
        if source == target:
            raise MigrationManagerError("Sorgente e destinazione devono essere diverse")
        if selected_mode not in {"cold", "hot"}:
            raise MigrationManagerError("mode deve essere cold oppure hot")

        identifier = str(migration_id or uuid4())
        with self._lock:
            if identifier in self._migrations:
                return identifier
            open_migration = next(
                (
                    migration
                    for migration in self._migrations.values()
                    if migration["status"]
                    in {"waiting_for_contact", "queued", "in_progress"}
                ),
                None,
            )
            if open_migration is not None:
                return open_migration["migration_id"]
            required_alignment = self.config.contact_window.required_alignment_seconds
            created_at = _utc_now()
            migration = {
                "migration_id": identifier,
                "sequence": len(self._migration_order) + 1,
                "mode": selected_mode,
                "source_satellite_id": source,
                "target_satellite_id": target,
                "status": (
                    "queued" if required_alignment == 0 else "waiting_for_contact"
                ),
                "created_at": created_at,
                "started_at": None,
                "completed_at": None,
                "recommendation": deepcopy(recommendation),
                "error": None,
                "events": [
                    {
                        "name": "target_selected",
                        "timestamp": created_at,
                        "source_satellite_id": source,
                        "target_satellite_id": target,
                    }
                ],
                "metrics": {
                    "duration_ms": None,
                    "alignment_wait_ms": None,
                    "alignment_count": 0,
                    "downtime_ms": None,
                    "state_bytes": 0,
                    "initial_state_bytes": 0,
                    "final_state_bytes": 0,
                    "initial_sequence_number": None,
                    "final_sequence_number": None,
                    "updates_during_transfer": None,
                    "retries": 0,
                    "ack_received": False,
                    "controller_restore_ack": False,
                    "timing_model": None,
                    "steps": [],
                    "rollback_attempted": False,
                    "rollback_succeeded": None,
                },
                "contact_window": {
                    **self.config.contact_window.to_dict(),
                    "eligible": None,
                    "reason": "waiting_for_constellation",
                    "current_distance_km": None,
                    "line_of_sight": None,
                    "alignment_started_at": None,
                    "last_observed_at": None,
                    "ready_at": None,
                    "continuous_alignment_seconds": 0.0,
                    "reset_count": 0,
                    "channel_established": required_alignment == 0,
                    "channel_established_at": created_at if required_alignment == 0 else None,
                    "channel_reused_for_delta": False,
                },
            }
            self._migrations[identifier] = migration
            self._migration_order.append(identifier)
            latest_constellation = deepcopy(self._latest_constellation_state)
            if migration["status"] == "queued":
                self._queue.put(identifier)
        if migration["status"] == "waiting_for_contact" and latest_constellation:
            self.update_constellation(latest_constellation)
        return identifier

    def update_constellation(self, snapshot: dict[str, Any]) -> None:
        """Avanza l'allineamento solo con contatto geometrico continuo."""

        with self._lock:
            self._latest_constellation_state = deepcopy(snapshot)
            waiting = [
                migration
                for migration in self._migrations.values()
                if migration["status"] == "waiting_for_contact"
            ]
            for migration in waiting:
                observation = evaluate_contact(
                    snapshot,
                    migration["source_satellite_id"],
                    migration["target_satellite_id"],
                    self.config.contact_window,
                )
                window = migration["contact_window"]
                observed_at = observation.observed_at
                previous_observation = _parse_timestamp(window["last_observed_at"])
                alignment_started = _parse_timestamp(window["alignment_started_at"])

                window["eligible"] = observation.eligible
                window["reason"] = observation.reason
                window["current_distance_km"] = (
                    round(observation.distance_km, 3)
                    if observation.distance_km is not None
                    else None
                )
                window["line_of_sight"] = observation.line_of_sight

                sample_gap_invalid = (
                    previous_observation is not None
                    and (
                        observed_at <= previous_observation
                        or (observed_at - previous_observation).total_seconds()
                        > self.config.contact_window.max_sample_gap_seconds
                    )
                )
                if not observation.eligible or sample_gap_invalid:
                    if alignment_started is not None:
                        window["reset_count"] += 1
                        migration["events"].append(
                            {
                                "name": "contact_alignment_reset",
                                "timestamp": _isoformat(observed_at),
                                "reason": (
                                    "sample_gap_exceeded"
                                    if sample_gap_invalid
                                    else observation.reason
                                ),
                                "distance_km": window["current_distance_km"],
                            }
                        )
                    alignment_started = None
                    window["alignment_started_at"] = None
                    window["continuous_alignment_seconds"] = 0.0
                    if sample_gap_invalid:
                        window["reason"] = "sample_gap_exceeded"
                elif alignment_started is None:
                    alignment_started = observed_at
                    window["alignment_started_at"] = _isoformat(observed_at)
                    migration["events"].append(
                        {
                            "name": "contact_alignment_started",
                            "timestamp": _isoformat(observed_at),
                            "distance_km": window["current_distance_km"],
                        }
                    )

                window["last_observed_at"] = _isoformat(observed_at)
                if alignment_started is None:
                    continue

                elapsed = max(
                    0.0, (observed_at - alignment_started).total_seconds()
                )
                window["continuous_alignment_seconds"] = round(elapsed, 3)
                if elapsed < self.config.contact_window.required_alignment_seconds:
                    window["reason"] = "alignment_in_progress"
                    continue

                if self._completion_deadline_exceeded(
                    migration,
                    observed_at + timedelta(
                        seconds=self.config.execution_budget_seconds
                    ),
                ):
                    self._expire_before_execution(migration, observed_at)
                    continue

                window["reason"] = "contact_window_ready"
                window["ready_at"] = _isoformat(observed_at)
                migration["events"].append(
                    {
                        "name": "contact_window_ready",
                        "timestamp": window["ready_at"],
                        "continuous_alignment_seconds": round(elapsed, 3),
                    }
                )
                window["channel_established"] = True
                window["channel_established_at"] = window["ready_at"]
                migration["metrics"]["alignment_count"] = 1
                migration["metrics"]["alignment_wait_ms"] = round(
                    elapsed * 1000, 3
                )
                migration["status"] = "queued"
                self._queue.put(migration["migration_id"])

    def process_next(self) -> bool:
        """Esegue sincronicamente il prossimo elemento; utile anche nei test."""

        try:
            migration_id = self._queue.get_nowait()
        except Empty:
            return False
        try:
            self._execute(migration_id)
        finally:
            self._queue.task_done()
        return True

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            ordered = [
                deepcopy(self._migrations[identifier])
                for identifier in self._migration_order
            ]
            return {
                "running": self.running,
                "config": {**self.config.to_dict(), "default_mode": self._default_mode},
                "count": len(ordered),
                "active_migration_id": self._active_migration_id,
                "latest": deepcopy(ordered[-1]) if ordered else None,
                "migrations": ordered,
            }

    def migration_snapshot(self, migration_id: str) -> dict[str, Any] | None:
        with self._lock:
            migration = self._migrations.get(migration_id)
            return deepcopy(migration) if migration else None

    def _worker(self) -> None:
        while not self._stop_event.is_set():
            try:
                migration_id = self._queue.get(timeout=0.2)
            except Empty:
                continue
            try:
                self._execute(migration_id)
            finally:
                self._queue.task_done()

    def _execute(self, migration_id: str) -> None:
        with self._lock:
            migration = self._migrations[migration_id]
            if migration["status"] != "queued":
                return
            migration["status"] = "in_progress"
            migration["started_at"] = _utc_now()
            migration["events"].append(
                {
                    "name": "migration_started",
                    "timestamp": migration["started_at"],
                    "mode": migration["mode"],
                }
            )
            self._active_migration_id = migration_id
            mode = migration["mode"]
            timing_snapshot = deepcopy(self._latest_constellation_state)
            migration["metrics"]["timing_model"] = self._timing_model.plan(
                migration, timing_snapshot
            )

        started = monotonic()
        context: dict[str, Any] = {
            "checkpoint": None,
            "target_started": False,
            "source_stopped": False,
            "controller_shutdown": False,
            "controller_quiesced": False,
            "downtime_started": None,
        }
        try:
            self._ensure_completion_deadline(migration, "start_protocol")
            if mode == "cold":
                self._execute_cold(migration, context)
            else:
                self._execute_hot(migration, context)
            self._ensure_completion_deadline(migration, "complete_protocol")
            with self._lock:
                migration["status"] = "completed"
                migration["completed_at"] = _utc_now()
                migration["events"].append(
                    {
                        "name": "migration_completed",
                        "timestamp": migration["completed_at"],
                    }
                )
                migration["metrics"]["duration_ms"] = round(
                    (monotonic() - started) * 1000, 3
                )
        except Exception as exc:
            rollback_succeeded = self._rollback(migration, context)
            with self._lock:
                migration["status"] = "failed"
                migration["error"] = str(exc)
                migration["completed_at"] = _utc_now()
                migration["events"].append(
                    {
                        "name": "migration_failed",
                        "timestamp": migration["completed_at"],
                        "error": str(exc),
                    }
                )
                migration["metrics"]["duration_ms"] = round(
                    (monotonic() - started) * 1000, 3
                )
                migration["metrics"]["rollback_attempted"] = True
                migration["metrics"]["rollback_succeeded"] = rollback_succeeded
        finally:
            with self._lock:
                self._active_migration_id = None

    def _execute_cold(
        self, migration: dict[str, Any], context: dict[str, Any]
    ) -> None:
        # La richiesta deve essere emessa dalla sorgente finché ospita ancora
        # il Controller. Prepariamo quindi il target prima di fermare SAT src.
        self._prepare_cold_target(migration)
        self._call_step(
            migration,
            "quiesce_source_controller",
            "POST",
            f"{self.config.controller_url}/quiesce",
            None,
            {200},
        )
        context["controller_quiesced"] = True

        checkpoint = self._checkpoint_controller(
            migration,
            step_name="cold_final_checkpoint",
            bytes_metric="final_state_bytes",
        )
        context["checkpoint"] = checkpoint
        final_sequence = _checkpoint_sequence(checkpoint)
        migration["metrics"]["final_sequence_number"] = final_sequence

        # Il checkpoint è completo e il Controller è quiescente: inizia il
        # downtime della Cold migration e la sorgente può essere arrestata.
        context["downtime_started"] = monotonic()
        self._stop_source(migration)
        context["source_stopped"] = True
        self._call_step(
            migration,
            "shutdown_controller",
            "POST",
            f"{self.config.controller_url}/shutdown",
            None,
            {202},
        )
        context["controller_shutdown"] = True
        context["controller_quiesced"] = False

        # Qui avviene l'unico trasferimento di stato della Cold migration. La
        # risposta HTTP 200 è l'ACK emesso dal Satellite Agent destinazione.
        self._transfer_complete_cold_state(migration, checkpoint)
        self._restore_controller(migration, checkpoint)
        context["controller_shutdown"] = False
        self._start_target(migration)
        context["target_started"] = True
        self._set_controller_host(migration, migration["target_satellite_id"])
        migration["metrics"]["downtime_ms"] = round(
            (monotonic() - context["downtime_started"]) * 1000, 3
        )

    def _execute_hot(
        self, migration: dict[str, Any], context: dict[str, Any]
    ) -> None:
        self._ensure_completion_deadline(migration, "initial_checkpoint")
        initial_checkpoint = self._checkpoint_controller(
            migration,
            step_name="initial_checkpoint",
            bytes_metric="initial_state_bytes",
        )
        context["checkpoint"] = initial_checkpoint
        initial_sequence = _checkpoint_sequence(initial_checkpoint)
        migration["metrics"]["initial_sequence_number"] = initial_sequence
        self._ensure_completion_deadline(migration, "prepare_target")
        self._prepare_target(migration, initial_checkpoint)

        self._ensure_completion_deadline(migration, "quiesce_source")
        self._call_step(
            migration,
            "quiesce_source_controller",
            "POST",
            f"{self.config.controller_url}/quiesce",
            None,
            {200},
        )
        context["controller_quiesced"] = True
        context["downtime_started"] = monotonic()

        self._ensure_completion_deadline(migration, "final_checkpoint")
        final_checkpoint = self._checkpoint_controller(
            migration,
            step_name="final_checkpoint",
            bytes_metric="final_state_bytes",
        )
        context["checkpoint"] = final_checkpoint
        final_sequence = _checkpoint_sequence(final_checkpoint)
        if final_sequence < initial_sequence:
            raise MigrationProtocolError(
                "Il sequence number del final state è precedente al checkpoint iniziale"
            )
        migration["metrics"]["final_sequence_number"] = final_sequence
        migration["metrics"]["updates_during_transfer"] = (
            final_sequence - initial_sequence
        )
        self._ensure_completion_deadline(migration, "transfer_final_state")
        migration["contact_window"]["channel_reused_for_delta"] = True
        migration["events"].append(
            {
                "name": "delta_channel_reused",
                "timestamp": _utc_now(),
                "channel_established_at": migration["contact_window"].get(
                    "channel_established_at"
                ),
            }
        )
        self._transfer_final_state(migration, final_checkpoint)

        self._ensure_completion_deadline(migration, "cutover")
        self._stop_source(migration)
        context["source_stopped"] = True
        self._ensure_completion_deadline(migration, "restore_controller")
        self._restore_controller(migration, final_checkpoint)
        context["controller_quiesced"] = False
        self._ensure_completion_deadline(migration, "start_target")
        self._start_target(migration)
        context["target_started"] = True
        self._ensure_completion_deadline(migration, "update_controller_host")
        self._set_controller_host(migration, migration["target_satellite_id"])
        migration["metrics"]["downtime_ms"] = round(
            (monotonic() - context["downtime_started"]) * 1000, 3
        )

    def _completion_deadline(self, migration: dict[str, Any]) -> datetime | None:
        recommendation = migration.get("recommendation")
        if not isinstance(recommendation, dict):
            return None
        return _parse_timestamp(recommendation.get("completion_deadline_at"))

    def _completion_deadline_exceeded(
        self, migration: dict[str, Any], moment: datetime
    ) -> bool:
        deadline = self._completion_deadline(migration)
        return deadline is not None and moment > deadline

    def _expire_before_execution(
        self, migration: dict[str, Any], observed_at: datetime
    ) -> None:
        deadline = self._completion_deadline(migration)
        migration["status"] = "expired"
        migration["error"] = "Tempo insufficiente per completare la migrazione prima della deadline"
        migration["completed_at"] = _isoformat(observed_at)
        migration["contact_window"]["reason"] = "insufficient_time_before_deadline"
        migration["events"].append(
            {
                "name": "migration_expired_before_execution",
                "timestamp": migration["completed_at"],
                "completion_deadline_at": _isoformat(deadline) if deadline else None,
            }
        )

    def _ensure_completion_deadline(
        self, migration: dict[str, Any], phase: str
    ) -> None:
        deadline = self._completion_deadline(migration)
        if deadline is None:
            return
        if datetime.now(timezone.utc) > deadline:
            raise MigrationProtocolError(
                "Deadline di completamento superata prima della fase "
                f"{phase}: {_isoformat(deadline)}"
            )

    def _checkpoint_controller(
        self,
        migration: dict[str, Any],
        step_name: str = "checkpoint_controller",
        bytes_metric: str | None = None,
    ) -> dict[str, Any]:
        response = self._call_step(
            migration,
            step_name,
            "POST",
            f"{self.config.controller_url}/checkpoint",
            None,
            {201},
        )
        checkpoint = response.payload.get("checkpoint")
        if not isinstance(checkpoint, dict):
            raise MigrationProtocolError("Il Controller non ha restituito un checkpoint")
        serialized = json.dumps(checkpoint, separators=(",", ":")).encode("utf-8")
        migration["metrics"]["state_bytes"] += len(serialized)
        if bytes_metric is not None:
            migration["metrics"][bytes_metric] = len(serialized)
        return checkpoint

    def _prepare_target(
        self, migration: dict[str, Any], checkpoint: dict[str, Any]
    ) -> None:
        self._request_source_migration(migration)
        self._ensure_target_passive(migration)
        target_url = self.config.agent_url(migration["target_satellite_id"])
        self._call_step(
            migration,
            "transfer_initial_state_to_target",
            "POST",
            f"{target_url}/prepare_migration",
            {
                "migration_id": migration["migration_id"],
                "source_satellite_id": migration["source_satellite_id"],
                "target_satellite_id": migration["target_satellite_id"],
                "controller_state": checkpoint,
            },
            {202},
        )

    def _prepare_cold_target(self, migration: dict[str, Any]) -> None:
        """Scambia solo i messaggi di controllo prima del freeze Cold."""

        self._request_source_migration(migration)
        self._ensure_target_passive(migration)
        target_url = self.config.agent_url(migration["target_satellite_id"])
        self._call_step(
            migration,
            "prepare_target_for_cold_migration",
            "POST",
            f"{target_url}/prepare_migration",
            {
                "migration_id": migration["migration_id"],
                "source_satellite_id": migration["source_satellite_id"],
                "target_satellite_id": migration["target_satellite_id"],
            },
            {202},
        )

    def _request_source_migration(self, migration: dict[str, Any]) -> None:
        source_url = self.config.agent_url(migration["source_satellite_id"])
        self._call_step(
            migration,
            "request_source_migration",
            "POST",
            f"{source_url}/migration_request",
            {
                "migration_id": migration["migration_id"],
                "source_satellite_id": migration["source_satellite_id"],
                "target_satellite_id": migration["target_satellite_id"],
                "mode": migration["mode"],
            },
            {202},
        )

    def _ensure_target_passive(self, migration: dict[str, Any]) -> None:
        target_url = self.config.agent_url(migration["target_satellite_id"])
        self._call_step(
            migration,
            "ensure_target_passive",
            "POST",
            f"{target_url}/stop_controller",
            None,
            {200},
        )

    def _restore_controller(
        self, migration: dict[str, Any], checkpoint: dict[str, Any]
    ) -> None:
        self._call_step(
            migration,
            "transfer_state_and_wait_ack",
            "POST",
            f"{self.config.controller_url}/restore",
            {"checkpoint": checkpoint},
            {200},
        )
        migration["metrics"]["controller_restore_ack"] = True

    def _transfer_final_state(
        self, migration: dict[str, Any], checkpoint: dict[str, Any]
    ) -> None:
        self._transfer_state_and_wait_target_ack(
            migration,
            checkpoint,
            "transfer_final_state_and_wait_target_ack",
        )

    def _transfer_complete_cold_state(
        self, migration: dict[str, Any], checkpoint: dict[str, Any]
    ) -> None:
        self._transfer_state_and_wait_target_ack(
            migration,
            checkpoint,
            "transfer_complete_state_and_wait_target_ack",
        )

    def _transfer_state_and_wait_target_ack(
        self,
        migration: dict[str, Any],
        checkpoint: dict[str, Any],
        step_name: str,
    ) -> None:
        target_url = self.config.agent_url(migration["target_satellite_id"])
        response = self._call_step(
            migration,
            step_name,
            "POST",
            f"{target_url}/receive_controller_state",
            {
                "migration_id": migration["migration_id"],
                "controller_state": checkpoint,
            },
            {200},
        )
        acknowledged_sequence = response.payload.get("sequence_number")
        expected_sequence = _checkpoint_sequence(checkpoint)
        if acknowledged_sequence != expected_sequence:
            raise MigrationProtocolError(
                "L'ACK del target non conferma il final sequence number"
            )
        migration["metrics"]["ack_received"] = True

    def _start_target(self, migration: dict[str, Any]) -> None:
        target_url = self.config.agent_url(migration["target_satellite_id"])
        self._call_step(
            migration,
            "start_target_controller",
            "POST",
            f"{target_url}/start_controller",
            None,
            {200},
        )

    def _stop_source(self, migration: dict[str, Any]) -> None:
        source_url = self.config.agent_url(migration["source_satellite_id"])
        self._call_step(
            migration,
            "stop_source_controller",
            "POST",
            f"{source_url}/stop_controller",
            None,
            {200},
        )

    def _set_controller_host(
        self, migration: dict[str, Any], satellite_id: str
    ) -> None:
        self._call_step(
            migration,
            "update_controller_host",
            "POST",
            f"{self.config.controller_url}/host",
            {"satellite_id": satellite_id},
            {200},
        )
        with self._lock:
            listener = self._handover_listener
        if listener is not None:
            listener(migration["source_satellite_id"], satellite_id)

    def _call_step(
        self,
        migration: dict[str, Any],
        name: str,
        method: str,
        url: str,
        payload: dict[str, Any] | None,
        expected_statuses: set[int],
    ) -> RestResponse:
        started = monotonic()
        started_at = _utc_now()
        last_error: Exception | None = None
        live_step = {
            "name": name,
            "status": "in_progress",
            "http_status": None,
            "attempts": 0,
            "duration_ms": None,
            "started_at": started_at,
            "completed_at": None,
            "timestamp": started_at,
            "error": None,
        }
        with self._lock:
            migration["metrics"]["steps"].append(live_step)
        timing_plan = migration["metrics"].get("timing_model") or {}
        simulated_delay_seconds, timing_breakdown = self._timing_model.delay_for_step(
            timing_plan, name
        )
        live_step["timing_contributions_ms"] = timing_breakdown
        if simulated_delay_seconds:
            sleep(simulated_delay_seconds)

        for attempt in range(1, self.config.max_retries + 2):
            with self._lock:
                live_step["attempts"] = attempt
            try:
                response = self.transport.request(
                    method,
                    url,
                    payload,
                    self.config.request_timeout_seconds,
                )
                if response.status not in expected_statuses:
                    raise MigrationProtocolError(
                        f"{name}: atteso HTTP {sorted(expected_statuses)}, "
                        f"ricevuto HTTP {response.status}"
                    )
                completed_at = _utc_now()
                with self._lock:
                    live_step.update(
                        {
                            "status": "ok",
                            "http_status": response.status,
                            "attempts": attempt,
                            "duration_ms": round(
                                (monotonic() - started) * 1000, 3
                            ),
                            "completed_at": completed_at,
                            "timestamp": completed_at,
                            "error": None,
                        }
                    )
                    migration["metrics"]["retries"] += attempt - 1
                return response
            except Exception as exc:
                last_error = exc
                if attempt <= self.config.max_retries:
                    sleep(self.config.retry_delay_seconds)

        completed_at = _utc_now()
        with self._lock:
            migration["metrics"]["retries"] += self.config.max_retries
            live_step.update(
                {
                    "status": "failed",
                    "http_status": None,
                    "attempts": self.config.max_retries + 1,
                    "duration_ms": round((monotonic() - started) * 1000, 3),
                    "completed_at": completed_at,
                    "timestamp": completed_at,
                    "error": str(last_error),
                }
            )
        raise MigrationProtocolError(f"Passo {name} fallito: {last_error}")

    def _rollback(
        self, migration: dict[str, Any], context: dict[str, Any]
    ) -> bool:
        checkpoint = context.get("checkpoint")
        succeeded = True
        try:
            if context.get("target_started"):
                target_url = self.config.agent_url(migration["target_satellite_id"])
                self._call_step(
                    migration,
                    "rollback_stop_target",
                    "POST",
                    f"{target_url}/stop_controller",
                    None,
                    {200},
                )
            if checkpoint is not None and context.get("controller_shutdown"):
                self._call_step(
                    migration,
                    "rollback_restore_controller",
                    "POST",
                    f"{self.config.controller_url}/restore",
                    {"checkpoint": checkpoint},
                    {200},
                )
            elif context.get("controller_quiesced"):
                self._call_step(
                    migration,
                    "rollback_resume_source",
                    "POST",
                    f"{self.config.controller_url}/resume",
                    None,
                    {200},
                )
            if context.get("source_stopped"):
                source_url = self.config.agent_url(migration["source_satellite_id"])
                self._call_step(
                    migration,
                    "rollback_start_source",
                    "POST",
                    f"{source_url}/start_controller",
                    None,
                    {200},
                )
                self._set_controller_host(
                    migration, migration["source_satellite_id"]
                )
        except Exception:
            succeeded = False
        return succeeded


def _checkpoint_sequence(checkpoint: dict[str, Any]) -> int:
    sequence = checkpoint.get("sequence_number")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        raise MigrationProtocolError("Checkpoint privo di sequence number valido")
    return sequence


def _canonical_satellite_id(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise MigrationManagerError("ID satellite non valido")
    text = str(value).strip().upper()
    if not text:
        raise MigrationManagerError("ID satellite vuoto")
    return text if text.startswith("SAT-") else f"SAT-{text}"


def _required_url(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.startswith(("http://", "https://")):
        raise MigrationManagerError(f"{name} deve essere un URL HTTP valido")
    return value


def _positive_number(value: Any, name: str) -> float:
    result = _non_negative_number(value, name)
    if result == 0:
        raise MigrationManagerError(f"{name} deve essere maggiore di zero")
    return result


def _non_negative_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MigrationManagerError(f"{name} deve essere numerico")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise MigrationManagerError(f"{name} deve essere finito e non negativo")
    return result


def _utc_now() -> str:
    return _isoformat(datetime.now(timezone.utc))


def _isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)
