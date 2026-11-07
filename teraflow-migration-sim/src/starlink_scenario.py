"""Two-plane Starlink scenario: plane selection, three-laser links, multi-hop paths, domain and events.

Offline only. Nothing here touches the laboratory. Every function is deterministic for
fixed inputs so that the frozen profile can be regenerated and compared by hash.

Laser rule (design hypothesis, documented in README): each satellite carries three
optical terminals, two towards its ring neighbours in the same plane and one towards
the other plane. A link formed during the replay is usable only after it has existed for
``alignment_s``; links already present at the first second are considered aligned.
"""
from __future__ import annotations

import bisect
import math
from collections import deque

POLICY = 'starlink-two-plane-v1'
EARTH_RADIUS_KM = 6378.137


# ---------------------------------------------------------------- plane selection

def plane_rows(candidates, jd, fraction, *, inclination_deg=(52.8, 53.4), altitude_km=(455.0, 475.0),
               max_eccentricity=0.002, max_tle_age_h=24.0):
    """Screen TLE candidates and compute RAAN and argument of latitude with SGP4 at one epoch."""
    from sgp4.api import Satrec
    rows = []
    for c in candidates:
        age_h = ((jd + fraction) - (c.epoch_jd + c.epoch_jd_fraction)) * 24.0
        if not (inclination_deg[0] <= c.inclination_deg <= inclination_deg[1]
                and altitude_km[0] <= c.screening_altitude_km <= altitude_km[1]
                and c.eccentricity < max_eccentricity and abs(age_h) <= max_tle_age_h):
            continue
        error, r, v = Satrec.twoline2rv(c.tle_line1, c.tle_line2).sgp4(jd, fraction)
        if error:
            continue
        h = _cross(r, v)
        hn = _unit(h)
        raan = math.degrees(math.atan2(hn[0], -hn[1])) % 360.0
        node = (math.cos(math.radians(raan)), math.sin(math.radians(raan)), 0.0)
        u = math.degrees(math.atan2(_dot(_cross(node, r), hn), _dot(node, r))) % 360.0
        rows.append({'norad_id': c.norad_id, 'name': c.name, 'raan_deg': raan, 'argument_of_latitude_deg': u,
                     'inclination_deg': math.degrees(math.acos(max(-1.0, min(1.0, hn[2])))),
                     'screening_altitude_km': c.screening_altitude_km, 'eccentricity': c.eccentricity,
                     'mean_motion_rev_day': c.mean_motion_rev_day, 'tle_age_hours_at_reference': age_h})
    return rows


def cluster_planes(rows, gap_deg=0.5):
    """Group rows whose RAAN values are closer than ``gap_deg`` (sorted, no wrap at 0/360)."""
    ordered = sorted(rows, key=lambda row: (row['raan_deg'], row['norad_id']))
    clusters, current = [], []
    for row in ordered:
        if current and row['raan_deg'] - current[-1]['raan_deg'] >= gap_deg:
            clusters.append(current)
            current = []
        current.append(row)
    if current:
        clusters.append(current)
    return clusters


def select_planes(rows, centers_deg, *, gap_deg=0.5, tolerance_deg=0.6):
    """Return one cluster per requested RAAN centre; fail if a centre is ambiguous or missing."""
    clusters = cluster_planes(rows, gap_deg)
    chosen = []
    for center in centers_deg:
        near = [c for c in clusters if abs(_mean_angle([r['raan_deg'] for r in c]) - center) <= tolerance_deg]
        if len(near) != 1:
            raise ValueError(f'RAAN {center}: {len(near)} plane clusters within {tolerance_deg} deg')
        chosen.append(sorted(near[0], key=lambda row: (row['argument_of_latitude_deg'], row['norad_id'])))
    if {r['norad_id'] for r in chosen[0]} & {r['norad_id'] for r in chosen[1]}:
        raise ValueError('Planes overlap')
    return chosen


def max_ring_gap_deg(plane):
    angles = sorted(row['argument_of_latitude_deg'] for row in plane)
    return max((angles[(i + 1) % len(angles)] - angles[i]) % 360.0 for i in range(len(angles)))


# ---------------------------------------------------------------- laser links

