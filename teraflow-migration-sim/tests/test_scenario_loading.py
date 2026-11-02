import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from src.preparation_budget import PreparationBudget, restore_budget, DEFAULTS
from src.tfs_adapter import TfsAdapter, NbiTimeout, NbiHttpError
from src.snapshot import snapshot
from src.progress import advance
from src.results import finalize

class ScenarioLoadingTests(unittest.TestCase):
    def document(self,count=64):
        return snapshot({'devices':[{'device_id':{'device_uuid':{'uuid':str(i)}},'name':f'sat-{i}',
          'device_config':{'config_rules':[{'custom':{'resource_key':'_connect/address'}},{'custom':{'resource_key':'/tables/x'}}]},
          'device_endpoints':[]} for i in range(count)]})

    def test_formula_override_and_validation(self):
        doc=self.document()
        evidence=restore_budget({},doc)
        self.assertEqual(evidence['calculated_limit_s'],824)
        for value in (0,-1,True,float('inf'),float('nan')):
            with self.assertRaises(ValueError):restore_budget({'live':{'restore_budget_coefficients_s':{'devices':value}}},doc)
        with tempfile.TemporaryDirectory() as folder:
            b=PreparationBudget(Path(folder),{'live':{'preparation_budgets_s':{'restore_scenario':120}}},lambda e:None,document=doc)
            self.assertEqual(b.limits['restore_scenario'],120)
            self.assertTrue(b.restore['override_below_calculated'])
            self.assertEqual(b.total_limit,sum(b.limits.values()))
            self.assertEqual(json.loads((Path(folder)/'preparation-budget.json').read_text())['restore']['counts']['devices'],64)

    def test_64_sequential_devices_outlive_old_budget_and_progress_is_truthful(self):
        tick=[0.];events=[];doc=self.document()
        adapter=TfsAdapter('http://unused');adapter.notify=events.append
        adapter._read=lambda:snapshot({})
        def request(method,path,body=None):
            if method=='POST' and path=='/devices':tick[0]+=5.6
            if method=='GET':return {'device_config':{'config_rules':[]}}
        adapter.request=request
        with tempfile.TemporaryDirectory() as folder,patch('src.preparation_budget.time.monotonic',side_effect=lambda:tick[0]):
            budget=PreparationBudget(Path(folder),{},events.append,document=doc)
            adapter.guard=lambda:self.assertGreater(budget.remaining(),0)
            with budget.stage('restore_scenario'):adapter.restore(doc)
            self.assertGreater(tick[0],120)
            self.assertEqual(adapter.restore_progress['devices']['completed'],64)
            completed=[e['counts']['devices']['completed'] for e in events if e.get('entity_completed') and e['entity']['kind']=='devices']
            self.assertEqual(completed,list(range(1,65)))

    def test_failed_entity_is_not_counted(self):
        adapter=TfsAdapter('http://unused');adapter._read=lambda:snapshot({})
        def request(method,path,body=None):
            if method=='POST' and path=='/devices':raise NbiTimeout('blocked')
        adapter.request=request
        with self.assertRaises(NbiTimeout):adapter.restore(self.document(1))
        self.assertEqual(adapter.restore_progress['devices']['completed'],0)

    def test_request_timeout_http_cancel_and_exhaustion_are_preserved(self):
        for failure,expected in ((TimeoutError('blocked'),'nbi_timeout'),(InterruptedError('cancel'),'interrupted'),
              (HTTPError('http://unused',503,'unavailable',{},None),'nbi_http_error')):
            with self.subTest(expected=expected):
                events=[];adapter=TfsAdapter('http://unused');adapter.notify=events.append
                adapter.remaining=lambda:10
                with patch('src.tfs_adapter.urlopen',side_effect=failure):
                    with self.assertRaises(Exception):adapter.request('POST','/devices',{})
                self.assertEqual(events[0]['request_status'],'running')
                self.assertEqual(events[-1]['request_status'],'failed')
                self.assertEqual(adapter.calls[-1]['error_code'],expected)
        adapter=TfsAdapter('http://unused');adapter.remaining=lambda:0
        with patch('src.tfs_adapter.urlopen') as opened:
            with self.assertRaises(TimeoutError):adapter.request('GET','/devices')
            opened.assert_not_called()

    def test_error_code_distinguishes_request_from_stage_timeout(self):
        for expired,code in ((False,'nbi_timeout'),(True,'preparation_timeout')):
            tick=[0.]
            with tempfile.TemporaryDirectory() as folder,patch('src.preparation_budget.time.monotonic',side_effect=lambda:tick[0]):
                budget=PreparationBudget(Path(folder),{},lambda e:None)
                with self.assertRaises(NbiTimeout):
                    with budget.stage('restore_scenario'):
                        if expired:tick[0]=121
                        raise NbiTimeout('blocked')
                self.assertEqual(budget.error['code'],code)
        result=finalize({'run_id':'run-x','outcome':'preparation_failed','error':{'code':'nbi_timeout'}})
        self.assertEqual(result['outcome'],'preparation_failed');self.assertFalse(result['experimental_valid'])

    def test_progress_survives_terminal_and_started_call_is_not_progress(self):
        initial=advance({}, {'phase':'preparation_operation','operation':'restore_scenario','label':'Caricamento'})
        with patch('src.progress.utc_now',return_value='later'):
            p=advance(initial,{'phase':'restore_request','request_status':'running','request':{'path':'/devices'}})
            self.assertEqual(p['last_progress_utc'],initial['last_progress_utc'])
        counts={'devices':{'completed':20,'total':64}}
        p=advance(p,{'phase':'restore_progress','counts':counts,'entity':{'name':'sat-20'}})
        p=advance(p,{'phase':'comparison_finished','outcome':'failed'})
        self.assertEqual(p['restore_counts'],counts)
        self.assertEqual(p['restore_entity']['name'],'sat-20')
