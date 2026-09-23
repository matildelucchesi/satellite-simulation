"""Application factory dell'agente satellitare."""

from __future__ import annotations

import atexit
import logging
import os
from typing import Any

from flask import Flask

from common.settings import ServiceSettings

from .agent import SatelliteAgent
from .routes import create_api_blueprint

try:
    from controller_core.routes import create_api_blueprint as create_controller_blueprint
except ModuleNotFoundError:  # import usato dai test eseguiti dal repository
    from controller.app.routes import create_api_blueprint as create_controller_blueprint


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    """Crea l'API REST e i worker autonomi del satellite."""

    app = Flask(__name__)
    settings = ServiceSettings.from_environment("satellite-agent")
    app.config.from_mapping(
        SERVICE_SETTINGS=settings,
        SATELLITE_ID=os.getenv("SATELLITE_ID", "UNASSIGNED"),
        CONTROLLER_ENABLED=_env_bool("CONTROLLER_ENABLED", False),
        SIMULATOR_URL=os.getenv("SIMULATOR_URL", "http://simulator:5000"),
        HEARTBEAT_URL=os.getenv("HEARTBEAT_URL", "http://controller:5000/heartbeat"),
        CONTROLLER_HEARTBEAT_URL=os.getenv(
            "CONTROLLER_HEARTBEAT_URL", "http://controller:5000/heartbeat"
        ),
        STATE_SYNC_INTERVAL_SECONDS=float(
            os.getenv("STATE_SYNC_INTERVAL_SECONDS", "1")
        ),
        HEARTBEAT_INTERVAL_SECONDS=float(
            os.getenv("HEARTBEAT_INTERVAL_SECONDS", "5")
        ),
        HTTP_REQUEST_TIMEOUT_SECONDS=float(
            os.getenv("HTTP_REQUEST_TIMEOUT_SECONDS", "2")
        ),
        AGENT_AUTOSTART=_env_bool("AGENT_AUTOSTART", True),
    )
    if test_config:
        app.config.update(test_config)

    logging.basicConfig(level=settings.log_level.upper())
    agent = SatelliteAgent(
        satellite_id=app.config["SATELLITE_ID"],
        controller_enabled=app.config["CONTROLLER_ENABLED"],
        simulator_url=app.config["SIMULATOR_URL"],
        heartbeat_url=app.config["HEARTBEAT_URL"],
        controller_heartbeat_url=app.config["CONTROLLER_HEARTBEAT_URL"],
        state_sync_interval_seconds=app.config["STATE_SYNC_INTERVAL_SECONDS"],
        heartbeat_interval_seconds=app.config["HEARTBEAT_INTERVAL_SECONDS"],
        request_timeout_seconds=app.config["HTTP_REQUEST_TIMEOUT_SECONDS"],
    )
    app.extensions["satellite_agent"] = agent
    app.register_blueprint(create_api_blueprint(settings.name, agent))
    app.register_blueprint(
        create_controller_blueprint(
            f"controller-{agent.satellite_id.lower()}", agent.controller_service
        ),
        url_prefix="/controller",
    )

    if app.config["AGENT_AUTOSTART"]:
        agent.start()
        atexit.register(agent.stop)

    return app


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}
