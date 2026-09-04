"""Ciclo ripetibile per confrontare esperimenti Hot e Cold Migration."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Event, RLock, Thread, current_thread
from typing import Any, Callable

from .metrics import MetricsManager
from .export_report import write_metrics_report
from .migration_manager import MigrationManager
from .orbit_engine import ConstellationSimulator
from .score_manager import ScoreManager
from .startup_controller import StartupControllerManager


class ExperimentManagerError(ValueError):
    pass


class ExperimentManager:
    """Configura, arresta, esporta e reimposta una prova di simulazione."""

    def __init__(
        self,
        simulator: ConstellationSimulator,
        score_manager: ScoreManager,
        migration_manager: MigrationManager,
        metrics_manager: MetricsManager,
        startup_controller_manager: StartupControllerManager,
        export_dir: str | Path,
        remote_resetter: Callable[[], None] | None = None,
    ) -> None:
        self.simulator = simulator
        self.score_manager = score_manager
        self.migration_manager = migration_manager
        self.metrics_manager = metrics_manager
        self.startup_controller_manager = startup_controller_manager
        self.export_dir = Path(export_dir)
        self.remote_resetter = remote_resetter or (lambda: None)
        self._lock = RLock()
        self._monitor_stop = Event()
        self._monitor_thread: Thread | None = None
        self._state = self._initial_state()

    def prepare(self) -> None:
        """Produce lo snapshot iniziale, lasciando il clock in pausa."""

        self.score_manager.reset(enabled=False)
        self.migration_manager.reset()
        self.startup_controller_manager.reset()
        self.simulator.reset()

    def start(self, mode: Any, migration_limit: Any) -> dict[str, Any]:
        selected_mode = str(mode or "").strip().lower()
        if selected_mode not in {"hot", "cold"}:
            raise ExperimentManagerError("mode deve essere hot oppure cold")
        if (
            isinstance(migration_limit, bool)
            or not isinstance(migration_limit, int)
            or migration_limit < 1
            or migration_limit > 100
        ):
            raise ExperimentManagerError(
                "migration_limit deve essere un intero compreso tra 1 e 100"
            )
        with self._lock:
            if self._state["status"] == "running":
                raise ExperimentManagerError("Una simulazione è già in esecuzione")

        self._stop_components()
        self.remote_resetter()
        self.score_manager.reset(enabled=False)
        self.migration_manager.reset(selected_mode)
        self.startup_controller_manager.reset()
        self.metrics_manager.reset(selected_mode, migration_limit)
        self.simulator.reset()

        started_at = _utc_now()
        with self._lock:
            self._state = {
                "status": "running",
                "mode": selected_mode,
                "migration_limit": migration_limit,
                "completed_migrations": 0,
                "started_at": started_at,
                "finished_at": None,
                "exports": [],
                "last_error": None,
            }

        self.startup_controller_manager.start()
        self.migration_manager.start()
        self.score_manager.set_enabled(True)
        self.simulator.start()
        self._start_monitor()
        return self.snapshot()

    def reset(self) -> dict[str, Any]:
        """Torna alla scelta iniziale conservando gli export già prodotti."""

        previous_exports = self.snapshot().get("exports", [])
        self._stop_components()
        self.remote_resetter()
        self.score_manager.reset(enabled=False)
        self.migration_manager.reset()
        self.startup_controller_manager.reset()
        self.simulator.reset()
        with self._lock:
            self._state = self._initial_state()
            self._state["exports"] = previous_exports
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = deepcopy(self._state)
        if state["status"] == "running":
            state["completed_migrations"] = self._completed_count()
        return state

    def close(self) -> None:
        self._stop_components()

    def _initial_state(self) -> dict[str, Any]:
        return {
            "status": "awaiting_configuration",
            "mode": None,
            "migration_limit": None,
            "completed_migrations": 0,
            "started_at": None,
            "finished_at": None,
            "exports": [],
            "last_error": None,
        }

    def _start_monitor(self) -> None:
        self._monitor_stop.clear()
        self._monitor_thread = Thread(
            target=self._monitor,
            name="simulation-experiment-monitor",
            daemon=True,
        )
        self._monitor_thread.start()

    def _monitor(self) -> None:
        while not self._monitor_stop.wait(0.2):
            with self._lock:
                if self._state["status"] != "running":
                    return
                limit = self._state["migration_limit"]
            completed = self._completed_count()
            with self._lock:
                self._state["completed_migrations"] = completed
            if completed >= limit:
                self._finish()
                return

    def _finish(self) -> None:
        self.score_manager.set_enabled(False)
        self.migration_manager.stop()
        self.simulator.stop()
        self.startup_controller_manager.stop()
        self.metrics_manager.finish()
        finished_at = _utc_now()
        try:
            exports = self._write_exports(finished_at)
            last_error = None
        except OSError as exc:
            exports = []
            last_error = f"Export automatico fallito: {exc}"
        with self._lock:
            self._state.update(
                {
                    "status": "completed",
                    "completed_migrations": self._completed_count(),
                    "finished_at": finished_at,
                    "exports": exports,
                    "last_error": last_error,
                }
            )

    def _write_exports(self, finished_at: str) -> list[str]:
        self.export_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            mode = self._state["mode"]
        stamp = datetime.fromisoformat(finished_at.replace("Z", "+00:00")).strftime(
            "%Y%m%d-%H%M%S"
        )
        basename = f"metrics-{mode}-{stamp}"
        json_path = self.export_dir / f"{basename}.json"
        pdf_path = self.export_dir / f"{basename}.pdf"
        migrations = self.migration_manager.snapshot().get("migrations", [])
        migrations = migrations if isinstance(migrations, list) else []
        snapshot = self.metrics_manager.snapshot()
        # The final JSON is the machine-readable counterpart of the PDF.  It
        # deliberately keeps the exact per-migration timing plan so neither
        # format needs to reconstruct contributors after the experiment.
        report_payload = {**snapshot, "migrations": migrations}
        json_path.write_text(
            json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        write_metrics_report(
            pdf_path,
            snapshot,
            migrations,
        )
        return [json_path.name, pdf_path.name]

    def _completed_count(self) -> int:
        migrations = self.migration_manager.snapshot().get("migrations", [])
        return sum(item.get("status") == "completed" for item in migrations)

    def _stop_components(self) -> None:
        self._monitor_stop.set()
        monitor = self._monitor_thread
        if (
            monitor is not None
            and monitor.is_alive()
            and monitor is not current_thread()
        ):
            monitor.join(timeout=2)
        self._monitor_thread = None
        self.score_manager.set_enabled(False)
        self.simulator.stop()
        self.migration_manager.stop()
        self.startup_controller_manager.stop()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
