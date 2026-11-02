import copy
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.authority import Authority
from src.clock import ManualClock
from src.fixture import for_role
from src.migration_model import Workload
from src.planner import Planner, OrbitIndex, ScenarioRejected, validate_parameters
from src.probes import baseline_ready, summarize_ping
from src.processes import run_process
from src.simulation import Simulation
from test_authority_orchestrator import Backend

ROOT=Path(__file__).parents[1]
IDS=[53848,53913,51726]


class TinyOrbit:
    ids=IDS
    duration=150
    periods={IDS[0]:[(0,30),(78,150)],IDS[1]:[(18,60)],IDS[2]:[(48,90)]}
    def operational(self,sid,tick):return any(a<=tick<b for a,b in self.periods[sid])
    def graph(self,tick):return {a:{b:100 for b in IDS if b!=a} for a in IDS}


def planner():
    scenario=json.loads((ROOT/'config/scenario.json').read_text())
    scenario['fso']['alignment_s']=1
    orbit=TinyOrbit()
    windows=[dict(sat_a=a,sat_b=b,start_s=0,end_s=150) for a in IDS for b in IDS if a<b]
    return Planner(orbit,OrbitIndex(orbit,windows),scenario,
        {'horizon_s':10,'manifest_resources':{'cpu_cores':.1,'ram_gib':.1,'disk_gib':.1}},
        Workload(1,1,1,1,0,0,0,0,0,0,0))


class SessionBackend(Backend):
    def __init__(self,root,directory,event,rate,orbit,scenario,cancel,notify):
        self.event=event;self.active_role='sat-a';self.event_context={};self.cancel=cancel
        self.notify=notify;self.reset_count=0;self.shutdown_count=0;self.rate=rate
        self.clock=None;self.calls=[];self.failure=None;self.attempts=[]
        self.logical_host=event.get('sat_a')
    def reset(self):self.reset_count+=1
    def establish_baseline(self,identifier):return {'success':True}
    def start_observation(self,clock,identifier):self.clock=clock
    def check(self):
        if self.cancel.is_set():raise InterruptedError('cancel')
    def begin_attempt(self,attempt):self.attempts.append((self.event_context['migration_id'],attempt))
    def set_migration(self,event,migration_id,simulation_id):
        self.event=event;self.source_slot=self.active_role
        self.target_slot='sat-b' if self.active_role=='sat-a' else 'sat-a'
        self.event_context={'simulation_id':simulation_id,'migration_id':migration_id,
            'source_slot':self.source_slot,'target_slot':self.target_slot}
    def transfer(self,path,event):
        result=super().transfer(path,event);result['useful_throughput_bps']=self.rate
        return result
    def cutover(self):self.active_role=self.target_slot
    def finish_handover(self):pass
    def verify_service(self, *, evidence_directory=None):
        from src.storage import atomic_json
        self.calls.append('verify_service')
        result={'success':True}
        atomic_json(evidence_directory/'service-verification.json',result)
        return result
    def shutdown(self):self.shutdown_count+=1


