"""Adapter HTTP Flask del servizio Simulator."""

from __future__ import annotations

from flask import Blueprint, Response, jsonify, request

from .experiment_manager import ExperimentManager, ExperimentManagerError
from .metrics import MetricsManager
from .migration_manager import MigrationManager, MigrationManagerError
from .orbit_engine import ConstellationSimulator
from .score_manager import ScoreManager, ScoreManagerError
from .startup_controller import StartupControllerManager


def create_api_blueprint(
    service_name: str,
    simulator: ConstellationSimulator,
    score_manager: ScoreManager,
    migration_manager: MigrationManager,
    metrics_manager: MetricsManager,
    startup_controller_manager: StartupControllerManager,
    experiment_manager: ExperimentManager,
    enforce_experiment_state: bool = True,
) -> Blueprint:
    """Crea le route iniettando esplicitamente i casi d'uso richiesti."""

    api = Blueprint("simulator_api", __name__)

    @api.get("/health")
    def health():
        status = "ok" if simulator.ready else "unavailable"
        payload = {
            "service": service_name,
            "status": status,
            "ready": simulator.ready,
            "running": simulator.running,
            "last_error": simulator.last_error,
        }
        return jsonify(payload), 200 if simulator.ready else 503

    @api.get("/api/v1/constellation")
    def constellation_state():
        return jsonify(simulator.snapshot())

    @api.get("/api/v1/satellites")
    def satellites_state():
        state = simulator.snapshot()
        return jsonify(
            {
                "generated_at": state.get("generated_at"),
                "satellites": state.get("satellites", {}),
            }
        )

    @api.get("/api/v1/satellites/<satellite_id>")
    def satellite_state(satellite_id: str):
        satellite = simulator.satellite_snapshot(satellite_id.upper())
        if satellite is None:
            return jsonify({"error": "satellite_not_found"}), 404
        return jsonify(satellite)

    @api.route("/api/v1/heartbeats", methods=["GET", "POST"])
    def heartbeats():
        if request.method == "GET":
            return jsonify(score_manager.heartbeat_snapshot())
        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify({"error": "invalid_json"}), 400
        if enforce_experiment_state and experiment_manager.snapshot()["status"] != "running":
            return jsonify({"status": "ignored", "reason": "simulation_not_running"}), 202
        try:
            heartbeat = score_manager.record_heartbeat(payload)
        except ScoreManagerError as exc:
            return jsonify({"error": "invalid_heartbeat", "message": str(exc)}), 400
        metrics_manager.record_heartbeat()
        return jsonify(
            {
                "status": "accepted",
                "heartbeat": heartbeat,
                "evaluation": score_manager.snapshot()["evaluation"],
            }
        ), 202

    @api.get("/api/v1/scores")
    def scores():
        return jsonify(score_manager.snapshot())

    @api.get("/api/v1/startup-controller")
    def startup_controller():
        return jsonify(startup_controller_manager.snapshot())

    @api.route("/api/v1/migrations", methods=["GET", "POST"])
    def migrations():
        if request.method == "POST":
            if enforce_experiment_state and experiment_manager.snapshot()["status"] != "running":
                return jsonify(
                    {"error": "simulation_not_running", "message": "Avvia prima una simulazione"}
                ), 409
            payload = request.get_json(silent=True)
            if payload is None:
                return jsonify({"error": "invalid_json"}), 400
            try:
                migration_id = migration_manager.enqueue(
                    source_satellite_id=payload.get("source_satellite_id"),
                    target_satellite_id=payload.get("target_satellite_id"),
                    mode=payload.get("mode"),
                    recommendation={"source": "manual_api"},
                )
            except MigrationManagerError as exc:
                return jsonify(
                    {"error": "migration_rejected", "message": str(exc)}
                ), 409
            migration = migration_manager.migration_snapshot(migration_id)
            return jsonify(
                {
                    "status": migration["status"] if migration else "unknown",
                    "migration_id": migration_id,
                }
            ), 202
        return jsonify(migration_manager.snapshot())

    @api.route("/api/v1/experiment", methods=["GET", "POST"])
    def experiment():
        if request.method == "GET":
            return jsonify(experiment_manager.snapshot())
        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify({"error": "invalid_json"}), 400
        try:
            state = experiment_manager.start(
                payload.get("mode"), payload.get("migration_limit")
            )
        except ExperimentManagerError as exc:
            return jsonify({"error": "experiment_rejected", "message": str(exc)}), 409
        except Exception as exc:
            return jsonify({"error": "experiment_start_failed", "message": str(exc)}), 503
        return jsonify(state), 201

    @api.post("/api/v1/experiment/reset")
    def reset_experiment():
        try:
            return jsonify(experiment_manager.reset()), 200
        except Exception as exc:
            return jsonify({"error": "experiment_reset_failed", "message": str(exc)}), 503

    @api.get("/api/v1/migrations/<migration_id>")
    def migration(migration_id: str):
        state = migration_manager.migration_snapshot(migration_id)
        if state is None:
            return jsonify({"error": "migration_not_found"}), 404
        return jsonify(state)

    @api.get("/api/v1/metrics")
    def metrics():
        return jsonify(metrics_manager.snapshot())

    @api.get("/api/v1/metrics/export")
    @api.get("/api/v1/metrics/export.<export_format>")
    def export_metrics(export_format: str | None = None):
        selected_format = (export_format or request.args.get("format", "json")).lower()
        if selected_format == "json":
            response = jsonify(metrics_manager.snapshot())
            response.headers["Content-Disposition"] = (
                'attachment; filename="simulation-metrics.json"'
            )
            return response
        if selected_format == "csv":
            return Response(
                metrics_manager.to_csv(),
                mimetype="text/csv",
                headers={
                    "Content-Disposition": (
                        'attachment; filename="simulation-metrics.csv"'
                    )
                },
            )
        return jsonify(
            {
                "error": "unsupported_format",
                "message": "I formati supportati sono json e csv",
            }
        ), 400

    return api
