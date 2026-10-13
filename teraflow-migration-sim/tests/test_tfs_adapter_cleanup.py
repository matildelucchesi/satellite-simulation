import unittest
from src.snapshot import snapshot
from src.tfs_adapter import TfsAdapter


class CleanupTests(unittest.TestCase):
    def test_endpoint_dependencies_removed_before_topology(self):
        document = snapshot({
            'contexts': [{'context_id': {'context_uuid': {'uuid': 'migration-lab'}}}],
            'devices': [{'device_id': {'device_uuid': {'uuid': 'sat-1'}}}],
            'links': [{'link_id': {'link_uuid': {'uuid': 'isl-1'}}}],
            'topologies': [{'topology_id': {'context_id': {'context_uuid': {'uuid': 'migration-lab'}},
                                          'topology_uuid': {'uuid': 'starlink-17'}}}],
            'services': [{'service_id': {'context_id': {'context_uuid': {'uuid': 'migration-lab'}},
                                        'service_uuid': {'uuid': 'migration-l2'}}}]})
        adapter = TfsAdapter('http://unused')
        adapter._read = lambda: document
        deleted = []
        def request(method, path, body=None):
            self.assertEqual(method, 'DELETE')
            if '/topology/' in path:
                self.assertIn('/device/sat-1', deleted)
                self.assertIn('/link/isl-1', deleted)
            deleted.append(path)
        adapter.request = request
        adapter.cleanup(document)
        self.assertEqual(len(deleted), 5)
        self.assertTrue(deleted[0].endswith('/service/migration-l2'))
        self.assertEqual(deleted[-1], '/context/migration-lab')
