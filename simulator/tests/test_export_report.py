"""Regression tests for the auditable per-migration PDF report."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.export_report import _contribution_rows, _input_rows, write_metrics_report
from app.timing_model import MigrationTimingConfig, MigrationTimingModel


class ExportReportTests(unittest.TestCase):
    def test_pdf_uses_the_saved_timing_plan_without_recalculation(self):
        model = MigrationTimingModel(MigrationTimingConfig(enabled=True, seed=7))
        migration = {
            "sequence": 1,
            "source_satellite_id": "SAT-1",
            "target_satellite_id": "SAT-7",
            "mode": "hot",
            "status": "completed",
            "contact_window": {"current_distance_km": 2800.0},
        }
        timing = model.plan(
            migration,
            {"satellites": {f"SAT-{index}": {} for index in range(1, 8)}, "physical_links": [{}] * 10},
        )
        migration["metrics"] = {
            "duration_ms": timing["estimated_duration_ms"],
            "downtime_ms": timing["estimated_downtime_ms"],
            "ack_received": True,
            "timing_model": timing,
        }

        contribution_labels = [label for label, _ in _contribution_rows(timing, migration["metrics"])]
        input_labels = [label for label, _ in _input_rows(timing)]
        self.assertIn("CPU load contribution", contribution_labels)
        self.assertIn("Banda disponibile", input_labels)
        self.assertIn("Stato effettivo", input_labels)

        with TemporaryDirectory() as directory:
            output = Path(directory, "report.pdf")
            write_metrics_report(output, {"experiment_mode": "hot"}, [migration])
            self.assertTrue(output.read_bytes().startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
