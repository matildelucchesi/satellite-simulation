"""Stato versionato, checkpoint e routing del microservizio Controller."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import RLock
from typing import Any

from .repository import CheckpointRepository, JsonFileCheckpointRepository


class ControllerStateError(ValueError):
    """Segnala heartbeat o checkpoint non validi."""


@dataclass(slots=True)
class ControllerState:
    """Rappresentazione JSON-serializzabile dello stato replicabile."""

    topology: dict[str, Any]
    routing_table: dict[str, Any]
    heartbeats: dict[str, Any]
    sequence_number: int
    timestamp: str

    @classmethod
    def empty(cls) -> "ControllerState":
        return cls(
            topology={"nodes": {}, "links": []},
            routing_table={},
            heartbeats={},
            sequence_number=0,
            timestamp=_utc_now(),
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ControllerState":
        if not isinstance(payload, dict):
            raise ControllerStateError("Il checkpoint deve essere un oggetto JSON")
        required = {
            "topology",
            "routing_table",
            "heartbeats",
            "sequence_number",
            "timestamp",
        }
        missing = required - payload.keys()
        if missing:
            raise ControllerStateError(
                "Campi del checkpoint mancanti: " + ", ".join(sorted(missing))
            )
        if not all(
            isinstance(payload[field], dict)
            for field in ("topology", "routing_table", "heartbeats")
        ):
            raise ControllerStateError(
                "topology, routing_table e heartbeats devono essere oggetti JSON"
            )
        sequence = payload["sequence_number"]
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise ControllerStateError("sequence_number deve essere un intero positivo")
        _validate_timestamp(payload["timestamp"])

        topology = deepcopy(payload["topology"])
        topology.setdefault("nodes", {})
        topology.setdefault("links", [])
        if not isinstance(topology["nodes"], dict) or not isinstance(
            topology["links"], list
        ):
            raise ControllerStateError("La topologia deve contenere nodes e links validi")

        return cls(
            topology=topology,
            routing_table=deepcopy(payload["routing_table"]),
            heartbeats=deepcopy(payload["heartbeats"]),
            sequence_number=sequence,
            timestamp=payload["timestamp"],
        )

    @classmethod
    def from_json(cls, value: str) -> "ControllerState":
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ControllerStateError(f"JSON del checkpoint non valido: {exc}") from exc
        return cls.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topology": deepcopy(self.topology),
            "routing_table": deepcopy(self.routing_table),
            "heartbeats": deepcopy(self.heartbeats),
            "sequence_number": self.sequence_number,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


class ControllerService:
    """Gestisce lo stato del Controller in modo atomico e thread-safe."""

    def __init__(
        self,
        checkpoint_path: str | Path,
        checkpoint_repository: CheckpointRepository | None = None,
        host_satellite_id: str = "UNASSIGNED",
    ) -> None:
        self._checkpoint_repository = checkpoint_repository or (
            JsonFileCheckpointRepository(checkpoint_path)
        )
        self.checkpoint_path = self._checkpoint_repository.path
        self._lock = RLock()
        self._state = ControllerState.empty()
        self._active = True
        self._quiesced = False
        self._host_satellite_id = _validate_host_satellite_id(host_satellite_id)

    @property
    def host_satellite_id(self) -> str:
        with self._lock:
            return self._host_satellite_id

    def set_host_satellite(self, satellite_id: Any) -> dict[str, Any]:
        normalized = _validate_host_satellite_id(satellite_id)
        with self._lock:
            previous = self._host_satellite_id
            self._host_satellite_id = normalized
            for satellite_id, heartbeat in self._state.heartbeats.items():
                heartbeat["controller"] = satellite_id == normalized
            for satellite_id, node in self._state.topology.get("nodes", {}).items():
                if isinstance(node, dict):
                    node["controller"] = satellite_id == normalized
            self._touch()
            return {
                "status": "updated",
                "previous_host_satellite_id": previous,
                "host_satellite_id": normalized,
            }

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    @property
    def quiesced(self) -> bool:
        with self._lock:
            return self._quiesced

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._state.to_dict()

    def reset_simulation(self) -> dict[str, Any]:
        """Ripristina lo stato iniziale senza riavviare il processo Flask."""

        with self._lock:
            self._state = ControllerState.empty()
            self._active = True
            self._quiesced = False
            self._host_satellite_id = "UNASSIGNED"
        return {"status": "reset", "host_satellite_id": "UNASSIGNED"}

    def activate(self) -> dict[str, Any]:
        """Avvia questa istanza mantenendo lo stato già caricato."""
        with self._lock:
            self._active = True
            self._quiesced = False
            return {
                "status": "active",
                "host_satellite_id": self._host_satellite_id,
                "sequence_number": self._state.sequence_number,
            }

    def heartbeat_snapshot(self, satellite_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            if satellite_id is None:
                heartbeats = deepcopy(self._state.heartbeats)
            else:
                canonical_id = _canonical_satellite_id(satellite_id)
                heartbeat = self._state.heartbeats.get(canonical_id)
                if heartbeat is None:
                    raise KeyError(canonical_id)
                heartbeats = {canonical_id: deepcopy(heartbeat)}
            return {
                "sequence_number": self._state.sequence_number,
                "timestamp": self._state.timestamp,
                "heartbeats": heartbeats,
            }

    def record_heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        heartbeat = _validate_heartbeat(payload)
        satellite_id = _canonical_satellite_id(heartbeat["id"])
        received_at = _utc_now()
        record = deepcopy(heartbeat)
        record["received_at"] = received_at

        with self._lock:
            if not self._active:
                raise RuntimeError("Il Controller è arrestato")
            if self._quiesced:
                raise RuntimeError("Il Controller è in quiescenza")
            self._state.heartbeats[satellite_id] = record
            self._update_topology(satellite_id, record)
            self._rebuild_routing_table()
            self._touch()
            return deepcopy(record)

    def checkpoint(self) -> dict[str, Any]:
        """Serializza lo stato corrente e lo salva atomicamente su disco."""

        with self._lock:
            serialized = self._state.to_json()
            state = self._state.to_dict()
            self._checkpoint_repository.save(serialized)
        return state

    def restore(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Ripristina uno stato dal corpo JSON oppure dall'ultimo file salvato."""

        defer_activation = bool(payload.get("defer_activation", False)) if payload else False
        if payload is None:
            restored = ControllerState.from_json(self._checkpoint_repository.load())
        else:
            checkpoint = payload.get("checkpoint", payload)
            restored = ControllerState.from_dict(checkpoint)

        with self._lock:
            self._state = restored
            self._active = not defer_activation
            self._quiesced = False
            return self._state.to_dict()

    def quiesce(self) -> dict[str, Any]:
        """Blocca nuove mutazioni mantenendo leggibile lo stato corrente."""

        with self._lock:
            if not self._active:
                raise RuntimeError("Il Controller è arrestato")
            changed = not self._quiesced
            self._quiesced = True
            return {
                "status": "quiesced",
                "changed": changed,
                "sequence_number": self._state.sequence_number,
                "timestamp": self._state.timestamp,
            }

    def resume(self) -> dict[str, Any]:
        """Riapre le mutazioni, usato anche dal rollback della Hot Migration."""

        with self._lock:
            if not self._active:
                raise RuntimeError("Il Controller è arrestato")
            changed = self._quiesced
            self._quiesced = False
            return {
                "status": "active",
                "changed": changed,
                "sequence_number": self._state.sequence_number,
                "timestamp": self._state.timestamp,
            }

    def shutdown(self) -> dict[str, Any]:
        """Salva lo stato e disattiva le operazioni mutabili del Controller."""

        checkpoint = self.checkpoint()
        with self._lock:
            changed = self._active
            self._active = False
            self._quiesced = False
        return {
            "status": "shutdown",
            "changed": changed,
            "checkpoint_path": str(self.checkpoint_path),
            "sequence_number": checkpoint["sequence_number"],
            "timestamp": checkpoint["timestamp"],
        }

    def _update_topology(self, satellite_id: str, heartbeat: dict[str, Any]) -> None:
        nodes = self._state.topology.setdefault("nodes", {})
        neighbor_ids = heartbeat.get("neighbor_ids")
        if neighbor_ids is not None:
            normalized_neighbors = sorted(
                {
                    _canonical_satellite_id(neighbor)
                    for neighbor in neighbor_ids
                    if _canonical_satellite_id(neighbor) != satellite_id
                }
            )
        else:
            normalized_neighbors = nodes.get(satellite_id, {}).get("neighbor_ids", [])

        nodes[satellite_id] = {
            "online": True,
            "last_seen": heartbeat["received_at"],
            "neighbors": heartbeat["neighbors"],
            "neighbor_ids": normalized_neighbors,
            "controller": heartbeat["controller"],
        }

        links: set[tuple[str, str]] = set()
        for source, node in nodes.items():
            for target in node.get("neighbor_ids", []):
                links.add(tuple(sorted((source, target))))
        self._state.topology["links"] = [
            {"source": source, "target": target}
            for source, target in sorted(links)
        ]

    def _rebuild_routing_table(self) -> None:
        nodes = self._state.topology.get("nodes", {})
        adjacency: dict[str, set[str]] = {node: set() for node in nodes}
        for link in self._state.topology.get("links", []):
            source, target = link["source"], link["target"]
            adjacency.setdefault(source, set()).add(target)
            adjacency.setdefault(target, set()).add(source)

        self._state.routing_table = {
            source: _routes_from(source, adjacency) for source in sorted(adjacency)
        }

    def _touch(self) -> None:
        self._state.sequence_number += 1
        self._state.timestamp = _utc_now()


