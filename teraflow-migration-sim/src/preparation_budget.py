"""Bounded preparation stages, independent from the orbital clock."""
import contextlib
import math
import subprocess
import time
from datetime import datetime, timedelta, timezone

from .storage import append_json, atomic_json, utc_now

DEFAULTS = {'infrastructure': 15, 'start_source': 180, 'start_target': 180,
            'clean_target': 120, 'clean_source': 120, 'restore_scenario': 120,
            'restore_authority': 60, 'stop_target': 45, 'baseline': 60}
LABELS = {'infrastructure': 'Verifica Mininet e autorità P4',
          'start_source': 'Avvio controller sorgente', 'start_target': 'Avvio controller destinazione',
          'clean_target': 'Pulizia scenario destinazione', 'clean_source': 'Pulizia scenario sorgente',
          'restore_scenario': 'Caricamento scenario iniziale', 'restore_authority': 'Ripristino autorità P4',
          'stop_target': 'Arresto previsto della destinazione', 'baseline': 'Verifica API, autorità e sonde'}


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
            if self.diagnostics:
                try:
                    self.error['services'] = self.diagnostics()
                    unhealthy = [row['name'] for row in self.error['services'].get('containers', [])
                                 if row.get('health') == 'unhealthy']
                    if unhealthy and code != 'interrupted':
                        self.error.update(code='dependency_unhealthy', unhealthy_services=unhealthy)
                except Exception as diagnostic_error: self.error['diagnostics_error'] = str(diagnostic_error)
            messages = {'interrupted':'Esecuzione interrotta su richiesta.',
                        'dependency_unhealthy':'Una dipendenza del controller non supera il controllo di salute.',
                        'startup_timeout':'Il controller non è diventato disponibile entro il limite di avvio.',
                        'startup_failed':'Il controller non è riuscito ad avviarsi.',
                        'preparation_timeout':'Il passaggio di preparazione ha raggiunto il limite di tempo.',
                        'p4_not_ready':'Mininet o l’autorità P4 non sono pronti.',
                        'invalid_baseline':'Il servizio iniziale non supera la verifica API, autorità e sonde.'}
            messages.update(nbi_timeout='Una chiamata NBI ha superato il proprio limite di tempo.',
                            nbi_http_error='Una chiamata NBI è stata rifiutata dal controller.')
            self.error['message'] = messages.get(self.error['code'],'Preparazione del laboratorio non riuscita.')
            self.error['recovery_hint'] = 'Consultare stato e log dei servizi indicati; risolvere la causa prima di riprovare.'
            atomic_json(self.directory/'preparation-error.json', self.error)
            self.notify({**row, 'operation_status': 'failed', 'error': self.error})
            raise
        else:
            self.notify({**row, 'operation_status': 'completed', 'elapsed_s': time.monotonic()-started})
        finally:
            append_json(self.directory/'preparation-operations.jsonl',
                        {**row, 'elapsed_s': time.monotonic()-started, 'success': self.error is None})
            self.stage_deadline = self.deadline