def argument_of_latitude(positions):
    """Argument of latitude in degrees, shape (T, N), from consecutive TEME positions."""
    import numpy as np
    following = np.concatenate([positions[1:], positions[-1:] + (positions[-1:] - positions[-2:-1])])
    h = np.cross(positions, following)
    hn = h / np.linalg.norm(h, axis=-1)[..., None]
    raan = np.arctan2(hn[..., 0], -hn[..., 1])
    node = np.stack([np.cos(raan), np.sin(raan), np.zeros_like(raan)], -1)
    return np.degrees(np.arctan2(np.einsum('...k,...k', np.cross(node, positions), hn),
                                 np.einsum('...k,...k', node, positions))) % 360.0


def _usable(points_a, points_b, max_range_km, earth_radius_km):
    import numpy as np
    d = points_b - points_a
    squared = np.sum(d * d, axis=-1)
    t = np.clip(-np.sum(points_a * d, axis=-1) / np.maximum(squared, 1e-30), 0.0, 1.0)
    nearest = points_a + t[..., None] * d
    clear = np.sum(nearest * nearest, axis=-1) > earth_radius_km ** 2
    return (squared > 0) & (squared <= max_range_km ** 2) & clear, np.sqrt(squared)


def laser_links(positions, ids, planes, *, max_range_km, alignment_s, earth_radius_km=EARTH_RADIUS_KM, chunk=3600):
    """Assign the three terminals second by second and return usable link intervals.

    Intra-plane: each satellite links its predecessor and successor in its plane ring,
    ordered by the current argument of latitude. Inter-plane: one terminal per satellite,
    stable pairs kept while in range, free terminals paired greedily by shortest distance.
    """
    import numpy as np
    duration, count = positions.shape[0], positions.shape[1]
    planes = np.asarray(planes)
    members = [np.flatnonzero(planes == p) for p in (0, 1)]
    open_since, intervals = {}, []
    matched = {}

    def close(pair, end):
        start = open_since.pop(pair)
        kind = pair[2]
        # Links already up when the replay starts belong to a constellation in steady state:
        # they are aligned. Only links formed during the replay pay the alignment time.
        usable = start if start == 0 else start + alignment_s
        if end > usable:
            intervals.append({'sat_a': ids[pair[0]], 'sat_b': ids[pair[1]], 'kind': kind,
                              'assigned_start_s': int(start), 'start_s': int(usable), 'end_s': int(end)})

    for first in range(0, duration, chunk):
        block = positions[first:first + chunk]
        u = argument_of_latitude(positions[first:min(duration, first + chunk + 1)])[:len(block)]
        a_pts, b_pts = block[:, members[0]], block[:, members[1]]
        inter_ok, inter_d = _usable(a_pts[:, :, None, :], b_pts[:, None, :, :], max_range_km, earth_radius_km)
        for offset in range(len(block)):
            tick = first + offset
            current = set()
            ring_a, ring_b = [], []
            for plane in (0, 1):
                ring = members[plane][np.argsort(u[offset, members[plane]], kind='stable')]
                if len(ring) < 2:
                    continue
                following = np.roll(ring, -1)
                if len(ring) == 2:
                    ring, following = ring[:1], following[:1]
                ring_a.append(ring)
                ring_b.append(following)
            if ring_a:
                ra, rb = np.concatenate(ring_a), np.concatenate(ring_b)
                ok, _ = _usable(block[offset, ra], block[offset, rb], max_range_km, earth_radius_km)
                for a, b in zip(ra[ok].tolist(), rb[ok].tolist()):
                    current.add((min(a, b), max(a, b), 'intra'))
            ok_now, dist_now = inter_ok[offset], inter_d[offset]
            for ia, ib in list(matched.items()):
                if not ok_now[ia, ib]:
                    del matched[ia]
            free_a = [i for i in range(len(members[0])) if i not in matched]
            taken_b = set(matched.values())
            free_b = [j for j in range(len(members[1])) if j not in taken_b]
            if free_a and free_b:
                options = sorted((dist_now[i, j], i, j) for i in free_a for j in free_b if ok_now[i, j])
                used_a, used_b = set(), set()
                for _, i, j in options:
                    if i not in used_a and j not in used_b:
                        matched[i] = j
                        used_a.add(i)
                        used_b.add(j)
            for ia, ib in matched.items():
                a, b = int(members[0][ia]), int(members[1][ib])
                current.add((min(a, b), max(a, b), 'inter'))
            for pair in [p for p in open_since if p not in current]:
                close(pair, tick)
            for pair in current:
                open_since.setdefault(pair, tick)
    for pair in list(open_since):
        close(pair, duration)
    intervals.sort(key=lambda row: (row['start_s'], row['sat_a'], row['sat_b']))
    return intervals


