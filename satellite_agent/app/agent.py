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

try:
    from controller_core.service import ControllerService
except ModuleNotFoundError:  # import usato dai test eseguiti dal repository
    from controller.app.service import ControllerService

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
        controller_heartbeat_url: str = "",
        state_sync_interval_seconds: float = 1.0,
        heartbeat_interval_seconds: float = 5.0,
        request_timeout_seconds: float = 2.0,
        transport: AgentHttpTransport | None = None,
        controller_service: ControllerService | None = None,
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
        self.controller_heartbeat_url = controller_heartbeat_url
        self.state_sync_interval_seconds = state_sync_interval_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self.transport = transport or UrllibAgentHttpTransport()
        self.controller_service = controller_service or ControllerService(
            f"/tmp/{self.satellite_id.lower()}-controller-checkpoint.json",
            host_satellite_id=self.satellite_id,
        )

        self._lock = RLock()
        self._stop_event = Event()
        self._threads: list[Thread] = []
        self._orbital_state: dict[str, Any] | None = None
        self._state_received_at: str | None = None
        self._source_generated_at: str | None = None
        self._controller_running = controller_enabled
        if controller_enabled:
            self.controller_service.activate()
        else:
            self.controller_service.shutdown()
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
                "controller_instance_active": self.controller_service.active,
                "orbital_state": {
                    "available": self._orbital_state is not None,
                    "received_at": self._state_received_at,
                    "source_generated_at": self._source_generated_at,
                    "last_sync_at": self._last_sync_at,
                    "last_sync_error": self._last_sync_error,
                },
                "heartbeat": {
                    "interval_seconds": self.heartbeat_interval_seconds,
                    "destinations": [
                        destination
                        for destination in (
                            self.heartbeat_url,
                            self.controller_heartbeat_url,
                        )
                        if destination
                    ],
                    "latest": deepcopy(self._latest_heartbeat),
                    "last_sent_at": self._last_heartbeat_sent_at,
                    "last_error": self._last_heartbeat_error,
                },
                "migration": deepcopy(self._migration),
            }

    def start_controller(self) -> dict[str, Any]:
        with self._lock:
            if (
                not self._controller_running
                and self._migration
                and self._migration.get("direction") == "inbound"
                and self._migration.get("status") not in {
                    "final_state_received",
                    "activated",
                }
            ):
                raise AgentValidationError(
                    "Il Controller può essere attivato sul target solo dopo "
                    "la ricezione dell'update finale"
                )
            changed = not self._controller_running
            migration_state = (
                self._migration.get("controller_state")
                if self._migration and self._migration.get("direction") == "inbound"
                else None
            )
            if isinstance(migration_state, dict):
                self.controller_service.restore({"checkpoint": migration_state})
            else:
                self.controller_service.activate()
            self.controller_service.set_host_satellite(self.satellite_id)
            self._controller_running = True
            if self._migration and self._migration["status"] == "final_state_received":
                self._migration["status"] = "activated"
                self._migration["activated_at"] = _utc_now()
                controller_state = self._migration.get("controller_state")
                if isinstance(controller_state, dict):
                    for satellite_id, heartbeat in controller_state.get(
                        "heartbeats", {}
                    ).items():
                        if isinstance(heartbeat, dict):
                            heartbeat["controller"] = satellite_id == self.satellite_id
                    for satellite_id, node in controller_state.get(
                        "topology", {}
                    ).get("nodes", {}).items():
                        if isinstance(node, dict):
                            node["controller"] = satellite_id == self.satellite_id
            return {
                "id": self.satellite_id,
                "controller": True,
                "changed": changed,
            }

    def stop_controller(self) -> dict[str, Any]:
        with self._lock:
            changed = self._controller_running
            if self.controller_service.active:
                self.controller_service.shutdown()
            self._controller_running = False
            if (
                changed
                and self._migration
                and self._migration.get("direction") == "outbound"
            ):
                self._migration["status"] = (
                    "source_stopped"
                    if self._migration.get("mode") == "cold"
                    else "source_stopped_after_delta"
                )
                self._migration["stopped_at"] = _utc_now()
            return {
                "id": self.satellite_id,
                "controller": False,
                "changed": changed,
            }

    def reset_simulation(self) -> dict[str, Any]:
        """Azzera lo stato volatile mantenendo attivi i worker del container."""

        with self._lock:
            self._orbital_state = None
            self._state_received_at = None
            self._source_generated_at = None
            self._controller_running = False
            self.controller_service.reset_simulation()
            self.controller_service.shutdown()
            self._migration = None
            self._latest_heartbeat = None
            self._last_heartbeat_sent_at = None
            self._last_heartbeat_error = None
            self._last_sync_at = None
            self._last_sync_error = None
        return {"id": self.satellite_id, "status": "reset"}

    def request_migration(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Registra sul satellite Controller la richiesta di migrazione in uscita."""

        if not isinstance(payload, dict):
            raise AgentValidationError("Il corpo deve essere un oggetto JSON")
        source_id = str(
            payload.get("source_satellite_id", self.satellite_id)
        ).strip().upper()
        target_id = str(payload.get("target_satellite_id", "")).strip().upper()
        if source_id != self.satellite_id:
            raise AgentValidationError(
                f"La richiesta deve essere avviata da {source_id}, non da {self.satellite_id}"
            )
        if not target_id:
            raise AgentValidationError("target_satellite_id è obbligatorio")
        if target_id == self.satellite_id:
            raise AgentValidationError("Sorgente e destinazione devono essere diverse")

        with self._lock:
            if not self._controller_running:
                raise AgentValidationError(
                    "La migration_request può essere avviata solo dal satellite "
                    "che ospita il Controller"
                )
            migration = {
                "migration_id": str(payload.get("migration_id") or uuid4()),
                "source_satellite_id": self.satellite_id,
                "target_satellite_id": target_id,
                "mode": str(payload.get("mode", "hot")).lower(),
                "direction": "outbound",
                "status": "requested",
                "requested_at": _utc_now(),
            }
            self._migration = migration
            return deepcopy(migration)

    def prepare_migration(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Prepara il target senza attivare il Controller."""

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
                "direction": "inbound",
                "status": "prepared",
                "requested_at": _utc_now(),
                "controller_state": deepcopy(payload.get("controller_state")),
            }
            self._migration = migration
            return deepcopy(migration)

    def receive_controller_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Memorizza lo stato finale della migrazione e restituisce l'ACK."""

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
            if self._migration.get("direction") != "inbound":
                raise AgentValidationError("Il satellite non è il target della migrazione")
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
        neighbor_ids: list[str] = []
        if orbital_state:
            seconds = orbital_state.get("illumination", {}).get(
                "seconds_until_eclipse"
            )
            if isinstance(seconds, (int, float)) and math.isfinite(seconds):
                time_to_eclipse = max(0, round(seconds))
            physical_neighbors = orbital_state.get("physical_neighbors")
            if isinstance(physical_neighbors, list):
                neighbor_ids = sorted(
                    {
                        str(satellite_id).strip().upper()
                        for satellite_id in physical_neighbors
                        if str(satellite_id).strip().upper() != self.satellite_id
                    }
                )
                neighbors = len(neighbor_ids)
            else:
                distances = orbital_state.get("distances_km", {})
                neighbor_ids = sorted(
                    satellite_id
                    for satellite_id, distance in distances.items()
                    if satellite_id != self.satellite_id
                    and isinstance(distance, (int, float))
                    and math.isfinite(distance)
                )
                neighbors = len(neighbor_ids)

        heartbeat = {
            "id": _heartbeat_id(self.satellite_id),
            "time_to_eclipse": time_to_eclipse,
            "neighbors": neighbors,
            "neighbor_ids": neighbor_ids,
            "cpu": round(float(psutil.cpu_percent(interval=0.1))),
            "controller": controller_running,
        }
        with self._lock:
            self._latest_heartbeat = heartbeat
        return deepcopy(heartbeat)

    def send_heartbeat(self) -> dict[str, Any]:
        heartbeat = self.build_heartbeat()
        LOGGER.info("heartbeat=%s", json.dumps(heartbeat, separators=(",", ":")))
        destinations = list(
            dict.fromkeys(
                destination
                for destination in (
                    self.heartbeat_url,
                    self.controller_heartbeat_url,
                )
                if destination
            )
        )
        if not destinations:
            return heartbeat

        errors: list[str] = []
        for destination in destinations:
            try:
                status = self.transport.post_json(
                    destination,
                    heartbeat,
                    self.request_timeout_seconds,
                )
                if not 200 <= status < 300:
                    raise RuntimeError(f"HTTP {status}")
            except Exception as exc:
                errors.append(f"{destination}: {exc}")
        with self._lock:
            self._last_heartbeat_sent_at = _utc_now()
            self._last_heartbeat_error = "; ".join(errors) if errors else None
        if errors:
            raise RuntimeError(self._last_heartbeat_error)
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
