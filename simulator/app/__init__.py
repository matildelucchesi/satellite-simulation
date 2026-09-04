"""Application factory del servizio Simulator."""

from __future__ import annotations

import atexit
from datetime import datetime
import logging
import os
from pathlib import Path
from typing import Any

from flask import Flask

from common.settings import ServiceSettings

from .configuration import load_constellation_config
from .experiment_manager import ExperimentManager
from .migration_manager import (
    MigrationConfig,
    MigrationManager,
    MigrationProtocolError,
    UrllibRestTransport,
)
from .metrics import MetricsManager
from .orbit_engine import ConstellationSimulator
from .routes import create_api_blueprint
from .score_manager import ScoreManager, ScoreManagerConfig
from .startup_controller import StartupControllerConfig, StartupControllerManager


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    """Crea l'API headless e avvia il coordinatore della simulazione."""

    app = Flask(__name__)
    settings = ServiceSettings.from_environment("simulator")
    app.config.from_mapping(
        SERVICE_SETTINGS=settings,
        CONFIG_PATH=settings.config_path,
        TLE_PATH=os.getenv("TLE_PATH", "/app/config/starlink.tle"),
        SIMULATOR_TICK_SECONDS=float(os.getenv("SIMULATOR_TICK_SECONDS", "1")),
        ECLIPSE_SEARCH_HOURS=float(os.getenv("ECLIPSE_SEARCH_HOURS", "24")),
        SCORING_CONFIG_PATH=os.getenv("SCORING_CONFIG_PATH"),
        MIGRATION_CONFIG_PATH=os.getenv("MIGRATION_CONFIG_PATH"),
        LOG_DIR=os.getenv("LOG_DIR", "/app/logs"),
        SIMULATOR_AUTOSTART=os.getenv("SIMULATOR_AUTOSTART", "true").lower()
        in {"1", "true", "yes"},
    )
    if test_config:
        app.config.update(test_config)

    logging.basicConfig(level=settings.log_level.upper())
    constellation_config = load_constellation_config(app.config["CONFIG_PATH"])
    satellite_ids = [item["id"] for item in constellation_config["satellites"]]
    scoring_config_path = app.config["SCORING_CONFIG_PATH"] or str(
        Path(app.config["CONFIG_PATH"]).with_name("scoring.json")
    )
    migration_config_path = app.config["MIGRATION_CONFIG_PATH"] or str(
        Path(app.config["CONFIG_PATH"]).with_name("migration.json")
    )
    migration_config = MigrationConfig.from_file(migration_config_path)
    migration_manager = MigrationManager(
        config=migration_config,
        satellite_ids=satellite_ids,
    )
    metrics_manager = MetricsManager(migration_manager.snapshot)
    score_manager = ScoreManager(
        satellite_ids=satellite_ids,
        config=ScoreManagerConfig.from_file(scoring_config_path),
        migration_notifier=migration_manager.notify_migration,
        evaluation_listener=metrics_manager.record_election,
        required_contact_seconds=(
            migration_config.contact_window.required_alignment_seconds
        ),
        migration_execution_budget_seconds=(
            migration_config.execution_budget_seconds
        ),
        contact_window_config=migration_config.contact_window,
        migration_state_provider=migration_manager.snapshot,
    )
    migration_manager.set_handover_listener(
        score_manager.record_controller_handover
    )
    startup_controller_config = StartupControllerConfig.from_dict(
        constellation_config["constellation"]["initial_controller"]
    )
    minimum_safe_startup_sunlight = (
        migration_config.contact_window.required_alignment_seconds
        + migration_config.execution_budget_seconds
        + score_manager.config.handover_safety_margin_seconds
    )
    if startup_controller_config.minimum_sunlight_seconds < minimum_safe_startup_sunlight:
        raise ValueError(
            "initial_controller.minimum_sunlight_seconds deve essere almeno "
            f"{minimum_safe_startup_sunlight:g} secondi per coprire allineamento, "
            "migrazione e margine di sicurezza"
        )
    startup_controller_manager = StartupControllerManager(
        satellite_ids=satellite_ids,
        config=startup_controller_config,
        agent_url=migration_config.agent_url,
        controller_url=migration_config.controller_url,
        request_timeout_seconds=migration_config.request_timeout_seconds,
        contact_window_config=migration_config.contact_window,
    )

    def update_coordinators(snapshot: dict[str, Any]) -> None:
        startup_controller_manager.update_constellation(snapshot)
        migration_manager.update_constellation(snapshot)
        score_manager.update_constellation(snapshot)

    simulator = ConstellationSimulator(
        tle_path=app.config["TLE_PATH"],
        satellite_ids=satellite_ids,
        constellation_name=constellation_config["constellation"]["name"],
        tick_seconds=app.config["SIMULATOR_TICK_SECONDS"],
        eclipse_search_hours=app.config["ECLIPSE_SEARCH_HOURS"],
        simulation_start_at=_parse_simulation_start(
            constellation_config["constellation"].get("simulation_start_at")
        ),
        state_listener=update_coordinators,
        contact_window_config=migration_config.contact_window,
    )

    def reset_remote_components() -> None:
        custom_resetter = app.config.get("EXPERIMENT_REMOTE_RESETTER")
        if custom_resetter is not None:
            custom_resetter()
            return
        transport = UrllibRestTransport()
        targets = [
            f"{migration_config.controller_url}/reset_simulation",
            *[
                f"{migration_config.agent_url(satellite_id)}/reset_simulation"
                for satellite_id in satellite_ids
            ],
        ]
        for target in targets:
            response = transport.request(
                "POST", target, None, migration_config.request_timeout_seconds
            )
            if response.status != 200:
                raise MigrationProtocolError(
                    f"Reset logico rifiutato da {target}: HTTP {response.status}"
                )

    experiment_manager = ExperimentManager(
        simulator=simulator,
        score_manager=score_manager,
        migration_manager=migration_manager,
        metrics_manager=metrics_manager,
        startup_controller_manager=startup_controller_manager,
        export_dir=app.config["LOG_DIR"],
        remote_resetter=reset_remote_components,
    )
    app.extensions["constellation_simulator"] = simulator
    app.extensions["score_manager"] = score_manager
    app.extensions["migration_manager"] = migration_manager
    app.extensions["metrics_manager"] = metrics_manager
    app.extensions["startup_controller_manager"] = startup_controller_manager
    app.extensions["experiment_manager"] = experiment_manager
    app.register_blueprint(
        create_api_blueprint(
            settings.name,
            simulator,
            score_manager,
            migration_manager,
            metrics_manager,
            startup_controller_manager,
            experiment_manager,
            app.config["SIMULATOR_AUTOSTART"],
        )
    )

    if app.config["SIMULATOR_AUTOSTART"]:
        experiment_manager.prepare()
        atexit.register(experiment_manager.close)
        atexit.register(simulator.close)

    return app


def _parse_simulation_start(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
