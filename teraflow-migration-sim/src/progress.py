"""Durable experiment progress. Worker liveness is not experimental progress."""
from .storage import utc_now


def advance(previous, event):
    result = dict(previous or {})
    phase = event.get('phase')
    now = utc_now()
    result.setdefault('started_utc', now)
    if phase == 'continuous_comparison':
        result.update(phase=event['comparison_phase'], method=event.get('method'),
                      phase_started_utc=now, subphase=None, label=None, deadline_utc=None, operation_status=None)
    elif phase == 'departure_search':
        if result.get('subphase')!='departure_search':result['phase_started_utc']=now
        result.update(phase='planning',subphase='departure_search')
        for key in ('label','operation_status','limit_s','deadline_utc','examined_candidates','elapsed_s','selected','rejections','exhaustive'):
            result[key]=event.get(key)
    elif phase == 'calibration':
        replicas=event.get('replicas_per_mode',3)
        result.update(phase='calibration', method=event.get('method'), replica=event.get('replica'),replicas_per_mode=replicas,
                      calibration_index=event.get('replica', 1)+(replicas if event.get('method') == 'hot' else 0),
                      calibration_total=event.get('calibration_total',2*replicas), phase_started_utc=now)
    elif phase == 'preparation_operation':
        for key in ('operation', 'label', 'phase_started_utc', 'deadline_utc', 'limit_s', 'operation_status'):
            result[key] = event.get(key)
        result['subphase'] = event.get('operation')
        if event.get('error'): result['error'] = event['error']
    elif phase == 'infrastructure_wait':
        result.update(subphase='infrastructure',label=event.get('label'),
                      infrastructure_status=event.get('infrastructure_status'))
    elif phase == 'scenario_creation':
        result.update(phase='scenario_creation',subphase='scenario_creation',label=event.get('label'),operation_status='running',deadline_utc=None)
    elif phase == 'source_startup':
        result.update(subphase='start_source',label=event.get('label'),
                      startup_stage=event.get('startup_stage'),startup_status=event.get('operation_status'))
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
    elif phase == 'comparison_finished':
        result.update(phase='finished', outcome=event.get('outcome'), deadline_utc=None)
    elif phase == 'job_finished':
        result['worker_status'] = event.get('status')
    elif phase in ('cleanup','cleanup_verified'):
        result.update(subphase=phase,label=event.get('label'),deadline_utc=None,operation_status=None)
    elif phase in ('session_tick', 'baseline_check'):
        keys = ('completed_migrations', 'controller_satellite', 'fresh_ping_successes', 'udp_packets', 'active_slot')
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