def terminal_usage_ok(intervals, ids, planes):
    """Check the three-terminal rule: at most 2 intra and 1 inter usable link per satellite at any time."""
    plane_of = dict(zip(ids, planes))
    events = []
    for row in intervals:
        if row['kind'] == 'intra' and plane_of[row['sat_a']] != plane_of[row['sat_b']]:
            return False
        if row['kind'] == 'inter' and plane_of[row['sat_a']] == plane_of[row['sat_b']]:
            return False
        for sid in (row['sat_a'], row['sat_b']):
            events.append((row['start_s'], 1, sid, row['kind']))
            events.append((row['end_s'], -1, sid, row['kind']))
    load = {}
    for _, delta, sid, kind in sorted(events, key=lambda e: (e[0], e[1])):
        key = (sid, kind)
        load[key] = load.get(key, 0) + delta
        if load[key] > (2 if kind == 'intra' else 1):
            return False
    return True


# ---------------------------------------------------------------- multi-hop paths

class LinkIndex:
    """Piecewise-constant usable-link graph with reachability, hop counts and path persistence."""

    def __init__(self, intervals, ids, duration):
        self.ids, self.duration = list(ids), duration
        bounds = {0, duration}
        for row in intervals:
            bounds.update((row['start_s'], row['end_s']))
        self.bounds = sorted(b for b in bounds if 0 <= b <= duration)
        self.segments = []
        starts = sorted(intervals, key=lambda r: r['start_s'])
        active, pointer = [], 0
        for start, end in zip(self.bounds, self.bounds[1:]):
            while pointer < len(starts) and starts[pointer]['start_s'] <= start:
                active.append(starts[pointer])
                pointer += 1
            active = [row for row in active if row['end_s'] > start]
            graph = {sid: set() for sid in self.ids}
            for row in active:
                graph[row['sat_a']].add(row['sat_b'])
                graph[row['sat_b']].add(row['sat_a'])
            self.segments.append((start, end, graph))

    def segment(self, tick):
        if not 0 <= tick < self.duration:
            raise ValueError('Tick outside replay')
        return self.segments[bisect.bisect_right(self.bounds, tick) - 1]

    def hops(self, source, tick):
        """Fewest hops and one shortest path from ``source`` to every reachable satellite."""
        graph = self.segment(tick)[2]
        parent, depth, queue = {source: None}, {source: 0}, deque([source])
        while queue:
            node = queue.popleft()
            for neighbour in sorted(graph[node]):
                if neighbour not in depth:
                    depth[neighbour] = depth[node] + 1
                    parent[neighbour] = node
                    queue.append(neighbour)
        paths = {}
        for node in depth:
            path, cursor = [], node
            while cursor is not None:
                path.append(cursor)
                cursor = parent[cursor]
            paths[node] = path[::-1]
        return depth, paths

    def path_end(self, source, target, tick, limit_s=None):
        """First second after ``tick`` at which ``target`` is no longer reachable from ``source``.

        With ``limit_s`` the scan stops at ``tick + limit_s`` and returns that value if the
        path is still available, so callers can test a minimum persistence cheaply."""
        index = bisect.bisect_right(self.bounds, tick) - 1
        stop = self.duration if limit_s is None else min(self.duration, tick + limit_s)
        for start, end, graph in self.segments[index:]:
            if start >= stop:
                return stop
            if not _reachable(graph, source, target):
                return max(start, tick)
        return self.duration


def component(graph, source):
    """Set of satellites reachable from ``source`` (including itself)."""
    seen, queue = {source}, deque([source])
    while queue:
        for neighbour in graph[queue.popleft()]:
            if neighbour not in seen:
                seen.add(neighbour)
                queue.append(neighbour)
    return seen


def _reachable(graph, source, target):
    if source == target:
        return True
    seen, queue = {source}, deque([source])
    while queue:
        node = queue.popleft()
        for neighbour in graph[node]:
            if neighbour == target:
                return True
            if neighbour not in seen:
                seen.add(neighbour)
                queue.append(neighbour)
    return False


# ---------------------------------------------------------------- illumination, domain, events

def lit_periods(eclipsed_column):
    """[start, end) intervals in which the satellite is in sunlight."""
    periods, start = [], None
    for tick, shadow in enumerate(eclipsed_column):
        if not shadow and start is None:
            start = tick
        if shadow and start is not None:
            periods.append((start, tick))
            start = None
    if start is not None:
        periods.append((start, len(eclipsed_column)))
    return periods


