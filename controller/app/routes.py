"""Adapter HTTP Flask del microservizio Controller."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from .service import ControllerService, ControllerStateError


def create_api_blueprint(
    service_name: str,
    controller: ControllerService,
) -> Blueprint:
    api = Blueprint("controller_api", __name__)

    @api.get("/health")
    def health():
        active = controller.active
        return jsonify(
            {
                "service": service_name,
                "host_satellite_id": controller.host_satellite_id,
                "status": "ok" if active else "shutdown",
                "active": active,
                "quiesced": controller.quiesced,
            }
        ), 200 if active else 503

    @api.get("/heartbeat")
    def get_heartbeat():
        satellite_id = request.args.get("id")
        try:
            heartbeat = controller.heartbeat_snapshot(satellite_id)
        except KeyError:
            return jsonify({"error": "heartbeat_not_found"}), 404
        return jsonify(heartbeat)

    @api.post("/heartbeat")
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

    @api.get("/state")
    def state():
        return jsonify(
            {
                **controller.snapshot(),
                "host_satellite_id": controller.host_satellite_id,
            }
        )

    @api.post("/host")
    def update_host():
        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify({"error": "invalid_json"}), 400
        try:
            result = controller.set_host_satellite(payload.get("satellite_id"))
        except ControllerStateError as exc:
            return jsonify({"error": "invalid_host", "message": str(exc)}), 400
        return jsonify(result), 200

    @api.post("/checkpoint")
    def checkpoint():
        state = controller.checkpoint()
        return jsonify(
            {
                "status": "created",
                "checkpoint_path": str(controller.checkpoint_path),
                "checkpoint": state,
            }
        ), 201

    @api.post("/restore")
    def restore():
        payload = request.get_json(silent=True)
        try:
            state = controller.restore(payload)
        except FileNotFoundError as exc:
            return jsonify({"error": "checkpoint_not_found", "message": str(exc)}), 404
        except ControllerStateError as exc:
            return jsonify({"error": "invalid_checkpoint", "message": str(exc)}), 400
        return jsonify({"status": "restored", "state": state})

    @api.post("/shutdown")
    def shutdown():
        return jsonify(controller.shutdown()), 202

    @api.post("/quiesce")
    def quiesce():
        try:
            result = controller.quiesce()
        except RuntimeError as exc:
            return jsonify({"error": "controller_shutdown", "message": str(exc)}), 409
        return jsonify(result), 200

    @api.post("/resume")
    def resume():
        try:
            result = controller.resume()
        except RuntimeError as exc:
            return jsonify({"error": "controller_shutdown", "message": str(exc)}), 409
        return jsonify(result), 200

    return api
