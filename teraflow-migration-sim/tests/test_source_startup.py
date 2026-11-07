import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from src.live_backend import LiveBackend, SOURCE_STARTUP
from src.deployment import role_services
from src.progress import advance


class SourceStartupTests(unittest.TestCase):
    def backend(self, directory):
        backend=object.__new__(LiveBackend)
        backend.directory=Path(directory)
        backend.check=Mock()
        backend.compose=Mock()
        backend.event_context={}
        backend.notify=Mock()
        return backend

    def test_dependency_stages_are_real_commands_and_only_start_source(self):
        with tempfile.TemporaryDirectory() as directory:
            backend=self.backend(directory)
            backend.start_source()
            calls=backend.compose.command.call_args_list
            self.assertEqual(len(calls),len(SOURCE_STARTUP))
            for call,(_,_,services) in zip(calls,SOURCE_STARTUP):
                self.assertEqual(call.args,('sat-a','up','-d','--wait','--wait-timeout','120',*role_services('sat-a',services)))
            events=[call.args[0] for call in backend.notify.call_args_list]
            self.assertEqual([row['operation_status'] for row in events],['running','completed']*6)
            self.assertEqual(events[-1]['startup_stage'],'api')

    def test_failure_reports_the_stage_and_does_not_start_later_services(self):
        with tempfile.TemporaryDirectory() as directory:
            backend=self.backend(directory)
            backend.compose.command.side_effect=[None,RuntimeError('context failed')]
            with self.assertRaises(RuntimeError) as raised:backend.start_source()
            self.assertEqual(raised.exception.startup_stage,'context')
            self.assertEqual(backend.compose.command.call_count,2)
            self.assertEqual(backend.notify.call_args.args[0]['operation_status'],'failed')

    def test_stage_progress_preserves_overall_startup_deadline(self):
        progress=advance({}, {'phase':'preparation_operation','operation':'start_source',
            'label':'Avvio sorgente','operation_status':'running','deadline_utc':'deadline'})
        progress=advance(progress,{'phase':'source_startup','startup_stage':'api',
            'label':'Attivazione API del controller sorgente','operation_status':'running'})
        self.assertEqual(progress['deadline_utc'],'deadline')
        self.assertEqual(progress['subphase'],'start_source')
        self.assertEqual(progress['startup_stage'],'api')
        self.assertEqual(progress['label'],'Attivazione API del controller sorgente')

    def test_reset_stops_destination_without_calling_its_api(self):
        with tempfile.TemporaryDirectory() as directory:
            backend=self.backend(directory)
            backend.root=Path(directory)
            backend.event={'start_s':0,'trigger_s':0}
            backend.fixture={'emulator':{'devices':[{'norad':11}],'hosts':[{'satellite':11},{'satellite':11}]}}
            backend.scenario={}
            backend.clock=None
            backend.preparation_deadline=None
            backend.orbit=SimpleNamespace(ids=[11],graph=lambda tick:{11:{}})
            document={'entities':{key:[] for key in ('contexts','topologies','devices','links','services')}}
            backend.a=Mock();backend.a.export.return_value=document
            backend.a.restore_progress={key:{'completed':0,'total':0} for key in ('devices','links','services')}
            backend.b=Mock();backend.b.export.side_effect=AssertionError('Destination API must stay offline')
            backend.set_links=Mock();backend.admin=Mock();backend.signature=Mock(return_value='graph')
            backend.preparation_status=Mock(return_value={})
            backend.cancel=Mock();backend.cancel.wait.return_value=False
            with patch('src.live_backend.state',return_value=document),patch('src.live_backend.shortest_paths',return_value={11:0}),patch('src.live_backend.http',side_effect=[{'switch_count':1,'switches_alive':True},{'ipv4':'127.0.0.1','states':[{'upstream_master':True}]}]):
                backend.reset()
            backend.compose.stop.assert_called_once_with('sat-b')
            backend.compose.start.assert_not_called()
            backend.b.export.assert_not_called();backend.b.cleanup.assert_not_called()
            self.assertFalse(backend.target_started)
            stages=[call.args[0]['operation'] for call in backend.notify.call_args_list if call.args[0]['phase']=='preparation_operation']
            self.assertNotIn('start_target',stages);self.assertNotIn('clean_target',stages)
            self.assertIn('restore_scenario',stages)
