"""Deterministic admission and re-planning on the frozen orbital observation."""
from bisect import bisect_right
from functools import lru_cache
import math

from .migration_model import evaluate
from .resource_model import sat_a_load_percent
from .score_model import CandidateMetrics, score_candidates
from .orbit import shortest_paths

POLICY = 'continuous-planned-v2'


class ScenarioRejected(ValueError):
    pass


def validate_parameters(parameters):
    result = {'method': 'hot', 'rate_bps': 1000000000, 'duration_s': 3600,
              'start_orbital_s': None, 'initial_satellite_id': None, 'max_migrations': None}
    if set(parameters)-set(result): raise ValueError('Unsupported simulation parameter')
    result.update(parameters)
    if result['method'] not in ('hot', 'cold'): raise ValueError('Choose hot or cold')
    if isinstance(result['rate_bps'], bool) or result['rate_bps'] not in (100000000, 1000000000, 10000000000):
        raise ValueError('Unapproved throughput')
    for field, minimum in (('duration_s', 1), ('start_orbital_s', 0), ('initial_satellite_id', 1), ('max_migrations', 1)):
        value = result[field]
        if value is None and field != 'duration_s': continue
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ValueError(field + ': invalid integer')
    return result


class OrbitIndex:
    def __init__(self, orbit, windows):
        self.orbit = orbit
        self.periods = {}
        for sid in orbit.ids:
            periods, start = [], None
            for tick in range(orbit.duration):
                operational = orbit.operational(sid, tick)
                if operational and start is None: start = tick
                if not operational and start is not None:
                    periods.append((start, tick)); start = None
            if start is not None: periods.append((start, orbit.duration))
            self.periods[sid] = periods
        self.contacts = {}
        for window in windows:
            key = tuple(sorted((window['sat_a'], window['sat_b'])))
            self.contacts.setdefault(key, []).append((window['start_s'], window['end_s']))
        for intervals in self.contacts.values(): intervals.sort()

    @staticmethod
    def containing(intervals, tick):
        index = bisect_right(intervals, (tick, math.inf))-1
        return intervals[index] if index >= 0 and tick < intervals[index][1] else None

    def period(self, sid, tick): return self.containing(self.periods[sid], tick)

    def contact_end(self, a, b, tick):
        interval = self.containing(self.contacts.get(tuple(sorted((a, b))), []), tick)
        return interval[1] if interval else tick

    def changes(self, start, end):
        return sorted({point for intervals in self.contacts.values() for interval in intervals
                       for point in interval if start < point < end})


