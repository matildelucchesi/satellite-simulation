#!/usr/bin/env python3
"""Destination policy of a frozen scenario profile, with the downtime measured by an experiment (offline).

Reads the profile's replay, laser links, domain and designed events; takes the median controller
downtime and migration duration per mode from a completed event experiment; adds to the profile's ``events.json``:

- ``destination_policy``: parameters with their provenance, the choice at every shadow entry,
  the sensitivity to the availability threshold and the comparison with the designed events;
- ``policy_selected``: the policy's events for the designed shadow entries, run by the
  experiment when the cost policy is chosen.

The designed events and the profile's other files are not changed; the manifest records the new
hash of ``events.json``. The installed configuration and the laboratory are not touched: install
with ``tools/install_scenario.py --refresh``.

    python tools/destination_policy.py --downtime-from events-<id> [--availability-min 0.95] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.artifacts import describe, file_digest  # noqa: E402
from src.event_comparison import measured_times  # noqa: E402
from src.storage import atomic_json  # noqa: E402
from src import starlink_scenario as model  # noqa: E402


def load_profile(profile):
    """Index, lit periods, domain, planes, distance function and designed events of a profile."""
    import numpy as np
    read = lambda name: json.loads((profile / name).read_text(encoding='utf-8'))
    arrays = np.load(profile / 'replay.npz', allow_pickle=False)
    ids = [int(value) for value in arrays['ids']]
    positions, eclipsed = arrays['positions'], arrays['eclipsed']
    links = read('laser_links.json')
    index = model.LinkIndex(links['links'], ids, links['inputs']['duration_s'])
    periods = {sid: model.lit_periods(eclipsed[:, column]) for column, sid in enumerate(ids)}
    domain_file = read('domain.json')
    domain = domain_file['plane_1'] + domain_file['plane_2']
    plane_of = {row['norad_id']: row['plane'] - 1 for row in read('selected_constellation.json')['satellites']}
    column = {sid: position for position, sid in enumerate(ids)}
    distance_km = lambda a, b, tick: float(np.linalg.norm(positions[int(tick), column[a]] - positions[int(tick), column[b]]))
    events = read('events.json')
    return index, periods, domain, plane_of, distance_km, events


def experiment_times(root, identifier):
    """Median downtime and duration per mode of a completed experiment, with their provenance."""
    path = root / 'results/event-comparisons' / identifier / 'metadata.json'
    metadata = json.loads(path.read_text(encoding='utf-8'))
    if not metadata.get('complete'):
        raise SystemExit(f'{identifier}: esperimento non completato')
    measured = {mode: row for mode, row in measured_times(metadata).items() if mode in ('hot', 'cold')}
    missing = [mode for mode in ('hot', 'cold') if mode not in measured
               or measured[mode]['downtime_median_s'] is None or measured[mode]['duration_median_s'] is None]
    if missing:
        raise SystemExit(f'{identifier}: downtime o durata assenti per {", ".join(missing)}')
    return measured, {'experiment': identifier, 'metadata_sha256': file_digest(path), 'measured': measured,
                      'statistic': 'mediane di downtime del controller e durata della migrazione sulle repliche accettate, eventi riuniti'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--profile', default='starlink-53-463-2x31')
    parser.add_argument('--downtime-from', required=True, metavar='EXPERIMENT', help='Esperimento completato (events-...)')
    parser.add_argument('--availability-min', type=float, default=model.DESTINATION_POLICY['availability_min'])
    parser.add_argument('--overhead-ms', type=float, default=model.DESTINATION_POLICY['overhead_ms'],
                        help='Termine costante misurato aggiunto alla latenza di controllo')
    parser.add_argument('--selection-mode', choices=('hot', 'cold'), default=model.DESTINATION_POLICY['selection_mode'],
                        help='Downtime usato per ammettere le destinazioni (vale per entrambe le modalita)')
    parser.add_argument('--dry-run', action='store_true', help='Stampa il resoconto senza scriverlo nel profilo')
    args = parser.parse_args(argv)

    profile = ROOT / 'artifacts/constellation-profiles' / args.profile
    if not (profile / 'replay.npz').exists():
        parser.error(f'{profile}: profilo senza replay')
    measured, source = experiment_times(ROOT, args.downtime_from)
    downtime_s = {mode: row['downtime_median_s'] for mode, row in measured.items()}
    duration_s = {mode: row['duration_median_s'] for mode, row in measured.items()}
    index, periods, domain, plane_of, distance_km, events = load_profile(profile)
    limits = {name: events['parameters'][name] for name in
              ('trigger_lead_s', 'minimum_destination_light_s', 'minimum_path_persistence_s')}
    report = model.destination_policy_report(events['selected'], index, periods, domain, plane_of, distance_km, **limits,
                                             availability_min=args.availability_min, downtime_s=downtime_s,
                                             duration_s=duration_s,
                                             overhead_ms=args.overhead_ms, downtime_source=source,
                                             selection_mode=args.selection_mode)
    report['inputs'] = {name: file_digest(profile / name) for name in
                        ('replay.npz', 'laser_links.json', 'domain.json', 'selected_constellation.json')}
    report['inputs'] |= {'model_sha256': file_digest(ROOT / 'src/starlink_scenario.py'),
                         'created_utc': datetime.now(timezone.utc).isoformat()}
    try:
        selected = model.policy_selected_events(report['designed_vs_policy'], report['events'], index,
                                                limits['minimum_path_persistence_s'])
    except ValueError as exc:
        selected = None
        print(f'Eventi della politica non creati: {exc}')
    if not args.dry_run:
        if selected is None:
            raise SystemExit('Catalogo non aggiornato: la politica non serve abbastanza ingressi in ombra')
        events['destination_policy'], events['policy_selected'] = report, selected
        catalogue = profile / 'events.json'
        catalogue.write_text(json.dumps(events, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
        manifest = json.loads((profile / 'manifest.json').read_text(encoding='utf-8'))
        manifest['outputs']['events.json'] = describe(catalogue)
        atomic_json(profile / 'manifest.json', manifest)

    for mode in ('hot', 'cold'):
        row = measured[mode]
        print(f'{mode.capitalize()}: downtime mediano {row["downtime_median_s"]:.1f} s ({row["downtime_runs"]} prove), '
              f'durata mediana {row["duration_median_s"]:.1f} s ({row["duration_runs"]} prove)')
    print(f'Selezione con il downtime {args.selection_mode.capitalize()}, soglia {args.availability_min:.0%}: servite {report["summary"]["served"]} di {report["summary"]["shadow_entries"]} '
          f'ingressi in ombra, salti {report["summary"]["hops_histogram"]}')
    print('Sensibilita (soglia: servite, salti medi, permanenza media, latenza media)')
    for row in report['sensitivity']:
        mean = lambda field, fmt: format(row[field], fmt) if row[field] is not None else "-"
        print(f'  {row["availability_min"]:.0%}: {row["served"]:3d}  {mean("mean_hops", ".2f")}  '
              f'{mean("mean_stay_s", ".0f")} s  {mean("mean_control_latency_ms", ".2f")} ms')
    print('Eventi progettati e scelta della politica')
    for row in report['designed_vs_policy']:
        policy = row['policy']
        print(f'  {row["event_id"]}: progettato {row["designed"]["destination"]} ({row["designed"]["hops"]} salti, '
              f'fattibile {row["designed"]["feasible"]}, ammesso {row["designed"]["admissible"]}) -> politica '
              + (f'{policy["destination"]} ({policy["hops"]} salti, {policy["stay_s"]} s, {policy["control_latency_ms"]:.2f} ms)'
                 if policy else 'nessuna destinazione ammessa'))
    if selected:
        print('Eventi della politica')
        for pick in selected:
            note = f' (sostituisce {pick["designed_event_id"]})' if pick['replaces_designed_entry'] else ''
            print(f'  {pick["event_id"]}: {pick["source"]} -> {pick["destination"]}, {pick["hops"]} salti, '
                  f'{"altro piano" if pick["other_plane"] else "stesso piano"}, permanenza {pick["stay_s"]:.0f} s{note}')
    print('Catalogo non scritto (--dry-run)' if args.dry_run else
          f'Scritto {(profile / "events.json").relative_to(ROOT)}: installare con tools/install_scenario.py --refresh')


if __name__ == '__main__':
    main()
