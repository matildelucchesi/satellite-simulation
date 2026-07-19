"""Application factory del microservizio Controller."""

from __future__ import annotations

import logging
import os
from typing import Any

from flask import Flask, jsonify, request

from common.settings import ServiceSettings

from .service import ControllerService, ControllerStateError


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    """Crea l'API REST del Controller e il relativo stato replicabile."""

    app = Flask(__name__)
    settings = ServiceSettings.from_environment("controller")
    app.config.from_mapping(
        SERVICE_SETTINGS=settings,
        HOST_SATELLITE_ID=os.getenv("HOST_SATELLITE_ID", "SAT-1"),
        CHECKPOINT_PATH=os.getenv(
            "CHECKPOINT_PATH", "/app/state/controller-checkpoint.json"
        ),
    )
    if test_config:
        app.config.update(test_config)

    logging.basicConfig(level=settings.log_level.upper())
    controller = ControllerService(app.config["CHECKPOINT_PATH"])
    app.extensions["controller_service"] = controller

    @app.get("/health")
    def health():
        active = controller.active
        return jsonify(
            {
                "service": settings.name,
                "host_satellite_id": app.config["HOST_SATELLITE_ID"],
                "status": "ok" if active else "shutdown",
                "active": active,
                "quiesced": controller.quiesced,
            }
        ), 200 if active else 503

    @app.get("/heartbeat")
    def get_heartbeat():
        satellite_id = request.args.get("id")
        try:
            heartbeat = controller.heartbeat_snapshot(satellite_id)
        except KeyError:
            return jsonify({"error": "heartbeat_not_found"}), 404
        return jsonify(heartbeat)

    @app.post("/heartbeat")
    def receive_heartbeat():
        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify({"error": "invalid_json"}), 400
        try:
            heartbeat = controller.record_heartbeat(payload)
        except ControllerStateError as exc:
            return jsonify({"error": "invalid_heartbeat", "message": str(exc)}), 400
        except RuntimeError as exc:
            return jsonify({"error": "controller_shutdown", "message": str(exc)}), 503
        return jsonify({"status": "accepted", "heartbeat": heartbeat}), 202

    @app.get("/state")
    def state():
        return jsonify(controller.snapshot())

    @app.post("/checkpoint")
    def checkpoint():
        state = controller.checkpoint()
        return jsonify(
            {
                "status": "created",
                "checkpoint_path": str(controller.checkpoint_path),
                "checkpoint": state,
            }
        ), 201

    @app.post("/restore")
    def restore():
        payload = request.get_json(silent=True)
        try:
            state = controller.restore(payload)
        except FileNotFoundError as exc:
            return jsonify({"error": "checkpoint_not_found", "message": str(exc)}), 404
        except ControllerStateError as exc:
            return jsonify({"error": "invalid_checkpoint", "message": str(exc)}), 400
        return jsonify({"status": "restored", "state": state})

    @app.post("/shutdown")
    def shutdown():
        result = controller.shutdown()
        return jsonify(result), 202

    @app.post("/quiesce")
    def quiesce():
        try:
            result = controller.quiesce()
        except RuntimeError as exc:
            return jsonify({"error": "controller_shutdown", "message": str(exc)}), 409
        return jsonify(result), 200

    @app.post("/resume")
    def resume():
        try:
            result = controller.resume()
        except RuntimeError as exc:
            return jsonify({"error": "controller_shutdown", "message": str(exc)}), 409
        return jsonify(result), 200

    return app
