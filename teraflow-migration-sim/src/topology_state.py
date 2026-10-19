"""Read-only reconstruction of orbital UI state from durable evidence."""
from datetime import datetime, timezone
import json

from .probes import json_lines


def presentation(directory, tick, *, context=None, metadata=None, replay=False):
    metadata = metadata or {}
    context = context or {}
    result = dict(controller_satellite=None, source_satellite=None, target_satellite=None,
                  phase='unknown', migration_status='none', forwarding_observed=None,
                  updated_utc=None, stale=False, mode='replay' if replay else 'live')
    records = []
    def add(row, kind):
        orbital = row.get('orbital_s')
        if orbital is None or orbital > tick:
            return
        stamp = row.get('timestamp_utc')
        unix = row.get('unix_s')
        if stamp:
            unix = datetime.fromisoformat(stamp).timestamp()
        records.append((orbital, unix or 0, len(records), kind, row))

    for name, kind in [('observations', 'sample'), ('events', 'event'),
                       ('heartbeat', 'health'), ('authority', 'authority'), ('geometry', 'geometry')]:
        for row in json_lines(directory/(name+'.jsonl')):
            add(row, kind)
    operation = directory/'operation/events.jsonl'
    for row in json_lines(operation):
        add(row, 'event')
    # Continuous-session migration transitions carry the slot/satellite mapping.
    for path in directory.glob('migrations/*/operation/events.jsonl'):
        for row in json_lines(path):
            add(row, 'event')
    inputs = directory/'inputs.json'
    event = json.loads(inputs.read_text()).get('event', {}) if inputs.exists() else {}
    if event.get('sat_a') is not None and event.get('sat_b') is not None:
        result.update(source_satellite=event['sat_a'], target_satellite=event['sat_b'],
                      phase='planned', migration_status='planned')
    slots = {'sat-a': event.get('sat_a'), 'sat-b': event.get('sat_b')}
    health = {}
    latest_unix = 0
    controller = None
    for orbital, unix, _, kind, row in sorted(records):
        latest_unix = max(latest_unix, unix)
        if row.get('source_slot'):
            slots[row['source_slot']] = row.get('source_satellite')
            slots[row.get('target_slot')] = row.get('target_satellite')
        if kind == 'sample':
            controller = None if row.get('controllers_fenced') else row.get('controller_satellite')
            if row.get('active_slot'):
                slots[row['active_slot']] = controller
            result['forwarding_observed'] = (row.get('service_state') or {}).get('forwarding_observed')
            result['phase'] = row.get('phase', 'running')
            next_event = row.get('next_migration') or {}
            result.update(source_satellite=next_event.get('sat_a'), target_satellite=next_event.get('sat_b'),
                          migration_status='planned' if next_event else 'none')
        elif kind == 'geometry':
            # Geometry availability is never evidence of working forwarding.
            result['forwarding_observed'] = row.get('forwarding_observed')
        elif kind == 'health':
            health = row.get('controllers', {})
            slot = next((slot for slot, sid in slots.items() if sid == controller), None)
            if health.get(slot) is False:
                controller = None
        elif kind == 'authority':
            proxy = row.get('proxy') or {}
            slot = proxy.get('active')
            controller = slots.get(slot) if proxy.get('frozen') is False and health.get(slot) is True else None
        else:
            phase = row.get('phase', 'unknown')
            if phase in {'session_tick', 'planning', 'baseline_check', 'replanning', 'plan_admitted'}:
                continue
            result['phase'] = phase
            source = row.get('source_satellite', event.get('sat_a'))
            target = row.get('target_satellite', event.get('sat_b'))
            if source is not None:
                result.update(source_satellite=source, target_satellite=target)
            if phase == 'transfer':
                result['migration_status'] = 'transferring'
            elif phase in {'completed', 'service_verified'}:
                if target is not None:
                    controller = target
                result['migration_status'] = 'completed'
                if phase == 'service_verified':
                    result['forwarding_observed'] = True
            elif phase in {'source_stopped', 'source_frozen', 'source_stop', 'freeze', 'cutover',
                           'attempt_failed', 'rollback', 'failed', 'recovery_failed', 'recovery_required'}:
                controller = None
                for slot in (row.get('source_slot', 'sat-a'), row.get('target_slot', 'sat-b')):
                    health[slot] = False
                result['migration_status'] = 'failed' if phase in {'failed', 'recovery_failed', 'recovery_required'} else 'in_progress'
            elif phase in {'trigger', 'alignment', 'snapshot_initial', 'transfer_verified', 'target_start',
                           'restore_initial', 'restore_delta', 'verify', 'ack', 'quiescence'}:
                result['migration_status'] = 'in_progress'
    if not records and context.get('placement_status') == 'planned':
        next_event = context.get('next_migration') or {}
        result.update(phase='planned', source_satellite=context.get('controller_satellite'),
                      target_satellite=next_event.get('sat_b'), migration_status='planned')
    result['controller_satellite'] = controller
    if latest_unix:
        result['updated_utc'] = datetime.fromtimestamp(latest_unix, timezone.utc).isoformat()
        result['stale'] = not replay and datetime.now(timezone.utc).timestamp()-latest_unix > 20
    else:
        result['stale'] = not replay
    if metadata.get('controllers_fenced') and not replay:
        result['controller_satellite'] = None
    return result
