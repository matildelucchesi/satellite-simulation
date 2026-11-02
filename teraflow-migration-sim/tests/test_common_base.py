import copy
import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from src import common_base
from src.storage import atomic_json
from src.continuous_comparison import ContinuousComparison,validate_parameters
from src.simulation import engine_fingerprint

class CommonBaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        for name,value in {'config/scenario.json':{},'config/fixture.json':{},'config/selected_constellation.json':{},'config/artifact_manifest.json':{},'results/calibration.json':{},'results/direct_link_windows.json':{'windows':[]}}.items():atomic_json(self.root/name,value)
        replay=self.root/'artifacts/orbit/replay.npz';replay.parent.mkdir(parents=True);replay.write_bytes(b'orbit')
        atomic_json(replay.with_suffix('.json'),{'artifact':{'sha256':hashlib.sha256(b'orbit').hexdigest()}})
        self.app=SimpleNamespace(root=self.root,scenario={'live':{}},cancel=threading.Event(),publish=Mock(),orbit=SimpleNamespace(graph=Mock(return_value={})))
        self.plan={'initial_satellite_id':11,'start_s':100,'parameters':{'rate_bps':100000000},'migrations':[{'sat_a':11+i,'sat_b':12+i,'trigger_s':100+i*100,'estimated_operation_s':50,'recovery_reserve_s':5} for i in range(3)]}
        self.selected={'initial_satellite_id':11,'start_orbital_s':100,'initial_time_to_shadow_s':80,'minimum_margin_s':5}
        manifest={'resources':{'measured_controller_'+key:1 for key in ('cpu_cores','ram_gib','disk_gib')}}
        self.inputs=patch('src.common_base.calibration_inputs',return_value=({'horizon_s':100},manifest));self.inputs.start()
        self.mocks=[patch('src.planner.Planner'),patch('src.planner.OrbitIndex'),patch('src.migration_model.workload_from_manifest'),patch('src.fixture.state',return_value={'entities':{}}),patch('src.automatic_start.select_start',return_value=({'selected':self.selected,'exhaustive':True},{'100000000':self.plan})),patch('src.continuous_comparison.SharedPlanner')]
        active=[mock.start() for mock in self.mocks];active[-1].return_value.estimate.return_value=(50,5)
    def tearDown(self):
        for mock in reversed(self.mocks):mock.stop()
        self.inputs.stop();self.temp.cleanup()
    def test_base_freezes_scenario_and_one_schedule_for_all_rates(self):
        metadata=common_base.prepare(self.app)
        loaded,plan=common_base.load(self.root,metadata['base_id'],full=True)
        self.assertEqual(loaded['rates'],common_base.RATES)
        self.assertEqual(plan['admission_rate_bps'],100000000)
        self.assertEqual(plan['migrations'],self.plan['migrations'])
        self.assertTrue((common_base.directory(self.root,metadata['base_id'])/'initial-state.json').exists())
        self.assertTrue(common_base.status(self.root)['plan_ready'])
        self.assertFalse(common_base.status(self.root)['ready'])
    def test_plan_tampering_and_input_changes_invalidate_the_base(self):
        metadata=common_base.prepare(self.app);path=common_base.directory(self.root,metadata['base_id'])
        (path/'plan.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'alterato'):common_base.load(self.root,metadata['base_id'])
        metadata=common_base.prepare(self.app)
        atomic_json(self.root/'config/fixture.json',{'changed':True})
        self.assertFalse(common_base.status(self.root)['ready'])
    def test_all_rates_reuse_identical_events_without_running_a_new_search(self):
        metadata=common_base.prepare(self.app)
        coordinator=ContinuousComparison(self.app);coordinator.directory=self.root/'comparison';coordinator.directory.mkdir()
        coordinator.result={};coordinator.save=Mock();coordinator.selection_identity=Mock(return_value={})
        events=[]
        for rate in common_base.RATES:
            plan=coordinator.automatic_plan(validate_parameters({'base_id':metadata['base_id'],'migration_count':3,'rate_bps':rate}))
            self.assertEqual(plan['parameters']['rate_bps'],rate);events.append(plan['migrations'])
        self.assertEqual(events[0],events[1]);self.assertEqual(events[1],events[2])
        self.assertEqual(coordinator.result['common_schedule_sha256'],metadata['schedule_sha256'])
    def test_gui_and_job_changes_do_not_invalidate_calibration_but_backend_changes_do(self):
        source=self.root/'src';source.mkdir()
        (source/'live_backend.py').write_text('backend')
        before=engine_fingerprint(self.root)
        (source/'web.py').write_text('changed UI');(source/'jobs.py').write_text('dispatch');(source/'common_base.py').write_text('base')
        self.assertEqual(before,engine_fingerprint(self.root))
        (source/'live_backend.py').write_text('changed backend')
        self.assertNotEqual(before,engine_fingerprint(self.root))
    def test_unsupported_fast_rate_estimate_prevents_base_publication(self):
        with patch('src.continuous_comparison.SharedPlanner') as shared:
            shared.return_value.estimate.side_effect=lambda method,rate:(60 if rate==1000000000 else 50,5)
            with self.assertRaisesRegex(ValueError,'tutte le velocità'):common_base.prepare(self.app)
        self.assertFalse(list((self.root/'results/common-bases').glob('*/metadata.json')))

    def test_full_validation_checks_the_actual_orbital_replay(self):
        metadata=common_base.prepare(self.app)
        (self.root/'artifacts/orbit/replay.npz').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'Replay orbitale alterato'):common_base.load(self.root,metadata['base_id'],full=True)

    def test_invalid_base_identifiers_and_incompatible_parameters_are_rejected(self):
        with self.assertRaises(ValueError):common_base.directory(self.root,'../elsewhere')
        with self.assertRaises(ValueError):validate_parameters({'base_id':'base-'+'a'*32,'additional_data_bytes':1})


class ScenarioCreationWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.activation=patch('src.prepared_source.prepare',side_effect=lambda app,metadata:metadata)
        self.activation.start();self.addCleanup(self.activation.stop)
    def app(self,root):
        return SimpleNamespace(root=Path(root),cancel=threading.Event(),publish=Mock(),
            functional=Mock(return_value={'complete':True}),calibrate=Mock(return_value={'complete':True}))
    def test_valid_measurements_skip_calibration(self):
        from src.experiment import Experiment
        with tempfile.TemporaryDirectory() as root,patch('src.preconditions.calibration_inputs'),patch('src.common_base.prepare',return_value={'complete':True}) as prepare:
            app=self.app(root);result=Experiment.prepare_base(app)
            app.functional.assert_not_called();app.calibrate.assert_not_called();prepare.assert_called_once_with(app)
            self.assertTrue(result['complete'])
    def test_missing_measurements_run_preliminary_checks_then_calibrate_then_prepare(self):
        from src.experiment import Experiment
        with tempfile.TemporaryDirectory() as root,patch('src.preconditions.calibration_inputs',side_effect=ValueError('missing')),patch('src.common_base.prepare',return_value={'complete':True}) as prepare:
            app=self.app(root);calls=[]
            app.functional.side_effect=lambda:calls.append('functional') or {'complete':True}
            app.calibrate.side_effect=lambda:calls.append('calibrate') or {'complete':True}
            prepare.side_effect=lambda app:calls.append('prepare') or {'complete':True}
            Experiment.prepare_base(app);self.assertEqual(calls,['functional','calibrate','prepare'])
    def test_failed_calibration_does_not_publish_a_base_and_preserves_recovery(self):
        from src.experiment import Experiment
        with tempfile.TemporaryDirectory() as root,patch('src.preconditions.calibration_inputs',side_effect=ValueError('missing')),patch('src.common_base.prepare') as prepare:
            app=self.app(root);app.calibrate.return_value={'complete':False,'recovery_required':True,'reason':'failed'}
            result=Experiment.prepare_base(app)
            self.assertTrue(result['recovery_required']);self.assertFalse(result['complete']);prepare.assert_not_called()
    def test_valid_functional_gate_is_reused(self):
        from src.experiment import Experiment
        with tempfile.TemporaryDirectory() as root,patch('src.preconditions.calibration_inputs',side_effect=ValueError('missing')),patch('src.common_base.prepare'):
            app=self.app(root);runs=[{'run_id':'a'},{'run_id':'b'}]
            atomic_json(app.root/'results/functional-gate.json',{'complete':True,'runs':runs})
            for row in runs:atomic_json(app.root/'results/runs'/row['run_id']/'metadata.json',{})
            Experiment.prepare_base(app);app.functional.assert_not_called();app.calibrate.assert_called_once()
