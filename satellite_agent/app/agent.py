"""Stato locale, sincronizzazione orbitale e heartbeat del Satellite Agent."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import logging
import math
import re
from threading import Event, RLock, Thread
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import psutil

from .transport import AgentHttpTransport, UrllibAgentHttpTransport

LOGGER = logging.getLogger(__name__)
REQUIRED_ORBITAL_FIELDS = {
    "position_km",
    "velocity_km_s",
    "illumination",
    "distances_km",
}


class AgentValidationError(ValueError):
    """Errore di validazione traducibile in una risposta HTTP 400/409."""


class SatelliteAgent:
    """Mantiene lo stato autonomo di un satellite e i suoi worker periodici."""

    def __init__(
        self,
        satellite_id: str,
        controller_enabled: bool = False,
        simulator_url: str = "",
        heartbeat_url: str = "",
        state_sync_interval_seconds: float = 1.0,
        heartbeat_interval_seconds: float = 5.0,
        request_timeout_seconds: float = 2.0,
        transport: AgentHttpTransport | None = None,
    ) -> None:
        satellite_id = satellite_id.strip().upper()
        if not satellite_id or satellite_id == "UNASSIGNED":
            raise ValueError("SATELLITE_ID deve essere configurato")
        if state_sync_interval_seconds <= 0 or heartbeat_interval_seconds <= 0:
            raise ValueError("Gli intervalli periodici devono essere maggiori di zero")
        if request_timeout_seconds <= 0:
            raise ValueError("Il timeout HTTP deve essere maggiore di zero")

        self.satellite_id = satellite_id
        self.simulator_url = simulator_url.rstrip("/")
        self.heartbeat_url = heartbeat_url
        self.state_sync_interval_seconds = state_sync_interval_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self.transport = transport or UrllibAgentHttpTransport()

        self._lock = RLock()
        self._stop_event = Event()
        self._threads: list[Thread] = []
        self._orbital_state: dict[str, Any] | None = None
        self._state_received_at: str | None = None
        self._source_generated_at: str | None = None
        self._controller_running = controller_enabled
        self._migration: dict[str, Any] | None = None
        self._latest_heartbeat: dict[str, Any] | None = None
        self._last_heartbeat_sent_at: str | None = None
        self._last_heartbeat_error: str | None = None
        self._last_sync_at: str | None = None
        self._last_sync_error: str | None = None

    @property
    def running(self) -> bool:
        return bool(self._threads) and all(thread.is_alive() for thread in self._threads)

    def start(self) -> None:
        """Avvia sincronizzazione dal Simulator e invio heartbeat."""

        if self.running:
            return
        self._stop_event.clear()
        self._attempt_state_sync()
        self._attempt_heartbeat()
        self._threads = [
            Thread(
                target=self._periodic_loop,
                args=(self.state_sync_interval_seconds, self._attempt_state_sync),
                name=f"{self.satellite_id}-state-sync",
                daemon=True,
            ),
            Thread(
                target=self._periodic_loop,
                args=(self.heartbeat_interval_seconds, self._attempt_heartbeat),
                name=f"{self.satellite_id}-heartbeat",
                daemon=True,
            ),
        ]
        for thread in self._threads:
            thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        for thread in self._threads:
            if thread.is_alive():
                thread.join(timeout=timeout)
        self._threads = []

    def receive_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Accetta un record singolo o estrae il proprio record da uno snapshot."""

        if not isinstance(payload, dict):
            raise AgentValidationError("Il corpo deve essere un oggetto JSON")

        source_generated_at = payload.get("generated_at")
        if "satellites" in payload:
            satellites = payload["satellites"]
            if not isinstance(satellites, dict):
                raise AgentValidationError("satellites deve essere un oggetto JSON")
            orbital_state = satellites.get(self.satellite_id)
            if orbital_state is None:
                raise AgentValidationError(
                    f"Lo snapshot non contiene {self.satellite_id}"
                )
        else:
            orbital_state = payload

        if not isinstance(orbital_state, dict):
            raise AgentValidationError("Lo stato orbitale deve essere un oggetto JSON")
        received_id = str(orbital_state.get("id", self.satellite_id)).upper()
        if received_id != self.satellite_id:
            raise AgentValidationError(
                f"Stato destinato a {received_id}, agente corrente {self.satellite_id}"
            )
        missing = REQUIRED_ORBITAL_FIELDS - orbital_state.keys()
        if missing:
            raise AgentValidationError(
                "Campi orbitali mancanti: " + ", ".join(sorted(missing))
            )

        received_at = _utc_now()
        with self._lock:
            self._orbital_state = deepcopy(orbital_state)
            self._state_received_at = received_at
            self._source_generated_at = source_generated_at
            self._last_sync_at = received_at
            self._last_sync_error = None
        return self.orbital_state() or {}

    def orbital_state(self) -> dict[str, Any] | None:
        with self._lock:
            return deepcopy(self._orbital_state)

    def position_state(self) -> dict[str, Any] | None:
        with self._lock:
            if self._orbital_state is None:
                return None
            state = self._orbital_state
            return {
                "id": self.satellite_id,
                "source_generated_at": self._source_generated_at,
                "received_at": self._state_received_at,
                "position_km": deepcopy(state.get("position_km")),
                "geodetic": deepcopy(state.get("geodetic")),
                "velocity_km_s": deepcopy(state.get("velocity_km_s")),
                "speed_km_s": state.get("speed_km_s"),
                "illumination": deepcopy(state.get("illumination")),
            }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "id": self.satellite_id,
                "running": self.running,
                "controller": self._controller_running,
                "orbital_state": {
                    "available": self._orbital_state is not None,
                    "received_at": self._state_received_at,
                    "source_generated_at": self._source_generated_at,
                    "last_sync_at": self._last_sync_at,
                    "last_sync_error": self._last_sync_error,
                },
                "heartbeat": {
                    "interval_seconds": self.heartbeat_interval_seconds,
                    "destination": self.heartbeat_url or None,
                    "latest": deepcopy(self._latest_heartbeat),
                    "last_sent_at": self._last_heartbeat_sent_at,
                    "last_error": self._last_heartbeat_error,
                },
                "migration": deepcopy(self._migration),
            }

    def start_controller(self) -> dict[str, Any]:
        with self._lock:
            changed = not self._controller_running
            self._controller_running = True
            if self._migration and self._migration["status"] in {
                "accepted",
                "final_state_received",
            }:
                self._migration["status"] = "activated"
                self._migration["activated_at"] = _utc_now()
            return {
                "id": self.satellite_id,
                "controller": True,
                "changed": changed,
            }

    def stop_controller(self) -> dict[str, Any]:
        with self._lock:
            changed = self._controller_running
            self._controller_running = False
            return {
                "id": self.satellite_id,
                "controller": False,
                "changed": changed,
            }

    def accept_migration(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise AgentValidationError("Il corpo deve essere un oggetto JSON")
        source_id = str(payload.get("source_satellite_id", "")).strip().upper()
        target_id = str(
            payload.get("target_satellite_id", self.satellite_id)
        ).strip().upper()
        if not source_id:
            raise AgentValidationError("source_satellite_id è obbligatorio")
        if target_id != self.satellite_id:
            raise AgentValidationError(
                f"La richiesta è destinata a {target_id}, non a {self.satellite_id}"
            )
        if source_id == self.satellite_id:
            raise AgentValidationError("Sorgente e destinazione devono essere diverse")

        with self._lock:
            if self._controller_running and not bool(payload.get("force", False)):
                raise AgentValidationError(
                    "Il Controller è già attivo sul satellite di destinazione"
                )
            migration = {
                "migration_id": str(payload.get("migration_id") or uuid4()),
                "source_satellite_id": source_id,
                "target_satellite_id": self.satellite_id,
                "status": "accepted",
                "requested_at": _utc_now(),
                "controller_state": deepcopy(payload.get("controller_state")),
            }
            self._migration = migration
            return deepcopy(migration)

    def receive_controller_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Memorizza il final state della Hot Migration e restituisce l'ACK."""

        if not isinstance(payload, dict):
            raise AgentValidationError("Il corpo deve essere un oggetto JSON")
        migration_id = str(payload.get("migration_id", "")).strip()
        controller_state = payload.get("controller_state")
        if not migration_id:
            raise AgentValidationError("migration_id è obbligatorio")
        if not isinstance(controller_state, dict):
            raise AgentValidationError("controller_state deve essere un oggetto JSON")
        required = {
            "topology",
            "routing_table",
            "heartbeats",
            "sequence_number",
            "timestamp",
        }
        missing = required - controller_state.keys()
        if missing:
            raise AgentValidationError(
                "Campi Controller mancanti: " + ", ".join(sorted(missing))
            )
        sequence = controller_state["sequence_number"]
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise AgentValidationError("sequence_number deve essere un intero non negativo")

        with self._lock:
            if self._migration is None or self._migration["migration_id"] != migration_id:
                raise AgentValidationError("Migrazione non preparata o migration_id errato")
            initial_state = self._migration.get("controller_state") or {}
            initial_sequence = initial_state.get("sequence_number", -1)
            if sequence < initial_sequence:
                raise AgentValidationError(
                    "Il final state è precedente al checkpoint iniziale"
                )
            self._migration["controller_state"] = deepcopy(controller_state)
            self._migration["status"] = "final_state_received"
            self._migration["final_state_received_at"] = _utc_now()
            self._migration["final_sequence_number"] = sequence
            return {
                "status": "ack",
                "migration_id": migration_id,
                "satellite_id": self.satellite_id,
                "sequence_number": sequence,
            }

    def build_heartbeat(self) -> dict[str, Any]:
        with self._lock:
            orbital_state = deepcopy(self._orbital_state)
            controller_running = self._controller_running

        time_to_eclipse: int | None = None
        neighbors = 0
        if orbital_state:
            seconds = orbital_state.get("illumination", {}).get(
                "seconds_until_eclipse"
            )
            if isinstance(seconds, (int, float)) and math.isfinite(seconds):
                time_to_eclipse = max(0, round(seconds))
            distances = orbital_state.get("distances_km", {})
            neighbors = sum(
                1
                for satellite_id, distance in distances.items()
                if satellite_id != self.satellite_id
                and isinstance(distance, (int, float))
                and math.isfinite(distance)
            )

        heartbeat = {
            "id": _heartbeat_id(self.satellite_id),
            "time_to_eclipse": time_to_eclipse,
            "neighbors": neighbors,
            "cpu": round(float(psutil.cpu_percent(interval=0.1))),
            "controller": controller_running,
        }
        with self._lock:
            self._latest_heartbeat = heartbeat
        return deepcopy(heartbeat)

    def send_heartbeat(self) -> dict[str, Any]:
        heartbeat = self.build_heartbeat()
        LOGGER.info("heartbeat=%s", json.dumps(heartbeat, separators=(",", ":")))
        if not self.heartbeat_url:
            return heartbeat

        try:
            status = self.transport.post_json(
                self.heartbeat_url,
                heartbeat,
                self.request_timeout_seconds,
            )
            if not 200 <= status < 300:
                raise RuntimeError(f"Heartbeat rifiutato con HTTP {status}")
            with self._lock:
                self._last_heartbeat_sent_at = _utc_now()
                self._last_heartbeat_error = None
        except Exception as exc:
            with self._lock:
                self._last_heartbeat_error = str(exc)
            raise
        return heartbeat

    def sync_from_simulator(self) -> dict[str, Any]:
        if not self.simulator_url:
            raise RuntimeError("SIMULATOR_URL non configurato")
        url = (
            f"{self.simulator_url}/api/v1/satellites/"
            f"{quote(self.satellite_id, safe='')}"
        )
        payload = self.transport.get_json(url, self.request_timeout_seconds)
        return self.receive_state(payload)

    def _periodic_loop(self, interval: float, callback: Any) -> None:
        while not self._stop_event.wait(interval):
            callback()

    def _attempt_state_sync(self) -> None:
        if not self.simulator_url:
            return
        try:
            self.sync_from_simulator()
        except Exception as exc:  # pragma: no cover - dipende dalla rete
            LOGGER.warning("Sincronizzazione orbitale fallita: %s", exc)
            with self._lock:
                self._last_sync_error = str(exc)

    def _attempt_heartbeat(self) -> None:
        try:
            self.send_heartbeat()
        except Exception as exc:  # pragma: no cover - dipende dalla rete
            LOGGER.warning("Invio heartbeat fallito: %s", exc)


def _heartbeat_id(satellite_id: str) -> int | str:
    match = re.fullmatch(r"SAT-(\d+)", satellite_id)
    return int(match.group(1)) if match else satellite_id


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
