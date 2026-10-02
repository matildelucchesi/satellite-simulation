import unittest

from src.migration_model import Workload, evaluate


class MigrationModelTests(unittest.TestCase):
    def setUp(self):
        self.workload = Workload(
            image_bytes=100_000_000,
            cold_state_bytes=20_000_000,
            hot_initial_state_bytes=18_000_000,
            hot_final_delta_bytes=2_000_000,
            cold_snapshot_s=2,
            hot_freeze_s=1,
            hot_delta_apply_s=1,
            controller_startup_s=5,
            api_restore_s=3,
            api_verification_s=2,
            ack_cutover_s=1,
        )

    def test_cold_transfer_uses_measured_bytes_and_useful_rate(self):
        case = evaluate(self.workload, "cold", 100_000_000, 60, 3600, 3600)
        self.assertEqual(case.transfer_bytes, 120_000_000)
        self.assertAlmostEqual(case.transfer_s, 9.6)
        self.assertAlmostEqual(case.total_operation_s, 82.6)
        self.assertAlmostEqual(case.controller_downtime_s, 20.6)
        self.assertTrue(case.completes_in_contact)

    def test_hot_pre_copy_is_outside_downtime_but_inside_total_time(self):
        case = evaluate(self.workload, "hot", 100_000_000, 60, 3600, 3600)
        self.assertEqual(case.transfer_bytes, 120_000_000)
        self.assertAlmostEqual(case.transfer_s, 9.6)
        self.assertAlmostEqual(case.total_operation_s, 82.6)
        self.assertAlmostEqual(case.controller_downtime_s, 5.16)
        self.assertLess(case.controller_downtime_s, case.total_operation_s)

    def test_migration_margin_is_negative_when_window_is_too_short(self):
        case = evaluate(self.workload, "cold", 100_000_000, 60, 70, 70)
        self.assertFalse(case.completes_in_contact)
        self.assertLess(case.migration_margin_s, 0)


if __name__ == "__main__":
    unittest.main()
