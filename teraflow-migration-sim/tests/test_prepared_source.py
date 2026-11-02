import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from src import prepared_source as source
from src.storage import atomic_json
from src.artifacts import file_digest

BASE='base-'+'a'*32
PLAN={'initial_satellite_id':42,'start_s':100,'end_s':1000}
PROXY={'active':'sat-a','frozen':False,'generation':7,'ipv4':'10.0.0.1','states':[{'upstream_master':True}]}

class PreparedSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.path=source.record_path(self.root,BASE).parent
        self.path.mkdir(parents=True)
        self.snapshot=self.path/'source-preparation/prepared-snapshot.json'
        atomic_json(self.snapshot,{'entities':{}})
        atomic_json(source.record_path(self.root,BASE),{'ready':True,'generation':7,'snapshot_sha256':file_digest(self.snapshot)})
        self.http=patch('src.live_backend.http',return_value=PROXY);self.http.start();self.addCleanup(self.http.stop)
        self.health=patch('src.prepared_source.urlopen');self.health.start().return_value.__enter__.return_value.status=200;self.addCleanup(self.health.stop)
        self.load=patch('src.common_base.load',return_value=({},PLAN));self.load.start();self.addCleanup(self.load.stop)
    def backend(self):
        backend=Mock(root=self.root,fixture={})
        backend.wait_infrastructure.return_value=PROXY
        backend.a.verify.return_value={'equivalent':True}
        return backend
    def test_ready_requires_live_api_and_unchanged_p4_authority(self):
        self.assertTrue(source.readiness(self.root,BASE)['ready'])
        with patch('src.live_backend.http',return_value={**PROXY,'generation':8}):
            self.assertFalse(source.readiness(self.root,BASE)['ready'])
        with patch('src.prepared_source.urlopen',side_effect=OSError('offline')):
            self.assertFalse(source.readiness(self.root,BASE)['ready'])
    def test_adoption_consumes_once_and_checks_inventory_without_reset(self):
        backend=self.backend();source.adopt(backend,BASE,PLAN)
        backend.a.verify.assert_called_once_with({'entities':{}})
        backend.reset.assert_not_called();backend.start_source.assert_not_called()
        self.assertEqual(backend.proxy_generation,7)
        self.assertFalse(source.readiness(self.root,BASE)['ready'])
    def test_inventory_changes_block_adoption_and_consume_stale_record(self):
        backend=self.backend();backend.a.verify.return_value={'equivalent':False}
        with self.assertRaisesRegex(ValueError,'Scenario sorgente cambiato'):source.adopt(backend,BASE,PLAN)
        self.assertFalse(source.readiness(self.root,BASE)['ready'])
    def test_source_is_left_running_only_after_successful_baseline(self):
        backend=self.backend();backend.directory=self.snapshot.parent
        backend.establish_baseline.return_value={'success':True}
        app=SimpleNamespace(root=self.root,orbit=Mock(),scenario={},cancel=threading.Event(),publish=Mock(),checkpoint=Mock())
        with patch('src.live_backend.LiveBackend',return_value=backend):
            result=source.prepare(app,{'base_id':BASE,'rates':[100000000],'complete':True})
        self.assertTrue(result['source_ready']);backend.shutdown.assert_not_called()
        backend.reset.assert_called_once();backend.establish_baseline.assert_called_once_with(BASE)
    def test_failure_cleans_up_and_never_advertises_readiness(self):
        backend=self.backend();backend.reset.side_effect=RuntimeError('API failed')
        app=SimpleNamespace(root=self.root,orbit=Mock(),scenario={},cancel=threading.Event(),publish=Mock(),checkpoint=Mock())
        with patch('src.live_backend.LiveBackend',return_value=backend):
            result=source.prepare(app,{'base_id':BASE,'rates':[100000000],'complete':True})
        self.assertFalse(result['complete']);backend.shutdown.assert_called_once()
        self.assertFalse(source.readiness(self.root,BASE)['ready'])
    def test_cleanup_failure_requires_recovery(self):
        backend=self.backend();backend.reset.side_effect=RuntimeError('failed');backend.shutdown.side_effect=RuntimeError('still running')
        app=SimpleNamespace(root=self.root,orbit=Mock(),scenario={},cancel=threading.Event(),publish=Mock(),checkpoint=Mock())
        with patch('src.live_backend.LiveBackend',return_value=backend):
            result=source.prepare(app,{'base_id':BASE,'rates':[100000000],'complete':True})
        self.assertTrue(result['recovery_required'])
