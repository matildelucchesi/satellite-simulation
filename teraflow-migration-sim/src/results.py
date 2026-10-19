"""Shared acceptance, recovery propagation and measurement projections."""
import json


def requires_recovery(value):
    if isinstance(value, dict):
        return (value.get('recovery_required') is True or value.get('outcome') == 'recovery_required'
                or value.get('reason') == 'recovery_required'
                or any(requires_recovery(v) for v in value.values() if isinstance(v, (dict, list))))
    return isinstance(value, list) and any(requires_recovery(v) for v in value)


def finalize(result):
    """Normalize a new live result; protocol completion is not acceptance."""
    result['recovery_required'] = bool(result.get('recovery_required', False))
    interrupted = result.get('interrupted', False) or result.get('outcome') == 'interrupted'
    result['interrupted'] = bool(interrupted)
    result.setdefault('migration_completed', False)
    result.setdefault('observation_complete', False)
    result.setdefault('experimental_valid', True)
    service = (result.get('service_verification') or {}).get('success') is True
    result['success'] = (result['migration_completed'] and service and result['observation_complete']
                         and result['experimental_valid'] is True and not interrupted
                         and not result['recovery_required'] and not result.get('failure_reason'))
    if result['recovery_required']: result['outcome'] = 'recovery_required'
    elif interrupted: result['outcome'] = 'interrupted'
    elif result.get('outcome') == 'invalid_baseline' or result.get('baseline', {}).get('success') is False: result['outcome'] = 'invalid_baseline'
    elif result['experimental_valid'] is False: result['outcome'] = 'invalid_lab'
    elif result['success']: result['outcome'] = 'success'
    else: result['outcome'] = 'experimental_failure'
    if result['success']:
        result['failure_reason'] = result['failure_phase'] = None
    result['schema_version'] = 4
    return result


def read_result(document):
    """Add nullable fields to historical records without inventing evidence."""
    result = dict(document)
    for field in ('migration_completed', 'observation_complete', 'experimental_valid',
                  'service_verification_s', 'observation_s'):
        result.setdefault(field, None)
    result['service_verification'] = result.get('service_verification') or {'success': None}
    result.setdefault('recovery_required', result.get('outcome') == 'recovery_required')
    result['metrics']=summary_metrics(result)
    return result


def transfer_metrics(result, image_name):
    receipts = [row['receipt'] for row in result.get('events', [])
                if row['phase'] == 'transfer_verified']
    images = [row['receipt']['useful_throughput_bps'] for row in result.get('events', [])
              if row['phase'] == 'transfer_verified' and row.get('payload') == image_name]
    delivered = {r['sha256']: r['received_bytes'] for r in receipts}
    useful = sum(delivered.values())
    return {'image_throughput_bps': min(images) if images else None,
            'useful_payload_bytes': useful,
            'restarted_payload_bytes': max(0, result.get('bytes_sent', 0)-useful),
            'retries': max(0, result['attempt']-1) if 'attempt' in result else None,
            'tcp_retransmissions': None}


def summary_metrics(result):
    ping = (result.get('probes') or {}).get('ping') or {}
    return {**{key: result.get(key) for key in ('controller_downtime_s', 'total_operation_s',
                'service_verification_s', 'observation_s', 'image_throughput_bps', 'attempt',
                'retries', 'restarted_payload_bytes')},
            'ping_recovery_s': ping.get('time_to_stable_recovery_s'),
            'service_verified': (result.get('service_verification') or {}).get('success'),
            'ping_continuous': ping.get('continuous_during_observation')}


def campaign_summary(root, runs):
    path = root/'results/campaign.json'
    execution = json.loads(path.read_text()) if path.exists() else {}
    selected = [r for r in runs if r.get('purpose') == 'primary']
    if 'runs' in execution:
        selected = [r for r in selected if r['run_id'] in execution['runs']]
    recorded = {(r.get('event', {}).get('event_id'), r['method'], r['configured_rate_bps']) for r in selected}
    expected = {tuple(row) for row in execution.get('expected_cases', [])}
    valid = {(r.get('event', {}).get('event_id'), r['method'], r['configured_rate_bps'])
             for r in selected if r.get('outcome') in ('success', 'experimental_failure')
             and r.get('experimental_valid') is not False and r.get('observation_complete') is True
             and not requires_recovery(r)}
    return {'primary_count': len(selected), 'unique_primary_cases': len(recorded),
            'expected_primary_count': len(expected) if expected else 18,
            'primary_complete': bool(expected) and expected <= valid,
            'all_primary_successful': bool(expected) and expected <= {
                (r.get('event', {}).get('event_id'), r['method'], r['configured_rate_bps'])
                for r in selected if r.get('success') and r.get('observation_complete') is True},
            'campaign_id': execution.get('campaign_id')}
