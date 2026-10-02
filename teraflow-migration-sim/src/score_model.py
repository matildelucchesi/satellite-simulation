"""Transparent next-controller eligibility and score calculation."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CandidateMetrics:
    satellite_id: int
    control_latency_ms: float
    reachable_nodes: int
    total_nodes: int
    time_to_control_outage_s: float
    horizon_s: float
    cpu_free_after_placement: float
    ram_free_after_placement: float
    disk_free_after_placement: float
    fso_distance_km: float


WEIGHTS = {"latency": 0.35, "connectivity": 0.30, "continuity": 0.20, "resources": 0.15}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def score_candidates(
    candidates: list[CandidateMetrics],
    reserve_fraction: float = 0.20,
) -> list[dict]:
    """Score eligible candidates, returning descending score with deterministic tie-breaks.

    Latency utility is normalized within the eligible candidate set for the same
    event. Connectivity is reachable nodes / modeled nodes. Continuity is the
    fraction of the common forecast horizon until a predicted control outage.
    Resource utility is the weakest CPU/RAM/disk headroom above the reserve,
    normalized to [0, 1].
    """
    if not 0 <= reserve_fraction < 1:
        raise ValueError("reserve_fraction must be in [0, 1)")
    eligible = []
    for candidate in candidates:
        if candidate.control_latency_ms < 0 or candidate.fso_distance_km < 0:
            raise ValueError("latency and distance must be non-negative")
        if candidate.total_nodes <= 0 or not 0 <= candidate.reachable_nodes <= candidate.total_nodes:
            raise ValueError("reachable_nodes must be between 0 and a positive total_nodes")
        if candidate.horizon_s <= 0:
            raise ValueError("horizon_s must be positive")
        free = (candidate.cpu_free_after_placement, candidate.ram_free_after_placement,
                candidate.disk_free_after_placement)
        if any(not 0 <= value <= 1 for value in free):
            raise ValueError("post-placement free-resource fractions must be in [0, 1]")
        if candidate.reachable_nodes == 0 or any(value < reserve_fraction for value in free):
            continue
        eligible.append(candidate)
    if not eligible:
        return []

    min_latency = min(c.control_latency_ms for c in eligible)
    max_latency = max(c.control_latency_ms for c in eligible)
    scored = []
    for candidate in eligible:
        if max_latency == min_latency:
            u_latency = 1.0
        else:
            u_latency = 1.0 - (candidate.control_latency_ms - min_latency) / (max_latency - min_latency)
        u_connectivity = candidate.reachable_nodes / candidate.total_nodes
        u_continuity = _clamp01(candidate.time_to_control_outage_s / candidate.horizon_s)
        u_resources = _clamp01(min(
            (candidate.cpu_free_after_placement - reserve_fraction) / (1 - reserve_fraction),
            (candidate.ram_free_after_placement - reserve_fraction) / (1 - reserve_fraction),
            (candidate.disk_free_after_placement - reserve_fraction) / (1 - reserve_fraction),
        ))
        score = 100.0 * (
            WEIGHTS["latency"] * u_latency
            + WEIGHTS["connectivity"] * u_connectivity
            + WEIGHTS["continuity"] * u_continuity
            + WEIGHTS["resources"] * u_resources
        )
        scored.append({
            "satellite_id": candidate.satellite_id,
            "score": score,
            "utilities": {"latency": u_latency, "connectivity": u_connectivity,
                          "continuity": u_continuity, "resources": u_resources},
            "metrics": asdict(candidate),
        })
    return sorted(scored, key=lambda row: (-row["score"], row["metrics"]["fso_distance_km"], row["satellite_id"]))
