"""Continuous sessions: admission precedes all laboratory mutations.

One monotonic clock survives every handover. Crash recovery ends the session;
it never replays the missing wall-clock interval.
"""
import json
import math
import time
import threading
import uuid
import copy
import hashlib
from pathlib import Path

from .artifacts import verify_artifact, file_digest, canonical_bytes
from .clock import LiveClock
from .live_backend import LiveBackend
from .orchestrator import Migration
from .planner import Planner, OrbitIndex, ScenarioRejected, validate_parameters, POLICY
from .storage import atomic_json, append_json, utc_now
from .simulation_report import report
from .handover import execute as execute_handover
from .results import finalize, requires_recovery


def engine_fingerprint(root):
    """Calibration is valid only for this implementation and configuration."""
    import hashlib
    paths = sorted(path for path in (root/'src').glob('*.py') if path.name not in {'web.py','jobs.py','common_base.py'}) + [root/'config/scenario.json', root/'config/fixture.json']
    paths += [path for path in (root/'deploy/compose.yaml',root/'deploy/stack.yaml') if path.exists()]
    return hashlib.sha256(''.join(p.name+file_digest(p) for p in paths).encode()).hexdigest()


def simulation_directory(root, identifier):
    if len(identifier) != 36 or not identifier.startswith('sim-') or any(c not in '0123456789abcdef' for c in identifier[4:]):
        raise ValueError('Invalid simulation identifier')
    directory = Path(root)/'results/simulations'/identifier
    if not (directory/'inputs.json').is_file(): raise FileNotFoundError(identifier)
    return directory


