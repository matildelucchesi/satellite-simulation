import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.experiment import Experiment
from src.live_backend import LiveBackend
from src.snapshot import snapshot
from src.fixture import with_endpoint_rules
from src.tfs_adapter import TfsAdapter


class CalibrationNetworkTests(unittest.TestCase):
    def test_reconciliation_preserves_discovered_endpoint_rules_but_removes_stale_forwarding(self):
        endpoint={'uuid':'ep1','name':'1','type':'port','context_uuid':'c','topology_uuid':'t'}
        device={'device_id':{'device_uuid':{'uuid':'d'}},'device_config':{'config_rules':[
            {'action':'CONFIGACTION_SET','custom':{'resource_key':'_connect/settings',
                                                  'resource_value':json.dumps({'endpoints':[endpoint]})}}]}}
        desired=snapshot({'devices':[device]})
        enriched=with_endpoint_rules(desired)
        current=copy.deepcopy(enriched)
        current['entities']['devices'][0]['device_config']['config_rules'].append(
            {'action':'CONFIGACTION_SET','custom':{'resource_key':'/tables/stale','resource_value':'{}'}})
        adapter=TfsAdapter('http://unused');adapter._read=lambda:current
        adapter.request=Mock();adapter.restore=Mock()
        adapter.reconcile(enriched)
        removed=adapter.request.call_args.args[2]['device_config']['config_rules']
        self.assertEqual([r['custom']['resource_key'] for r in removed],['/tables/stale'])
        self.assertEqual(len(desired['entities']['devices'][0]['device_config']['config_rules']),1)
        self.assertEqual(with_endpoint_rules(enriched),enriched)

    def test_network_created_once_and_left_available_for_trials(self):
        with tempfile.TemporaryDirectory() as folder:
            app=SimpleNamespace(root=Path(folder),functional_event=Mock(return_value={}),
                orbit=Mock(),scenario={},cancel=threading.Event(),publish=Mock(),checkpoint=Mock())
            backend=Mock()
            backend.establish_baseline.return_value={'success':True}
            with patch('src.experiment.LiveBackend',return_value=backend) as factory:
                Experiment.prepare_calibration_network(app)
                Experiment.prepare_calibration_network(app)
            factory.assert_called_once()
            backend.reset.assert_called_once_with()
            backend.shutdown.assert_not_called()
            backend.close.assert_called_once()
            self.assertTrue(app._calibration_network_ready)

    def test_failed_initial_baseline_fences_network_and_never_marks_it_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            app=SimpleNamespace(root=Path(folder),functional_event=Mock(return_value={}),
                orbit=Mock(),scenario={},cancel=threading.Event(),publish=Mock(),checkpoint=Mock())
            backend=Mock();backend.establish_baseline.return_value={'success':False}
            with patch('src.experiment.LiveBackend',return_value=backend):
                with self.assertRaisesRegex(RuntimeError,'Baseline'):
                    Experiment.prepare_calibration_network(app)
            backend.shutdown.assert_called_once();backend.close.assert_called_once()
            self.assertFalse(getattr(app,'_calibration_network_ready',False))

    def reset_backend(self, folder, changed_connection=False):
        backend=object.__new__(LiveBackend)
        backend.directory=Path(folder);backend.root=Path(folder)
        backend.event={'start_s':0,'trigger_s':0};backend.fixture={};backend.scenario={}
        backend.clock=None;backend.preparation_deadline=None
        backend.orbit=SimpleNamespace(ids=[53848,53913],graph=lambda tick:{53848:{53913:1},53913:{53848:1}})
        backend.check=Mock();backend.compose=Mock();backend.notify=Mock();backend.event_context={}
        backend.cancel=threading.Event();backend.start_source=Mock()
        backend.set_links=Mock();backend.admin=Mock();backend.signature=Mock(return_value='graph')
        backend.wait_infrastructure=Mock(return_value={'ipv4':'127.0.0.1'})
        backend.preparation_status=Mock(return_value={})
        desired=snapshot({'devices':[{'device_id':{'device_uuid':{'uuid':'d1'}},
            'device_config':{'config_rules':[{'custom':{'resource_key':'_connect/address','resource_value':'127.0.0.1'}}]}}],
            'services':[{'service_id':{'context_id':{'context_uuid':{'uuid':'c'}},'service_uuid':{'uuid':'s'}}}]})
        current=copy.deepcopy(desired)
        if changed_connection:
            current['entities']['devices'][0]['device_config']['config_rules'][0]['custom']['resource_value']='old-address'
        backend.a=Mock();backend.b=Mock()
        backend.a.export.side_effect=[current, desired, desired]
        backend.a.restore_progress={}
        return backend,desired

    def test_incremental_preserves_devices_but_resets_service_and_reconciles(self):
        with tempfile.TemporaryDirectory() as folder:
            backend,desired=self.reset_backend(folder)
            with patch('src.live_backend.state',return_value=desired):
                backend.reset(reuse_inventory=True)
            backend.a.restore.assert_not_called()
            backend.a.reconcile.assert_called_once_with(desired)
            removed=backend.a.cleanup.call_args.args[0]['entities']
            self.assertEqual(removed['devices'],[])
            self.assertEqual(removed['services'],desired['entities']['services'])
            self.assertEqual([c.args[0] for c in backend.admin.call_args_list],['/recover','/clear-standby'])
            backend.b.export.assert_not_called()

    def test_changed_connection_uses_full_restore_instead_of_partial_reuse(self):
        with tempfile.TemporaryDirectory() as folder:
            backend,desired=self.reset_backend(folder,changed_connection=True)
            with patch('src.live_backend.state',return_value=desired):
                backend.reset(reuse_inventory=True)
            backend.a.reconcile.assert_not_called()
            backend.a.restore.assert_called_once_with(desired)
            self.assertEqual(len(backend.a.cleanup.call_args.args[0]['entities']['devices']),1)
