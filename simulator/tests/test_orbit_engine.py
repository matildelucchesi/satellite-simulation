"""Test del coordinatore orbitale senza avviare il worker periodico."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from app.contact_window import ContactWindowConfig, evaluate_contact
from app.orbit_engine import ConstellationSimulator, load_tle_file


ROOT = Path(__file__).resolve().parents[2]
TLE_PATH = ROOT / "config" / "starlink.tle"


class TleLoadingTests(unittest.TestCase):
    def test_loads_all_configured_satellites(self):
        _, satellites = load_tle_file(TLE_PATH)

        self.assertEqual(len(satellites), 7)
        self.assertEqual(satellites[0].satellite.name, "STARLINK-5446")


class ConstellationSimulatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.simulator = ConstellationSimulator(
            TLE_PATH,
            [f"SAT-{index}" for index in range(1, 8)],
            eclipse_search_hours=3,
            contact_window_config=ContactWindowConfig(
                required_alignment_seconds=60,
                max_distance_km=5500,
                require_line_of_sight=True,
                earth_radius_km=6378.137,
                max_sample_gap_seconds=2.5,
            ),
        )

    @classmethod
    def tearDownClass(cls):
        cls.simulator.close()

    def test_update_produces_complete_state(self):
        state = self.simulator.update(datetime(2026, 7, 19, tzinfo=timezone.utc))

        self.assertEqual(state["satellite_count"], 7)
        self.assertEqual(set(state["satellites"]), {f"SAT-{i}" for i in range(1, 8)})
        satellite = state["satellites"]["SAT-1"]
        self.assertIn("position_km", satellite)
        self.assertIn("velocity_km_s", satellite)
        self.assertIn("illumination", satellite)
        self.assertIn(
            "next_eclipse_position_km",
            satellite["illumination"],
        )
        self.assertIn("seconds_until_sunlight", satellite["illumination"])
        self.assertEqual(satellite["distances_km"]["SAT-1"], 0.0)
        self.assertGreater(satellite["distances_km"]["SAT-2"], 0.0)
        self.assertIn("physical_neighbors", satellite)
        self.assertEqual(
            satellite["physical_neighbor_count"],
            len(satellite["physical_neighbors"]),
        )
        self.assertIn("physical_links", state)
        for link in state["physical_links"]:
            self.assertIn(
                link["target"],
                state["satellites"][link["source"]]["physical_neighbors"],
            )
            self.assertIn(
                link["source"],
                state["satellites"][link["target"]]["physical_neighbors"],
            )

    def test_snapshot_is_a_defensive_copy(self):
        state = self.simulator.update(datetime(2026, 7, 19, tzinfo=timezone.utc))
        state["satellites"].clear()

        self.assertEqual(len(self.simulator.snapshot()["satellites"]), 7)

    def test_configured_clock_starts_from_simulation_epoch(self):
        start_at = datetime(2026, 7, 20, 23, 57, 30, tzinfo=timezone.utc)
        simulator = ConstellationSimulator(
            TLE_PATH,
            [f"SAT-{index}" for index in range(1, 8)],
            eclipse_search_hours=3,
            simulation_start_at=start_at,
        )
        self.addCleanup(simulator.close)

        state = simulator.update()

        self.assertEqual(state["generated_at"], "2026-07-20T23:57:30.000Z")
        self.assertTrue(
            all(
                satellite["illumination"]["state"] == "sunlight"
                for satellite in state["satellites"].values()
            )
        )
        self.assertGreater(
            state["satellites"]["SAT-1"]["illumination"][
                "seconds_until_eclipse"
            ],
            300,
        )
        self.assertLess(
            state["satellites"]["SAT-1"]["illumination"][
                "seconds_until_eclipse"
            ],
            310,
        )

    def test_selected_tles_form_a_connected_multi_neighbor_network(self):
        state = self.simulator.update(
            datetime(2026, 7, 20, 23, 57, 30, tzinfo=timezone.utc)
        )
        adjacency = {
            satellite_id: set(satellite["physical_neighbors"])
            for satellite_id, satellite in state["satellites"].items()
        }
        visited = {"SAT-1"}
        pending = ["SAT-1"]
        while pending:
            current = pending.pop()
            for neighbor in adjacency[current] - visited:
                visited.add(neighbor)
                pending.append(neighbor)

        self.assertEqual(visited, set(adjacency))
        self.assertGreaterEqual(len(state["physical_links"]), 10)
        self.assertGreaterEqual(min(map(len, adjacency.values())), 1)

    def test_first_handover_target_remains_in_contact_during_alignment(self):
        handover_at = datetime(2026, 7, 20, 23, 59, 5, tzinfo=timezone.utc)

        for elapsed_seconds in range(61):
            state = self.simulator.update(
                handover_at + timedelta(seconds=elapsed_seconds)
            )
            contact = evaluate_contact(
                state,
                "SAT-1",
                "SAT-7",
                self.simulator.contact_window_config,
            )
            self.assertTrue(contact.eligible, msg=f"contatto perso a {elapsed_seconds}s")


if __name__ == "__main__":
    unittest.main()
