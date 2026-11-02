import threading
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from src.live_backend import LiveBackend
from src.preparation_budget import PreparationBudget


class InfrastructureReadinessTests(unittest.TestCase):
    def backend(self, duration=5):
        clock=[0.0]
        cancel=Mock()
        cancel.wait.side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds) or False
        backend=SimpleNamespace(orbit=SimpleNamespace(ids=[11,22]),remaining=lambda:max(0,duration-clock[0]),
            check=Mock(),cancel=cancel,notify=Mock(),event_context={})
        return backend,clock

    def ready(self,port,**kwargs):
        if port==18090:return {'switch_count':2,'switches_alive':True}
        return {'ipv4':'172.25.0.3','states':[{'upstream_master':True}]*2}

    def test_transient_closed_connection_is_retried_without_starting_controllers(self):
        backend,clock=self.backend();attempts=[0]
        def http(port,**kwargs):
            if port==18091:
                attempts[0]+=1
                if attempts[0]==1:raise ConnectionResetError('Remote end closed connection without response')
            return self.ready(port,**kwargs)
        with patch('src.live_backend.http',side_effect=http):result=LiveBackend.wait_infrastructure(backend)
        self.assertEqual(result['ipv4'],'172.25.0.3');self.assertEqual(attempts[0],2)
        self.assertEqual(clock[0],1)
        self.assertEqual(backend.notify.call_args.args[0]['operation_status'],'completed')

    def test_switch_arbitration_must_be_complete_even_when_http_responds(self):
        backend,clock=self.backend();attempts=[0]
        def http(port,**kwargs):
            result=self.ready(port,**kwargs)
            if port==18091:
                attempts[0]+=1
                if attempts[0]<3:result['states']=[{'upstream_master':True},{'upstream_master':False}]
            return result
        with patch('src.live_backend.http',side_effect=http):LiveBackend.wait_infrastructure(backend)
        self.assertEqual(attempts[0],3);self.assertEqual(clock[0],2)
        self.assertEqual(backend.notify.call_count,2)

    def test_missing_proxy_reaches_deadline_with_component_diagnostics(self):
        backend,clock=self.backend(duration=3)
        def http(port,**kwargs):
            if port==18091:raise ConnectionResetError('proxy starting')
            return self.ready(port,**kwargs)
        with patch('src.live_backend.http',side_effect=http):
            with self.assertRaises(TimeoutError) as raised:LiveBackend.wait_infrastructure(backend)
        self.assertEqual(clock[0],3)
        self.assertTrue(raised.exception.infrastructure_status['Mininet']['ready'])
        self.assertFalse(raised.exception.infrastructure_status['Proxy P4']['ready'])
        self.assertIn('proxy starting',str(raised.exception))
        self.assertEqual(backend.notify.call_count,1)

    def test_cancellation_interrupts_the_wait(self):
        backend,_=self.backend();backend.cancel.wait.return_value=True;backend.cancel.wait.side_effect=None
        with patch('src.live_backend.http',side_effect=ConnectionResetError('starting')):
            with self.assertRaises(InterruptedError):LiveBackend.wait_infrastructure(backend)

    def test_timeout_respects_remaining_budget_and_keeps_p4_error_classification(self):
        backend,clock=self.backend(duration=1)
        with tempfile.TemporaryDirectory() as directory:
            with patch('src.preparation_budget.time.monotonic',side_effect=lambda:clock[0]):
                budget=PreparationBudget(Path(directory),{},Mock())
                backend.remaining=lambda: min(max(0,1-clock[0]),budget.remaining())
                def http(port,timeout):
                    self.assertLessEqual(timeout,backend.remaining())
                    clock[0]+=timeout
                    raise TimeoutError('not ready')
                with patch('src.live_backend.http',side_effect=http):
                    with self.assertRaises(TimeoutError):
                        with budget.stage('infrastructure'):LiveBackend.wait_infrastructure(backend)
                self.assertEqual(budget.error['code'],'p4_not_ready')
                self.assertIn('infrastructure_status',budget.error)
