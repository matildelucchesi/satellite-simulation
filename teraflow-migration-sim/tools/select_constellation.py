#!/usr/bin/env python3
"""Select a reproducible two-plane sample from a frozen CelesTrak TLE.

This is a screening/selection utility, not an orbital propagator. TLE mean
motion is used only to screen for the nominal 53-degree, ~550 km shell. The
chosen records are subsequently propagated with SGP4 by the simulator.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from sgp4.api import Satrec

EARTH_MU_KM3_S2 = 398600.4418
EARTH_EQUATORIAL_RADIUS_KM = 6378.137


@dataclass(frozen=True)
class Candidate:
    name: str
    norad_id: int
    inclination_deg: float
    raan_deg: float
    eccentricity: float
    mean_motion_rev_day: float
    screening_altitude_km: float
    mean_anomaly_rad_at_epoch: float
    mean_motion_rad_min: float
    epoch_jd: float
    epoch_jd_fraction: float
    raan_element_deg: float
    tle_line1: str
    tle_line2: str


def checksum_ok(line: str) -> bool:
    if len(line) < 69 or line[68].isdigit() is False:
        return False
    total = sum(int(c) for c in line[:68] if c.isdigit())
    total += line[:68].count("-")
    return total % 10 == int(line[68])


def parse_tle(path: Path) -> list[Candidate]:
    lines = path.read_text(encoding="ascii").splitlines()
    candidates: list[Candidate] = []
    i = 0
    while i < len(lines):
        if not lines[i].startswith("1 "):
            i += 1
            continue
        if i + 1 >= len(lines) or not lines[i + 1].startswith("2 "):
            raise ValueError(f"Unpaired TLE line 1 at {path}:{i + 1}")
        l1, l2 = lines[i], lines[i + 1]
        name = lines[i - 1].strip() if i > 0 and not lines[i - 1].startswith(("1 ", "2 ")) else "UNKNOWN"
        if not checksum_ok(l1) or not checksum_ok(l2):
            raise ValueError(f"Invalid TLE checksum for {name!r} at {path}:{i + 1}")
        sat = Satrec.twoline2rv(l1, l2)
        inclination = math.degrees(sat.inclo)
        raan = math.degrees(sat.nodeo) % 360.0
        n_rev_day = sat.no_kozai * 1440.0 / (2.0 * math.pi)
        candidates.append(
            Candidate(
                name=name,
                norad_id=sat.satnum,
                inclination_deg=inclination,
                raan_deg=raan,
                eccentricity=sat.ecco,
                mean_motion_rev_day=n_rev_day,
                screening_altitude_km=sat.a * EARTH_EQUATORIAL_RADIUS_KM - EARTH_EQUATORIAL_RADIUS_KM,
                mean_anomaly_rad_at_epoch=sat.mo,
                mean_motion_rad_min=sat.no_kozai,
                epoch_jd=sat.jdsatepoch,
                epoch_jd_fraction=sat.jdsatepochF,
                raan_element_deg=raan,
                tle_line1=l1,
                tle_line2=l2,
            )
        )
        i += 2
    # Normalize orbital plane elements to one epoch. Raw RAAN values from TLEs
    # with different epochs can differ due to nodal precession and should not
    # be clustered as if they were simultaneous measurements.
    reference = max(candidates, key=lambda c: c.epoch_jd + c.epoch_jd_fraction)
    normalized = []
    for candidate in candidates:
        sat = Satrec.twoline2rv(candidate.tle_line1, candidate.tle_line2)
        error, position, velocity = sat.sgp4(reference.epoch_jd, reference.epoch_jd_fraction)
        if error:
            raise ValueError(f"SGP4 error {error} while normalizing plane for NORAD {candidate.norad_id}")
        hx = position[1] * velocity[2] - position[2] * velocity[1]
        hy = position[2] * velocity[0] - position[0] * velocity[2]
        hz = position[0] * velocity[1] - position[1] * velocity[0]
        hnorm = math.sqrt(hx * hx + hy * hy + hz * hz)
        inclination = math.degrees(math.acos(max(-1.0, min(1.0, hz / hnorm))))
        normalized.append(replace(candidate, inclination_deg=inclination,
                                  raan_deg=math.degrees(math.atan2(hx, -hy)) % 360.0))
    return normalized


def phase_at(candidate: Candidate, jd: float, fraction: float) -> float:
    delta_minutes = ((jd - candidate.epoch_jd) + (fraction - candidate.epoch_jd_fraction)) * 1440.0
    return (candidate.mean_anomaly_rad_at_epoch + candidate.mean_motion_rad_min * delta_minutes) % (2.0 * math.pi)


def phase_distributed(candidates: list[Candidate], count: int, jd: float, fraction: float) -> list[Candidate]:
    """Choose a reproducible subset spread in orbital phase; retain all if requested."""
    if len(candidates) < count:
        raise ValueError(f"Selected RAAN group has {len(candidates)} records; {count} requested")
    if count == len(candidates):
        return sorted(candidates, key=lambda c: phase_at(c, jd, fraction))
    best: tuple[float, tuple[int, ...]] | None = None
    target = 2.0 * math.pi / count
    phased = [(phase_at(c, jd, fraction), c) for c in candidates]
    for combo in itertools.combinations(phased, count):
        angles = sorted(x[0] for x in combo)
        gaps = [angles[(i + 1) % count] - angles[i] for i in range(count - 1)]
        gaps.append(angles[0] + 2.0 * math.pi - angles[-1])
        score = sum((gap - target) ** 2 for gap in gaps)
        ids = tuple(sorted(x[1].norad_id for x in combo))
        value = (score, ids)
        if best is None or value < best:
            best = value
            selected = [x[1] for x in combo]
    return sorted(selected, key=lambda c: phase_at(c, jd, fraction))


def select(
    candidates: list[Candidate],
    inclination_min: float,
    inclination_max: float,
    altitude_min: float,
    altitude_max: float,
    raan_bin_width: float,
    min_plane_separation: float,
    max_plane_separation: float,
    count_per_plane: int | None,
) -> tuple[list[dict], dict]:
    screened = [
        c for c in candidates
        if inclination_min <= c.inclination_deg <= inclination_max
        and altitude_min <= c.screening_altitude_km <= altitude_max
    ]
    ordered = sorted(screened, key=lambda c: c.raan_deg)
    clusters: list[list[Candidate]] = []
    for index, candidate in enumerate(ordered):
        gap = (candidate.raan_deg - ordered[index - 1].raan_deg) % 360.0 if index else 360.0
        if not clusters or gap > raan_bin_width:
            clusters.append([candidate])
        else:
            clusters[-1].append(candidate)
    if len(clusters) > 1:
        wrap_gap = (clusters[0][0].raan_deg + 360.0 - clusters[-1][-1].raan_deg) % 360.0
        if wrap_gap <= raan_bin_width:
            clusters[0] = clusters[-1] + clusters[0]
            clusters.pop()
    groups = []
    for rows in clusters:
        mean_x = sum(math.cos(math.radians(c.raan_deg)) for c in rows)
        mean_y = sum(math.sin(math.radians(c.raan_deg)) for c in rows)
        center = math.degrees(math.atan2(mean_y, mean_x)) % 360.0
        groups.append((center, rows))
    groups.sort(key=lambda pair: (-len(pair[1]), pair[0]))
    minimum_group_size = count_per_plane or 1
    eligible = [(center, rows) for center, rows in groups if len(rows) >= minimum_group_size]
    pair_options = []
    for first, second in itertools.combinations(eligible, 2):
        delta = abs((first[0] - second[0] + 180.0) % 360.0 - 180.0)
        if min_plane_separation <= delta <= max_plane_separation:
            # Favor groups that contain enough choices, then deterministic RAAN order.
            pair_options.append((-(len(first[1]) + len(second[1])), first[0], second[0], first, second))
    if not pair_options:
        raise ValueError(
            "No two RAAN bins satisfy the current shell filter and minimum group size; "
            "adjust screening tolerances and document the change."
        )
    _, _, _, first, second = min(pair_options)
    reference = max(candidates, key=lambda c: c.epoch_jd + c.epoch_jd_fraction)
    reference_jd, reference_fraction = reference.epoch_jd, reference.epoch_jd_fraction
    selected = []
    selected_candidates = []
    for plane_index, (center, rows) in enumerate(sorted((first, second), key=lambda x: x[0]), start=1):
        take = len(rows) if count_per_plane is None else count_per_plane
        for rank, c in enumerate(phase_distributed(rows, take, reference_jd, reference_fraction), start=1):
            selected_candidates.append(c)
            cdata = asdict(c)
            cdata.pop("tle_line1")
            cdata.pop("tle_line2")
            selected.append({
                "plane": plane_index,
                "phase_rank": rank,
                **cdata,
                "mean_anomaly_rad_at_reference": phase_at(c, reference_jd, reference_fraction),
                "tle_age_hours_at_reference": ((reference_jd + reference_fraction)
                                                - (c.epoch_jd + c.epoch_jd_fraction)) * 24.0,
            })
    metadata = {
        "catalog_count": len(candidates),
        "screened_count": len(screened),
        "screen": {
            "inclination_deg": [inclination_min, inclination_max],
            "screening_altitude_km": [altitude_min, altitude_max],
        "raan_cluster_gap_deg": raan_bin_width,
        "minimum_plane_separation_deg": min_plane_separation,
        "maximum_plane_separation_deg": max_plane_separation,
        },
        "raan_groups": [
            {"center_deg": center, "count": len(rows)}
            for center, rows in sorted(groups, key=lambda pair: pair[0])
        ],
        "selected_plane_raan_centers_deg": sorted([first[0], second[0]]),
        "selected_plane_satellite_counts": [len(rows) if count_per_plane is None else count_per_plane
                                            for _, rows in sorted((first, second), key=lambda x: x[0])],
        "reference_epoch": {
            "jd": reference_jd,
            "fraction": reference_fraction,
            "iso_utc": datetime.fromtimestamp(
                ((reference_jd + reference_fraction) - 2440587.5) * 86400.0,
                tz=timezone.utc,
            ).isoformat(),
        },
        "selected_tle_age_hours": {
            "minimum": min((((reference_jd + reference_fraction)
                              - (c.epoch_jd + c.epoch_jd_fraction)) * 24.0) for c in selected_candidates),
            "maximum": max((((reference_jd + reference_fraction)
                              - (c.epoch_jd + c.epoch_jd_fraction)) * 24.0) for c in selected_candidates),
        },
    }
    return selected, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tle", type=Path, default=Path(__file__).parents[1] / "data" / "starlink_2026-10-01.tle")
    parser.add_argument("--output", type=Path, default=Path(__file__).parents[1] / "config" / "selected_constellation.json")
    parser.add_argument("--inc-min", type=float, default=52.5)
    parser.add_argument("--inc-max", type=float, default=53.5)
    parser.add_argument("--alt-min-km", type=float, default=520.0)
    parser.add_argument("--alt-max-km", type=float, default=580.0)
    parser.add_argument("--raan-cluster-gap-deg", type=float, default=1.5)
    parser.add_argument("--min-plane-separation-deg", type=float, default=10.0)
    parser.add_argument("--max-plane-separation-deg", type=float, default=30.0)
    parser.add_argument("--count-per-plane", type=int, default=None,
                        help="fixed count for both selected planes; default: use all screened candidates in each")
    args = parser.parse_args()
    candidates = parse_tle(args.tle)
    selected, metadata = select(
        candidates, args.inc_min, args.inc_max, args.alt_min_km, args.alt_max_km,
        args.raan_cluster_gap_deg, args.min_plane_separation_deg,
        args.max_plane_separation_deg, args.count_per_plane,
    )
    result = {"metadata": metadata, "satellites": selected}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "metadata": metadata,
                      "selected": [{"plane": x["plane"], "norad_id": x["norad_id"],
                                    "name": x["name"], "raan_deg": x["raan_deg"],
                                    "screening_altitude_km": x["screening_altitude_km"]}
                                   for x in selected]}, indent=2))


if __name__ == "__main__":
    main()
