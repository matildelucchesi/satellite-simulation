#!/usr/bin/env python3
"""Check whether the selected subset yields direct FSO contact windows."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

from sgp4.api import Satrec

EARTH_RADIUS_KM = 6378.137


def unobstructed(r1: tuple[float, float, float], r2: tuple[float, float, float]) -> bool:
    d = tuple(b - a for a, b in zip(r1, r2))
    dd = sum(x * x for x in d)
    if dd == 0:
        return False
    u = max(0.0, min(1.0, -sum(a * b for a, b in zip(r1, d)) / dd))
    nearest = tuple(a + u * b for a, b in zip(r1, d))
    return sum(x * x for x in nearest) > EARTH_RADIUS_KM**2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).parents[1]
    parser.add_argument("--tle", type=Path, default=root / "data" / "starlink_2026-10-01.tle")
    parser.add_argument("--selection", type=Path, default=root / "config" / "selected_constellation.json")
    parser.add_argument("--duration-s", type=int, default=86400)
    parser.add_argument("--step-s", type=int, default=1)
    parser.add_argument("--range-km", type=float, default=1700.0)
    parser.add_argument("--alignment-s", type=int, default=60)
    parser.add_argument("--output", type=Path, default=root / "results" / "direct_link_windows.json")
    args = parser.parse_args()

    selection = json.loads(args.selection.read_text(encoding="utf-8"))
    lines = args.tle.read_text(encoding="ascii").splitlines()
    by_id = {}
    for index, line in enumerate(lines):
        if line.startswith("1 ") and index + 1 < len(lines) and lines[index + 1].startswith("2 "):
            by_id[int(line[2:7])] = (line, lines[index + 1])
    satellites = []
    for item in selection["satellites"]:
        norad_id = int(item["norad_id"])
        l1, l2 = by_id[norad_id]
        satellites.append((norad_id, Satrec.twoline2rv(l1, l2)))

    start_jd = float(selection["metadata"]["reference_epoch"]["jd"])
    start_fraction = float(selection["metadata"]["reference_epoch"]["fraction"])
    windows = defaultdict(list)
    active_start = {}
    errors = defaultdict(int)
    for elapsed in range(0, args.duration_s, args.step_s):
        day, sec = divmod(elapsed, 86400)
        jd = start_jd + day
        fr = start_fraction + sec / 86400.0
        if fr >= 1.0:
            carry = int(fr)
            jd += carry
            fr -= carry
        positions = {}
        for norad_id, sat in satellites:
            error, pos, _ = sat.sgp4(jd, fr)
            if error:
                errors[norad_id] += 1
            else:
                positions[norad_id] = pos
        present = set(positions)
        for i in range(len(satellites)):
            a = satellites[i][0]
            if a not in present:
                continue
            for j in range(i + 1, len(satellites)):
                b = satellites[j][0]
                if b not in present:
                    continue
                ra, rb = positions[a], positions[b]
                distance = math.dist(ra, rb)
                eligible = distance <= args.range_km and unobstructed(ra, rb)
                key = (a, b)
                if eligible:
                    active_start.setdefault(key, elapsed)
                elif key in active_start:
                    start = active_start.pop(key)
                    duration = elapsed - start
                    windows[key].append({"start_s": start, "end_s": elapsed, "duration_s": duration})
        for key, start in list(active_start.items()):
            if key[0] not in present or key[1] not in present:
                windows[key].append({"start_s": start, "end_s": elapsed, "duration_s": elapsed - start})
                active_start.pop(key)

    for key, start in active_start.items():
        windows[key].append({"start_s": start, "end_s": args.duration_s, "duration_s": args.duration_s - start})
    rows = []
    for (a, b), spans in sorted(windows.items()):
        for span in spans:
            rows.append({"sat_a": a, "sat_b": b, **span,
                         "alignment_fits": span["duration_s"] >= args.alignment_s})
    result = {
        "inputs": {"duration_s": args.duration_s, "step_s": args.step_s,
                   "range_km": args.range_km, "alignment_s": args.alignment_s,
                   "earth_occultation_model": "spherical Earth, radius 6378.137 km",
                   "start_epoch": selection["metadata"]["reference_epoch"]["iso_utc"]},
        "sgp4_errors_by_norad": dict(errors),
        "window_count": len(rows),
        "windows_at_least_alignment_count": sum(row["alignment_fits"] for row in rows),
        "windows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "window_count": result["window_count"],
                      "windows_at_least_alignment_count": result["windows_at_least_alignment_count"],
                      "errors": result["sgp4_errors_by_norad"]}, indent=2))


if __name__ == "__main__":
    main()
