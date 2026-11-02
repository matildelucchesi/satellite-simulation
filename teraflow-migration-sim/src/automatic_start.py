"""Bounded deterministic search; admission is never a claim of live success."""
import copy
import time
from datetime import datetime, timedelta, timezone
from .planner import ScenarioRejected

POLICY = 'automatic-start-service-v2'


class SearchDeadline(Exception):
    pass


class SelectionRejected(ScenarioRejected):
    def __init__(self, evidence):
        self.evidence = evidence
        super().__init__('Ricerca incompleta' if not evidence['exhaustive'] else
                         'Nessuna partenza ammissibile nel replay')


class SelectionInvalidated(ScenarioRejected):
    pass


def margin(planner, plan):
    values = []
    for event in plan['migrations']:
        start = event['trigger_s']; operation = event['estimated_operation_s']
        arrival = start + operation
        values.extend((event['contact_end_s']-arrival,
            min(planner.index.period(event['sat_a'], start)[1], planner.orbit.duration)
                -arrival-event['recovery_reserve_s'],
            planner.index.period(event['sat_b'], start)[1]-arrival))
        if hasattr(planner.index,'service_contact_end'):
            values.append(planner.index.service_contact_end(start)-arrival)
    return min(values)


def select_start(planner, parameters, rates=None, *, budget_s=600, clock=time.monotonic):
    from .continuous_comparison import shared_plan
    if not 0 < budget_s <= 86400:
        raise ValueError('Invalid automatic-start search budget')
    rates = sorted(set(rates or [parameters['rate_bps']]))
    started = clock(); deadline = started + budget_s
    evidence = {'policy_version':POLICY,'search_start_s':0,
        'search_end_s_exclusive':planner.orbit.duration,'resolution_s':1,
        'budget_s':budget_s,'rates':rates,'examined_candidates':0,'exhaustive':False,
        'rejections':{},'selected':None,'elapsed_s':0}
    best = None; plans = None; last_publish = -1
    original_check = planner.check
    def check():
        original_check()
        if clock() >= deadline: raise SearchDeadline()
    working = copy.copy(planner); working.check = check
    working.publish = lambda event: None
    def publish(final=False):
        nonlocal last_publish
        elapsed = clock()-started
        if final or elapsed-last_publish >= 1:
            last_publish = elapsed
            planner.publish({'phase':'departure_search','label':'Ricerca della partenza',
                'operation_status':'completed' if final else 'running',
                'limit_s':budget_s,'deadline_utc':(datetime.now(timezone.utc)+timedelta(seconds=max(0,deadline-clock()))).isoformat(),
                **copy.deepcopy(evidence),'elapsed_s':elapsed})
    # Sample the whole replay first, then fill every remaining one-second slot.
    # A budget-limited sample must never be described as exhaustive.
    ticks = (tick for sweep in (range(0,planner.orbit.duration,300),
                               (t for t in range(planner.orbit.duration) if t%300)) for tick in sweep)
    publish()
    try:
        for tick in ticks:
            for host in sorted(planner.orbit.ids):
                check(); candidate = {}; margins = []
                evidence['examined_candidates'] += 1
                for rate in rates:
                    working.rejections = {}
                    try:
                        plan = shared_plan(working,{**parameters,'rate_bps':rate,
                            'start_orbital_s':tick,'initial_satellite_id':host})
                    except ScenarioRejected:
                        for reason,count in working.rejections.items():
                            evidence['rejections'][reason] = evidence['rejections'].get(reason,0)+count
                        break
                    candidate[str(rate)] = plan; margins.append(margin(working,plan))
                else:
                    if not margins or min(margins)<0:
                        evidence['rejections']['negative_safety_margin']=evidence['rejections'].get('negative_safety_margin',0)+1
                        continue
                    score = (min(margins),-tick,-host)
                    if best is None or score > best:
                        best=score; plans=candidate
                        evidence['selected']={'initial_satellite_id':host,'start_orbital_s':tick,
                            'minimum_margin_s':score[0],
                            'margins_by_rate_s':dict(zip(map(str,rates),margins))}
                publish()
        evidence['exhaustive'] = True
    except SearchDeadline:
        pass
    evidence['elapsed_s'] = clock()-started
    publish(True)
    if plans is None: raise SelectionRejected(evidence)
    return evidence,plans
