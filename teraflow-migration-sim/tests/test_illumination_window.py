import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.orbit import Orbit


class IlluminationWindowTests(unittest.TestCase):
    def test_next_transition_and_exact_boundary_follow_frozen_eclipse(self):
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary) / 'orbit.npz'
            np.savez(artifact, ids=np.array([11, 22]), positions=np.zeros((7, 2, 3)),
                     eclipsed=np.array([[False, True], [False, True], [True, True],
                                        [True, True], [False, True], [False, True], [False, True]]))
            orbit = Orbit(artifact, links=[])
            self.assertEqual(orbit.illumination_window(11, 1),
                             {'phase_start_s': 0, 'next_transition_s': 2, 'shadow_duration_s': 2})
            self.assertEqual(orbit.illumination_window(11, 2),
                             {'phase_start_s': 2, 'next_transition_s': 4, 'shadow_duration_s': 2})
            self.assertFalse(orbit.operational(11, 2))
            self.assertEqual(orbit.illumination_window(11, 4),
                             {'phase_start_s': 4, 'next_transition_s': None, 'shadow_duration_s': None})
            self.assertTrue(orbit.operational(11, 4))
            self.assertEqual(orbit.illumination_window(22, 3),
                             {'phase_start_s': 0, 'next_transition_s': None, 'shadow_duration_s': None})
            for tick in (-1, 7):
                with self.assertRaises(ValueError):
                    orbit.illumination_window(11, tick)