class Planner:
    def __init__(self, orbit, index, scenario, calibration, workload, *, cancel=None, publish=None):
        self.orbit, self.index, self.scenario = orbit, index, scenario
        self.horizon = calibration['horizon_s']
        self.resources = calibration['manifest_resources']
        self.workload = workload
        self.cancel = cancel
        self.publish = publish or (lambda event: None)
        if self.horizon <= 0: raise ScenarioRejected('Invalid calibrated horizon')
        self.rejections = {}

    def check(self):
        if self.cancel and self.cancel.is_set(): raise InterruptedError('Planning interrupted')

    def node(self, sid, tick):
        period = self.index.period(sid, tick)
        profile = self.scenario['controller']['resource_profile']
        background = self.scenario['controller']['background_load_model']
        curve = sat_a_load_percent(tick-period[0], self.horizon,
            background['sat_a_cpu_ram_start_percent'], background['sat_a_cpu_ram_end_percent'])/100 if period else 1.0
        cpu = max(curve, background['candidate_cpu_start_percent']/100 + self.resources['cpu_cores']/profile['cpu_cores'])
        ram = max(curve, background['candidate_ram_start_percent']/100 + self.resources['ram_gib']/profile['ram_gib'])
        disk = self.resources['disk_gib']/profile['disk_gib']
        return {'satellite_id': sid, 'operational': period is not None, 'period': period,
                'execution_kind': 'modeled-resources', 'policy_version': POLICY,
                'projected_cpu_fraction': cpu, 'projected_ram_fraction': ram,
                'projected_disk_fraction': disk, 'free': [1-cpu, 1-ram, 1-disk]}

    def trigger(self, sid, tick, end):
        period = self.index.period(sid, tick)
        if not period: return tick, ['source_in_shadow']
        config = self.scenario['controller']; background = config['background_load_model']
        threshold = config['resource_trigger_fraction']*100
        slope = (background['sat_a_cpu_ram_end_percent']-background['sat_a_cpu_ram_start_percent'])/(2*self.horizon)
        resource_time = math.inf
        if slope > 0:
            resource_time = period[0] + math.ceil(max(0, (threshold-background['sat_a_cpu_ram_start_percent'])/slope-self.horizon)) + config['resource_persistence_s']-1
        eclipse_time = period[1]-self.horizon if period[1] < self.orbit.duration else math.inf
        when = max(tick, min(resource_time, eclipse_time))
        return min(when, end), [name for name, value in (('resources',resource_time),('eclipse',eclipse_time)) if value <= when]

    def estimate(self, method, rate):
        estimate = evaluate(self.workload, method, rate, self.scenario['fso']['alignment_s'], 1e12, 1e12)
        factor = self.scenario['controller']['resource_forecast_horizon_factor']
        duration = math.ceil(estimate.total_operation_s*factor)
        recovery = math.ceil((self.workload.controller_startup_s + self.workload.api_restore_s + self.workload.api_verification_s)*factor)
        return duration, max(1, recovery)

    def ranked(self, source, tick, operation_s, end):
        graph = self.orbit.graph(tick)
        reserve = self.scenario['controller']['resource_reserve_fraction']
        candidates, excluded = [], [{'satellite_id':sid,'reason':'no_direct_contact'}
            for sid in self.orbit.ids if sid != source and sid not in graph[source]]
        for sid, distance in sorted(graph[source].items()):
            node = self.node(sid, tick+operation_s) if tick+operation_s < self.orbit.duration else None
            reason = None
            if not node or not self.orbit.operational(sid, tick): reason = 'destination_in_shadow'
            elif min(node['free']) < reserve: reason = 'resource_reserve_at_arrival'
            elif self.index.period(sid, tick)[1] <= tick+operation_s: reason = 'destination_deadline'
            elif self.index.contact_end(source, sid, tick) < tick+operation_s: reason = 'insufficient_contact'
            if reason:
                self.rejections[reason] = self.rejections.get(reason,0)+1
                excluded.append({'satellite_id': sid, 'reason': reason}); continue
            paths = shortest_paths(graph, sid)
            continuity = min(self.horizon, node['period'][1]-tick)
            for change in self.index.changes(tick, min(end, tick+self.horizon)):
                if not set(paths).issubset(shortest_paths(self.orbit.graph(change), sid)):
                    continuity = min(continuity, change-tick); break
            candidates.append(CandidateMetrics(sid, sum(paths.values())/len(paths)*2/299792.458*1000,
                len(paths), len(self.orbit.ids), continuity, self.horizon, *node['free'], distance))
        return score_candidates(candidates, reserve, self.scenario['score']['weights']), excluded

    def chain(self, host, start, end, method, rate, maximum=None):
        operation_s, recovery_s = self.estimate(method, rate)
        rejected = []
        @lru_cache(maxsize=100000)
        def visit(source, tick, left):
            self.check()
            period = self.index.period(source, tick)
            if not period: return None
            if left == 0: return ()
            trigger, causes = self.trigger(source, tick, end)
            if trigger >= end:
                return () if period[1] >= end else None
            trigger = int(trigger)
            deadline = min(period[1], end)
            if trigger+operation_s+recovery_s > deadline: return None
            # If a contact is not open at the forecast trigger, wait only for
            # indexed contact/sunrise boundaries that still leave rollback time.
            opportunities={trigger}
            for pair,intervals in self.index.contacts.items():
                if source not in pair: continue
                target=pair[0] if pair[1]==source else pair[1]
                opportunities.update(a for a,b in intervals if trigger<a<=deadline-operation_s-recovery_s)
                opportunities.update(a for a,b in self.index.periods[target] if trigger<a<=deadline-operation_s-recovery_s)
            for operation_start in sorted(opportunities):
                ranked, excluded = self.ranked(source, operation_start, operation_s+recovery_s, end)
                for candidate in ranked:
                    target = candidate['satellite_id']
                    arrival = operation_start+operation_s
                    remainder = visit(target, arrival, left-1)
                    if remainder is not None:
                        return ({'event_id': f'{source}-{target}-{operation_start}', 'sat_a': source, 'sat_b': target,
                            'trigger_s': operation_start, 'deadline_s': deadline, 'trigger_causes': causes,
                            'contact_end_s': self.index.contact_end(source,target,operation_start),
                            'contact_window_s': self.index.contact_end(source,target,operation_start)-operation_start,
                            'deadline_window_s': deadline-operation_start, 'recovery_reserve_s': recovery_s,
                            'estimated_operation_s': operation_s, 'estimated_arrival_s': arrival,
                            'candidates': ranked, 'excluded_candidates': excluded + rejected[-20:]}, *remainder)
                    rejected.append({'satellite_id': target, 'reason': 'future_dead_end', 'orbital_s': operation_start})
                    self.rejections['future_dead_end'] = self.rejections.get('future_dead_end',0)+1
            return None
        result = visit(host, int(math.ceil(start)), maximum if maximum is not None else self.orbit.duration)
        return list(result) if result is not None else None

    def plan(self, parameters, minimum_migrations=0):
        p = validate_parameters(parameters)
        if p['duration_s'] > self.orbit.duration: raise ScenarioRejected('Duration exceeds frozen observation')
        if p['initial_satellite_id'] is not None and p['initial_satellite_id'] not in self.orbit.ids:
            raise ScenarioRejected('Unknown initial satellite')
        last = self.orbit.duration-p['duration_s']
        starts = range(last+1) if p['start_orbital_s'] is None else [p['start_orbital_s']]
        for start in starts:
            self.check()
            if start > last: raise ScenarioRejected('Duration exceeds remaining observation')
            if start % 300 == 0: self.publish({'phase': 'planning', 'orbital_s': start,'rejections':dict(self.rejections)})
            hosts = [p['initial_satellite_id']] if p['initial_satellite_id'] is not None else sorted(self.orbit.ids)
            hosts = [host for host in hosts if self.node(host,start)['operational'] and
                     min(self.node(host,start)['free']) >= self.scenario['controller']['resource_reserve_fraction']]
            if not hosts:
                self.rejections['initial_resource_or_shadow']=self.rejections.get('initial_resource_or_shadow',0)+1
                continue
            graph = self.orbit.graph(start)
            if 53913 not in shortest_paths(graph, 53848):
                self.rejections['initial_service_path']=self.rejections.get('initial_service_path',0)+1
                continue
            initial = []
            for host in hosts:
                node = self.node(host,start)
                if node['operational'] and min(node['free']) >= self.scenario['controller']['resource_reserve_fraction'] and len(graph[host]):
                    paths = shortest_paths(graph,host)
                    initial.append(CandidateMetrics(host, sum(paths.values())/len(paths)*2/299792.458*1000,
                        len(paths), len(self.orbit.ids), min(self.horizon,node['period'][1]-start), self.horizon, *node['free'], 0))
            ranked = score_candidates(initial, self.scenario['controller']['resource_reserve_fraction'], self.scenario['score']['weights'])
            for row in ranked:
                chain = self.chain(row['satellite_id'],start,start+p['duration_s'],p['method'],p['rate_bps'],p['max_migrations'])
                if chain is not None and len(chain) >= minimum_migrations:
                    return {'policy_version': POLICY, 'execution_kind': 'calibrated-model-plan',
                        'parameters': p, 'start_s': start, 'end_s': start+p['duration_s'],
                        'initial_satellite_id': row['satellite_id'], 'initial_candidates': ranked,
                        'migrations': chain, 'guarantees_zero_downtime': False}
        self.publish({'phase':'admission_rejected','rejections':dict(self.rejections)})
        raise ScenarioRejected('No feasible sequence in the requested frozen observation; inputs were not changed. Rejections: '+str(self.rejections))
