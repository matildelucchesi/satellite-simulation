"""Trova un sottoinsieme Starlink illuminato e connesso per una demo ripetibile."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import combinations
from urllib.request import urlopen

import numpy as np
from skyfield.api import EarthSatellite, Loader
from skyfield_data import get_skyfield_data_path


TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?INTDES=2022-175&FORMAT=tle"
START = datetime(2026, 7, 21, tzinfo=timezone.utc)
STEP_SECONDS = 5
MAX_DISTANCE_KM = 5_500.0
EARTH_RADIUS_KM = 6_378.137
SATELLITE_COUNT = 7


def main() -> None:
    lines = [
        line.strip()
        for line in urlopen(TLE_URL, timeout=30).read().decode().splitlines()
        if line.strip()
    ]
    records = [tuple(lines[index : index + 3]) for index in range(0, len(lines), 3)]
    loader = Loader(get_skyfield_data_path(), expire=False)
    timescale = loader.timescale(builtin=True)
    ephemeris = loader("de421.bsp")
    satellites = [EarthSatellite(line1, line2, name, timescale) for name, line1, line2 in records]
    sample_count = 24 * 60 * 60 // STEP_SECONDS
    datetimes = [START + timedelta(seconds=index * STEP_SECONDS) for index in range(sample_count)]
    times = timescale.from_datetimes(datetimes)
    illumination = np.vstack([satellite.at(times).is_sunlit(ephemeris) for satellite in satellites])

    for time_index in range(sample_count):
        remaining = [_remaining_seconds(row, time_index) for row in illumination]
        controller_candidates = [
            index for index, seconds in enumerate(remaining) if 120 < seconds <= 125
        ]
        if not controller_candidates:
            continue
        eligible = [
            index
            for index, seconds in enumerate(remaining)
            if illumination[index, time_index] and seconds > 120
        ]
        if len(eligible) < SATELLITE_COUNT:
            continue
        positions = {
            index: satellites[index].at(times[time_index]).position.km
            for index in eligible
        }
        adjacency = _adjacency(eligible, positions)
        for controller in controller_candidates:
            component = _component(controller, adjacency)
            if len(component) < SATELLITE_COUNT or len(adjacency[controller]) < 2:
                continue
            ranked = sorted(
                component - {controller},
                key=lambda item: (-len(adjacency[item] & component), item),
            )[:18]
            best_selection = None
            best_visual_separation = -1.0
            best_minimum_distance = -1.0
            for others in combinations(ranked, SATELLITE_COUNT - 1):
                selected = (controller, *others)
                selected_set = set(selected)
                if min(len(adjacency[item] & selected_set) for item in selected) < 2:
                    continue
                if _component(controller, adjacency, selected_set) != selected_set:
                    continue
                minimum_distance = min(
                    float(np.linalg.norm(positions[source] - positions[target]))
                    for source, target in combinations(selected, 2)
                )
                visual_separation = min(
                    float(
                        np.linalg.norm(
                            _visual_point(positions[source])
                            - _visual_point(positions[target])
                        )
                    )
                    for source, target in combinations(selected, 2)
                )
                if visual_separation > best_visual_separation:
                    best_visual_separation = visual_separation
                    best_minimum_distance = minimum_distance
                    best_selection = selected
            if best_selection is not None:
                selected_set = set(best_selection)
                ordered = [controller, *sorted(selected_set - {controller})]
                print(f"simulation_start_at={datetimes[time_index].isoformat()}")
                print(f"controller_seconds={remaining[controller]}")
                print(f"minimum_distance_km={best_minimum_distance:.1f}")
                print(f"minimum_visual_separation_px={best_visual_separation:.1f}")
                print(f"physical_links={sum(len(adjacency[item] & selected_set) for item in selected_set) // 2}")
                for number, index in enumerate(ordered, 1):
                    print(f"SAT-{number}: remaining={remaining[index]} s")
                    print("\n".join(records[index]))
                ephemeris.close()
                return
    ephemeris.close()
    raise SystemExit("Nessuna configurazione trovata")


def _remaining_seconds(row: np.ndarray, start: int) -> int:
    if not row[start]:
        return 0
    future_shadow = np.flatnonzero(~row[start:])
    return int(future_shadow[0] * STEP_SECONDS) if len(future_shadow) else 999_999


def _adjacency(nodes: list[int], positions: dict[int, np.ndarray]) -> dict[int, set[int]]:
    result = {node: set() for node in nodes}
    for offset, source in enumerate(nodes):
        for target in nodes[offset + 1 :]:
            if _contact(positions[source], positions[target]):
                result[source].add(target)
                result[target].add(source)
    return result


def _contact(source: np.ndarray, target: np.ndarray) -> bool:
    segment = target - source
    distance = float(np.linalg.norm(segment))
    if distance > MAX_DISTANCE_KM:
        return False
    denominator = float(np.dot(segment, segment))
    fraction = float(np.clip(-np.dot(source, segment) / denominator, 0.0, 1.0))
    closest = source + fraction * segment
    return float(np.linalg.norm(closest)) > EARTH_RADIUS_KM


def _visual_point(position: np.ndarray) -> np.ndarray:
    angle = float(np.arctan2(position[1], position[0]))
    return np.array([500 + np.cos(angle) * 270, 220 - np.sin(angle) * 155])


def _component(
    start: int,
    adjacency: dict[int, set[int]],
    allowed: set[int] | None = None,
) -> set[int]:
    allowed = allowed or set(adjacency)
    visited = {start}
    pending = [start]
    while pending:
        current = pending.pop()
        for neighbor in (adjacency[current] & allowed) - visited:
            visited.add(neighbor)
            pending.append(neighbor)
    return visited


if __name__ == "__main__":
    main()
