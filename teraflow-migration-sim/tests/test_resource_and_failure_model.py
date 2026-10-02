import unittest

from src.failure_model import recovery_decision
from src.resource_model import (eclipse_trigger, reference_horizon_s,
                                resource_clear_condition, resource_trigger,
                                sat_a_load_percent)


class ResourceAndFailureTests(unittest.TestCase):
    def test_horizon_and_deterministic_load_ramp(self):
        self.assertEqual(reference_horizon_s(100, 1.2), 120)
        self.assertEqual(sat_a_load_percent(0, 120), 55)
        self.assertAlmostEqual(sat_a_load_percent(120, 120), 70)
        self.assertEqual(sat_a_load_percent(240, 120), 85)

    def test_forecast_trigger_requires_persistent_samples(self):
        self.assertFalse(resource_trigger(695, 1000))
        self.assertTrue(resource_trigger(697, 1000))

    def test_eclipse_trigger_and_resource_hysteresis(self):
        self.assertTrue(eclipse_trigger(900, 1000))
        self.assertFalse(eclipse_trigger(1001, 1000))
        self.assertTrue(resource_clear_condition([69.9] * 60))
        self.assertFalse(resource_clear_condition([69.9] * 59))
        self.assertFalse(resource_clear_condition([69.9] * 59 + [70]))

    def test_hot_failure_keeps_sat_a_active_and_ack_is_withheld(self):
        result = recovery_decision("hot", "api_restore_failure", True)
        self.assertFalse(result.ack_allowed)
        self.assertFalse(result.sat_b_may_become_active)
        self.assertTrue(result.retry_allowed)

    def test_cold_exhausted_attempts_restarts_source_but_does_not_ack(self):
        result = recovery_decision("cold", "sat_b_start_failure", True, attempts_used=3, max_attempts=3)
        self.assertFalse(result.ack_allowed)
        self.assertFalse(result.retry_allowed)
        self.assertIn("restart_sat_a", result.action)


if __name__ == "__main__":
    unittest.main()
