"""Frozen SGP4/TEME positions and offline solar eclipse geometry."""
from __future__ import annotations

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


def generate(root: Path, destination: Path):
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
    scenario = json.loads((root / "config/scenario.json").read_text())
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
                "scenario_sha256": file_digest(root / "config/scenario.json"),
                "tle_sha256": file_digest(root / scenario["orbital"]["tle_file"])}
    destination.with_suffix(".json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


class Orbit:
    def __init__(self, artifact: Path, max_range_km=1700, earth_radius_km=6378.137):
        import numpy as np
        arrays = np.load(artifact, allow_pickle=False)
        self.ids = [int(value) for value in arrays["ids"]]
        self.positions = arrays["positions"]
        self.eclipsed = arrays["eclipsed"]
        self.duration = len(self.positions)
        self.max_range = max_range_km
        self.radius = earth_radius_km
        self.index = {sid: index for index, sid in enumerate(self.ids)}

    def graph(self, elapsed_s: float):
        return self._graph(int(elapsed_s))

    @lru_cache(maxsize=8192)
    def _graph(self, index):
        import numpy as np
        if not 0 <= index < self.duration:
            raise ValueError("Orbital replay time outside frozen observation")
        points = self.positions[index]
        edges = {sid: {} for sid in self.ids}
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

    def operational(self, sid, elapsed_s):
        return 0 <= int(elapsed_s) < self.duration and not bool(self.eclipsed[int(elapsed_s), self.index[sid]])


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
