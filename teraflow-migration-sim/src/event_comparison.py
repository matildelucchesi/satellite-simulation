"""Phase 3 experiment: Hot and Cold migrations on the frozen catalogue events (D2, D3, D12).

Each event is run with both modes from the same orbital instant and the same multi-hop path,
several times (replicas). A warm-up run comes first and is excluded. Replicas run one after the
other over all events and the Hot/Cold order inside each pair is drawn with a recorded seed.
Measures are taken from the live runs; orbital feasibility is evaluated afterwards on the measured
durations (D2). Missing measures stay None; differences and statistics use only paired values.
"""
from __future__ import annotations

import copy
import csv
import json
import math
import random
import secrets
import statistics
import uuid
from pathlib import Path

from .artifacts import file_digest
from .results import requires_recovery, summary_metrics
from .storage import atomic_json, utc_now

PHASES = ('snapshot', 'source_stop', 'freeze', 'controller_startup', 'target_perimeter_cleanup', 'api_restore',
          'delta_apply', 'api_verification', 'queued_topology_apply', 'cutover', 'image_load_shared_daemon')
DIFFERENCES = ('controller_downtime_s', 'total_operation_s', 'ping_recovery_s', 'lost_pings')


def phase_breakdown(run_directory):
    """Measured seconds per backend operation (summed when an operation repeats) and repetitions."""
    totals, counts = {}, {}
    path = Path(run_directory) / 'operations.jsonl'
    if not path.exists():
        return {'seconds': {}, 'counts': {}}
    for line in path.read_text(encoding='utf-8').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        name = row.get('name') or row.get('operation')
        if name is None or 'elapsed_s' not in row:
            continue
        totals[name] = totals.get(name, 0.0) + row['elapsed_s']
        counts[name] = counts.get(name, 0) + 1
    return {'seconds': totals, 'counts': counts}


def feasibility(event, total_operation_s, orbit):
    """Would the measured migration have fitted the orbital situation of this event?"""
    source, target, trigger = event['sat_a'], event['sat_b'], event['trigger_s']
    out = {'deadline_window_s': event['deadline_window_s'], 'path_hops': event.get('hops'),
           'direct_contact_at_trigger': bool(orbit.contact(source, target, trigger))}
    if total_operation_s is None:
        out.update(fits_before_shadow=None, multi_hop_path_whole_operation=None, direct_contact_whole_operation=None)
        return out
    end = min(int(trigger + total_operation_s), orbit.duration - 1)
    link = getattr(orbit, 'migration_link', orbit.contact)
    out.update(fits_before_shadow=total_operation_s <= event['deadline_window_s'],
               multi_hop_path_whole_operation=bool(link(source, target, trigger) and link(source, target, end)),
               direct_contact_whole_operation=bool(orbit.contact(source, target, trigger) and orbit.contact(source, target, end)))
    return out


def summarize_run(root, result, event, orbit):
    ping = ((result.get('probes') or {}).get('ping')) or {}
    metrics = summary_metrics(result)
    row = {'run_id': result.get('run_id'), 'method': result.get('method'), 'outcome': result.get('outcome'),
           'failure_reason': result.get('failure_reason'), 'success': bool(result.get('success')),
           'baseline_valid': bool((result.get('baseline') or {}).get('success')),
           'service_verified': bool((result.get('service_verification') or {}).get('success')),
           'recovery_required': requires_recovery(result),
           'controller_downtime_s': metrics.get('controller_downtime_s'),
           'total_operation_s': metrics.get('total_operation_s'),
           'ping_recovery_s': metrics.get('ping_recovery_s'),
           'observed_pings': ping.get('observed_probes'), 'lost_pings': ping.get('lost_probes'),
           'bytes_sent': result.get('bytes_sent'), 'bytes_received': result.get('bytes_received'),
           'attempt': metrics.get('attempt'), 'software_on_board': result.get('software_on_board')}
    row['phases'] = phase_breakdown(Path(root) / 'results/runs' / str(result.get('run_id')))
    receipts = [event.get('receipt') or {} for event in result.get('events') or [] if event.get('phase') == 'transfer_verified']
    row['transfer_one_way_delay_s'] = next((r['one_way_delay_s'] for r in receipts if r.get('one_way_delay_s') is not None), None)
    row['feasibility'] = feasibility(event, row['total_operation_s'], orbit)
    return row


