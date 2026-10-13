"""One first trigger per sunlight interval/source; unusable events remain visible."""
from __future__ import annotations

import math
from dataclasses import asdict
from .orbit import shortest_paths
from .resource_model import resource_trigger
from .score_model import CandidateMetrics, score_candidates


def operational_periods(eclipsed):
    start = None
    for index, shadow in enumerate(eclipsed):
        if not shadow and start is None: start = index
        if shadow and start is not None:
            yield start, index
            start = None
    if start is not None: yield start, len(eclipsed)


def generate_events(orbit, scenario, horizon_s, measured_resources):
    if horizon_s <= 0:
        raise ValueError("Calibrated H must be positive")
    profile = scenario["controller"]["resource_profile"]
    reserve = scenario["controller"]["resource_reserve_fraction"]
    free_cpu = 1 - 0.40 - measured_resources["cpu_cores"] / profile["cpu_cores"]
    free_ram = 1 - 0.45 - measured_resources["ram_gib"] / profile["ram_gib"]
    free_disk = 1 - measured_resources["disk_gib"] / profile["disk_gib"]
    events = []
    for sid in orbit.ids:
        for start, end in operational_periods(orbit.eclipsed[:, orbit.index[sid]]):
            trigger = None
            causes = []
            for tick in range(start, end):
                resource = resource_trigger(tick-start, horizon_s,
                    threshold_percent=scenario["controller"]["resource_trigger_fraction"]*100,
                    persistence_s=scenario["controller"]["resource_persistence_s"])
                # Observation boundary is censoring, not an invented eclipse.
                eclipse = end < orbit.duration and end-tick <= horizon_s
                if resource or eclipse:
                    trigger = tick
                    causes = (["resources"] if resource else []) + (["eclipse"] if eclipse else [])
                    break
            if trigger is None: continue
            graph = orbit.graph(trigger)
            candidates, excluded = [], []
            for candidate, distance in graph[sid].items():
                reason = None
                if not all(math.isfinite(value) for value in (distance,free_cpu,free_ram,free_disk)):
                    reason = "missing_or_nonfinite_required_metric"
                elif not orbit.operational(candidate, trigger): reason = "destination_in_shadow"
                elif min(free_cpu, free_ram, free_disk) < reserve: reason = "resource_reserve"
                if reason:
                    excluded.append({"sat_b": candidate, "reason": reason})
                    continue
                paths = shortest_paths(graph, candidate)
                continuity = horizon_s
                for future in range(trigger+1, min(orbit.duration, trigger+math.ceil(horizon_s)+1)):
                    if (not orbit.operational(candidate, future) or
                            not set(paths).issubset(shortest_paths(orbit.graph(future), candidate))):
                        continuity = future-trigger
                        break
                candidates.append(CandidateMetrics(candidate,
                    sum(paths.values()) / len(paths) * 2 / 299792.458 * 1000,
                    len(paths), len(orbit.ids), continuity, horizon_s,
                    free_cpu, free_ram, free_disk, distance))
            ranked = score_candidates(candidates, reserve, scenario["score"]["weights"])
            event = {"event_id": f"{sid}-{start}-{trigger}", "sat_a": sid, "trigger_s": trigger,
                     "period_start_s": start, "deadline_s": end, "deadline_censored": end == orbit.duration,
                     "horizon_s": horizon_s, "trigger_causes": causes, "candidates": ranked,
                     "excluded_candidates": excluded, "migrable": bool(ranked),
                     "service_path_available": 53913 in shortest_paths(graph, 53848)}
            if ranked:
                destination = ranked[0]["satellite_id"]
                contact_end = trigger
                while contact_end < orbit.duration and orbit.contact(sid, destination, contact_end):
                    contact_end += 1
                event.update(sat_b=destination, contact_window_s=contact_end-trigger,
                             deadline_window_s=end-trigger, contact_end_s=contact_end,
                             orbital_margin_s=min(contact_end, end)-trigger-scenario["fso"]["alignment_s"])
            events.append(event)
    return sorted(events, key=lambda row: (row["trigger_s"], row["sat_a"]))