class Simulation:
    def __init__(self, application, *, planner=None, backend_factory=LiveBackend, clock_factory=LiveClock):
        self.app = application
        self.root = application.root
        self.planner = planner
        self.backend_factory, self.clock_factory = backend_factory, clock_factory
        self.clock = None
        self.backend = None
        self.event_lock = threading.Lock()

    def prepare_planner(self):
        if self.planner: return self.planner
        from .preconditions import calibration_inputs
        calibration, manifest = calibration_inputs(self.root, full=True)
        atomic_json(self.directory/'calibration.json',calibration)
        atomic_json(self.directory/'artifact-manifest.json',manifest)
        calibration['manifest_resources'] = {key: manifest['resources']['measured_controller_'+key]
                                              for key in ('cpu_cores','ram_gib','disk_gib')}
        windows = json.loads((self.root/'results/direct_link_windows.json').read_text())['windows']
        self.planner = Planner(self.app.orbit, OrbitIndex(self.app.orbit, windows), self.app.scenario,
            calibration, self.app.workload(manifest), cancel=self.app.cancel, publish=self.emit)
        return self.planner

    def emit(self, event):
        row = {'simulation_id': self.identifier, 'timestamp_utc': utc_now(),
               'comparison_id':getattr(self,'result',{}).get('comparison_id'),
               'method':getattr(self,'parameters',{}).get('method'),
               'real_elapsed_s': self.clock.now() if self.clock else None,
               'orbital_s': self.clock.orbital() if self.clock else None, **event}
        with self.event_lock:
            append_json(self.directory/'events.jsonl', row)
            self.app.publish(row)

    def save(self):
        atomic_json(self.directory/'metadata.json', self.result)
        atomic_json(self.directory/'checkpoint.json', {
            'simulation_id': self.identifier, 'phase': self.result['phase'],
            'controller_satellite': self.result.get('controller_satellite'),
            'active_slot': self.result.get('active_slot'),
            'orbital_s': self.clock.orbital() if self.clock else None,
            'recovery_action': 'revoke authority, stop both workloads, conclude interrupted session'})

    def revision(self, host, tick, maximum):
        plan = self.planner.chain(host, tick, self.result['end_s'], self.parameters['method'],
                                  self.parameters['rate_bps'], maximum,
                                  placed_at=self.result['controller_history'][-1]['orbital_s'])
        row = {'orbital_s': tick, 'controller_satellite': host, 'migrations': plan,
               'feasible': plan is not None, 'revision': self.result['plan_revisions']+1}
        atomic_json(self.directory/'plans'/f"revision-{row['revision']:04d}.json", row)
        self.result['plan_revisions'] += 1
        self.emit({'phase': 'replanning', **row})
        if plan is None: raise ScenarioRejected('No safe residual sequence after measured operation delays')
        return plan

    def run(self, parameters, *, fixed_plan=None, comparison_id=None, plan_sha256=None, on_created=None):
        self.parameters = validate_parameters(parameters)
        self.identifier = 'sim-'+uuid.uuid4().hex
        self.directory = self.root/'results/simulations'/self.identifier
        self.directory.mkdir(parents=True)
        atomic_json(self.directory/'inputs.json', {'parameters': self.parameters, 'policy_version': POLICY,
                    'scenario': self.app.scenario, 'clock': 'monotonic real time, 1x',
                    'comparison_id':comparison_id,'shared_plan_sha256':plan_sha256})
        self.result = {'schema_version': 2, 'simulation_id': self.identifier, 'created_utc': utc_now(),
            'parameters': self.parameters, 'policy_version': POLICY, 'phase': 'planning',
            'outcome': 'running', 'success': False, 'complete': False, 'plan_revisions': 0,
            'migrations': [], 'controller_history': [], 'baseline': None,
            'directory': str(self.directory), 'execution_kind': 'live-hybrid'}
        self.result.update(comparison_id=comparison_id,shared_plan_sha256=plan_sha256,
                           fixed_schedule=fixed_plan is not None)
        self.save()
        if on_created:
            on_created(self.identifier)
        try:
            self.emit({'phase': 'planning'})
            planner = self.prepare_planner()
            if fixed_plan is None and self.parameters['additional_data_bytes']:
                from dataclasses import replace
                planner=copy.copy(planner)
                extra=self.parameters['additional_data_bytes']
                planner.workload=replace(planner.workload,image_bytes=planner.workload.image_bytes+extra)
                planner.resources={**planner.resources,'disk_gib':planner.resources['disk_gib']+extra/1024**3}
                self.planner=planner
            plan = copy.deepcopy(fixed_plan) if fixed_plan is not None else planner.plan(self.parameters)
            initial_host = plan.get('initial_satellite_id')
            if (isinstance(initial_host, bool) or initial_host not in self.app.orbit.ids
                    or not self.app.orbit.operational(initial_host, plan['start_s'])):
                raise ScenarioRejected('Controller must be assigned to an operational satellite before simulation start')
            if fixed_plan is not None:
                if (plan['end_s']-plan['start_s'] != self.parameters['duration_s']
                        or plan['initial_satellite_id'] != self.parameters['initial_satellite_id']
                        or plan['start_s'] != self.parameters['start_orbital_s']):
                    raise ScenarioRejected('Shared plan does not match session parameters')
                self.result['policy_version']=plan['policy_version']
                if plan.get('scenario_sha256') and hashlib.sha256(canonical_bytes(self.app.scenario)).hexdigest()!=plan['scenario_sha256']:
                    raise ScenarioRejected('Scenario changed between paired sessions')
                if plan.get('fixture_sha256') and file_digest(self.root/'config/fixture.json')!=plan['fixture_sha256']:
                    raise ScenarioRejected('Initial fixture changed between paired sessions')
            atomic_json(self.directory/'plans/initial.json', plan)
            self.result.update(start_s=plan['start_s'], end_s=plan['end_s'],
                               controller_satellite=plan['initial_satellite_id'], active_slot='sat-a',
                               target_migrations=plan.get('target_migrations'))
            self.emit({'phase': 'plan_admitted', 'plan': plan})
            bundle = self.app.bundle()
            if fixed_plan is not None and plan.get('image_bundle_identity'):
                from .continuous_comparison import bundle_identity
                if bundle_identity(bundle['image_bundle']) != plan['image_bundle_identity']:
                    raise ScenarioRejected('Image bundle changed between paired sessions')
            event = {'sat_a': plan['initial_satellite_id'], 'sat_b': None,
                     'trigger_s': plan['start_s'], 'start_s': plan['start_s'], 'deadline_s': plan['end_s']}
            self.result['phase'] = 'preparation'; self.save()
            if hasattr(self.app,'checkpoint'):
                self.app.checkpoint(kind='simulation',simulation_id=self.identifier,phase='preparation',
                    source_slot='sat-a',target_slot='sat-b',inputs_path=str(self.directory/'inputs.json'))
            self.backend = self.backend_factory(self.root, self.directory, event, self.parameters['rate_bps'],
                self.app.orbit, self.app.scenario, self.app.cancel, notify=self.emit)
            if self.backend.logical_host != initial_host:
                raise ScenarioRejected('Controller has no valid initial satellite assignment')
            if plan.get('common_base_id') and self.parameters['method']=='hot':
                from .prepared_source import adopt
                adopt(self.backend,plan['common_base_id'],plan)
            else:
                self.backend.reset()
            if self.parameters['additional_data_bytes']:
                payload=self.directory/'additional-migration-data.bin'
                with payload.open('wb') as output:output.truncate(self.parameters['additional_data_bytes'])
                self.backend.additional_payload=payload
            self.result['baseline'] = self.backend.establish_baseline(self.identifier)
            if not self.result['baseline']['success']: raise ScenarioRejected('Service baseline failed')
            if self.backend.logical_host != initial_host or self.backend.active_role != 'sat-a':
                raise ScenarioRejected('Initial controller assignment does not match the admitted satellite')
            self.emit({'phase': 'controller_assigned', 'orbital_s': plan['start_s'],
                       'controller_satellite': initial_host, 'active_slot': self.backend.active_role,
                       'baseline_verified': True})
            self.emit({'phase': 'baseline_valid', 'baseline': self.result['baseline']})
            self.clock = self.clock_factory(plan['start_s'])
            self.backend.start_observation(self.clock, self.identifier)
            self.result['controller_history'].append({'satellite_id': plan['initial_satellite_id'],
                'slot': 'sat-a', 'orbital_s': self.clock.orbital(), 'real_elapsed_s': self.clock.now()})
            remaining = plan['migrations']; previous_tick = None
            self.result['phase'] = 'running'
            while self.clock.orbital() < self.result['end_s']:
                # Idle checks use the current logical host deadline, not the previous handover deadline.
                tick = self.clock.orbital()
                host = self.result['controller_satellite']
                period = planner.index.period(host, int(tick))
                if not period: raise ScenarioRejected('Controller satellite no longer operational')
                self.backend.event = {'deadline_s': min(period[1], self.result['end_s'])}
                self.backend.check()
                if int(tick) != previous_tick:
                    previous_tick = int(tick)
                    nodes = [planner.node(sid, int(tick), placed_at=self.result['controller_history'][-1]['orbital_s']
                                          if sid == host else None) for sid in self.app.orbit.ids]
                    observation = {'simulation_id': self.identifier, 'orbital_s': tick,
                        'real_elapsed_s': self.clock.now(), 'timestamp_utc': utc_now(),
                        'controller_satellite': host, 'active_slot': self.backend.active_role,
                        'elapsed_s': tick-plan['start_s'], 'remaining_s': self.result['end_s']-tick,
                        'completed_migrations': len([r for r in self.result['migrations'] if r['success']]),
                        'service_state':getattr(self.backend,'service_status',None),
                        'phase': 'running', 'modeled_satellite_resources': nodes,
                        'next_migration': remaining[0] if remaining else None}
                    append_json(self.directory/'observations.jsonl', observation)
                    self.emit({'phase': 'session_tick', **observation})
                    self.save()
                if remaining and tick >= remaining[0]['trigger_s']:
                    event = remaining[0]
                    if fixed_plan is not None and (host != event['sat_a'] or tick-event['trigger_s'] > 1):
                        raise ScenarioRejected('Shared event missed; comparison will not replan')
                    migration_id = 'migration-'+uuid.uuid4().hex
                    self.backend.set_migration(event, migration_id, self.identifier)
                    self.result['migrations'].append({'migration_id':migration_id,'event':event,
                        'source_slot':self.backend.source_slot,'target_slot':self.backend.target_slot,
                        'success':False,'failure_reason':'Operation not yet concluded'})
                    self.result['phase'] = 'migrating'; self.save()
                    migration = Migration(self.backend, self.clock, self.directory/'migrations'/migration_id/'operation', self.app.scenario)
                    result = self.result['migrations'][-1]
                    result.pop('failure_reason',None)
                    result['configured_rate_bps']=self.parameters['rate_bps']
                    execute_handover(migration,self.backend,self.parameters['method'],event,
                        Path(bundle['image_bundle']['path']),result,self.directory/'migrations'/migration_id)
                    result['observation_complete']=result.get('service_verification',{}).get('success') is True
                    result['observation_s']=result.get('service_verification_s')
                    finalize(result)
                    result.update(migration_id=migration_id, source_slot=self.backend.source_slot,
                                  target_slot=self.backend.target_slot)
                    self.result['migrations'][-1]=result
                    if not result['success']:
                        if result.get('interrupted'):raise InterruptedError(result.get('failure_reason','Interrupted'))
                        raise ScenarioRejected('Migration failed: '+str(result.get('failure_reason')
                            or result.get('invalid_reason') or 'unconfirmed recovery'))
                    self.backend.finish_handover()
                    atomic_json(self.directory/'migrations'/migration_id/'handover.json',result)
                    host = event['sat_b']
                    self.result.update(controller_satellite=host, active_slot=self.backend.active_role, phase='running')
                    self.result['controller_history'].append({'satellite_id': host, 'slot': self.backend.active_role,
                        'orbital_s': self.clock.orbital(), 'real_elapsed_s': self.clock.now()})
                    maximum = self.parameters['max_migrations']
                    if fixed_plan is not None:
                        remaining=remaining[1:]
                        if not remaining and fixed_plan.get('stop_after_schedule'):
                            self.result['termination_reason']='verified_migration_target';break
                        if remaining and self.clock.orbital() > remaining[0]['trigger_s']:
                            raise ScenarioRejected('Migration overran the next shared event; comparison will not replan')
                        continue
                    if maximum is not None and len(self.result['migrations']) >= maximum:
                        self.result['termination_reason'] = 'requested_migration_limit'; break
                    left = maximum-len(self.result['migrations']) if maximum is not None else None
                    remaining = self.revision(host, math.ceil(self.clock.orbital()), left)
                    continue
                self.clock.sleep(min(.2, self.result['end_s']-self.clock.orbital()))
            if fixed_plan is not None and remaining:
                raise ScenarioRejected('Shared schedule not fully executed before session end')
            self.result.update(outcome='success', success=True, complete=True)
        except InterruptedError as exc:
            self.result.update(outcome='interrupted', failure_reason=str(exc))
        except Exception as exc:
            self.result.update(outcome='failed' if self.backend else 'rejected', failure_reason=str(exc))
            error_file=self.directory/'preparation-error.json'
            if error_file.exists():
                self.result['error']=json.loads(error_file.read_text())
                if not self.clock:
                    self.result['outcome']='invalid_baseline' if self.result['error'].get('operation')=='baseline' else 'preparation_failed'
        finally:
            ended_orbital=self.clock.orbital() if self.clock else None
            ended_elapsed=self.clock.now() if self.clock else None
            cleanup_started=time.monotonic()
            self.result['phase'] = 'concluding'
            self.save()
            if self.backend:
                try:
                    self.backend.shutdown()
                    self.result['controllers_fenced'] = True
                except Exception as exc:
                    self.result.update(outcome='recovery_required', recovery_required=True, success=False, complete=False, cleanup_failure=str(exc))
                baseline=self.directory/'baseline.json'
                if baseline.exists():self.result['baseline']=json.loads(baseline.read_text())
            self.result.update(phase='finished', finished_utc=utc_now(),
                real_elapsed_s=ended_elapsed, final_orbital_s=ended_orbital,
                cleanup_elapsed_s=time.monotonic()-cleanup_started)
            if ended_orbital is not None and ended_orbital < self.app.orbit.duration:
                append_json(self.directory/'observations.jsonl', {
                    'simulation_id':self.identifier,'orbital_s':ended_orbital,'real_elapsed_s':ended_elapsed,
                    'timestamp_utc':utc_now(),'controller_satellite':self.result.get('controller_satellite'),
                    'active_slot':self.result.get('active_slot'),'controllers_fenced':self.result.get('controllers_fenced'),
                    'elapsed_s':ended_orbital-self.result['start_s'],
                    'remaining_s':max(0,self.result['end_s']-ended_orbital),
                    'completed_migrations':sum(r['success'] for r in self.result['migrations']),
                    'phase':self.result['outcome'],'service_state':getattr(self.backend,'service_status',None),
                    'modeled_satellite_resources':[self.planner.node(sid,int(ended_orbital),
                        placed_at=self.result['controller_history'][-1]['orbital_s']
                        if self.result['controller_history'] and sid == self.result.get('controller_satellite') else None)
                        for sid in self.app.orbit.ids]})
            self.result['recovery_required']=requires_recovery(self.result)
            if self.result['recovery_required']:
                self.result.update(outcome='recovery_required',success=False,complete=False)
            self.save()
            try:
                report(self.directory, self.root)
            except Exception as exc:
                self.result['report_error']=str(exc)
                self.save()
                self.emit({'phase':'report_failed','reason':str(exc)})
            if not self.result['recovery_required'] and hasattr(self.app,'checkpoint'):
                self.app.checkpoint(kind='between_runs',phase='idle',last_simulation_id=self.identifier)
            self.emit({'phase': 'simulation_finished', 'outcome': self.result['outcome']})
        return self.result
