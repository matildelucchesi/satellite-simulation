"""Application factory dell'agente satellitare."""

import os

from flask import Flask, jsonify

from common.settings import ServiceSettings


def create_app() -> Flask:
    """Crea l'app Flask senza implementare il comportamento satellitare."""

    app = Flask(__name__)
    settings = ServiceSettings.from_environment("satellite-agent")
    satellite_id = os.getenv("SATELLITE_ID", "UNASSIGNED")
    app.config["SERVICE_SETTINGS"] = settings
    app.config["SATELLITE_ID"] = satellite_id

    @app.get("/health")
    def health():
        return jsonify(
            {"service": settings.name, "satellite_id": satellite_id, "status": "ok"}
        ), 200

    return app