def differences(runs):
    """Cold minus Hot for each comparable measure; None when either side is missing."""
    hot, cold = runs.get('hot'), runs.get('cold')
    if not hot or not cold:
        return {}
    return {field: (cold[field] - hot[field]) if hot.get(field) is not None and cold.get(field) is not None else None
            for field in DIFFERENCES}


def describe_values(values):
    """Median, quartiles and range of the measured values; missing values are left out."""
    known = sorted(value for value in values if value is not None)
    if not known:
        return {'n': 0, 'median': None, 'q1': None, 'q3': None, 'min': None, 'max': None}
    def quantile(fraction):
        position = fraction * (len(known) - 1)
        low = math.floor(position)
        high = min(low + 1, len(known) - 1)
        return known[low] + (known[high] - known[low]) * (position - low)
    return {'n': len(known), 'median': quantile(.5), 'q1': quantile(.25), 'q3': quantile(.75),
            'min': known[0], 'max': known[-1]}


def paired_difference(pairs, seed, resamples=2000):
    """Cold minus Hot over replicas with both values: median and a 95 % percentile bootstrap
    interval of the median (seeded, so the report is reproducible). No interval below 2 pairs."""
    differences = [cold - hot for hot, cold in pairs if hot is not None and cold is not None]
    summary = describe_values(differences)
    summary['ci95'] = None
    if len(differences) >= 2:
        generator = random.Random(seed)
        medians = sorted(statistics.median(generator.choices(differences, k=len(differences))) for _ in range(resamples))
        summary['ci95'] = [medians[int(.025 * (resamples - 1))], medians[int(.975 * (resamples - 1))]]
    return summary


def event_statistics(row, seed):
    """Per-event summary over the replicas, warm-up excluded."""
    out = {}
    for field in ('controller_downtime_s', 'total_operation_s', 'lost_pings'):
        values = {method: [(replica['runs'].get(method) or {}).get(field) for replica in row['replicas']]
                  for method in ('hot', 'cold')}
        pairs = [((replica['runs'].get('hot') or {}).get(field), (replica['runs'].get('cold') or {}).get(field))
                 for replica in row['replicas']]
        out[field] = {'hot': describe_values(values['hot']), 'cold': describe_values(values['cold']),
                      'cold_minus_hot': paired_difference(pairs, seed)}
    return out


def schedule(events, replicas, warmup_runs, seed):
    """Run order: warm-up first, then replica by replica over all events; inside each Hot/Cold
    pair the order is drawn at random. Replica-major order spreads slow drifts of the host over
    every event instead of tying an event to one part of the day."""
    generator = random.Random(seed)
    plan = []
    for number in range(warmup_runs):
        plan.append({'event': 1, 'replica': 0, 'method': generator.choice(('hot', 'cold')), 'warmup': True})
    for replica in range(1, replicas + 1):
        for event in range(1, len(events) + 1):
            for method in generator.sample(('hot', 'cold'), 2):
                plan.append({'event': event, 'replica': replica, 'method': method, 'warmup': False})
    for position, item in enumerate(plan, 1):
        item['position'] = position
    return plan


