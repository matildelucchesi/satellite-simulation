"""Application factory del servizio Simulator."""

from __future__ import annotations

import atexit
import logging
import os
from pathlib import Path
from typing import Any

from flask import Flask

from common.settings import ServiceSettings

from .configuration import load_constellation_config
from .migration_manager import MigrationConfig, MigrationManager
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
    )
    startup_controller_manager = StartupControllerManager(
        satellite_ids=satellite_ids,
        config=StartupControllerConfig.from_dict(
            constellation_config["constellation"]["initial_controller"]
        ),
        agent_url=migration_config.agent_url,
        controller_url=migration_config.controller_url,
        request_timeout_seconds=migration_config.request_timeout_seconds,
    )

    def update_coordinators(snapshot: dict[str, Any]) -> None:
        startup_controller_manager.update_constellation(snapshot)
        score_manager.update_constellation(snapshot)
        migration_manager.update_constellation(snapshot)

    simulator = ConstellationSimulator(
        tle_path=app.config["TLE_PATH"],
        satellite_ids=satellite_ids,
        constellation_name=constellation_config["constellation"]["name"],
        tick_seconds=app.config["SIMULATOR_TICK_SECONDS"],
        eclipse_search_hours=app.config["ECLIPSE_SEARCH_HOURS"],
        state_listener=update_coordinators,
    )
    app.extensions["constellation_simulator"] = simulator
    app.extensions["score_manager"] = score_manager
    app.extensions["migration_manager"] = migration_manager
    app.extensions["metrics_manager"] = metrics_manager
    app.extensions["startup_controller_manager"] = startup_controller_manager
    app.register_blueprint(
        create_api_blueprint(
            settings.name,
            simulator,
            score_manager,
            migration_manager,
            metrics_manager,
            startup_controller_manager,
        )
    )

    if app.config["SIMULATOR_AUTOSTART"]:
        startup_controller_manager.start()
        migration_manager.start()
        simulator.start()
        atexit.register(startup_controller_manager.stop)
        atexit.register(migration_manager.stop)
        atexit.register(simulator.close)

    return app
