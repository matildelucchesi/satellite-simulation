"""Bounded preparation stages, independent from the orbital clock."""
import contextlib
import math
import subprocess
import time
from datetime import datetime, timedelta, timezone

from .storage import append_json, atomic_json, utc_now

DEFAULTS = {'infrastructure': 120, 'start_source': 180, 'start_target': 180,
            'clean_target': 120, 'clean_source': 120, 'restore_scenario': 120,
            'restore_authority': 60, 'stop_target': 45, 'baseline': 60, 'reset_service': 120}
LABELS = {'reset_service': 'Restoring the service on the existing network',
          'infrastructure': 'Waiting for Mininet and the P4 proxy',
          'start_source': 'Starting the source controller', 'start_target': 'Starting the destination controller',
          'clean_target': 'Cleaning the destination scenario', 'clean_source': 'Cleaning the source scenario',
          'restore_scenario': 'Configuring and checking the network', 'restore_authority': 'Restoring the P4 authority',
          'stop_target': 'Planned stop of the destination', 'baseline': 'Checking API, authority and probes'}


RESTORE_COEFFICIENTS = {'base':120, 'devices':10, 'links':2, 'additional_rules':1, 'services':30}


def restore_budget(scenario, document):
    overrides = scenario.get('live', {}).get('restore_budget_coefficients_s', {})
    if set(overrides)-set(RESTORE_COEFFICIENTS): raise ValueError('Unknown restore budget coefficient')
    coefficients = {**RESTORE_COEFFICIENTS, **overrides}
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0
           for v in coefficients.values()): raise ValueError('Restore coefficients must be finite positive seconds')
    entities = (document or {}).get('entities', {})
    counts = {kind:len(entities.get(kind, [])) for kind in ('devices','links','services')}
    counts['additional_rules'] = sum(1 for device in entities.get('devices', [])
        for rule in device.get('device_config', {}).get('config_rules', [])
        if not rule.get('custom', {}).get('resource_key','').startswith('_connect/'))
    calculated = coefficients['base'] + sum(coefficients[key]*value for key,value in counts.items())
    explicit = scenario.get('live', {}).get('preparation_budgets_s', {}).get('restore_scenario')
    return {'policy':'scenario-operations-v1', 'counts':counts, 'coefficients_s':coefficients,
            'calculated_limit_s':calculated, 'explicit_override_s':explicit,
            'effective_limit_s':calculated if explicit is None else explicit,
            'override_below_calculated':explicit is not None and explicit<calculated}


class PreparationBudget:
    def __init__(self, directory, scenario, notify, diagnostics=None, document=None):
        self.directory, self.notify = directory, notify
        self.diagnostics = diagnostics
        overrides = scenario.get('live', {}).get('preparation_budgets_s', {})
        if set(overrides) - set(DEFAULTS): raise ValueError('Unknown preparation budget')
        self.restore = restore_budget(scenario, document)
        self.limits = {**DEFAULTS, 'restore_scenario':self.restore['calculated_limit_s'], **overrides}
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0
               for v in self.limits.values()): raise ValueError('Preparation budgets must be finite positive seconds')
        self.started = time.monotonic()
        self.total_limit = sum(self.limits.values())
        self.deadline = self.started + self.total_limit
        self.stage_deadline = self.deadline
        self.error = None
        atomic_json(self.directory/'preparation-budget.json', {'limits_s':self.limits,
            'total_limit_s':self.total_limit, 'restore':self.restore})

    def remaining(self):
        return max(0, min(self.deadline, self.stage_deadline) - time.monotonic())

    @contextlib.contextmanager
    def stage(self, name):
        started = time.monotonic()
        self.stage_deadline = min(self.deadline, started + self.limits[name])
        row = {'phase': 'preparation_operation', 'operation': name, 'label': LABELS[name],
               'phase_started_utc': utc_now(), 'limit_s': self.limits[name],
               'preparation_total_limit_s': self.total_limit,
               'deadline_utc': (datetime.now(timezone.utc) + timedelta(seconds=self.remaining())).isoformat()}
        if name == 'restore_scenario': row['budget'] = self.restore
        self.notify({**row, 'operation_status': 'running'})
        try:
            if self.remaining() <= 0: raise TimeoutError('Preparation budget exhausted before operation')
            yield
            if self.remaining() <= 0: raise TimeoutError('Preparation operation exceeded its budget')
        except Exception as exc:
            code = ('interrupted' if isinstance(exc, InterruptedError) else
                    'p4_not_ready' if name == 'infrastructure' else
                    'preparation_timeout' if self.remaining()<=0 else
                    'startup_timeout' if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)) and name.startswith('start_') else
                    'preparation_timeout' if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)) else
                    'invalid_baseline' if name == 'baseline' else
                    'p4_not_ready' if name in ('infrastructure', 'restore_authority') else
                    'startup_failed' if name.startswith('start_') else 'preparation_failed')
            if getattr(exc,'code',None) and not isinstance(exc,InterruptedError) and self.remaining()>0:
                code = exc.code
            self.error = {**row, 'code': code, 'detail': str(exc), 'elapsed_s': time.monotonic()-started,
                          'preparation_elapsed_s': time.monotonic()-self.started,
                          'timestamp_utc': utc_now()}
            if getattr(exc,'infrastructure_status',None):
                self.error['infrastructure_status']=exc.infrastructure_status
            if getattr(exc,'startup_stage',None):
                self.error.update(startup_stage=exc.startup_stage,startup_label=exc.startup_label)
            if self.diagnostics:
                try:
                    self.error['services'] = self.diagnostics()
                    unhealthy = [row['name'] for row in self.error['services'].get('containers', [])
                                 if row.get('health') == 'unhealthy']
                    if unhealthy and code != 'interrupted':
                        self.error.update(code='dependency_unhealthy', unhealthy_services=unhealthy)
                except Exception as diagnostic_error: self.error['diagnostics_error'] = str(diagnostic_error)
            messages = {'interrupted':'Run stopped on request.',
                        'dependency_unhealthy':'A controller dependency fails its health check.',
                        'startup_timeout':'The controller did not become available within the startup limit.',
                        'startup_failed':'The controller failed to start.',
                        'preparation_timeout':'The preparation step reached its time limit.',
                        'p4_not_ready':'Mininet or the P4 authority is not ready.',
                        'invalid_baseline':'The initial service fails the API, authority and probe check.'}
            messages.update(nbi_timeout='An NBI call exceeded its time limit.',
                            nbi_http_error='An NBI call was rejected by the controller.')
            self.error['message'] = messages.get(self.error['code'],'Laboratory preparation failed.')
            if name=='infrastructure' and self.error['code']=='p4_not_ready' and self.error.get('infrastructure_status'):
                unavailable=[component for component,status in self.error['infrastructure_status'].items() if not status['ready']]
                if unavailable:self.error['message']='Infrastructure not ready within the limit: '+', '.join(unavailable)+'.'
            self.error['recovery_hint'] = 'Check the status and logs of the services listed; fix the cause before trying again.'
            atomic_json(self.directory/'preparation-error.json', self.error)
            self.notify({**row, 'operation_status': 'failed', 'error': self.error})
            raise
        else:
            self.notify({**row, 'operation_status': 'completed', 'elapsed_s': time.monotonic()-started})
        finally:
            append_json(self.directory/'preparation-operations.jsonl',
                        {**row, 'elapsed_s': time.monotonic()-started, 'success': self.error is None})
            self.stage_deadline = self.deadline