def write_csv(path, output):
    columns = ['position', 'warmup', 'replica', 'event', 'catalog_event_id', 'source', 'destination', 'hops', 'other_plane',
               'trigger_s', 'pair_order', 'method', 'run_id', 'success', 'controller_downtime_s', 'total_operation_s',
               'ping_recovery_s', 'lost_pings', 'observed_pings', 'transfer_one_way_delay_s', 'fits_before_shadow',
               'multi_hop_path_whole_operation'] + ['phase_' + name + '_s' for name in PHASES]
    events = {row['index']: row for row in output['events']}
    with open(path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for item in output['design']['schedule']:
            row = events[item['event']]
            if item['warmup']:
                run, order = output.get('warmup', {}).get('run'), [item['method']]
            else:
                replica = next((entry for entry in row['replicas'] if entry['replica'] == item['replica']), None)
                run, order = (replica['runs'].get(item['method']), replica['order']) if replica else (None, [])
            if not run:
                continue
            seconds, feasible = run['phases']['seconds'], run['feasibility']
            writer.writerow([item['position'], item['warmup'], item['replica'], row['index'], row['catalog_event_id'],
                             row['source'], row['destination'], row['hops'], row['other_plane'], row['trigger_s'],
                             '>'.join(order), item['method'], run['run_id'], run['success'], run['controller_downtime_s'],
                             run['total_operation_s'], run['ping_recovery_s'], run['lost_pings'], run['observed_pings'],
                             run.get('transfer_one_way_delay_s'), feasible.get('fits_before_shadow'),
                             feasible.get('multi_hop_path_whole_operation')] + [seconds.get(name) for name in PHASES])


MAX_CONSECUTIVE_FAILURES = 3


def compare(app):
    root = Path(app.root)
    catalog_path = root / 'config/migration_events.json'
    if not catalog_path.exists():
        raise ValueError('Catalogo degli eventi assente: installare un profilo di scenario')
    selected = json.loads(catalog_path.read_text(encoding='utf-8'))['selected']
    rates = app.scenario['fso']['useful_throughput_bps']
    if len(rates) != 1:
        raise ValueError('Il confronto a eventi richiede una sola velocità nello scenario installato')
    settings = app.scenario.get('experiment', {})
    replicas, warmup_runs = int(settings.get('replicas', 3)), int(settings.get('warmup_runs', 1))
    seed = int(settings['seed']) if settings.get('seed') is not None else secrets.randbits(32)
    plan = schedule(selected, replicas, warmup_runs, seed)
    identifier = 'events-' + uuid.uuid4().hex
    directory = root / 'results/event-comparisons' / identifier
    directory.mkdir(parents=True)
    output = {'schema_version': 2, 'comparison_id': identifier, 'created_utc': utc_now(), 'purpose': 'event-comparison',
              'profile': app.scenario.get('orbital', {}).get('constellation_profile'), 'rate_bps': rates[0],
              'software_on_board': bool(app.scenario.get('migration', {}).get('software_on_board')),
              'inputs': {'catalog_sha256': file_digest(catalog_path),
                         'scenario_sha256': file_digest(root / 'config/scenario.json'),
                         'fixture_sha256': file_digest(root / 'config/fixture.json')},
              'design': {'replicas': replicas, 'warmup_runs': warmup_runs, 'seed': seed,
                         'order_policy': 'replica per replica su tutti gli eventi; ordine Hot/Cold casuale in ogni coppia',
                         'statistics': 'mediana e quartili per evento; Cold − Hot appaiato con intervallo bootstrap al 95 % della mediana',
                         'failure_policy': f'una prova non riuscita resta mancante e l esperimento prosegue; si ferma se serve il ripristino o dopo {MAX_CONSECUTIVE_FAILURES} prove non riuscite di fila',
                         'schedule': plan},
              'acceptance': 'api_equivalence+target_authority+10_fresh_consecutive_pings',
              'event_total': len(selected), 'run_total': len(plan), 'completed_runs': 0, 'failed_runs': 0,
              'events': [], 'complete': False, 'recovery_required': False}
    events = {}
    for index, entry in enumerate(selected, 1):
        row = {'index': index, 'catalog_event_id': entry['event_id'], 'source': entry['source'],
               'destination': entry['destination'], 'hops': entry['hops'], 'other_plane': bool(entry.get('other_plane')),
               'path': entry['path'], 'trigger_s': entry['trigger_s'], 'source_light_remaining_s': entry['source_light_remaining_s'],
               'destination_light_remaining_s': entry.get('destination_light_remaining_s'), 'replicas': []}
        events[index] = (row, app.catalog_event(entry, f'event{index}', ['source_shadow'], 'event-comparison'))
        output['events'].append(row)

    def save():
        atomic_json(directory / 'metadata.json', output)

    def finish(reason=None):
        output['current'] = None
        for row, _ in events.values():
            row['statistics'] = event_statistics(row, seed)
        if reason:
            output['reason'] = reason
        else:
            output['complete'] = True
            output['finished_utc'] = utc_now()
        save()
        write_csv(directory / 'summary.csv', output)
        return output

    save()
    consecutive_failures = 0
    for item in plan:
        if app.cancel and app.cancel.is_set():
            return finish('interrupted')
        row, event = events[item['event']]
        output['current'] = {**item, 'total': len(plan)}
        save()
        label = 'Riscaldamento' if item['warmup'] else f'Replica {item["replica"]}/{replicas}'
        app.publish({'phase': 'event_comparison', 'comparison_id': identifier, 'event_index': item['event'],
                     'event_total': len(selected), 'method': item['method'], 'replica': item['replica'],
                     'replica_total': replicas, 'warmup': item['warmup'], 'position': item['position'], 'run_total': len(plan),
                     'label': f'Prova {item["position"]}/{len(plan)} · Evento {item["event"]}/{len(selected)} · {label} · {item["method"].upper()}'})
        result = app.run(item['method'], rates[0], copy.deepcopy(event), purpose='event-comparison')
        run = summarize_run(root, result, event, app.orbit)
        if item['warmup']:
            output['warmup'] = {'event': item['event'], 'method': item['method'], 'run': run}
        else:
            replica = next((entry for entry in row['replicas'] if entry['replica'] == item['replica']), None)
            if replica is None:
                replica = {'replica': item['replica'], 'order': [], 'runs': {}}
                row['replicas'].append(replica)
            replica['order'].append(item['method'])
            replica['runs'][item['method']] = run
            replica['cold_minus_hot'] = differences(replica['runs'])
        output['recovery_required'] = output['recovery_required'] or run['recovery_required']
        accepted = run['success'] and run['baseline_valid'] and run['service_verified']
        output['completed_runs'] += 1
        if not accepted:
            output['failed_runs'] += 1
            consecutive_failures += 1
        else:
            consecutive_failures = 0
        if run['recovery_required']:
            return finish('recovery_required')
        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            return finish('too_many_failures')
        save()
    return finish()


def list_comparisons(root, running_since=None):
    """Recorded experiments, newest first.

    An unfinished experiment gets statistics over the replicas measured so far (``statistics_partial``).
    One left without a final reason and not started by the running experiment job (``running_since``:
    creation time of that job, None when no experiment holds the laboratory) lost its worker: it is
    reported as ``worker_stopped`` instead of looking still in progress. The files are not changed."""
    rows = []
    for path in sorted(Path(root, 'results/event-comparisons').glob('events-*/metadata.json'),
                       key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            row = json.loads(path.read_text(encoding='utf-8'))
        except ValueError:
            continue
        if row.get('schema_version', 0) >= 2 and not row.get('complete'):
            seed = (row.get('design') or {}).get('seed') or 0
            for event in row.get('events', []):
                if event.get('statistics') is None:
                    event['statistics'] = event_statistics(event, seed)
                    row['statistics_partial'] = True
            running = running_since is not None and row.get('created_utc', '') >= running_since
            if not row.get('reason') and not running:
                row['reason'] = 'worker_stopped'
                row['current'] = None
        rows.append(row)
    return rows
