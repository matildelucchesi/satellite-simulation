"""Durable experiment progress. Worker liveness is not experimental progress."""
from .storage import utc_now


def advance(previous, event):
    result = dict(previous or {})
    phase = event.get('phase')
    now = utc_now()
    result.setdefault('started_utc', now)
    if phase in ('event_comparison', 'comparison_run'):
        # A new migration of the verification or of the event experiment starts.
        result.update(phase=phase, subphase=None, label=event.get('label'), method=event.get('method'),
                      comparison_id=event.get('comparison_id'), event_index=event.get('event_index'),
                      event_total=event.get('event_total'), replica=event.get('replica'), replica_total=event.get('replica_total'),
                      warmup=event.get('warmup'), position=event.get('position'), run_total=event.get('run_total'),
                      phase_started_utc=now, deadline_utc=None, operation_status=None)
    elif phase == 'preparation_operation':
        for key in ('operation', 'label', 'phase_started_utc', 'deadline_utc', 'limit_s', 'operation_status'):
            result[key] = event.get(key)
        result['subphase'] = event.get('operation')
        if event.get('error'): result['error'] = event['error']
    elif phase == 'infrastructure_wait':
        result.update(subphase='infrastructure', label=event.get('label'),
                      infrastructure_status=event.get('infrastructure_status'))
    elif phase == 'source_startup':
        result.update(subphase='start_source', label=event.get('label'),
                      startup_stage=event.get('startup_stage'), startup_status=event.get('operation_status'))
    elif phase == 'restore_progress':
        result['restore_counts'] = event.get('counts')
        result['restore_entity'] = event.get('entity')
        if event.get('verification'): result['restore_verification'] = event['verification']
    elif phase == 'restore_request':
        if event.get('request_status') == 'running':
            result['current_request'] = event['request']
            return result  # liveness/started work is not completed progress
        result['last_request'] = event['request']
        result['current_request'] = None
    elif phase == 'job_finished':
        result['worker_status'] = event.get('status')
    elif phase in ('cleanup', 'cleanup_verified'):
        result.update(subphase=phase, label=event.get('label'), deadline_utc=None, operation_status=None)
    elif phase == 'baseline_check':
        keys = ('fresh_ping_successes', 'udp_packets', 'active_slot')
        sample = {key: event[key] for key in keys if key in event}
        changed = any(result.get(key) != value for key, value in sample.items())
        result.update(sample)
        if not changed: return result
    else:
        result['subphase'] = phase
        result['label'] = None
        result['operation_status'] = None
        result['deadline_utc'] = None
    result['last_progress_utc'] = now
    if event.get('run_id'): result['run_id'] = event['run_id']
    return result
