"""Application factory dell'agente satellitare."""

from __future__ import annotations

import atexit
import logging
import os
from typing import Any

from flask import Flask, jsonify, request

from common.settings import ServiceSettings

from .agent import AgentValidationError, SatelliteAgent


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
        state_sync_interval_seconds=app.config["STATE_SYNC_INTERVAL_SECONDS"],
        heartbeat_interval_seconds=app.config["HEARTBEAT_INTERVAL_SECONDS"],
        request_timeout_seconds=app.config["HTTP_REQUEST_TIMEOUT_SECONDS"],
    )
    app.extensions["satellite_agent"] = agent

    if app.config["AGENT_AUTOSTART"]:
        agent.start()
        atexit.register(agent.stop)

    @app.get("/health")
    def health():
        return jsonify(
            {
                "service": settings.name,
                "satellite_id": agent.satellite_id,
                "status": "ok",
                "running": agent.running,
            }
        )

    @app.get("/status")
    def status():
        return jsonify(agent.status())

    @app.get("/position")
    def position():
        state = agent.position_state()
        if state is None:
            return jsonify({"error": "orbital_state_not_available"}), 503
        return jsonify(state)

    @app.post("/receive_state")
    def receive_state():
        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify({"error": "invalid_json"}), 400
        try:
            state = agent.receive_state(payload)
        except AgentValidationError as exc:
            return jsonify({"error": "invalid_state", "message": str(exc)}), 400
        return jsonify({"id": agent.satellite_id, "status": "accepted", "state": state})

    @app.post("/start_controller")
    def start_controller():
        return jsonify(agent.start_controller())

    @app.post("/stop_controller")
    def stop_controller():
        return jsonify(agent.stop_controller())

    @app.post("/migration_request")
    def migration_request():
        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify({"error": "invalid_json"}), 400
        try:
            migration = agent.accept_migration(payload)
        except AgentValidationError as exc:
            return jsonify({"error": "migration_rejected", "message": str(exc)}), 409
        return jsonify(migration), 202

    @app.post("/receive_controller_state")
    def receive_controller_state():
        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify({"error": "invalid_json"}), 400
        try:
            acknowledgement = agent.receive_controller_state(payload)
        except AgentValidationError as exc:
            return jsonify(
                {"error": "controller_state_rejected", "message": str(exc)}
            ), 409
        return jsonify(acknowledgement), 200

    return app


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}
