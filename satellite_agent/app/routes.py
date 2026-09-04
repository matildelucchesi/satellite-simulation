"""Adapter HTTP Flask del Satellite Agent."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from .agent import AgentValidationError, SatelliteAgent


def create_api_blueprint(service_name: str, agent: SatelliteAgent) -> Blueprint:
    api = Blueprint("satellite_agent_api", __name__)

    @api.get("/health")
    def health():
        return jsonify(
            {
                "service": service_name,
                "satellite_id": agent.satellite_id,
                "status": "ok",
                "running": agent.running,
            }
        )

    @api.get("/status")
    def status():
        return jsonify(agent.status())

    @api.get("/position")
    def position():
        state = agent.position_state()
        if state is None:
            return jsonify({"error": "orbital_state_not_available"}), 503
        return jsonify(state)

    @api.post("/receive_state")
    def receive_state():
        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify({"error": "invalid_json"}), 400
        try:
            state = agent.receive_state(payload)
        except AgentValidationError as exc:
            return jsonify({"error": "invalid_state", "message": str(exc)}), 400
        return jsonify({"id": agent.satellite_id, "status": "accepted", "state": state})

    @api.post("/start_controller")
    def start_controller():
        try:
            return jsonify(agent.start_controller())
        except AgentValidationError as exc:
            return jsonify({"error": "controller_not_ready", "message": str(exc)}), 409

    @api.post("/stop_controller")
    def stop_controller():
        return jsonify(agent.stop_controller())

    @api.post("/reset_simulation")
    def reset_simulation():
        return jsonify(agent.reset_simulation())

    @api.post("/migration_request")
    def migration_request():
        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify({"error": "invalid_json"}), 400
        try:
            migration = agent.request_migration(payload)
        except AgentValidationError as exc:
            return jsonify({"error": "migration_rejected", "message": str(exc)}), 409
        return jsonify(migration), 202

    @api.post("/prepare_migration")
    def prepare_migration():
        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify({"error": "invalid_json"}), 400
        try:
            migration = agent.prepare_migration(payload)
        except AgentValidationError as exc:
            return jsonify({"error": "migration_rejected", "message": str(exc)}), 409
        return jsonify(migration), 202

    @api.post("/receive_controller_state")
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

    return api
