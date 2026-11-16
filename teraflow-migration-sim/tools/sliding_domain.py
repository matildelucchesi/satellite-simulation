#!/usr/bin/env python3
"""Cost policy with a domain that follows the controller, against the fixed domain (offline analysis).

The laboratory emulates a fixed domain of 16 satellites. Here, on the profile's replay, the cost
policy follows the controller from every shadow entry of a domain satellite in two ways:

- fixed domain: the domain of the profile, as in the laboratory;
- following domain: at every decision the domain is rebuilt around the satellite hosting the
  controller (``starlink_scenario.domain_around``: arc of its plane with ``--behind`` satellites
  trailing it, and the closest satellites of the other plane).

Same constraints, measured times and availability threshold as the installed policy. The report
gives, for each, how many migrations a chain lasts and why it stops, hops, stay, control latency,
admissible destinations, and how many satellites change domain at each step. ``journeys`` holds,
for each domain, the controller's day migration by migration from the same start (shown by the
console). Nothing in the laboratory changes.

    python tools/sliding_domain.py [--behind 4 6 7] [--output results/analysis/sliding-domain.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.artifacts import file_digest  # noqa: E402
from src.storage import atomic_json  # noqa: E402
from src import starlink_scenario as model  # noqa: E402


def load(profile):
    import numpy as np
    read = lambda name: json.loads((profile / name).read_text(encoding='utf-8'))
    arrays = np.load(profile / 'replay.npz', allow_pickle=False)
    ids = [int(value) for value in arrays['ids']]
    positions, eclipsed = arrays['positions'], arrays['eclipsed']
    links = read('laser_links.json')
    index = model.LinkIndex(links['links'], ids, links['inputs']['duration_s'])
    periods = {sid: model.lit_periods(eclipsed[:, column]) for column, sid in enumerate(ids)}
    domain_file = read('domain.json')
    plane_of = {row['norad_id']: row['plane'] - 1 for row in read('selected_constellation.json')['satellites']}
    column = {sid: position for position, sid in enumerate(ids)}
    distance_km = lambda a, b, tick: float(np.linalg.norm(positions[int(tick), column[a]] - positions[int(tick), column[b]]))
    latitudes = {}

    def latitude_at(tick):
        tick = int(tick)
        if tick not in latitudes:
            rows = positions[tick:tick + 2] if tick + 1 < len(positions) else positions[tick - 1:tick + 1][::-1]
            values = model.argument_of_latitude(rows)[0]
            latitudes[tick] = {sid: float(values[column[sid]]) for sid in ids}
        return latitudes[tick]
    return index, periods, domain_file, plane_of, distance_km, latitude_at, read('events.json')


def aggregate(summaries):
    """Distribution of chain lengths and stop reasons, means over chains with at least one migration."""
    lengths, stops = {}, {}
    for row in summaries:
        lengths[str(row['migrations'])] = lengths.get(str(row['migrations']), 0) + 1
        stops[row['stop']] = stops.get(row['stop'], 0) + 1
    served = [row for row in summaries if row['migrations']]
    mean = lambda field: (sum(row[field] for row in served if row.get(field) is not None)
                          / max(1, sum(row.get(field) is not None for row in served))) if served else None
    modes = lambda field: sorted({mode for row in served for mode in row.get(field, {})})
    mean_modes = lambda field: {mode: sum(row[field][mode] for row in served) / len(served) for mode in modes(field)}
    return {'starts': len(summaries), 'served_starts': len(served),
            'migrations_histogram': dict(sorted(lengths.items(), key=lambda item: int(item[0]))), 'stops': stops,
            'mean_migrations': mean('migrations'), 'max_migrations': max((row['migrations'] for row in served), default=0),
            'mean_span_s': mean('span_s'), 'mean_stay_s': mean('mean_stay_s'),
            'mean_control_latency_ms': mean('mean_control_latency_ms'),
            'mean_source_control_latency_ms': mean('mean_source_control_latency_ms'),
            'mean_admissible_destinations': mean('mean_admissible_destinations'),
            'mean_switches_changed': mean('mean_switches_changed'), 'other_plane_share': mean('other_plane_share'),
            'mean_interval_s': mean('mean_interval_s'),
            'downtime_share': mean_modes('downtime_share'), 'migrating_share': mean_modes('migrating_share')}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--profile', default='starlink-53-463-2x31')
    parser.add_argument('--behind', type=int, nargs='+', default=[4, 6, 7],
                        help='Satelliti del dominio che seguono il controller sul suo piano (uno o piu valori)')
    parser.add_argument('--output', default='results/analysis/sliding-domain.json')
    args = parser.parse_args(argv)

    profile = ROOT / 'artifacts/constellation-profiles' / args.profile
    index, periods, domain_file, plane_of, distance_km, latitude_at, events = load(profile)
    policy = events.get('destination_policy', {}).get('parameters')
    if not policy:
        raise SystemExit('Il profilo non ha la politica di destinazione: eseguire tools/destination_policy.py')
    size = domain_file['satellites_per_plane']
    fixed = domain_file['plane_1'] + domain_file['plane_2']
    limits = {name: events['parameters'][name] for name in
              ('trigger_lead_s', 'minimum_destination_light_s', 'minimum_path_persistence_s')}
    options = {**limits, 'availability_min': policy['availability_min'], 'minimum_stay_s': policy.get('minimum_stay_s', 0.0),
               'selection_mode': policy['selection_mode'],
               'downtime_s': policy['downtime_s'], 'duration_s': policy['duration_s'], 'overhead_ms': policy['overhead_ms']}
    starts = sorted(model._shadow_entries(index, periods, fixed, limits['trigger_lead_s']), key=lambda row: (row[1], row[0]))

    def run(domain_of):
        memo, summaries, chains = {}, [], {}
        for source, shadow in starts:
            steps, stop = model.follow_controller(index, periods, plane_of, distance_km, domain_of, source, shadow,
                                                  **options, memo=memo)
            summaries.append(model.chain_summary(steps, stop, policy['downtime_s'], policy['duration_s']))
            chains[(source, shadow)] = (steps, stop)
        return summaries, chains

    print(f'{len(starts)} ingressi in ombra di partenza nel dominio fisso')
    fixed_summaries, fixed_chains = run(lambda host, tick: fixed)
    # Consistency with the catalogue: the fixed domain gives the chains of policy_chains
    stored = {(event['source'], event['source_shadow_entry_s']): event for event in events['destination_policy']['events']}
    expected = {(chain[0]['source'], chain[0]['source_shadow_entry_s']): len(chain)
                for chain in model.policy_chains(list(stored.values()))}
    mismatch = [key for key, (steps, _) in fixed_chains.items() if steps and expected.get(key) != len(steps)]
    if mismatch:
        raise SystemExit(f'Dominio fisso diverso dalle catene del catalogo in {len(mismatch)} partenze: {mismatch[:3]}')
    report = {'created_utc': datetime.now(timezone.utc).isoformat(), 'profile': args.profile,
              'inputs': {name: file_digest(profile / name) for name in
                         ('replay.npz', 'laser_links.json', 'domain.json', 'selected_constellation.json', 'events.json')}
              | {'model_sha256': file_digest(ROOT / 'src/starlink_scenario.py')},
              'policy': options, 'domain_per_plane': size,
              'rule': 'dominio che segue il controller: arco di satelliti consecutivi del suo piano (behind dietro di lui) '
                      'e i satelliti dell altro piano piu vicini all arco, ricalcolato a ogni decisione',
              'fixed': aggregate(fixed_summaries), 'following': {}}
    # The day of the controller, for the console: every variant from the same start, the earliest
    # shadow entry the fixed domain serves, so the fixed domain shows where it stops
    start = next(((source, shadow) for source, shadow in starts if fixed_chains[(source, shadow)][0]), starts[0])

    def journey(key, label, behind, chains):
        steps, stop = chains[start]
        rows, previous = [], None
        for step in steps:
            domain = set(step['domain'])
            rows.append({**{name: value for name, value in step.items() if name != 'domain'},
                         'source_plane': plane_of[step['source']], 'destination_plane': plane_of[step['destination']],
                         'joined': sorted(domain - previous) if previous is not None else [],
                         'left': sorted(previous - domain) if previous is not None else []})
            previous = domain
        return {'key': key, 'label': label, 'behind': behind, 'domain': sorted(steps[0]['domain']) if steps else None,
                'summary': model.chain_summary(steps, stop, policy['downtime_s'], policy['duration_s']), 'steps': rows}

    report['journeys'] = {'start': {'source': start[0], 'source_shadow_entry_s': start[1],
                                    'trigger_s': start[1] - limits['trigger_lead_s']},
                          'variants': [journey('fixed', 'Fixed domain (laboratory)', None, fixed_chains)]}
    for behind in args.behind:
        summaries, chains = run(lambda host, tick, behind=behind: model.domain_around(host, plane_of, latitude_at(tick), size, behind))
        report['following'][str(behind)] = aggregate(summaries)
        report['journeys']['variants'].append(
            journey(f'following-{behind}', f'Domain following the controller, {behind} satellites behind', behind, chains))

    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(output, report)

    def line(name, row):
        if not row['served_starts']:
            print(f'{name}: nessuna delle {row["starts"]} partenze servita, arresti {row["stops"]}')
            return
        print(f'{name}: {row["served_starts"]} di {row["starts"]} partenze servite, migrazioni per catena '
              f'media {row["mean_migrations"]:.1f} max {row["max_migrations"]}, arresti {row["stops"]}')
        print(f'   durata media {row["mean_span_s"] / 3600:.2f} h, permanenza media {row["mean_stay_s"]:.0f} s, '
              f'latenza scelta {row["mean_control_latency_ms"]:.2f} ms (sorgente {row["mean_source_control_latency_ms"]:.2f} ms), '
              f'destinazioni ammesse {row["mean_admissible_destinations"]:.1f}, altro piano {row["other_plane_share"]:.0%}, '
              f'una migrazione ogni {row["mean_interval_s"]:.0f} s, downtime Hot {row["downtime_share"]["hot"]:.1%} '
              f'Cold {row["downtime_share"]["cold"]:.1%}, in migrazione Hot {row["migrating_share"]["hot"]:.0%} '
              f'Cold {row["migrating_share"]["cold"]:.0%}'
              + (f', satelliti che cambiano dominio per passo {row["mean_switches_changed"]:.1f}'
                 if row['mean_switches_changed'] is not None else ''))
    line('Dominio fisso', report['fixed'])
    for behind, row in report['following'].items():
        line(f'Dominio che segue il controller ({behind} dietro)', row)
    first = report['journeys']['start']
    print(f'Giornata del controller da {first["source"]} (trigger {first["trigger_s"]} s):')
    for variant in report['journeys']['variants']:
        s = variant['summary']
        print(f'   {variant["label"]}: {s["migrations"]} migrazioni in {s.get("span_s", 0) / 3600:.1f} h, arresto {s["stop"]}')
    print(f'Scritto {output.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
