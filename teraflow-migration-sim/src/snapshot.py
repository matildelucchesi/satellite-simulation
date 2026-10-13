"""Canonical state, explicit perimeters, and versioned hot migration deltas."""
from __future__ import annotations

import copy
from .artifacts import SOURCE_COMMIT, canonical_bytes

KINDS = ("contexts", "devices", "links", "topologies", "services", "connections")
ID_KEYS = {"contexts": "context_id", "devices": "device_id", "links": "link_id",
           "topologies": "topology_id", "services": "service_id", "connections": "connection_id"}


def identity(kind: str, item: dict) -> str:
    return canonical_bytes(item[ID_KEYS[kind]]).decode()


def normalize(value):
    if isinstance(value, dict):
        result = {key: normalize(item) for key, item in sorted(value.items())}
        # These fields are sets in the Release 7 context schema. Path hops and
        # ordered service endpoints retain their original order.
        for key in ("config_rules", "device_ids", "link_ids", "optical_link_ids", "device_endpoints"):
            if isinstance(result.get(key), list): result[key].sort(key=canonical_bytes)
        return result
    if isinstance(value, list):
        # Ordered paths in connections must retain their order.
        return [normalize(item) for item in value]
    return value


def snapshot(entities: dict) -> dict:
    result = {"schema_version": 1, "source_commit": SOURCE_COMMIT, "entities": {}}
    for kind in KINDS:
        rows = entities.get(kind, [])
        indexed = {identity(kind, row): normalize(row) for row in rows}
        if len(indexed) != len(rows):
            raise ValueError(f"Duplicate {kind} IDs")
        result["entities"][kind] = [indexed[key] for key in sorted(indexed)]
    return result


def validate(document: dict) -> None:
    if document.get("schema_version") != 1 or document.get("source_commit") != SOURCE_COMMIT:
        raise ValueError("Snapshot version/source mismatch")
    if set(document.get("entities", {})) != set(KINDS):
        raise ValueError("Snapshot entity perimeter mismatch")
    snapshot(document["entities"])


def delta(initial: dict, final: dict) -> dict:
    validate(initial)
    validate(final)
    changes = {}
    for kind in KINDS:
        before = {identity(kind, row): row for row in initial["entities"][kind]}
        after = {identity(kind, row): row for row in final["entities"][kind]}
        changes[kind] = {
            "upserts": [after[key] for key in sorted(after) if before.get(key) != after[key]],
            "deletes": [before[key][ID_KEYS[kind]] for key in sorted(before.keys() - after.keys())],
        }
    return {"schema_version": 1, "source_commit": SOURCE_COMMIT, "changes": changes}


def apply_delta(initial: dict, changes: dict) -> dict:
    validate(initial)
    if changes.get("schema_version") != 1 or changes.get("source_commit") != SOURCE_COMMIT:
        raise ValueError("Delta version/source mismatch")
    if set(changes.get("changes", {})) != set(KINDS):
        raise ValueError("Delta perimeter mismatch")
    entities = copy.deepcopy(initial["entities"])
    for kind in KINDS:
        indexed = {identity(kind, row): row for row in entities[kind]}
        for identifier in changes["changes"][kind]["deletes"]:
            indexed.pop(canonical_bytes(identifier).decode(), None)
        for row in changes["changes"][kind]["upserts"]:
            indexed[identity(kind, row)] = row
        entities[kind] = list(indexed.values())
    return snapshot(entities)
