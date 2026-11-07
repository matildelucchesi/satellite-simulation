"""Read a frozen CelesTrak TLE catalogue with checksum validation and plane normalisation."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
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
