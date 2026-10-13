import copy
import unittest
from src.snapshot import snapshot
from src.tfs_adapter import TfsAdapter


class RestoreReconcileTests(unittest.TestCase):
    def service(self,value):
        return {'service_id':{'context_id':{'context_uuid':{'uuid':'migration-lab'}},
            'service_uuid':{'uuid':'migration-l2'}},'name':'migration-l2',
            'service_type':'SERVICETYPE_L2NM','service_config':{'config_rules':[
                {'action':'CONFIGACTION_SET','custom':{'resource_key':'/settings','resource_value':value}}]}}

    def test_changed_intent_is_deleted_before_restore_unchanged_is_preserved(self):
        for changed in (False,True):
            adapter=TfsAdapter('http://unused')
            current=snapshot({'services':[self.service('old')]})
            desired=snapshot({'services':[self.service('new' if changed else 'old')]})
            adapter._read=lambda:current
            calls=[]
            adapter.request=lambda method,path,body=None:calls.append((method,path))
            adapter.restore=lambda document:calls.append(('RESTORE',document))
            adapter.reconcile(desired)
            self.assertEqual(calls[-1][0],'RESTORE')
            self.assertEqual(sum(method=='DELETE' for method,_ in calls),int(changed))
            if changed:self.assertTrue(calls[0][1].endswith('/service/migration-l2'))

    def test_failure_in_each_restore_phase_stops_before_later_phases(self):
        kinds=('contexts','devices','links','topologies','services')
        for kind in kinds:
            with self.subTest(kind=kind):
                adapter=TfsAdapter('http://unused')
                adapter._read=lambda:snapshot({})
                calls=[]
                adapter.request=lambda method,path,body=None:calls.append((method,path))
                with self.assertRaisesRegex(RuntimeError,'Injected restore failure: '+kind):
                    adapter.restore(snapshot({}),inject_failure_at=kind)
                self.assertEqual(len(calls),2) # only the static admin scaffold
