"""Application factory della dashboard real-time."""

from __future__ import annotations

import os
from typing import Any

from flask import Flask, jsonify, render_template

from common.settings import ServiceSettings

from .service import DashboardDataService


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    settings = ServiceSettings.from_environment("dashboard")
    app.config.from_mapping(
        SERVICE_SETTINGS=settings,
        SIMULATOR_URL=os.getenv("SIMULATOR_URL", "http://simulator:5000"),
        CONTROLLER_URL=os.getenv("CONTROLLER_URL", "http://controller:5000"),
        LOG_DIR=os.getenv("LOG_DIR", "/app/logs"),
        UPSTREAM_TIMEOUT_SECONDS=float(
            os.getenv("UPSTREAM_TIMEOUT_SECONDS", "2")
        ),
    )
    if test_config:
        app.config.update(test_config)

    data_service = DashboardDataService(
        simulator_url=app.config["SIMULATOR_URL"],
        controller_url=app.config["CONTROLLER_URL"],
        log_dir=app.config["LOG_DIR"],
        request_timeout_seconds=app.config["UPSTREAM_TIMEOUT_SECONDS"],
        fetcher=app.config.get("DASHBOARD_FETCHER"),
    )
    app.extensions["dashboard_data_service"] = data_service

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/dashboard")
    def dashboard_data():
        return jsonify(data_service.collect())

    @app.get("/health")
    def health():
        return jsonify({"service": settings.name, "status": "ok"})

    return app

