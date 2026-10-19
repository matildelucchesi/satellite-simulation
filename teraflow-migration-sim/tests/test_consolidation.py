import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.clock import ManualClock
from src.experiment import Experiment
from src.jobs import JobManager
from src.orchestrator import Migration
from src.results import campaign_summary, finalize, read_result, requires_recovery
from src.simulation import Simulation
from src.storage import atomic_json, append_json, utc_now
from test_authority_orchestrator import Backend
from test_continuous import planner, SessionBackend, IDS


class ConsolidationTests(unittest.TestCase):
    def test_nested_recovery_dominates_cancellation_and_keeps_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);manager=JobManager(root);jid='job-'+'1'*32
            atomic_json(manager.guard,{'job_id':jid})
            atomic_json(manager.directory/jid/'job.json',{'job_id':jid,'operation':'continuous_validation','parameters':{}})
            atomic_json(manager.directory/jid/'cancel.json',{})
            app=Mock();app.continuous_validation.return_value={'complete':False,'sessions':[{'outcome':'recovery_required'}]}
            with patch('src.experiment.Experiment',return_value=app):manager.work(jid)
            self.assertEqual(manager.get(jid)['status'],'recovery_required')
            self.assertTrue(manager.guard.exists())
            self.assertTrue(json.loads((manager.directory/jid/'result.json').read_text())['recovery_required'])

    def test_continuous_validation_propagates_child_recovery_and_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);atomic_json(root/'config/scenario.json',{})
            app=Experiment(root);app.simulate=Mock(return_value={'simulation_id':'sim-dead',
                'success':False,'migrations':[],'outcome':'recovery_required','recovery_required':True})
            fake=Mock();fake.prepare_planner.return_value.plan.return_value={'start_s':0,'initial_satellite_id':53848}
            with patch('src.simulation.Simulation',return_value=fake):result=app.continuous_validation()
            self.assertTrue(result['recovery_required']);self.assertFalse(result['complete'])
            self.assertEqual(app.simulate.call_count,1)

    def test_active_second_run_controls_recovery_not_first_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);atomic_json(root/'config/scenario.json',{})
            jid='job-'+'a'*32;first='run-'+'b'*32;second='run-'+'c'*32
            folder=root/'results/jobs'/jid
            atomic_json(folder/'job.json',{'job_id':jid})
            for rid,deadline in ((first,99999),(second,1)):
                atomic_json(root/'results/runs'/rid/'inputs.json',{'event':{'trigger_s':30,'deadline_s':deadline}})
                append_json(folder/'events.jsonl',{'run_id':rid,'orbital_s':200,'timestamp_utc':utc_now()})
            atomic_json(folder/'active-checkpoint.json',{'kind':'run','run_id':second,
                'orbital_s':200,'timestamp_utc':utc_now()})
            with patch('src.experiment.http'),patch('src.live_backend.Compose') as compose:
                result=Experiment(root).recover(jid)
            self.assertTrue(result['source_expired']);self.assertTrue(result['complete'])
            compose.return_value.start.assert_not_called()

    def test_ambiguous_legacy_job_fences_both_and_requires_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);atomic_json(root/'config/scenario.json',{})
            jid='job-'+'a'*32;folder=root/'results/jobs'/jid
            folder.mkdir(parents=True)
            for rid in ('run-'+'b'*32,'run-'+'c'*32):append_json(folder/'events.jsonl',{'run_id':rid})
            with patch('src.experiment.http'),patch('src.live_backend.Compose') as compose:
                result=Experiment(root).recover(jid)
            self.assertTrue(result['recovery_required']);self.assertFalse(result['complete'])
            self.assertEqual({c.args[0] for c in compose.return_value.stop.call_args_list},{'sat-a','sat-b'})

    def test_continuous_ping_failure_never_advances_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);image=root/'image.tar';image.write_bytes(b'image');p=planner()
            app=SimpleNamespace(root=root,scenario=p.scenario,orbit=p.orbit,cancel=threading.Event(),
                publish=Mock(),bundle=lambda:{'image_bundle':{'path':str(image)}})
            class Broken(SessionBackend):
                def verify_service(self,**kwargs):raise RuntimeError('ping failed')
            session=Simulation(app,planner=p,backend_factory=Broken,clock_factory=ManualClock)
            result=session.run({'duration_s':100,'start_orbital_s':0,'initial_satellite_id':IDS[0]})
            self.assertFalse(result['success']);self.assertEqual(len(result['controller_history']),1)
            self.assertTrue(result['migrations'][0]['migration_completed'])
            self.assertFalse(result['migrations'][0]['success'])
            self.assertEqual(session.backend.shutdown_count,1)

    def test_continuous_cleanup_failure_requires_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);image=root/'image.tar';image.write_bytes(b'image');p=planner()
            app=SimpleNamespace(root=root,scenario=p.scenario,orbit=p.orbit,cancel=threading.Event(),
                publish=Mock(),bundle=lambda:{'image_bundle':{'path':str(image)}})
            class Broken(SessionBackend):
                def shutdown(self):raise RuntimeError('cannot fence')
            result=Simulation(app,planner=p,backend_factory=Broken,clock_factory=ManualClock).run(
                {'duration_s':100,'start_orbital_s':0,'initial_satellite_id':IDS[0]})
            self.assertTrue(result['recovery_required']);self.assertFalse(result['success'])

    def test_retry_success_clears_final_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock=ManualClock();image=Path(tmp)/'image.tar';image.write_bytes(b'image')
            class Retry(Backend):
                count=0
                def transfer(self,path,event):
                    self.count+=1
                    if self.count==1:raise ConnectionError('first attempt failed')
                    return super().transfer(path,event)
            result=Migration(Retry(clock),clock,Path(tmp)/'op',{'fso':{'alignment_s':1,'max_attempts':3}}).run(
                'hot',{'deadline_s':1000,'trigger_causes':[]},image)
            self.assertTrue(result['success']);self.assertEqual(result['attempt'],2)
            self.assertIsNone(result['failure_reason']);self.assertIsNone(result['failure_phase'])
            self.assertTrue(any(e['phase']=='attempt_failed' for e in result['events']))

    def test_invalid_throughput_or_cancel_does_not_erase_technical_success(self):
        for invalid,cancelled in ((True,False),(False,True)):
            result={'migration_completed':True,'service_verification':{'success':True},
                'observation_complete':not cancelled,'experimental_valid':not invalid,'interrupted':cancelled}
            finalize(result)
            self.assertTrue(result['migration_completed']);self.assertFalse(result['success'])
            self.assertEqual(result['outcome'],'invalid_lab' if invalid else 'interrupted')

    def test_late_cancel_preserves_verified_destination_and_closes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);atomic_json(root/'config/scenario.json',{'fso':{'useful_throughput_bps':[10**9]}})
            image=root/'image.tar';image.write_bytes(b'image');cancel=threading.Event()
            app=Experiment(root,cancel);app.bundle=lambda:{'image_bundle':{'path':str(image)}}
            app._orbit=SimpleNamespace(duration=1000)
            backend=Mock(clock=None,source_snapshot={},measurements=[],cancelled=False)
            backend.a=SimpleNamespace(calls=[]);backend.b=SimpleNamespace(calls=[])
            backend.start_observation.side_effect=lambda clock,rid:setattr(backend,'clock',clock)
            backend.establish_baseline.return_value={'success':True}
            def verify(**kwargs):cancel.set();return {'success':True}
            backend.verify_service.side_effect=verify
            def check():
                if cancel.is_set():raise InterruptedError('cancel')
            backend.check.side_effect=check
            migration=Mock();migration.run.return_value={'success':True,'ack':True,'attempt':1,'events':[]}
            with patch('src.experiment.LiveBackend',return_value=backend),patch('src.experiment.LiveClock',side_effect=ManualClock),patch('src.experiment.Migration',return_value=migration),patch('src.experiment.time.sleep',side_effect=lambda seconds:backend.clock.sleep(seconds)):
                result=app.run('hot',10**9,{'trigger_s':30,'deadline_s':900})
            self.assertEqual(result['outcome'],'interrupted');self.assertFalse(result['success'])
            self.assertTrue(result['migration_completed']);self.assertFalse(result['observation_complete'])
            backend.abort_target.assert_not_called();backend.recover_source.assert_not_called();backend.close.assert_called_once()

    def test_campaign_uses_expected_cases_and_own_run_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            good={'run_id':'one','purpose':'primary','event':{'event_id':'expected'},'method':'hot',
                'configured_rate_bps':10**9,'outcome':'experimental_failure','success':False,
                'experimental_valid':True,'observation_complete':True}
            foreign={**good,'run_id':'foreign','event':{'event_id':'missing'},'success':True,'outcome':'success'}
            atomic_json(root/'results/campaign.json',{'campaign_id':'new','runs':['one'],
                'expected_cases':[['expected','hot',10**9],['missing','hot',10**9]]})
            result=campaign_summary(root,[good,good,foreign]);self.assertFalse(result['primary_complete'])
            self.assertEqual(result['unique_primary_cases'],1)
            atomic_json(root/'results/campaign.json',{'campaign_id':'new','runs':['one'],
                'expected_cases':[['expected','hot',10**9]]})
            result=campaign_summary(root,[good,foreign]);self.assertTrue(result['primary_complete'])
            self.assertFalse(result['all_primary_successful'])
            good['outcome']='interrupted';self.assertFalse(campaign_summary(root,[good])['primary_complete'])

    def test_historical_results_remain_nullable_not_promoted(self):
        result=read_result({'success':True,'outcome':'success'})
        self.assertIsNone(result['observation_complete'])
        self.assertIsNone(result['service_verification']['success'])
        self.assertFalse(requires_recovery(result))
        nullable=read_result({'success':False,'service_verification':None,'probes':None})
        self.assertIsNone(nullable['metrics']['ping_recovery_s'])
        self.assertIsNone(nullable['metrics']['service_verified'])

    def test_ping_metrics_use_only_the_migration_window(self):
        from src.probes import summarize_ping
        rows=[{'sequence':i,'unix_s':i,'success':i!=0,'rtt_ms':1 if i else None} for i in range(15)]
        result=summarize_ping(rows,migration_start_unix_s=2,observation_end_unix_s=12,baseline_path_available=True)
        self.assertEqual(result['observed_probes'],11)
        self.assertEqual(result['lost_probes'],0)
        self.assertTrue(result['continuous_during_observation'])
        self.assertIsNone(result['time_to_stable_recovery_s'])

    def test_transfer_cancellation_recovers_and_does_not_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            image=Path(tmp)/'image.tar';image.write_bytes(b'image');clock=ManualClock()
            class Cancelled(Backend):
                def transfer(self,*args):raise InterruptedError('cancel transfer')
            backend=Cancelled(clock)
            result=Migration(backend,clock,Path(tmp)/'op',{'fso':{'alignment_s':1,'max_attempts':3}}).run(
                'cold',{'deadline_s':1000,'trigger_causes':[]},image)
            self.assertFalse(result['success']);self.assertTrue(result['interrupted'])
            self.assertEqual(result['attempt'],1);self.assertIn('recover',backend.calls)

    def test_verification_cancellation_concludes_continuous_safely(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);image=root/'image.tar';image.write_bytes(b'image');p=planner()
            app=SimpleNamespace(root=root,scenario=p.scenario,orbit=p.orbit,cancel=threading.Event(),
                publish=Mock(),bundle=lambda:{'image_bundle':{'path':str(image)}})
            class Cancelled(SessionBackend):
                def verify_service(self,**kwargs):raise InterruptedError('cancel verification')
            session=Simulation(app,planner=p,backend_factory=Cancelled,clock_factory=ManualClock)
            result=session.run({'duration_s':100,'start_orbital_s':0,'initial_satellite_id':IDS[0]})
            self.assertEqual(result['outcome'],'interrupted');self.assertFalse(result['success'])
            self.assertEqual(session.backend.shutdown_count,1)

    def test_rate_gate_uses_only_image_receipt_and_preserves_cutover(self):
        from src.handover import execute
        for rate in (10**9,10**8):
            with self.subTest(image_rate=rate),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);image=root/'image.tar';image.write_bytes(b'image')
                def receipt(name,throughput):
                    return {'phase':'transfer_verified','payload':name,'receipt':{
                        'sha256':name,'received_bytes':5,'useful_throughput_bps':throughput}}
                protocol=Mock();protocol.run.return_value={'success':True,'ack':True,'attempt':1,
                    'events':[receipt(image.name,rate),receipt('snapshot-1.json',1)]}
                backend=SimpleNamespace(clock=ManualClock(),rate=10**9,
                    verify_service=Mock(return_value={'success':True}))
                result=execute(protocol,backend,'hot',{},image,{},root)
                result['observation_complete']=True;finalize(result)
                self.assertTrue(result['migration_completed']);self.assertTrue(result['ack'])
                self.assertEqual(result['image_throughput_bps'],rate)
                self.assertEqual(result['success'],rate==10**9)
                self.assertEqual(result['outcome'],'success' if rate==10**9 else 'invalid_lab')

    def test_api_projection_and_report_csv_share_metrics(self):
        import csv
        from src.analysis import Analysis
        from src.web import Application
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rid='run-'+'e'*32
            record={'run_id':rid,'purpose':'diagnostic','method':'hot','event':{},'outcome':'success',
                'success':True,'configured_rate_bps':10**9,'controller_downtime_s':2.5,
                'total_operation_s':12.5,'service_verification_s':1.25,'observation_s':30,
                'service_verification':{'success':True},'observation_complete':True,'experimental_valid':True}
            atomic_json(root/'results/runs'/rid/'inputs.json',{})
            atomic_json(root/'results/runs'/rid/'metadata.json',record)
            projected=Application(root).runs()[0]
            Analysis.report(SimpleNamespace(root=root))
            with (root/'results/report/runs.csv').open(newline='',encoding='utf-8') as stream:
                exported=next(csv.DictReader(stream))
            for key in ('controller_downtime_s','total_operation_s','service_verification_s','observation_s'):
                self.assertEqual(float(exported[key]),projected['metrics'][key])
            self.assertEqual(exported['service_verified'],'True')


if __name__=='__main__':unittest.main()