class ContinuousTests(unittest.TestCase):
    def test_only_placed_controller_accumulates_load_from_placement(self):
        p=planner()
        candidate=p.node(IDS[2],80)
        self.assertEqual(candidate['projected_cpu_fraction'],p.node(IDS[2],50)['projected_cpu_fraction'])
        fresh=p.node(IDS[2],80,placed_at=80)
        older=p.node(IDS[2],80,placed_at=50)
        self.assertGreater(older['projected_cpu_fraction'],fresh['projected_cpu_fraction'])
        self.assertEqual(candidate['resource_role'],'candidate')
        self.assertIsNone(candidate['controller_placed_at_s'])
        self.assertEqual(older['controller_placed_at_s'],50)

    def test_trigger_uses_placement_and_full_recovery_window_without_changing_ramp(self):
        p=planner();p.horizon=100;p.index.periods[IDS[0]]=[(0,1000)]
        normal=p.trigger(IDS[0],500,1000,placed_at=490)
        early=p.trigger(IDS[0],500,1000,placed_at=490,required_window_s=200)
        self.assertEqual(normal[0],586)
        self.assertEqual(early[0],519)
        self.assertIn('resources',early[1])
        self.assertEqual(p.horizon,100)
        self.assertLessEqual(early[0]+200,1000)

    def test_three_logical_satellites_and_bidirectional_slot_reuse(self):
        p=planner();params={'duration_s':100,'start_orbital_s':0,'initial_satellite_id':IDS[0]}
        first=p.plan(params);self.assertEqual(first,p.plan(params))
        self.assertEqual([e['sat_b'] for e in first['migrations']], [IDS[1],IDS[2],IDS[0]])
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);bundle=root/'image.tar';bundle.write_bytes(b'image')
            app=SimpleNamespace(root=root,scenario=p.scenario,orbit=p.orbit,cancel=threading.Event(),
                publish=Mock(),bundle=lambda:{'image_bundle':{'path':str(bundle)}})
            session=Simulation(app,planner=p,backend_factory=SessionBackend,clock_factory=ManualClock)
            result=session.run(params)
            self.assertTrue(result['success'],result.get('failure_reason'))
            self.assertEqual(len(result['migrations']),3)
            self.assertEqual([r['slot'] for r in result['controller_history']],['sat-a','sat-b','sat-a','sat-b'])
            self.assertEqual(session.backend.reset_count,1);self.assertEqual(session.backend.shutdown_count,1)
            self.assertEqual(len(set(session.backend.attempts)),3)
            self.assertEqual(result['plan_revisions'],3)
            self.assertEqual(session.backend.calls.count('verify_service'),3)
            for migration in result['migrations']:
                self.assertTrue((Path(result['directory'])/'migrations'/migration['migration_id']/'service-verification.json').exists())
            for name in ('report.html','report.json','migrations.csv','observations.csv','downtime.svg'):
                self.assertTrue((Path(result['directory'])/name).is_file())

    def test_prepared_hot_source_is_adopted_before_clock_and_cold_still_resets(self):
        p=planner();params={'duration_s':100,'start_orbital_s':0,'initial_satellite_id':IDS[0]}
        plan=p.plan(params);plan['common_base_id']='base-'+'a'*32
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);bundle=root/'image.tar';bundle.write_bytes(b'image')
            app=SimpleNamespace(root=root,scenario=p.scenario,orbit=p.orbit,cancel=threading.Event(),
                publish=Mock(),bundle=lambda:{'image_bundle':{'path':str(bundle)}})
            with patch('src.prepared_source.adopt') as adopt:
                for method in ('hot','cold'):
                    session=Simulation(app,planner=p,backend_factory=SessionBackend,clock_factory=ManualClock)
                    result=session.run({**params,'method':method},fixed_plan=plan)
                    self.assertTrue(result['success'],result.get('failure_reason'))
                    self.assertEqual(session.backend.reset_count,0 if method=='hot' else 1)
                    self.assertTrue(result['baseline']['success'])
                adopt.assert_called_once()
            with patch('src.prepared_source.adopt',side_effect=ValueError('stale')):
                session=Simulation(app,planner=p,backend_factory=SessionBackend,clock_factory=ManualClock)
                result=session.run({**params,'method':'hot'},fixed_plan=plan)
                self.assertFalse(result['success']);self.assertIsNone(session.clock)
                self.assertEqual(session.backend.shutdown_count,1)

    def test_rejected_admission_never_mutates_lab_and_preserves_report(self):
        p=planner()
        with tempfile.TemporaryDirectory() as temporary:
            factory=Mock();app=SimpleNamespace(root=Path(temporary),scenario=p.scenario,
                orbit=p.orbit,cancel=threading.Event(),publish=Mock())
            result=Simulation(app,planner=p,backend_factory=factory).run({'duration_s':100,'start_orbital_s':100})
            factory.assert_not_called();self.assertEqual(result['outcome'],'rejected')
            self.assertTrue((Path(result['directory'])/'report.json').exists())

    def test_failed_baseline_and_live_cancel_shutdown_without_migrations(self):
        for fail_baseline in (True,False):
            with self.subTest(fail_baseline=fail_baseline),tempfile.TemporaryDirectory() as temporary:
                p=planner();root=Path(temporary)
                app=SimpleNamespace(root=root,scenario=p.scenario,orbit=p.orbit,cancel=threading.Event(),
                    publish=Mock(),bundle=lambda:{'image_bundle':{'path':'unused.tar'}})
                class FailureBackend(SessionBackend):
                    def establish_baseline(self,identifier):return {'success':not fail_baseline}
                    def start_observation(self,clock,identifier):
                        super().start_observation(clock,identifier);self.cancel.set()
                session=Simulation(app,planner=p,backend_factory=FailureBackend,clock_factory=ManualClock)
                result=session.run({'duration_s':100,'start_orbital_s':0,'initial_satellite_id':IDS[0]})
                self.assertFalse(result['success']);self.assertEqual(result['migrations'],[])
                self.assertEqual(session.backend.shutdown_count,1)
                if fail_baseline:self.assertIsNone(session.clock)
                else:self.assertEqual(result['outcome'],'interrupted')

    def test_invalid_initial_assignment_rejected_before_backend_or_clock(self):
        for host in (None,99999,IDS[1]):
            with self.subTest(host=host),tempfile.TemporaryDirectory() as temporary:
                p=planner();plan=p.plan({'duration_s':100,'start_orbital_s':0,'initial_satellite_id':IDS[0]})
                plan['initial_satellite_id']=host
                p.plan=Mock(return_value=plan)
                factory=Mock();app=SimpleNamespace(root=Path(temporary),scenario=p.scenario,
                    orbit=p.orbit,cancel=threading.Event(),publish=Mock())
                session=Simulation(app,planner=p,backend_factory=factory,clock_factory=Mock())
                result=session.run({'duration_s':100,'start_orbital_s':0})
                factory.assert_not_called();self.assertIsNone(session.clock)
                self.assertEqual(result['outcome'],'rejected')

    def test_wrong_backend_assignment_never_resets_lab_or_starts_clock(self):
        p=planner()
        with tempfile.TemporaryDirectory() as temporary:
            class Unassigned(SessionBackend):
                def __init__(self,*args,**kwargs):
                    super().__init__(*args,**kwargs);self.logical_host=None
            app=SimpleNamespace(root=Path(temporary),scenario=p.scenario,orbit=p.orbit,
                cancel=threading.Event(),publish=Mock(),bundle=lambda:{'image_bundle':{'path':'unused'}})
            session=Simulation(app,planner=p,backend_factory=Unassigned,clock_factory=ManualClock)
            result=session.run({'duration_s':100,'start_orbital_s':0,'initial_satellite_id':IDS[0]})
            self.assertFalse(result['success']);self.assertIsNone(session.clock)
            self.assertEqual(session.backend.reset_count,0)
            self.assertEqual(result['controller_history'],[])

    def test_search_rejects_higher_score_future_dead_end(self):
        p=planner();p.index.periods[IDS[2]]=[(0,150)]
        p.trigger=lambda sid,tick,end,**kwargs:(10,['test']) if sid==IDS[0] else (end,[])
        p.ranked=lambda *args:([{'satellite_id':IDS[1],'score':99},{'satellite_id':IDS[2],'score':90}],[])
        chain=p.chain(IDS[0],0,100,'hot',10**9)
        self.assertEqual(chain[0]['sat_b'],IDS[2])
        self.assertTrue(any(r['reason']=='future_dead_end' and r['satellite_id']==IDS[1] for r in chain[0]['excluded_candidates']))

    def test_plan_can_wait_for_indexed_contact_within_deadline(self):
        p=planner()
        p.index.contacts[tuple(sorted((IDS[0],IDS[1])))]=[(22,150)]
        chain=p.chain(IDS[0],0,100,'hot',10**9)
        self.assertIsNotNone(chain)
        self.assertEqual(chain[0]['trigger_s'],22)

    def test_crash_recovery_concludes_without_resuming_clock(self):
        from src.experiment import Experiment
        from src.storage import atomic_json,append_json
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);atomic_json(root/'config/scenario.json',{})
            simulation_id='sim-'+'b'*32;folder=root/'results/simulations'/simulation_id
            atomic_json(folder/'inputs.json',{})
            atomic_json(folder/'metadata.json',{'simulation_id':simulation_id,'policy_version':'test',
                'migrations':[],'controller_history':[],'outcome':'running'})
            job_id='job-'+'a'*32;job=root/'results/jobs'/job_id
            atomic_json(job/'job.json',{'job_id':job_id,'status':'recovery_required'})
            append_json(job/'events.jsonl',{'simulation_id':simulation_id})
            with patch('src.live_backend.Compose.stop') as stop,patch('src.experiment.http') as http:
                output=Experiment(root).recover(job_id)
            self.assertFalse(output['clock_resumed'])
            self.assertEqual(stop.call_count,2)
            self.assertTrue(any(call.args[:2]==(18091,'/revoke') for call in http.call_args_list))
            self.assertEqual(json.loads((folder/'metadata.json').read_text())['outcome'],'worker_lost')

    def test_persistent_load_rejections_and_explicit_input(self):
        p=planner();before=p.node(IDS[1],25)
        p.chain(IDS[0],0,100,'hot',10**9)
        self.assertEqual(before,p.node(IDS[1],25))
        self.assertEqual(p.node(IDS[1],35)['projected_cpu_fraction'],before['projected_cpu_fraction'])
        self.assertGreater(p.node(IDS[1],35,placed_at=18)['projected_cpu_fraction'],
                           p.node(IDS[1],25,placed_at=18)['projected_cpu_fraction'])
        with self.assertRaises(ScenarioRejected):p.plan({'duration_s':100,'start_orbital_s':30,'initial_satellite_id':IDS[0]})
        with self.assertRaises(ScenarioRejected):p.plan({'duration_s':151})
        with self.assertRaises(ValueError):validate_parameters({'duration_s':True})

    def test_fresh_baseline_requires_authority_and_ten_successes_without_udp(self):
        rows=[{'unix_s':101+i/10,'sequence':i,'success':True,'rtt_ms':1} for i in range(10)]
        udp=[{'kind':'received','sent_unix_ns':101*10**9}]
        status={'active':'sat-a','frozen':False,'states':[{'upstream_master':True}]}
        self.assertTrue(baseline_ready(rows,udp,status,100,'sat-a'))
        self.assertFalse(baseline_ready(rows[:9],udp,status,100,'sat-a'))
        self.assertTrue(baseline_ready(rows,[],status,100,'sat-a'))
        self.assertFalse(baseline_ready(rows,udp,status,102,'sat-a'))
        late=copy.deepcopy(rows);late[0]['rtt_ms']=5000
        self.assertFalse(baseline_ready(late,udp,status,100,'sat-a'))
        self.assertFalse(baseline_ready(rows,udp,{**status,'active':'sat-b'},100,'sat-a'))

    def test_recovery_confirmation_separate_from_first_reply(self):
        rows=[dict(sequence=0,unix_s=1,success=False,rtt_ms=None)]+[
            dict(sequence=i,unix_s=i+1,success=True,rtt_ms=1) for i in range(1,11)]
        result=summarize_ping(rows,baseline_path_available=True)
        self.assertEqual(result['time_to_first_reply_s'],1)
        self.assertEqual(result['time_to_stable_recovery_s'],10)

    def test_authority_alternates_without_dual_writers_and_revokes_ack(self):
        authority=Authority()
        for target in ('sat-b','sat-a','sat-b'):
            authority.freeze();self.assertTrue(authority.ready(images=True,api=True,staged=True))
            authority.cutover(target,lambda:None)
            self.assertTrue(authority.writable(target))
            self.assertFalse(authority.writable('sat-a' if target=='sat-b' else 'sat-b'))
            self.assertFalse(authority.ack)

    def test_child_process_timeout_and_cancel(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            run_process([sys.executable,'-c','import time;time.sleep(30)'],timeout=.1)
        def cancelled():raise InterruptedError('cancel')
        with self.assertRaises(InterruptedError):
            run_process([sys.executable,'-c','import time;time.sleep(30)'],check=cancelled)

    def test_unfrozen_campaign_and_faults_do_not_run_lab(self):
        from src.experiment import Experiment
        from src.storage import atomic_json
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);atomic_json(root/'config/scenario.json',{})
            app=Experiment(root);app.run=Mock()
            self.assertFalse(app.campaign()['complete']);self.assertFalse(app.faults()['complete'])
            app.run.assert_not_called()