def choose_domain(planes, size_per_plane):
    """Contiguous arc of ``size_per_plane`` satellites in plane 1 (lowest argument of latitude first)
    and the satellites of plane 2 closest to that arc in argument of latitude."""
    first = planes[0][:size_per_plane]
    if len(first) < size_per_plane or len(planes[1]) < size_per_plane:
        raise ValueError('Plane too small for the requested domain')
    centre = _mean_angle([row['argument_of_latitude_deg'] for row in first])
    second = sorted(planes[1], key=lambda row: (_angle_gap(row['argument_of_latitude_deg'], centre), row['norad_id']))
    second = sorted(second[:size_per_plane], key=lambda row: (row['argument_of_latitude_deg'], row['norad_id']))
    return [row['norad_id'] for row in first], [row['norad_id'] for row in second]


def migration_events(index, periods, domain, *, trigger_lead_s, minimum_destination_light_s,
                     minimum_path_persistence_s):
    """One event per shadow entry of a domain satellite: trigger ``trigger_lead_s`` before shadow.

    For each event the destination is the reachable lit satellite with the fewest hops whose
    remaining light is at least ``minimum_destination_light_s`` and whose path lasts at least
    ``minimum_path_persistence_s`` (ties: more remaining light, then lower NORAD id). Events
    without such a destination stay in the catalogue with ``destination`` None so that
    infeasible cases remain visible. Only shadow entries observed inside the replay qualify.
    """
    events = []
    for source in domain:
        for start, end in periods[source]:
            if end >= index.duration:
                continue
            trigger = end - trigger_lead_s
            if trigger < start or trigger < 0:
                continue
            depth, paths = index.hops(source, trigger)
            ranked = []
            for target, hop in depth.items():
                if target == source:
                    continue
                window = _containing(periods[target], trigger)
                if window is None or window[1] - trigger < minimum_destination_light_s:
                    continue
                ranked.append((hop, -(window[1] - trigger), target))
            best = None
            for hop, negative_light, target in sorted(ranked):
                persistence = index.path_end(source, target, trigger, minimum_path_persistence_s) - trigger
                if persistence >= minimum_path_persistence_s:
                    best = (target, -negative_light)
                    break
            event = {'event_id': f'{source}-{trigger}', 'source': source, 'trigger_s': trigger,
                     'source_shadow_entry_s': end, 'source_light_remaining_s': end - trigger,
                     'reachable_satellites': len(depth) - 1, 'lit_candidates': len(ranked),
                     'destination': None, 'hops': None, 'path': None}
            if best:
                target, light = best
                event.update(destination=target, hops=depth[target], path=paths[target],
                             destination_light_remaining_s=light, light_gained_s=light - (end - trigger),
                             path_persistence_at_least_s=minimum_path_persistence_s,
                             path_end_s=index.path_end(source, target, trigger))
            events.append(event)
    events.sort(key=lambda e: (e['trigger_s'], e['source']))
    return events


def representative_events(events, count=3):
    """Deterministic spread over feasible events ordered by (hops, trigger time).

    With different hop counts this yields fewest, median and most hops; when every event
    needs the same number of hops (regular shells repeat each orbit) it yields the first,
    median and last event of the day, i.e. replicas spread in time."""
    feasible = sorted((e for e in events if e['destination'] is not None),
                      key=lambda e: (e['hops'], e['trigger_s'], e['source']))
    if len(feasible) < count:
        raise ValueError('Not enough feasible migration events')
    picks, chosen = [], set()
    for quantile in [i / (count - 1) for i in range(count)] if count > 1 else [0.5]:
        position = math.floor(quantile * (len(feasible) - 1))  # lower median for even counts
        for candidate in feasible[position:] + feasible[:position][::-1]:
            if candidate['event_id'] not in chosen:
                chosen.add(candidate['event_id'])
                picks.append(candidate)
                break
    return picks


# ---------------------------------------------------------------- helpers

def _containing(intervals, tick):
    position = bisect.bisect_right(intervals, (tick, math.inf)) - 1
    if position >= 0 and intervals[position][0] <= tick < intervals[position][1]:
        return intervals[position]
    return None


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _unit(a):
    norm = math.sqrt(_dot(a, a))
    return tuple(x / norm for x in a)


def _mean_angle(values):
    return math.degrees(math.atan2(sum(math.sin(math.radians(v)) for v in values),
                                   sum(math.cos(math.radians(v)) for v in values))) % 360.0


def _angle_gap(a, b):
    return abs((a - b + 180.0) % 360.0 - 180.0)
