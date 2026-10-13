import unittest
from src.probes import classify_observations


class ClassificationTests(unittest.TestCase):
    def test_uses_preceding_geometry_and_keeps_control_separate(self):
        probes = [{'unix_s': t, 'success': good} for t,good in [(0,False),(1,False),(2,True),(3,False),(20,False)]]
        geometry = [{'unix_s':1,'service_path_available':True},
                    {'unix_s':3,'service_path_available':False}]
        heartbeats = [{'unix_s':1,'controllers':{'sat-a':False,'sat-b':False}}]
        rows = classify_observations(probes,geometry,heartbeats)
        self.assertEqual([r['classification'] for r in rows],
            ['unknown_geometry','loss_with_path','service_available','no_geometric_path','unknown_geometry'])
        self.assertIsNone(rows[0]['control_reachable'])
        self.assertFalse(rows[2]['control_reachable'])
        self.assertIsNone(rows[-1]['control_reachable'])

