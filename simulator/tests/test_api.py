"""Test dell'API REST del Simulator."""

from pathlib import Path
import unittest

from app import create_app


ROOT = Path(__file__).resolve().parents[2]


class SimulatorApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "SIMULATOR_AUTOSTART": False,
                "CONFIG_PATH": str(ROOT / "config" / "constellation.json"),
                "TLE_PATH": str(ROOT / "config" / "starlink.tle"),
            }
        )
        self.simulator = self.app.extensions["constellation_simulator"]
        self.simulator.update()
        self.client = self.app.test_client()

    def test_constellation_endpoint(self):
        response = self.client.get("/api/v1/constellation")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["satellite_count"], 5)

    def test_unknown_satellite_returns_404(self):
        response = self.client.get("/api/v1/satellites/SAT-99")

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()

