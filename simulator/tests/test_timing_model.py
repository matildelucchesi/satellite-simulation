"""Test del modello temporale parametrico e riproducibile."""

import unittest

from app.timing_model import MigrationTimingConfig, MigrationTimingModel


def snapshot():
    return {
        "satellites": {f"SAT-{index}": {} for index in range(1, 8)},
        "physical_links": [{}] * 11,
    }


def migration(sequence, target="SAT-7", mode="hot", distance=3000.0):
    return {
        "sequence": sequence,
        "source_satellite_id": "SAT-1",
        "target_satellite_id": target,
        "mode": mode,
        "contact_window": {"current_distance_km": distance},
    }


class MigrationTimingModelTests(unittest.TestCase):
    def setUp(self):
        self.config = MigrationTimingConfig(
            enabled=True,
            seed=314159,
            satellite_cpu_load_percent={"SAT-1": 26.0, "SAT-2": 38.0, "SAT-7": 27.0},
        )
        self.model = MigrationTimingModel(self.config)

    def test_same_seed_and_same_migration_produce_the_same_plan(self):
        first = self.model.plan(migration(1), snapshot())
        second = self.model.plan(migration(1), snapshot())

        self.assertEqual(first, second)
        self.assertGreater(first["estimated_duration_ms"], 6000)
        self.assertLess(first["estimated_duration_ms"], 7500)
        self.assertGreater(first["estimated_downtime_ms"], 3000)
        self.assertLess(first["estimated_downtime_ms"], 4500)

    def test_parameters_generate_plausible_hundreds_of_milliseconds_variation(self):
        first = self.model.plan(migration(1, "SAT-7", "hot", 2200.0), snapshot())
        second = self.model.plan(migration(4, "SAT-2", "hot", 4800.0), snapshot())

        difference = abs(
            first["estimated_duration_ms"] - second["estimated_duration_ms"]
        )
        self.assertGreater(difference, 100)
        self.assertNotEqual(
            first["available_bandwidth_mbps"], second["available_bandwidth_mbps"]
        )
        self.assertNotEqual(
            first["target_cpu_load_percent"], second["target_cpu_load_percent"]
        )

    def test_cold_plan_models_full_state_transfer_and_target_ack_path(self):
        plan = self.model.plan(migration(2, "SAT-2", "cold", 3500.0), snapshot())
        full_transfer = plan["step_delays_ms"]["transfer_complete_state_and_wait_target_ack"]
        delta_transfer = plan["step_delays_ms"]["transfer_final_state_and_wait_target_ack"]

        self.assertGreater(full_transfer["state_transfer_time_ms"], delta_transfer["state_transfer_time_ms"])
        self.assertIn("startup_delay_ms", plan["step_delays_ms"]["start_target_controller"])
        self.assertIn("synchronization_delay_ms", plan["step_delays_ms"]["update_controller_host"])

    def test_plan_persists_auditable_contributions_and_inputs(self):
        plan = self.model.plan(migration(3, "SAT-2", "hot", 4100.0), snapshot())
        contributions = plan["contribution_totals_ms"]

        self.assertGreater(contributions["network_latency_ms"], 0)
        self.assertGreater(contributions["cpu_load_contribution_ms"], 0)
        self.assertIn("gaussian_noise_ms", contributions)
        self.assertAlmostEqual(
            sum(contributions.values()), plan["estimated_duration_ms"], places=2
        )
        self.assertEqual(plan["model_parameters"]["base_link_latency_ms"], 90.0)
        self.assertEqual(plan["effective_state_bytes"], 6_525_000)


if __name__ == "__main__":
    unittest.main()
