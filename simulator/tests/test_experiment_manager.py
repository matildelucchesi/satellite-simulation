"""Test del ciclo ripetibile Hot/Cold."""

from pathlib import Path
from tempfile import TemporaryDirectory
from time import sleep
import json
import unittest

from app.experiment_manager import ExperimentManager
from app.metrics import MetricsManager


class FakeComponent:
    def __init__(self):
        self.running = False
        self.enabled = False
        self.reset_count = 0

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def reset(self, *args, **kwargs):
        self.reset_count += 1

    def set_enabled(self, enabled):
        self.enabled = enabled


class FakeMigrationManager(FakeComponent):
    def __init__(self):
        super().__init__()
        self.mode = "hot"
        self.migrations = []

    def reset(self, mode=None):
        super().reset()
        self.mode = mode or "hot"
        self.migrations = []

    def snapshot(self):
        return {"migrations": list(self.migrations)}


class ExperimentManagerTests(unittest.TestCase):
    def test_stops_at_limit_and_writes_dated_json_and_pdf(self):
        simulator = FakeComponent()
        score = FakeComponent()
        migrations = FakeMigrationManager()
        startup = FakeComponent()
        metrics = MetricsManager(migrations.snapshot)
        reset_calls = []

        with TemporaryDirectory() as directory:
            manager = ExperimentManager(
                simulator,
                score,
                migrations,
                metrics,
                startup,
                directory,
                lambda: reset_calls.append(True),
            )
            self.addCleanup(manager.close)
            started = manager.start("cold", 3)
            migrations.migrations = [
                {"status": "completed", "metrics": {}}
                for _ in range(3)
            ]
            for _ in range(20):
                if manager.snapshot()["status"] == "completed":
                    break
                sleep(0.05)

            finished = manager.snapshot()
            files = sorted(path.name for path in Path(directory).iterdir())
            pdf_bytes = next(
                Path(directory, name).read_bytes()
                for name in files
                if name.endswith(".pdf")
            )
            json_payload = next(
                json.loads(Path(directory, name).read_text(encoding="utf-8"))
                for name in files
                if name.endswith(".json")
            )

        self.assertEqual(started["mode"], "cold")
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["completed_migrations"], 3)
        self.assertEqual(len(reset_calls), 1)
        self.assertEqual(len(files), 2)
        self.assertTrue(any(name.startswith("metrics-cold-") and name.endswith(".json") for name in files))
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertEqual(len(json_payload["migrations"]), 3)
        self.assertFalse(simulator.running)
        self.assertFalse(migrations.running)


if __name__ == "__main__":
    unittest.main()
