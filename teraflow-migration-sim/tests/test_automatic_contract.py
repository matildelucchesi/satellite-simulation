import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from src.automatic_start import SelectionInvalidated, POLICY
from src.continuous_comparison import ContinuousComparison,validate_parameters
from src.storage import atomic_json,append_json


class AutomaticContractTests(unittest.TestCase):
    def test_frozen_selection_reuse_checks_input_identity_and_plan_integrity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);bundle=root/'image.tar';bundle.write_bytes(b'image')
            app=SimpleNamespace(root=root,scenario={'live':{}},bundle=lambda:{'image_bundle':{'path':str(bundle)}})
            coordinator=ContinuousComparison(app,planner=Mock())
            identifier='pair-'+'a'*32
            coordinator.directory=root/'results/continuous-comparisons'/identifier
            coordinator.result={};coordinator.save=Mock()
            atomic_json(coordinator.directory/'metadata.json',{})
            parameters=validate_parameters({'migration_count':3})
            chosen={'initial_satellite_id':7,'start_orbital_s':9,'minimum_margin_s':20}
            evidence={'selected':chosen,'policy_version':POLICY,'exhaustive':True}
            plan={'initial_satellite_id':7,'start_s':9,'migrations':[]}
            with patch('src.automatic_start.select_start',return_value=(evidence,{'1000000000':plan})):
                self.assertEqual(coordinator.automatic_plan(parameters),plan)
            reuse={**parameters,'selection_id':identifier}
            self.assertEqual(coordinator.automatic_plan(reuse),plan)
            path=coordinator.directory/'selection.json';saved=json.loads(path.read_text())
            saved['policy_version']='automatic-start-service-v2';atomic_json(path,saved)
            with self.assertRaisesRegex(SelectionInvalidated,'criterio di partenza precedente'):coordinator.automatic_plan(reuse)
            saved['policy_version']=POLICY;atomic_json(path,saved)
            app.scenario['changed']=True
            with self.assertRaises(SelectionInvalidated):coordinator.automatic_plan(reuse)
            del app.scenario['changed']
            path=coordinator.directory/'selection.json';saved=json.loads(path.read_text())
            saved['selected']['start_orbital_s']=10;atomic_json(path,saved)
            with self.assertRaisesRegex(SelectionInvalidated,'configurazione risolta'):coordinator.automatic_plan(reuse)
            saved['selected']['start_orbital_s']=9
            saved['plans']['1000000000']['start_s']=10;atomic_json(path,saved)
            with self.assertRaisesRegex(SelectionInvalidated,'alterato'):coordinator.automatic_plan(reuse)

    def test_container_diagnostics_do_not_break_physical_resources_csv(self):
        from src.simulation_report import report
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);directory=root/'session'
            atomic_json(directory/'metadata.json',{'simulation_id':'sim-test','outcome':'failed',
                'policy_version':'test','migrations':[],'controller_history':[],'failure_reason':'Forwarding failed'})
            append_json(directory/'resources.jsonl',{'timestamp_utc':'2026-10-22T00:00:00Z',
                'hosts':{'sat-a':{'running_containers':1,'cpu_cores':0.5,'ram_gib':1,
                                   'containers':[{'id':'preserved-in-json'}]}}})
            result=report(directory,root)
            with (directory/'physical-resources.csv').open(newline='') as handle:
                rows=list(csv.DictReader(handle))
            self.assertEqual(rows[0]['cpu_cores'],'0.5')
            self.assertIn('preserved-in-json',(directory/'resources.jsonl').read_text())
            self.assertEqual(json.loads((directory/'metadata.json').read_text())['failure_reason'],'Forwarding failed')
