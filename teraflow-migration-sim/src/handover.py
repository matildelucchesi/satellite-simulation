"""The common protocol + post-cutover service gate for both coordinators."""
from .results import finalize, transfer_metrics
from .storage import atomic_json
import time


def execute(migration, backend, method, event, bundle, result, evidence_directory):
    result['migration_start_unix_s'] = time.time()
    result.update(migration.run(method, event, bundle))
    result['migration_completed'] = bool(result['success'])
    result.update(observation_complete=False, experimental_valid=True, recovery_required=bool(result.get('recovery_required')))
    result.update(transfer_metrics(result, bundle.name))
    if result['migration_completed']:
        started = backend.clock.now()
        try:
            result['service_verification'] = backend.verify_service(evidence_directory=evidence_directory)
            if result['service_verification'].get('success') is not True:
                raise RuntimeError('Target service verification failed')
            result['failure_reason'] = result['failure_phase'] = None
        except Exception as exc:
            result.update(failure_reason=str(exc), failure_phase='service_verification',
                          interrupted=isinstance(exc, InterruptedError), service_failure=True)
            path = evidence_directory/'service-verification.json'
            if path.exists():
                import json
                result['service_verification'] = json.loads(path.read_text())
            else: result['service_verification'] = {'success': False, 'failure_reason': str(exc)}
        finally:
            result['service_verification_s'] = backend.clock.now()-started
            result['probe_window_end_unix_s'] = time.time()
    rate = result.get('configured_rate_bps', getattr(backend, 'rate', None))
    throughput = result.get('image_throughput_bps')
    if rate and throughput is not None and throughput < .9*rate:
        result.update(experimental_valid=False,
            invalid_reason='Measured bundle throughput below 90% of configured useful rate')
    finalize(result)
    atomic_json(evidence_directory/'handover.json', result)
    return result
