"""Frozen SGP4/TEME positions and offline solar eclipse geometry."""
from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path


def cylindrical_eclipse(position, sun_direction, earth_radius_km=6378.137):
    norm = math.sqrt(sum(value * value for value in sun_direction))
    if norm == 0:
        raise ValueError("Sun direction must be nonzero")
    projection = sum(a * b / norm for a, b in zip(position, sun_direction))
    return projection < 0 and sum(value * value for value in position) - projection**2 <= earth_radius_km**2


def generate(root: Path, destination: Path, scenario: dict | None = None, selection: dict | None = None):
    import astropy
    import numpy as np
    from astropy import units as u
    from astropy.coordinates import TEME, get_sun
    from astropy.time import Time
    from astropy.utils import iers
    from sgp4.api import Satrec, SatrecArray
    from .artifacts import describe, file_digest

    iers.conf.auto_download = False
    iers.conf.auto_max_age = None
    explicit_scenario = scenario is not None
    if scenario is None:
        scenario = json.loads((root / "config/scenario.json").read_text())
    if selection is None:
        selection = json.loads((root / "config/selected_constellation.json").read_text())
    ids = sorted(row["norad_id"] for row in selection["satellites"])
    lines = (root / scenario["orbital"]["tle_file"]).read_text().splitlines()
    pairs = {int(line[2:7]): (line, lines[index + 1]) for index, line in enumerate(lines[:-1]) if line.startswith("1 ")}
    satellites = SatrecArray([Satrec.twoline2rv(*pairs[sid]) for sid in ids])
    from datetime import datetime
    times = Time(datetime.fromisoformat(scenario["orbital"]["reference_epoch_utc"]), scale="utc")
    elapsed = np.arange(scenario["orbital"]["propagation_duration_s"], dtype=np.float64)
    times = times + elapsed * u.s
    errors, positions, _ = satellites.sgp4(np.asarray(times.jd1), np.asarray(times.jd2))
    if np.any(errors):
        raise ValueError("SGP4 errors prevent freezing orbital replay")
    positions = np.transpose(positions, (1, 0, 2))
    # Both vectors are geocentric TEME, never mix SGP4 TEME with raw GCRS.
    sun = get_sun(times).transform_to(TEME(obstime=times)).cartesian.xyz.to_value(u.km).T
    sun /= np.linalg.norm(sun, axis=1)[:, None]
    projection = np.sum(positions * sun[:, None, :], axis=2)
    eclipsed = (projection < 0) & ((positions**2).sum(axis=2) - projection**2 <= scenario["orbital"]["earth_radius_km"]**2)
    destination.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(destination, ids=np.array(ids), positions=positions, eclipsed=eclipsed)
    metadata = {"schema_version": 1, "artifact": describe(destination), "astropy": astropy.__version__,
                "numpy": np.__version__, "solar_ephemeris": "astropy-get_sun-built-in-ERFA",
                "frame": "TEME", "eclipse_model": "cylindrical-spherical-earth",
                "epoch_utc": scenario["orbital"]["reference_epoch_utc"],
                "scenario_sha256": (hashlib.sha256(json.dumps(scenario, sort_keys=True).encode()).hexdigest()
                                    if explicit_scenario else file_digest(root / "config/scenario.json")),
                "tle_sha256": file_digest(root / scenario["orbital"]["tle_file"])}
    destination.with_suffix(".json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


def load_orbit(root: Path, scenario: dict | None = None, artifact: Path | None = None):
    """Orbit for the installed scenario.

    A scenario with ``fso.laser_terminals`` uses the frozen three-laser link intervals in
    ``results/direct_link_windows.json`` and, when ``config/domain.json`` exists, exposes the
    laboratory domain through ``lab_graph``. Older scenarios keep the all-pairs range model."""
    root = Path(root)
    if scenario is None:
        scenario = json.loads((root / "config/scenario.json").read_text())
    artifact = artifact or root / "artifacts/orbit/replay.npz"
    fso = scenario.get("fso", {})
    if not fso.get("laser_terminals"):
        return Orbit(artifact)
    links = json.loads((root / "results/direct_link_windows.json").read_text())["windows"]
    domain_file = root / "config/domain.json"
    domain = None
    if domain_file.exists():
        document = json.loads(domain_file.read_text())
        domain = list(document["plane_1"]) + list(document["plane_2"])
    return Orbit(artifact, max_range_km=fso.get("max_range_km", 1700), links=links, domain=domain)


class Orbit:
    def __init__(self, artifact: Path, max_range_km=1700, earth_radius_km=6378.137, links=None, domain=None):
        import numpy as np
        arrays = np.load(artifact, allow_pickle=False)
        self.ids = [int(value) for value in arrays["ids"]]
        self.positions = arrays["positions"]
        self.eclipsed = arrays["eclipsed"]
        self.duration = len(self.positions)
        self.max_range = max_range_km
        self.radius = earth_radius_km
        self.index = {sid: index for index, sid in enumerate(self.ids)}
        # Laser model: usable link intervals [start_s, end_s); None keeps the range model.
        self.links = None if links is None else sorted(
            (int(row["start_s"]), int(row["end_s"]), int(row["sat_a"]), int(row["sat_b"])) for row in links)
        self.domain = None if domain is None else [int(sid) for sid in domain]
        if self.domain is not None and not set(self.domain) <= set(self.ids):
            raise ValueError("Domain satellites missing from the orbital replay")
        self.phase_changes = {
            sid: np.flatnonzero(self.eclipsed[1:, column] != self.eclipsed[:-1, column]) + 1
            for sid, column in self.index.items()
        }

    def illumination_window(self, sid, elapsed_s):
        """Current phase start and next transition in the frozen one-second ephemeris."""
        import bisect
        tick = int(elapsed_s)
        if not 0 <= tick < self.duration:
            raise ValueError("Orbital replay time outside frozen observation")
        changes = self.phase_changes[sid]
        upcoming = bisect.bisect_right(changes, tick)
        shadow_start = upcoming - 1 if bool(self.eclipsed[tick, self.index[sid]]) else upcoming
        shadow_end = shadow_start + 1
        shadow_duration = (int(changes[shadow_end] - changes[shadow_start])
                           if 0 <= shadow_start < shadow_end < len(changes) else None)
        return {
            'shadow_duration_s': shadow_duration,
            'phase_start_s': int(changes[upcoming - 1]) if upcoming else 0,
            'next_transition_s': int(changes[upcoming]) if upcoming < len(changes) else None,
        }

    def graph(self, elapsed_s: float):
        return self._graph(int(elapsed_s))

    @lru_cache(maxsize=8192)
    def _graph(self, index):
        import numpy as np
        if not 0 <= index < self.duration:
            raise ValueError("Orbital replay time outside frozen observation")
        points = self.positions[index]
        edges = {sid: {} for sid in self.ids}
        if getattr(self, 'links', None) is not None:
            for start, end, a, b in self.links:
                if start > index:
                    break
                if index < end:
                    difference = points[self.index[b]] - points[self.index[a]]
                    distance = math.sqrt(float(difference @ difference))
                    edges[a][b] = distance
                    edges[b][a] = distance
            return edges
        for ai, a in enumerate(self.ids):
            for bi in range(ai + 1, len(self.ids)):
                difference = points[bi] - points[ai]
                squared = float(difference @ difference)
                if squared == 0 or squared > self.max_range**2:
                    continue
                fraction = max(0.0, min(1.0, -float(points[ai] @ difference) / squared))
                nearest = points[ai] + fraction * difference
                if float(nearest @ nearest) <= self.radius**2:
                    continue
                distance = math.sqrt(squared)
                edges[a][self.ids[bi]] = distance
                edges[self.ids[bi]][a] = distance
        return edges

    def contact(self, a, b, elapsed_s):
        if not 0 <= int(elapsed_s) < self.duration:
            return False
        return b in self.graph(elapsed_s)[a]

    def lab_graph(self, elapsed_s: float):
        """Topology emulated in the laboratory: the domain's own links, or every link without a domain."""
        graph = self.graph(elapsed_s)
        if getattr(self, 'domain', None) is None:
            return graph
        members = set(self.domain)
        return {sid: {n: d for n, d in graph[sid].items() if n in members} for sid in self.domain}

    def migration_link(self, a, b, elapsed_s):
        """Whether the migration transfer can flow: multi-hop path with lasers, direct contact otherwise."""
        if not 0 <= int(elapsed_s) < self.duration:
            return False
        if getattr(self, 'links', None) is None:
            return self.contact(a, b, elapsed_s)
        return b in shortest_paths(self.graph(elapsed_s), a)

    def migration_path(self, a, b, elapsed_s):
        """Fewest-distance satellite path used by the transfer, or None."""
        graph = self.graph(elapsed_s)
        distances = shortest_paths(graph, b)
        if a not in distances:
            return None
        path, node = [a], a
        while node != b:
            node = min((length + distances[n], n) for n, length in graph[node].items() if n in distances)[1]
            path.append(node)
        return path

    def operational(self, sid, elapsed_s):
        return 0 <= int(elapsed_s) < self.duration and not bool(self.eclipsed[int(elapsed_s), self.index[sid]])


def lab_graph(orbit, elapsed_s):
    """Laboratory topology for any orbit-like object (test doubles may only provide ``graph``)."""
    method = getattr(orbit, 'lab_graph', None)
    return method(elapsed_s) if method else orbit.graph(elapsed_s)


def orbit_domain(orbit):
    return getattr(orbit, 'domain', None)


def shortest_paths(graph, source):
    import heapq
    distance = {source: 0.0}
    pending = [(0.0, source)]
    while pending:
        cost, node = heapq.heappop(pending)
        if cost != distance[node]: continue
        for neighbor, length in graph[node].items():
            candidate = cost + length
            if candidate < distance.get(neighbor, math.inf):
                distance[neighbor] = candidate
                heapq.heappush(pending, (candidate, neighbor))
    return distance
