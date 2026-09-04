"""Adapter HTTP Flask della Dashboard."""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request, send_file

from .service import DashboardDataService


def create_api_blueprint(
    service_name: str, data_service: DashboardDataService
) -> Blueprint:
    api = Blueprint("dashboard_api", __name__)

    @api.get("/")
    def index():
        return render_template("index.html")

    @api.get("/api/dashboard")
    def dashboard_data():
        return jsonify(data_service.collect())

    @api.get("/api/exports")
    def exports():
        return jsonify({"exports": data_service.list_exports()})

    @api.get("/exports/<path:filename>")
    def export_file(filename: str):
        path = data_service.export_path(filename)
        if path is None:
            return jsonify({"error": "export_not_found"}), 404
        mimetype = "application/json" if path.suffix.lower() == ".json" else "application/pdf"
        return send_file(
            path,
            mimetype=mimetype,
            as_attachment=request.args.get("download") == "1",
            download_name=path.name,
        )

    @api.post("/api/experiment")
    def start_experiment():
        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify({"error": "invalid_json"}), 400
        try:
            return jsonify(data_service.start_experiment(payload)), 201
        except Exception as exc:
            return jsonify({"error": "experiment_start_failed", "message": str(exc)}), 502

    @api.post("/api/experiment/reset")
    def reset_experiment():
        try:
            return jsonify(data_service.reset_experiment()), 200
        except Exception as exc:
            return jsonify({"error": "experiment_reset_failed", "message": str(exc)}), 502

    @api.get("/health")
    def health():
        return jsonify({"service": service_name, "status": "ok"})

    return api
