"""Phase 3 experiment: Hot and Cold migrations on the frozen catalogue events (D2, D3, D12).

Each event is run with both modes from the same orbital instant, alternating which mode goes
first. Measures are taken from the live runs; orbital feasibility is evaluated afterwards on the
measured durations (D2). Missing measures stay None and differences are computed only when both
values exist.
"""
from __future__ import annotations

import copy
import csv
import json
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
           'attempt': metrics.get('attempt'), 'software_on_board': result.get('software_on_board')}
    row['phases'] = phase_breakdown(Path(root) / 'results/runs' / str(result.get('run_id')))
    row['feasibility'] = feasibility(event, row['total_operation_s'], orbit)
    return row


def differences(runs):
    """Cold minus Hot for each comparable measure; None when either side is missing."""
    hot, cold = runs.get('hot'), runs.get('cold')
    if not hot or not cold:
        return {}
    return {field: (cold[field] - hot[field]) if hot.get(field) is not None and cold.get(field) is not None else None
            for field in DIFFERENCES}


def write_csv(path, events):
    columns = ['event', 'catalog_event_id', 'source', 'destination', 'hops', 'trigger_s', 'order', 'method', 'run_id',
               'success', 'controller_downtime_s', 'total_operation_s', 'ping_recovery_s', 'lost_pings', 'observed_pings',
               'fits_before_shadow', 'multi_hop_path_whole_operation', 'direct_contact_whole_operation'] + [
               'phase_' + name + '_s' for name in PHASES]
    with open(path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for row in events:
            for method in row['order']:
                run = row['runs'].get(method)
                if not run:
                    continue
                seconds = run['phases']['seconds']
                feasible = run['feasibility']
                writer.writerow([row['index'], row['catalog_event_id'], row['source'], row['destination'], row['hops'],
                                 row['trigger_s'], '>'.join(row['order']), method, run['run_id'], run['success'],
                                 run['controller_downtime_s'], run['total_operation_s'], run['ping_recovery_s'],
                                 run['lost_pings'], run['observed_pings'], feasible.get('fits_before_shadow'),
                                 feasible.get('multi_hop_path_whole_operation'), feasible.get('direct_contact_whole_operation')] +
                                [seconds.get(name) for name in PHASES])


def compare(app):
    root = Path(app.root)
    catalog_path = root / 'config/migration_events.json'
    if not catalog_path.exists():
        raise ValueError('Catalogo degli eventi assente: installare un profilo di scenario')
    selected = json.loads(catalog_path.read_text(encoding='utf-8'))['selected']
    rates = app.scenario['fso']['useful_throughput_bps']
    if len(rates) != 1:
        raise ValueError('Il confronto a eventi richiede una sola velocità nello scenario installato')
    identifier = 'events-' + uuid.uuid4().hex
    directory = root / 'results/event-comparisons' / identifier
    directory.mkdir(parents=True)
    output = {'schema_version': 1, 'comparison_id': identifier, 'created_utc': utc_now(), 'purpose': 'event-comparison',
              'profile': app.scenario.get('orbital', {}).get('constellation_profile'), 'rate_bps': rates[0],
              'software_on_board': bool(app.scenario.get('migration', {}).get('software_on_board')),
              'inputs': {'catalog_sha256': file_digest(catalog_path),
                         'scenario_sha256': file_digest(root / 'config/scenario.json'),
                         'fixture_sha256': file_digest(root / 'config/fixture.json')},
              'order_policy': 'Hot prima negli eventi dispari, Cold prima negli eventi pari',
              'acceptance': 'api_equivalence+target_authority+10_fresh_consecutive_pings',
              'event_total': len(selected), 'events': [], 'complete': False, 'recovery_required': False}

    def save():
        atomic_json(directory / 'metadata.json', output)

    save()
    for index, entry in enumerate(selected):
        event = app.catalog_event(entry, f'event{index + 1}', ['source_shadow'], 'event-comparison')
        order = ('hot', 'cold') if index % 2 == 0 else ('cold', 'hot')
        row = {'index': index + 1, 'catalog_event_id': entry['event_id'], 'source': entry['source'],
               'destination': entry['destination'], 'hops': entry['hops'], 'path': entry['path'],
               'trigger_s': entry['trigger_s'], 'source_light_remaining_s': entry['source_light_remaining_s'],
               'destination_light_remaining_s': entry.get('destination_light_remaining_s'),
               'order': list(order), 'runs': {}}
        output['events'].append(row)
        for method in order:
            if app.cancel and app.cancel.is_set():
                output['reason'] = 'interrupted'
                save()
                return output
            output['current'] = {'event': index + 1, 'method': method}
            save()
            app.publish({'phase': 'event_comparison', 'comparison_id': identifier, 'event_index': index + 1,
                         'event_total': len(selected), 'method': method,
                         'label': f'Evento {index + 1}/{len(selected)} · {method.upper()}'})
            result = app.run(method, rates[0], copy.deepcopy(event), purpose='event-comparison')
            run = summarize_run(root, result, event, app.orbit)
            row['runs'][method] = run
            output['recovery_required'] = output['recovery_required'] or run['recovery_required']
            if not (run['success'] and run['baseline_valid'] and run['service_verified']):
                output['reason'] = run['outcome'] if not run['success'] else 'service_not_verified'
                output['current'] = None
                save()
                write_csv(directory / 'summary.csv', output['events'])
                return output
        row['cold_minus_hot'] = differences(row['runs'])
        output['current'] = None
        save()
    output['complete'] = True
    output['finished_utc'] = utc_now()
    save()
    write_csv(directory / 'summary.csv', output['events'])
    return output


def list_comparisons(root):
    rows = []
    for path in sorted(Path(root, 'results/event-comparisons').glob('events-*/metadata.json'),
                       key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            rows.append(json.loads(path.read_text(encoding='utf-8')))
        except ValueError:
            continue
    return rows
