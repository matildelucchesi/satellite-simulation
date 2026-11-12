#!/usr/bin/env python3
"""Build the frozen two-plane Starlink scenario profile (phase 0, offline).

Writes only under artifacts/constellation-profiles/<profile>/: selection, derived scenario,
orbital replay, three-laser link intervals, domain, migration events and a manifest with
hashes. The active configuration (config/, results/) and the laboratory are not touched;
installing the profile is a separate, later step.
"""
from __future__ import annotations

import argparse
import copy
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.artifacts import describe, file_digest  # noqa: E402
from src.orbit import generate  # noqa: E402
from src import starlink_scenario as model  # noqa: E402
from tools.tle_catalog import parse_tle  # noqa: E402

DEFAULTS = {'profile': 'starlink-53-463-2x31', 'raan': [80.8, 82.8], 'domain_per_plane': 8,
            'trigger_lead_s': 900, 'minimum_destination_light_s': 600, 'minimum_path_persistence_s': 900}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')


def julian(iso):
    from sgp4.api import jday
    moment = datetime.fromisoformat(iso).astimezone(timezone.utc)
    return jday(moment.year, moment.month, moment.day, moment.hour, moment.minute,
                moment.second + moment.microsecond / 1e6)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--profile', default=DEFAULTS['profile'])
    parser.add_argument('--raan', type=float, nargs=2, default=DEFAULTS['raan'], metavar=('PLANE1', 'PLANE2'))
    parser.add_argument('--domain-per-plane', type=int, default=DEFAULTS['domain_per_plane'])
    parser.add_argument('--trigger-lead-s', type=int, default=DEFAULTS['trigger_lead_s'])
    parser.add_argument('--minimum-destination-light-s', type=int, default=DEFAULTS['minimum_destination_light_s'])
    parser.add_argument('--minimum-path-persistence-s', type=int, default=DEFAULTS['minimum_path_persistence_s'])
    parser.add_argument('--policy-availability-min', type=float, default=model.DESTINATION_POLICY['availability_min'],
                        help='Politica di destinazione: quota minima della permanenza con il controller disponibile')
    parser.add_argument('--policy-downtime-hot-s', type=float, default=model.DESTINATION_POLICY['downtime_s']['hot'],
                        help='Politica di destinazione: downtime Hot misurato (usato per la selezione)')
    parser.add_argument('--policy-downtime-cold-s', type=float, default=model.DESTINATION_POLICY['downtime_s']['cold'],
                        help='Politica di destinazione: downtime Cold misurato')
    parser.add_argument('--policy-duration-hot-s', type=float, default=model.DESTINATION_POLICY['duration_s']['hot'],
                        help='Politica di destinazione: durata Hot misurata della migrazione')
    parser.add_argument('--policy-duration-cold-s', type=float, default=model.DESTINATION_POLICY['duration_s']['cold'],
                        help='Politica di destinazione: durata Cold misurata (la permanenza parte dalla fine della piu lunga)')
    parser.add_argument('--force', action='store_true', help='Overwrite an existing profile directory')
    args = parser.parse_args(argv)

    profile = ROOT / 'artifacts/constellation-profiles' / args.profile
    if profile.exists() and not args.force:
        parser.error(f'{profile} exists; inspect it or pass --force')
    profile.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    log = lambda message: print(f'[{time.monotonic() - started:7.1f} s] {message}', flush=True)

    base = json.loads((ROOT / 'config/scenario.json').read_text(encoding='utf-8'))
    orbital = base['orbital']
    tle = ROOT / orbital['tle_file']
    jd, fraction = julian(orbital['reference_epoch_utc'])

    log('Selezione dei piani dal catalogo TLE')
    candidates = parse_tle(tle)
    rows = model.plane_rows(candidates, jd, fraction)
    planes = model.select_planes(rows, args.raan)
    satellites = []
    for number, plane in enumerate(planes, 1):
        for rank, row in enumerate(plane, 1):
            satellites.append({**row, 'plane': number, 'phase_rank': rank})
    selection = {'metadata': {
        'policy': model.POLICY, 'catalog_count': len(candidates), 'screened_count': len(rows),
        'tle_file': orbital['tle_file'], 'tle_sha256': file_digest(tle),
        'reference_epoch': {'jd': jd, 'fraction': fraction, 'iso_utc': orbital['reference_epoch_utc']},
        'screen': {'inclination_deg': [52.8, 53.4], 'screening_altitude_km': [455.0, 475.0],
                   'max_eccentricity': 0.002, 'max_tle_age_hours': 24.0, 'raan_cluster_gap_deg': 0.5},
        'requested_raan_deg': args.raan,
        'selected_plane_raan_centers_deg': [model._mean_angle([r['raan_deg'] for r in p]) for p in planes],
        'selected_plane_satellite_counts': [len(p) for p in planes],
        'max_ring_gap_deg': [model.max_ring_gap_deg(p) for p in planes],
        'synthetic_satellites': False}, 'satellites': satellites}
    write_json(profile / 'selected_constellation.json', selection)

    scenario = copy.deepcopy(base)
    altitudes = [row['screening_altitude_km'] for row in satellites]
    scenario['orbital'].update(constellation_profile=args.profile, satellites_total=len(satellites),
        satellites_per_plane=[len(p) for p in planes], planes=2,
        selected_raan_centers_deg=selection['metadata']['selected_plane_raan_centers_deg'],
        selected_altitude_range_km=[min(altitudes), max(altitudes)],
        inclination_screen_deg=[52.8, 53.4], sgp4_mean_semi_major_axis_altitude_screening_km=[455.0, 475.0])
    scenario['fso']['useful_throughput_bps'] = [1000000000]
    scenario['fso']['laser_terminals'] = {'intra_plane': 2, 'inter_plane': 1,
                                          'source': 'https://starlink.com/it/technology (3 laser, consultata 2026-11-07)',
                                          'assignment': 'ipotesi di progetto: 2 vicini nello stesso piano, 1 verso il piano adiacente'}
    scenario['domain'] = {'satellites_per_plane': args.domain_per_plane}
    # D10: controller software is on board every satellite, only state migrates.
    # Lab hygiene: the destination's store is emptied before the trigger, as on a real satellite.
    scenario['migration'] = {'software_on_board': True, 'clean_target_store_before_trigger': True,
                             'image_transfer': 'variante opzionale (aggiornamento software), disattivata'}
    scenario['migration_events'] = {'trigger_lead_s': args.trigger_lead_s,
                                    'minimum_destination_light_s': args.minimum_destination_light_s,
                                    'minimum_path_persistence_s': args.minimum_path_persistence_s,
                                    'event_specs': [{'hops': hops, 'other_plane': other, 'slot': slot, 'source': source} for hops, other, slot, source in model.EVENT_SPECS],
                                    'event_slots': model.EVENT_SLOTS,
                                    'destination_policy': {'availability_min': args.policy_availability_min,
                                                           'selection_mode': model.DESTINATION_POLICY['selection_mode'],
                                                           'downtime_s': {'hot': args.policy_downtime_hot_s, 'cold': args.policy_downtime_cold_s},
                                                           'duration_s': {'hot': args.policy_duration_hot_s, 'cold': args.policy_duration_cold_s},
                                                           'overhead_ms': model.DESTINATION_POLICY['overhead_ms'],
                                                           'rule': 'ammessa se downtime (modalita selection_mode) / permanenza <= 1 - availability_min, con la permanenza dalla fine della migrazione piu lunga; fra le ammesse latenza media di controllo minima',
                                                           'role': 'politica alternativa agli eventi progettati, scelta prima dell avvio dell esperimento'},
                                    'selection': 'combinazione 12: 1 salto stesso piano, 5 salti stesso piano, 7 salti verso l altro piano; sorgente e fascia del giorno fissate per evento; destinazione e percorso nel dominio; destinazione al sole piu a lungo della sorgente e almeno per la soglia'}
    # Experiment design: replicas per event and mode, one discarded warm-up run; the Hot/Cold
    # order inside each pair is drawn with a seed chosen and recorded by every experiment.
    scenario['experiment'] = {'replicas': 3, 'warmup_runs': 1, 'seed': None}
    # Hypotheses of the laser model, stated where the parameters live.
    scenario['fso']['alignment_hypothesis'] = ('ipotesi: prima di ogni tentativo il percorso multi-hop deve restare '
                                               'disponibile per alignment_s secondi di fila; i laser gia puntati non lo richiederebbero')
    scenario['fso']['propagation'] = {'speed_km_s': 299792.458, 'model': 'ritardo = distanza / velocita della luce, per collegamento'}
    write_json(profile / 'scenario.json', scenario)

    log('Propagazione SGP4 e illuminazione sulle 24 ore (replay)')
    generate(ROOT, profile / 'replay.npz', scenario=scenario, selection=selection)

    import numpy as np
    arrays = np.load(profile / 'replay.npz', allow_pickle=False)
    ids = [int(value) for value in arrays['ids']]
    positions, eclipsed = arrays['positions'], arrays['eclipsed']
    plane_of = {row['norad_id']: row['plane'] - 1 for row in satellites}
    plane_index = [plane_of[sid] for sid in ids]

    log('Assegnazione dei 3 laser secondo per secondo')
    intervals = model.laser_links(positions, ids, plane_index, max_range_km=scenario['fso']['max_range_km'],
                                  alignment_s=scenario['fso']['alignment_s'])
    if not model.terminal_usage_ok(intervals, ids, plane_index):
        raise SystemExit('Regola dei 3 laser violata')
    duration = len(positions)
    write_json(profile / 'laser_links.json', {'policy': model.POLICY, 'inputs': {
        'duration_s': duration, 'range_km': scenario['fso']['max_range_km'], 'alignment_s': scenario['fso']['alignment_s'],
        'terminals': {'intra_plane': 2, 'inter_plane': 1}}, 'link_count': len(intervals), 'links': intervals})

    log('Indice dei percorsi multi-hop')
    index = model.LinkIndex(intervals, ids, duration)
    periods = {sid: model.lit_periods(eclipsed[:, column]) for column, sid in enumerate(ids)}
    domain_a, domain_b = model.choose_domain(planes, args.domain_per_plane)
    domain = domain_a + domain_b

    log('Statistiche di copertura')
    inter_time = {sid: 0 for sid in ids}
    for row in intervals:
        if row['kind'] == 'inter':
            for sid in (row['sat_a'], row['sat_b']):
                inter_time[sid] += row['end_s'] - row['start_s']
    domain_connected = 0
    constellation_connected = 0
    for start, end, graph in index.segments:
        sub = {sid: {n for n in graph[sid] if n in domain} for sid in domain}
        if len(model.component(sub, domain[0])) == len(domain):
            domain_connected += end - start
        if len(model.component(graph, ids[0])) == len(ids):
            constellation_connected += end - start
    durations = {kind: [r['end_s'] - r['start_s'] for r in intervals if r['kind'] == kind] for kind in ('intra', 'inter')}
    stats = {
        'links': {kind: {'count': len(values), 'median_duration_s': statistics.median(values) if values else None,
                         'min_duration_s': min(values) if values else None} for kind, values in durations.items()},
        'inter_partner_time_fraction': {'min': min(inter_time.values()) / duration,
                                        'median': statistics.median(inter_time.values()) / duration},
        'constellation_connected_fraction': constellation_connected / duration,
        'domain_internal_connected_fraction': domain_connected / duration,
        'path_segments': len(index.segments)}
    write_json(profile / 'domain.json', {'policy': model.POLICY, 'satellites_per_plane': args.domain_per_plane,
        'plane_1': domain_a, 'plane_2': domain_b,
        'rule': 'arco contiguo del piano 1 (argomento di latitudine crescente) e i satelliti del piano 2 piu vicini all arco',
        'service_endpoints': 'da definire in M2 sulla base della connettivita interna del dominio',
        'statistics': {'domain_internal_connected_fraction': stats['domain_internal_connected_fraction']}})

    log('Catalogo degli eventi di migrazione')
    events = model.migration_events(index, periods, domain, trigger_lead_s=args.trigger_lead_s,
                                    minimum_destination_light_s=args.minimum_destination_light_s,
                                    minimum_path_persistence_s=args.minimum_path_persistence_s)
    feasible = [e for e in events if e['destination'] is not None]
    chosen = model.designed_events(index, periods, domain, plane_of, model.EVENT_SPECS, slots=model.EVENT_SLOTS,
                                   trigger_lead_s=args.trigger_lead_s,
                                   minimum_destination_light_s=args.minimum_destination_light_s,
                                   minimum_path_persistence_s=args.minimum_path_persistence_s)
    log('Politica di destinazione (disponibilita e latenza di controllo)')
    column = {sid: position for position, sid in enumerate(ids)}
    distance_km = lambda a, b, tick: float(np.linalg.norm(positions[int(tick), column[a]] - positions[int(tick), column[b]]))
    destination_policy = model.destination_policy_report(
        chosen, index, periods, domain, plane_of, distance_km, trigger_lead_s=args.trigger_lead_s,
        minimum_destination_light_s=args.minimum_destination_light_s,
        minimum_path_persistence_s=args.minimum_path_persistence_s, availability_min=args.policy_availability_min,
        downtime_s={'hot': args.policy_downtime_hot_s, 'cold': args.policy_downtime_cold_s},
        duration_s={'hot': args.policy_duration_hot_s, 'cold': args.policy_duration_cold_s})
    policy_selected = model.policy_selected_events(destination_policy['designed_vs_policy'], destination_policy['events'],
                                                   index, args.minimum_path_persistence_s)
    hop_histogram = {}
    for event in feasible:
        hop_histogram[str(event['hops'])] = hop_histogram.get(str(event['hops']), 0) + 1
    write_json(profile / 'events.json', {'policy': model.POLICY, 'parameters': scenario['migration_events'],
        'event_count': len(events), 'feasible_count': len(feasible), 'hops_histogram': hop_histogram,
        'selected': chosen, 'events': events, 'destination_policy': destination_policy,
        'policy_selected': policy_selected})

    outputs = ['selected_constellation.json', 'scenario.json', 'replay.npz', 'replay.json',
               'laser_links.json', 'domain.json', 'events.json']
    manifest = {'schema_version': 1, 'policy': model.POLICY, 'profile': args.profile,
                'created_utc': datetime.now(timezone.utc).isoformat(), 'installed': False,
                'inputs': {'tle': describe(tle), 'base_scenario_sha256': file_digest(ROOT / 'config/scenario.json'),
                           'builder_sha256': file_digest(Path(__file__)), 'model_sha256': file_digest(ROOT / 'src/starlink_scenario.py'),
                           'parameters': vars(args) | {'force': None}},
                'outputs': {name: describe(profile / name) for name in outputs},
                'statistics': stats,
                'summary': {'satellites': len(ids), 'per_plane': [len(p) for p in planes],
                            'raan_deg': selection['metadata']['selected_plane_raan_centers_deg'],
                            'altitude_km': [min(altitudes), max(altitudes)], 'domain': len(domain),
                            'events': len(events), 'feasible_events': len(feasible),
                            'selected_events': [e['event_id'] for e in chosen]}}
    write_json(profile / 'manifest.json', manifest)
    log('Profilo scritto in ' + str(profile))
    print(json.dumps(manifest['summary'] | {'statistics': stats}, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