def _validate_heartbeat(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ControllerStateError("L'heartbeat deve essere un oggetto JSON")
    required = {"id", "time_to_eclipse", "neighbors", "cpu", "controller"}
    missing = required - payload.keys()
    if missing:
        raise ControllerStateError(
            "Campi heartbeat mancanti: " + ", ".join(sorted(missing))
        )
    if isinstance(payload["id"], bool) or not isinstance(payload["id"], (int, str)):
        raise ControllerStateError("id deve essere un numero o una stringa")
    if (
        isinstance(payload["neighbors"], bool)
        or not isinstance(payload["neighbors"], int)
        or payload["neighbors"] < 0
    ):
        raise ControllerStateError("neighbors deve essere un intero non negativo")
    if not isinstance(payload["controller"], bool):
        raise ControllerStateError("controller deve essere booleano")
    if payload["time_to_eclipse"] is not None and not isinstance(
        payload["time_to_eclipse"], (int, float)
    ):
        raise ControllerStateError("time_to_eclipse deve essere numerico o null")
    if isinstance(payload["cpu"], bool) or not isinstance(payload["cpu"], (int, float)):
        raise ControllerStateError("cpu deve essere numerico")
    if not 0 <= float(payload["cpu"]) <= 100:
        raise ControllerStateError("cpu deve essere compreso tra 0 e 100")
    if "neighbor_ids" in payload:
        if not isinstance(payload["neighbor_ids"], list):
            raise ControllerStateError("neighbor_ids deve essere un array")
        if any(not isinstance(value, (int, str)) for value in payload["neighbor_ids"]):
            raise ControllerStateError("neighbor_ids contiene un identificatore non valido")
    return deepcopy(payload)


def _canonical_satellite_id(value: int | str) -> str:
    text = str(value).strip().upper()
    if not text:
        raise ControllerStateError("Identificatore satellite vuoto")
    return text if text.startswith("SAT-") else f"SAT-{text}"


def _routes_from(
    source: str, adjacency: dict[str, set[str]]
) -> dict[str, dict[str, Any]]:
    routes: dict[str, dict[str, Any]] = {}
    queue: deque[tuple[str, str, int]] = deque(
        (neighbor, neighbor, 1) for neighbor in sorted(adjacency.get(source, set()))
    )
    visited = {source}
    while queue:
        node, first_hop, hops = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        routes[node] = {"next_hop": first_hop, "hops": hops}
        for neighbor in sorted(adjacency.get(node, set())):
            if neighbor not in visited:
                queue.append((neighbor, first_hop, hops + 1))
    return routes


def _validate_timestamp(value: Any) -> None:
    if not isinstance(value, str):
        raise ControllerStateError("timestamp deve essere una stringa ISO-8601")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ControllerStateError("timestamp non è un valore ISO-8601 valido") from exc
    if parsed.tzinfo is None:
        raise ControllerStateError("timestamp deve includere il fuso orario")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _validate_host_satellite_id(value: Any) -> str:
    if not isinstance(value, str):
        raise ControllerStateError("satellite_id deve essere una stringa")
    normalized = value.strip().upper()
    if normalized == "UNASSIGNED":
        return normalized
    if not normalized.startswith("SAT-") or not normalized[4:].isdigit():
        raise ControllerStateError("satellite_id deve avere formato SAT-N")
    return normalized
