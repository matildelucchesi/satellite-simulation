import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.artifacts import canonical_bytes
from src.clock import ManualClock
from src.continuous_comparison import ContinuousComparison, shared_plan, validate_parameters, reconcile_recovery
from src.planner import OrbitIndex, ScenarioRejected
from src.simulation import Simulation
from src.storage import atomic_json
from test_continuous import planner, SessionBackend, IDS


def comparison_planner():
    p = planner()
    class Orbit:
        ids = IDS
        duration = 1500
        periods = {IDS[0]:[(0,300),(780,1500)], IDS[1]:[(180,600)], IDS[2]:[(480,900)]}
        def operational(self,sid,tick):
            return any(a<=tick<b for a,b in self.periods[sid])
        def graph(self,tick):
            return {a:{b:100 for b in IDS if b!=a} for a in IDS}
    p.orbit = Orbit()
    p.index = OrbitIndex(p.orbit,[dict(sat_a=a,sat_b=b,start_s=0,end_s=1500)
                                for a in IDS for b in IDS if a<b])
    p.horizon = 100
    return p


class ContinuousComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.planner = comparison_planner()
        bundle = self.root/'image.tar'; bundle.write_bytes(b'image')
        self.app = SimpleNamespace(root=self.root,scenario=self.planner.scenario,orbit=self.planner.orbit,
            cancel=threading.Event(),publish=Mock(),bundle=lambda:{'image_bundle':{'path':str(bundle)}})
        self.parameters = {'duration_s':850,'start_orbital_s':0,'initial_satellite_id':IDS[0]}
        self.sessions = []
        self.reporting = patch('src.simulation.report', return_value={})
        self.reporting.start()

    def tearDown(self):
        self.reporting.stop()
        self.temp.cleanup()

    def coordinator(self, backend=SessionBackend):
        def factory():
            session = Simulation(self.app,planner=self.planner,backend_factory=backend,clock_factory=ManualClock)
            self.sessions.append(session)
            return session
        return ContinuousComparison(self.app,planner=self.planner,session_factory=factory)

    def test_full_hot_and_cold_sessions_share_exact_plan_and_reset_twice(self):
        result = self.coordinator().run(self.parameters)
        self.assertTrue(result['success'],result.get('reason'))
        self.assertEqual(len(self.sessions),2)
        self.assertGreater(len(result['events']),0)
        plans = []
        for session in self.sessions:
            plans.append(json.loads((session.directory/'plans/initial.json').read_text()))
            self.assertEqual(session.result['plan_revisions'],0)
            self.assertAlmostEqual(session.result['real_elapsed_s'],850)
            self.assertEqual(session.backend.reset_count,1)
            self.assertEqual(session.backend.shutdown_count,1)
            self.assertEqual(session.result['shared_plan_sha256'],result['shared_plan_sha256'])
        self.assertEqual(plans[0],plans[1])
        self.assertEqual(hashlib.sha256(canonical_bytes(plans[0])).hexdigest(),result['shared_plan_sha256'])
        self.assertTrue(all(row['comparable'] for row in result['events']))
        self.assertTrue((self.root/'results/continuous-comparisons'/result['comparison_id']/'events.csv').exists())
        self.assertEqual([s.parameters['method'] for s in self.sessions],['hot','cold'])

    def test_shared_admission_reserves_both_methods_and_service_verification(self):
        plan = shared_plan(self.planner,validate_parameters(self.parameters))
        hot = self.planner.estimate('hot',1000000000)
        cold = self.planner.estimate('cold',1000000000)
        for event in plan['migrations']:
            self.assertGreaterEqual(event['estimated_operation_s'],max(hot[0],cold[0])+30)
            self.assertLessEqual(event['trigger_s']+event['estimated_operation_s'],event['deadline_s'])
        with self.assertRaises(ScenarioRejected):
            shared_plan(self.planner,validate_parameters({**self.parameters,'max_migrations':1}))

    def test_no_event_plan_is_rejected_without_mutating_laboratory(self):
        result = self.coordinator().run({**self.parameters,'duration_s':100})
        self.assertFalse(result['complete'])
        self.assertEqual(self.sessions,[])

    def test_overrun_stops_without_replanning_or_starting_cold(self):
        class SlowBackend(SessionBackend):
            def finish_handover(self):
                self.clock.sleep(500)
        result = self.coordinator(SlowBackend).run(self.parameters)
        self.assertFalse(result['complete'])
        self.assertIn('shared',result['reason'].lower())
        self.assertEqual(len(self.sessions),1)
        self.assertEqual(self.sessions[0].result['plan_revisions'],0)
        self.assertTrue(all(row.get('cold') is None for row in result['events']))

    def test_cancel_between_sessions_keeps_hot_and_never_starts_cold(self):
        def publish(event):
            if event.get('comparison_phase')=='resetting':
                self.app.cancel.set()
        self.app.publish = publish
        result = self.coordinator().run(self.parameters)
        self.assertEqual(result['outcome'],'interrupted')
        self.assertTrue(result['session_results']['hot']['success'])
        self.assertNotIn('cold',result['sessions'])
        self.assertIsNone(result['events'][0].get('cold_minus_hot'))

    def test_cold_failure_preserves_hot_and_no_false_numeric_differences(self):
        count = [0]
        class FailingCold(SessionBackend):
            def __init__(backend,*args,**kwargs):
                super().__init__(*args,**kwargs)
                count[0] += 1
                if count[0] == 2:
                    backend.failure = 'copy'
        result = self.coordinator(FailingCold).run(self.parameters)
        self.assertFalse(result['complete'])
        self.assertTrue(result['session_results']['hot']['success'])
        self.assertFalse(result['session_results']['cold']['success'])
        self.assertNotIn('cold_minus_hot',result['totals'])
        for row in result['events']:
            self.assertFalse(row.get('comparable',False))
            self.assertTrue(row.get('cold_minus_hot') is None or
                            all(value is None for value in row['cold_minus_hot'].values()))

    def test_validation_rejects_independent_method_and_invalid_duration(self):
        for params in ({'method':'hot'},{'duration_s':True},{'duration_s':0},{'rate_bps':1}):
            with self.assertRaises(ValueError):
                validate_parameters(params)

    def test_preparation_failure_preserves_recovery_and_never_starts_child(self):
        self.app.functional = Mock(return_value={'complete':False,'reason':'invalid_baseline','recovery_required':True})
        coordinator = ContinuousComparison(self.app,session_factory=Mock())
        with patch('src.continuous_comparison.calibration_inputs',side_effect=ValueError('missing')):
            result = coordinator.run(self.parameters)
        self.assertEqual(result['outcome'],'recovery_required')
        self.assertEqual(result['sessions'],{})
        coordinator.session_factory.assert_not_called()

    def test_preparation_runs_required_checks_and_calibration_automatically(self):
        self.app.functional=Mock(return_value={'complete':True})
        self.app.calibrate=Mock(return_value={'complete':True})
        self.app.workload=lambda manifest:self.planner.workload
        calibration={'horizon_s':100}
        manifest={'resources':{'measured_controller_cpu_cores':.1,
                              'measured_controller_ram_gib':.1,'measured_controller_disk_gib':.1}}
        atomic_json(self.root/'results/direct_link_windows.json',{'windows':[
            dict(sat_a=a,sat_b=b,start_s=0,end_s=1500) for a in IDS for b in IDS if a<b]})
        fake=Mock()
        fake.run.return_value={'simulation_id':'sim-'+'a'*32,'migrations':[],
            'success':False,'complete':False,'outcome':'rejected'}
        with patch('src.continuous_comparison.calibration_inputs',side_effect=[ValueError('missing'),(calibration,manifest)]) as inputs:
            result=ContinuousComparison(self.app,session_factory=lambda:fake).run(self.parameters)
        self.app.functional.assert_called_once()
        self.app.calibrate.assert_called_once()
        self.assertEqual(inputs.call_count,2)
        self.assertEqual([row['stage'] for row in result['preparation']],['functional','calibration'])
        fake.run.assert_called_once()

    def test_recovery_concludes_stale_parent_without_resuming_comparison(self):
        identifier='pair-'+'b'*32
        path=self.root/'results/continuous-comparisons'/identifier/'metadata.json'
        atomic_json(path,{'comparison_id':identifier,'job_id':'job-old','phase':'cold',
            'parameters':{'duration_s':850},'sessions':{},'session_results':{},'events':[],
            'totals':{},'shared_plan_sha256':'fixed','outcome':'running'})
        reconcile_recovery(self.app,'job-old',{'complete':True,'controllers_fenced':True})
        saved=json.loads(path.read_text())
        self.assertEqual(saved['outcome'],'interrupted')
        self.assertEqual(saved['phase'],'finished')
        self.assertFalse(saved['complete'])
        self.assertEqual(saved['shared_plan_sha256'],'fixed')

    def test_unexpected_child_exception_keeps_recovery_lock_requirement(self):
        fake=Mock()
        def crash(parameters,**kwargs):
            identifier='sim-'+'f'*32
            atomic_json(self.root/'results/simulations'/identifier/'metadata.json',
                {'simulation_id':identifier,'phase':'migrating','migrations':[],
                 'success':False,'outcome':'running'})
            kwargs['on_created'](identifier)
            raise RuntimeError('worker failure before child return')
        fake.run.side_effect=crash
        result=ContinuousComparison(self.app,planner=self.planner,session_factory=lambda:fake).run(self.parameters)
        self.assertEqual(result['outcome'],'recovery_required')
        self.assertTrue(result['recovery_required'])
        self.assertEqual(fake.run.call_count,1)

    def test_changed_inputs_are_rejected_before_any_controller_reset(self):
        atomic_json(self.root/'config/fixture.json',{})
        for field,value in [('scenario_sha256','changed'),('fixture_sha256','changed'),
                            ('image_bundle_identity',{'sha256':'changed','bytes':5})]:
            with self.subTest(field=field):
                plan=shared_plan(self.planner,validate_parameters(self.parameters))
                plan[field]=value
                session=Simulation(self.app,planner=self.planner,backend_factory=SessionBackend,clock_factory=ManualClock)
                result=session.run({**self.parameters,'method':'hot'},fixed_plan=plan)
                self.assertFalse(result['success'])
                self.assertEqual(result['outcome'],'rejected')
                self.assertIsNone(session.backend)


if __name__ == '__main__':
    unittest.main()
