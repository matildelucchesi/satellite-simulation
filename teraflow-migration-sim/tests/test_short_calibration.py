import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from src.preparation import Preparation
from src.storage import atomic_json
from src.preconditions import calibration_inputs
from src.progress import advance

class ShortCalibrationTests(unittest.TestCase):
    def test_calibration_runs_exactly_once_per_mode_and_publishes_two_total(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);atomic_json(root/'results/functional-gate.json',{'complete':True})
            app=SimpleNamespace(root=root,scenario={'fso':{'alignment_s':1,'useful_throughput_bps':[1000000000]}},publish=Mock(),
                run=Mock(side_effect=lambda method,rate,**kw:{'run_id':method,'method':method,'success':True,'baseline':{'success':True}}),
                calibration_manifest=Mock(return_value={}),workload=Mock())
            with patch('src.simulation.engine_fingerprint',return_value='current'),patch('tools.validate_artifact_manifest.validate',return_value=[]),patch('src.preparation.describe',return_value={}),patch('src.preparation.evaluate',return_value=SimpleNamespace(total_operation_s=10)),patch('src.preparation.asdict',side_effect=lambda row:vars(row)):
                result=Preparation.calibrate(app)
            self.assertEqual([call.args[0] for call in app.run.call_args_list],['cold','hot'])
            self.assertEqual(result['replicas_per_mode'],1);self.assertEqual(result['calibration_total'],2)
            self.assertTrue(result['complete'])
            for call in app.publish.call_args_list:self.assertEqual(call.args[0]['replicas_per_mode'],1)
    def test_short_progress_hot_is_second_of_two(self):
        progress=advance({}, {'phase':'calibration','method':'hot','replica':1,'replicas_per_mode':1,'calibration_total':2})
        self.assertEqual(progress['calibration_index'],2);self.assertEqual(progress['calibration_total'],2)
    def test_admission_requires_both_modes_with_successful_baselines(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);bundle=root/'image';bundle.write_bytes(b'image')
            atomic_json(root/'config/artifact_manifest.json',{'image_bundle':{'path':str(bundle),'bytes':5}})
            atomic_json(root/'results/calibration.json',{'complete':True,'engine_fingerprint':'current','replicas_per_mode':1,'runs':['cold','hot'],'manifest':{}})
            for mode in ['cold','hot']:atomic_json(root/'results/runs'/mode/'metadata.json',{'method':mode,'success':True,'baseline':{'success':True}})
            with patch('src.simulation.engine_fingerprint',return_value='current'),patch('src.preconditions.verify_artifact'):
                self.assertTrue(calibration_inputs(root,full=False)[0]['complete'])
                atomic_json(root/'results/runs/hot/metadata.json',{'method':'cold','success':True,'baseline':{'success':True}})
                with self.assertRaisesRegex(ValueError,'Both cold and hot'):calibration_inputs(root,full=False)
                atomic_json(root/'results/runs/hot/metadata.json',{'method':'hot','success':True,'baseline':{'success':False}})
                with self.assertRaisesRegex(ValueError,'baseline'):calibration_inputs(root,full=False)
