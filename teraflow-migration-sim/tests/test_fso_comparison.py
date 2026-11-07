import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.experiment import Experiment
from src.clock import ManualClock
from src.live_backend import LiveBackend
from src.probes import baseline_ready
from src.storage import atomic_json


class ComparisonTests(unittest.TestCase):
    def test_baseline_or_post_cutover_ping_failure_cannot_leave_success_true(self):
        for baseline_failed in (True,False):
            with self.subTest(baseline_failed=baseline_failed),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);atomic_json(root/'config/scenario.json',{'fso':{'useful_throughput_bps':[10**9]}})
                image=root/'image.tar';image.write_bytes(b'image')
                app=Experiment(root);app.bundle=Mock(return_value={'image_bundle':{'path':str(image)}})
                app._orbit=SimpleNamespace(duration=1000)
                backend=Mock(clock=None,source_snapshot={'verified':True},measurements=[],cancelled=False)
                backend.a=SimpleNamespace(calls=[]);backend.b=SimpleNamespace(calls=[])
                def start(clock,identifier):backend.clock=clock
                backend.start_observation.side_effect=start
                backend.establish_baseline.return_value={'success':True}
                if baseline_failed:backend.establish_baseline.side_effect=TimeoutError('baseline ping failed')
                backend.verify_service.side_effect=TimeoutError('post-cutover ping failed')
                migration=Mock()
                migration.run.return_value={'success':True,'ack':True,'attempt':1,'events':[]}
                event={'trigger_s':30,'deadline_s':900}
                with patch('src.experiment.LiveBackend',return_value=backend), \
                     patch('src.experiment.LiveClock',side_effect=ManualClock), \
                     patch('src.experiment.Migration',return_value=migration) as factory, \
                     patch('src.experiment.time.sleep',side_effect=lambda seconds:backend.clock.sleep(seconds)):
                    result=app.run('hot',10**9,event)
                self.assertFalse(result['success']);self.assertFalse(result['ack'])
                if baseline_failed:
                    factory.assert_not_called();self.assertEqual(result['outcome'],'invalid_baseline')
                else:
                    backend.abort_target.assert_called_once();backend.recover_source.assert_called_once()
                    self.assertEqual(result['outcome'],'experimental_failure')

    def test_pair_freezes_one_event_and_preserves_both_runs_and_differences(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);atomic_json(root/'config/scenario.json',{'fso':{'useful_throughput_bps':[10**9]}})
            app=Experiment(root)
            event={'event_id':'fso-one','trigger_s':100,'sat_a':1,'sat_b':2}
            app.functional_event=Mock(return_value=event)
            calls=[]
            def run(method,rate,selected,**kwargs):
                calls.append((method,rate,copy.deepcopy(selected)))
                selected['trigger_s']=999  # A run must not modify its paired input.
                return {'run_id':'run-'+method,'method':method,'success':True,'outcome':'success',
                    'baseline':{'success':True},'service_verification':{'success':True},
                    'controller_downtime_s':2 if method=='hot' else 8,
                    'total_operation_s':20,'attempt':1,
                    'probes':{'ping':{'continuous_during_observation':True,'time_to_stable_recovery_s':None}}}
            app.run=run
            result=app.functional()
            self.assertTrue(result['complete'])
            app.functional_event.assert_called_once()
            self.assertEqual(calls,[('hot',10**9,event),('cold',10**9,event)])
            self.assertEqual(result['cold_minus_hot']['controller_downtime_s'],6)
            self.assertIsNone(result['cold_minus_hot']['ping_recovery_s'])
            saved=json.loads((root/'results/comparisons'/result['comparison_id']/'metadata.json').read_text())
            self.assertEqual(saved,result)

    def test_pair_stops_on_invalid_baseline_or_failed_post_cutover_ping(self):
        for outcome in ('invalid_baseline','experimental_failure','recovery_required'):
            with self.subTest(outcome=outcome),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);atomic_json(root/'config/scenario.json',{'fso':{'useful_throughput_bps':[10**9]}})
                app=Experiment(root);app.functional_event=Mock(return_value={'event_id':'one'})
                app.run=Mock(return_value={'run_id':'run-hot','method':'hot','success':False,
                    'outcome':outcome,'baseline':{'success':outcome!='invalid_baseline'}})
                result=app.functional()
                self.assertFalse(result['complete']);self.assertEqual(result['reason'],outcome)
                self.assertEqual(app.run.call_count,1)

    def test_baseline_rejects_stale_or_nonconsecutive_ping_even_without_udp(self):
        rows=[dict(unix_s=101+i/10,sequence=i,success=True,rtt_ms=1) for i in range(10)]
        status={'active':'sat-a','frozen':False,'states':[{'upstream_master':True}]}
        self.assertTrue(baseline_ready(rows,[],status,100,'sat-a',now=102))
        self.assertFalse(baseline_ready(rows,[],status,100,'sat-a',now=105))
        rows[-1]['sequence']=99
        self.assertFalse(baseline_ready(rows,[],status,100,'sat-a'))

    def test_post_cutover_requires_fresh_ping_and_target_authority(self):
        for old,active in ((False,'sat-b'),(True,'sat-b'),(False,'sat-a')):
            with self.subTest(old=old,active=active),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);probes=root/'results/lab/run-one';probes.mkdir(parents=True)
                base=180 if old else 199
                (probes/'ping.log').write_text('\n'.join(
                    f'[{base+i/20}] 64 bytes from 10.0.0.2: icmp_seq={i} ttl=64 time=1 ms' for i in range(10)))
                backend=LiveBackend.__new__(LiveBackend)
                backend.directory=root;backend.root=root;backend.probe_id='run-one'
                backend.cutover_unix_s=190;backend.target_slot='sat-b'
                backend.orbit=SimpleNamespace(duration=1000);backend.clock=SimpleNamespace(orbital=lambda:200)
                backend.remaining=lambda:100;backend.check=Mock();backend.cancel=threading.Event()
                backend.b=SimpleNamespace(base_url='http://localhost:18081/tfs-api')
                backend.notify=Mock();backend.event_context={}
                status={'active':active,'frozen':False,'states':[{'upstream_master':True}]}
                response=Mock();response.__enter__=Mock(return_value=SimpleNamespace(status=200));response.__exit__=Mock()
                with patch('src.live_backend.http',return_value=status),patch('src.live_backend.urlopen',return_value=response), \
                     patch('src.live_backend.time.time',return_value=200),patch('src.live_backend.time.monotonic',side_effect=[0,0,31]):
                    if old or active!='sat-b':
                        with self.assertRaises(TimeoutError):backend.verify_service()
                    else:self.assertTrue(backend.verify_service()['success'])
                evidence=json.loads((root/'service-verification.json').read_text())
                self.assertEqual(evidence['success'],not old and active=='sat-b')


if __name__=='__main__':unittest.main()
