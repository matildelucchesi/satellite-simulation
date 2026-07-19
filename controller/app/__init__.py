"""Application factory del microservizio Controller."""

from __future__ import annotations

import logging
import os
from typing import Any

from flask import Flask

from common.settings import ServiceSettings

from .routes import create_api_blueprint
from .repository import JsonFileCheckpointRepository
from .service import ControllerService


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    """Crea l'API REST del Controller e il relativo stato replicabile."""

    app = Flask(__name__)
    settings = ServiceSettings.from_environment("controller")
    app.config.from_mapping(
        SERVICE_SETTINGS=settings,
        HOST_SATELLITE_ID=os.getenv("HOST_SATELLITE_ID", "UNASSIGNED"),
        CHECKPOINT_PATH=os.getenv(
            "CHECKPOINT_PATH", "/app/state/controller-checkpoint.json"
        ),
    )
    if test_config:
        app.config.update(test_config)

    logging.basicConfig(level=settings.log_level.upper())
    checkpoint_repository = JsonFileCheckpointRepository(
        app.config["CHECKPOINT_PATH"]
    )
    controller = ControllerService(
        app.config["CHECKPOINT_PATH"],
        checkpoint_repository=checkpoint_repository,
        host_satellite_id=app.config["HOST_SATELLITE_ID"],
    )
    app.extensions["controller_service"] = controller
    app.register_blueprint(
        create_api_blueprint(
            settings.name,
            controller,
        )
    )

    return app
