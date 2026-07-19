"""Test del coordinatore orbitale senza avviare il worker periodico."""

from datetime import datetime, timezone
from pathlib import Path
import unittest

from app.orbit_engine import ConstellationSimulator, load_tle_file


ROOT = Path(__file__).resolve().parents[2]
TLE_PATH = ROOT / "config" / "starlink.tle"


class TleLoadingTests(unittest.TestCase):
    def test_loads_exactly_five_satellites(self):
        _, satellites = load_tle_file(TLE_PATH)

        self.assertEqual(len(satellites), 5)
        self.assertEqual(satellites[0].satellite.name, "STARLINK-1008")


class ConstellationSimulatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.simulator = ConstellationSimulator(
            TLE_PATH,
            [f"SAT-{index}" for index in range(1, 6)],
            eclipse_search_hours=3,
        )

    def test_update_produces_complete_state(self):
        state = self.simulator.update(datetime(2026, 7, 19, tzinfo=timezone.utc))

        self.assertEqual(state["satellite_count"], 5)
        self.assertEqual(set(state["satellites"]), {f"SAT-{i}" for i in range(1, 6)})
        satellite = state["satellites"]["SAT-1"]
        self.assertIn("position_km", satellite)
        self.assertIn("velocity_km_s", satellite)
        self.assertIn("illumination", satellite)
        self.assertEqual(satellite["distances_km"]["SAT-1"], 0.0)
        self.assertGreater(satellite["distances_km"]["SAT-2"], 0.0)

    def test_snapshot_is_a_defensive_copy(self):
        state = self.simulator.update(datetime(2026, 7, 19, tzinfo=timezone.utc))
        state["satellites"].clear()

        self.assertEqual(len(self.simulator.snapshot()["satellites"]), 5)


if __name__ == "__main__":
    unittest.main()

