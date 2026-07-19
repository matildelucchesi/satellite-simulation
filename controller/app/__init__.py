"""Application factory del microservizio Controller."""

import os

from flask import Flask, jsonify

from common.settings import ServiceSettings


def create_app() -> Flask:
    """Crea l'app Flask del Controller, ospitato logicamente su SAT-1."""

    app = Flask(__name__)
    settings = ServiceSettings.from_environment("controller")
    host_satellite_id = os.getenv("HOST_SATELLITE_ID", "SAT-1")
    app.config["SERVICE_SETTINGS"] = settings
    app.config["HOST_SATELLITE_ID"] = host_satellite_id

    @app.get("/health")
    def health():
        return jsonify(
            {
                "service": settings.name,
                "host_satellite_id": host_satellite_id,
                "status": "ok",
            }
        ), 200

    return app

