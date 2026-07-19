"""Adapter HTTP Flask della Dashboard."""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template

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

    @api.get("/health")
    def health():
        return jsonify({"service": service_name, "status": "ok"})

    return api
