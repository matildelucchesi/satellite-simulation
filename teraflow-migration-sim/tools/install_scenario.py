#!/usr/bin/env python3
"""Install a frozen scenario profile built by tools/build_scenario.py into config/ and results/.

The current configuration is archived first under <profile>/original/, using the same layout
as src/constellation.py, so historical runs keep their own geometry in the console. The tool
refuses to run while a laboratory job holds the lock. It does not restart containers: Mininet
and the P4 proxy read config/fixture.json at start and must be restarted afterwards.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.artifacts import describe, file_digest, verify_artifact  # noqa: E402
from src.fixture import build  # noqa: E402
from src.storage import atomic_json  # noqa: E402

ARCHIVED = ('config/scenario.json', 'config/selected_constellation.json', 'config/fixture.json',
            'config/lab-manifest.json', 'config/artifact_manifest.json', 'config/domain.json',
            'config/migration_events.json', 'results/calibration.json', 'results/functional-gate.json',
            'results/direct_link_windows.json', 'artifacts/orbit/replay.npz', 'artifacts/orbit/replay.json')


def invalidate_functional_gate(root, profile):
    """The previous verification belongs to the previous scenario: archive it and require a new one."""
    gate = root / 'results/functional-gate.json'
    archived = profile / 'original/results/functional-gate.json'
    if gate.exists() and not archived.exists():
        archived.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(gate, archived)
    atomic_json(gate, {'complete': False, 'reason': 'Scenario installato: nuova verifica funzionale richiesta',
                       'previous_evidence': str(archived)})


def windows_from_links(document):
    """Laser link intervals in the schema of results/direct_link_windows.json."""
    rows = [{'sat_a': row['sat_a'], 'sat_b': row['sat_b'], 'start_s': row['start_s'], 'end_s': row['end_s'],
             'duration_s': row['end_s'] - row['start_s'], 'alignment_fits': True, 'kind': row['kind'],
             'assigned_start_s': row['assigned_start_s']} for row in document['links']]
    inputs = document['inputs']
    return {'inputs': {'duration_s': inputs['duration_s'], 'step_s': 1, 'range_km': inputs['range_km'],
                       'alignment_s': inputs['alignment_s'], 'link_model': 'laser-3-terminals',
                       'terminals': inputs['terminals']},
            'sgp4_errors_by_norad': {}, 'window_count': len(rows),
            'windows_at_least_alignment_count': sum(row['duration_s'] >= inputs['alignment_s'] for row in rows),
            'windows': rows}


def service_endpoints(domain):
    """Both ends of the plane-1 arc.

    TeraFlow's path computation and the fixture's forwarding rules must choose the same path.
    Between the two planes the domain is a ladder with many equal-hop paths and TeraFlow's
    tie-break is internal, so the endpoints lie on one rail, where the shortest path is unique
    (any detour through the other plane costs at least two extra hops)."""
    return [domain['plane_1'][0], domain['plane_1'][-1]]


def unique_shortest_path(graph, source, target):
    """The single fewest-hop path between source and target, or None if absent or not unique."""
    from collections import deque
    depth, count, parent = {source: 0}, {source: 1}, {source: None}
    queue = deque([source])
    while queue:
        node = queue.popleft()
        for neighbour in graph[node]:
            if neighbour not in depth:
                depth[neighbour] = depth[node] + 1
                count[neighbour] = count[node]
                parent[neighbour] = node
                queue.append(neighbour)
            elif depth[neighbour] == depth[node] + 1:
                count[neighbour] += count[node]
    if target not in depth or count[target] != 1:
        return None
    path, node = [], target
    while node is not None:
        path.append(node)
        node = parent[node]
    return path[::-1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--profile', default='starlink-53-463-2x31')
    parser.add_argument('--resume', action='store_true',
                        help='Completa fixture, manifest del laboratorio e registrazione dopo un\'installazione interrotta')
    parser.add_argument('--refresh', action='store_true',
                        help='Ricopia gli output di un profilo installato e ricostruito, senza archiviare di nuovo')
    args = parser.parse_args(argv)
    profile = ROOT / 'artifacts/constellation-profiles' / args.profile
    if (ROOT / 'results/jobs/lab.lock').exists():
        parser.error('Un job o un recupero detiene il lock del laboratorio')
    manifest = json.loads((profile / 'manifest.json').read_text(encoding='utf-8'))
    for item in manifest['outputs'].values():
        verify_artifact(item)
    current = json.loads((ROOT / 'config/scenario.json').read_text(encoding='utf-8'))
    installed = current['orbital'].get('constellation_profile') == args.profile
    if args.resume:
        if not installed or manifest.get('installed') or not (profile / 'archive.json').exists():
            parser.error('Nessuna installazione interrotta da completare per questo profilo')
        return finalize(profile, manifest, json.loads((profile / 'archive.json').read_text(encoding='utf-8')))
    if args.refresh:
        if not installed or not (profile / 'archive.json').exists():
            parser.error("Il profilo non risulta installato: usare l'installazione normale")
        copy_outputs(profile)
        return finalize(profile, manifest, json.loads((profile / 'archive.json').read_text(encoding='utf-8')))
    if installed:
        parser.error('Profilo già installato')
    if (profile / 'original').exists():
        parser.error(f'{profile / "original"} esiste già: ispezionarlo prima di una nuova installazione')

    archived = {}
    for name in ARCHIVED:
        source = ROOT / name
        if source.exists():
            target = profile / 'original' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            archived[name] = file_digest(target)
    atomic_json(profile / 'archive.json', archived)
    copy_outputs(profile)
    return finalize(profile, manifest, archived)


def copy_outputs(profile):
    domain = json.loads((profile / 'domain.json').read_text(encoding='utf-8'))
    domain['service_endpoints'] = service_endpoints(domain)
    domain['service_endpoints_rule'] = 'primo satellite dell arco del piano 1 e ultimo dell arco del piano 2'
    atomic_json(ROOT / 'config/domain.json', domain)
    shutil.copy2(profile / 'events.json', ROOT / 'config/migration_events.json')
    shutil.copy2(profile / 'selected_constellation.json', ROOT / 'config/selected_constellation.json')
    shutil.copy2(profile / 'scenario.json', ROOT / 'config/scenario.json')
    links = json.loads((profile / 'laser_links.json').read_text(encoding='utf-8'))
    atomic_json(ROOT / 'results/direct_link_windows.json', windows_from_links(links))
    shutil.copy2(profile / 'replay.npz', ROOT / 'artifacts/orbit/replay.npz')
    shutil.copy2(profile / 'replay.json', ROOT / 'artifacts/orbit/replay.json')


def check_service_path(domain, step_s=600):
    """Refuse endpoints whose fewest-hop path is ambiguous or differs from the distance-based one."""
    from src.orbit import load_orbit, shortest_paths
    orbit = load_orbit(ROOT)
    source, target = domain['service_endpoints']
    for tick in range(0, orbit.duration, step_s):
        graph = orbit.lab_graph(tick)
        unique = unique_shortest_path(graph, source, target)
        if unique is None:
            raise SystemExit(f'Estremi del servizio {source}-{target}: percorso minimo assente o non unico al secondo {tick}')
        distances = shortest_paths(graph, target)
        node, by_distance = source, [source]
        while node != target:
            node = min((length + distances[n], n) for n, length in graph[node].items() if n in distances)[1]
            by_distance.append(node)
        if by_distance != unique:
            raise SystemExit(f'Estremi del servizio {source}-{target}: percorso per distanza diverso da quello minimo al secondo {tick}')


def write_if_changed(path, value):
    """Avoid replacing files that Docker keeps open on Windows when nothing changed."""
    if path.exists() and json.loads(path.read_text(encoding='utf-8')) == json.loads(json.dumps(value)):
        return False
    atomic_json(path, value)
    return True


def finalize(profile, manifest, archived):
    """Fixture, laboratory manifest, functional gate and installation record.

    On Windows the fixture cannot be replaced while Docker containers keep it open: stop
    Mininet and the P4 proxy first, then rerun with --resume."""
    domain = json.loads((ROOT / 'config/domain.json').read_text(encoding='utf-8'))
    check_service_path(domain)
    fixture_changed = write_if_changed(ROOT / 'config/fixture.json', build(ROOT))
    lab = json.loads((ROOT / 'config/lab-manifest.json').read_text(encoding='utf-8'))
    lab['fixture'] = describe(ROOT / 'config/fixture.json')
    write_if_changed(ROOT / 'config/lab-manifest.json', lab)
    invalidate_functional_gate(ROOT, profile)

    fixture = json.loads((ROOT / 'config/fixture.json').read_text(encoding='utf-8'))
    manifest['installed'] = True
    manifest['installed_utc'] = datetime.now(timezone.utc).isoformat()
    manifest['installation'] = {'archive': 'original/', 'archived_files': sorted(archived),
                                'service_endpoints': domain['service_endpoints'],
                                'fixture_devices': len(fixture['emulator']['devices']),
                                'fixture_links': len(fixture['emulator']['pairs']),
                                'restart_required': ['mininet', 'p4-proxy'] if fixture_changed else []}
    atomic_json(profile / 'manifest.json', manifest)
    print(json.dumps(manifest['installation'], indent=1))
    if fixture_changed:
        print('Riavviare Mininet e proxy P4 prima di qualsiasi prova: docker compose ... restart mininet p4-proxy')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
