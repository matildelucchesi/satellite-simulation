import json
import math
import unittest
from pathlib import Path
from src.analysis import variations


class SensitivityTests(unittest.TestCase):
    def test_variations_keep_weights_normalized_and_change_one_family(self):
        scenario=json.loads((Path(__file__).parents[1]/'config/scenario.json').read_text())
        changed=list(variations(scenario))
        self.assertEqual(len(changed),16)
        self.assertEqual(len({name for name,_ in changed}),16)
        for name,row in changed:
            self.assertTrue(math.isclose(sum(row['score']['weights'].values()),1))
            self.assertEqual(row['orbital'],scenario['orbital'])
            self.assertEqual(row['fso'],scenario['fso'])
        self.assertEqual(scenario['controller']['resource_profile']['cpu_cores'],6)
