"""Application factory del servizio Simulator."""

from __future__ import annotations

import atexit
import json
import logging
import os
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request

from common.settings import ServiceSettings

from .migration_manager import (
    MigrationConfig,
    MigrationManager,
    MigrationManagerError,
)
from .orbit_engine import ConstellationSimulator
from .score_manager import ScoreManager, ScoreManagerConfig, ScoreManagerError


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    """Crea l'API headless e avvia il coordinatore della simulazione."""

    app = Flask(__name__)
    settings = ServiceSettings.from_environment("simulator")
    app.config.from_mapping(
        SERVICE_SETTINGS=settings,
        CONFIG_PATH=settings.config_path,
        TLE_PATH=os.getenv("TLE_PATH", "/app/config/starlink.tle"),
        SIMULATOR_TICK_SECONDS=float(os.getenv("SIMULATOR_TICK_SECONDS", "1")),
        ECLIPSE_SEARCH_HOURS=float(os.getenv("ECLIPSE_SEARCH_HOURS", "24")),
        SCORING_CONFIG_PATH=os.getenv("SCORING_CONFIG_PATH"),
        MIGRATION_CONFIG_PATH=os.getenv("MIGRATION_CONFIG_PATH"),
        SIMULATOR_AUTOSTART=os.getenv("SIMULATOR_AUTOSTART", "true").lower()
        in {"1", "true", "yes"},
    )
    if test_config:
        app.config.update(test_config)

    logging.basicConfig(level=settings.log_level.upper())
    constellation_config = _read_constellation_config(app.config["CONFIG_PATH"])
    satellite_ids = [item["id"] for item in constellation_config["satellites"]]
    scoring_config_path = app.config["SCORING_CONFIG_PATH"] or str(
        Path(app.config["CONFIG_PATH"]).with_name("scoring.json")
    )
    migration_config_path = app.config["MIGRATION_CONFIG_PATH"] or str(
        Path(app.config["CONFIG_PATH"]).with_name("migration.json")
    )
    migration_manager = MigrationManager(
        config=MigrationConfig.from_file(migration_config_path),
        satellite_ids=satellite_ids,
    )
    score_manager = ScoreManager(
        satellite_ids=satellite_ids,
        config=ScoreManagerConfig.from_file(scoring_config_path),
        migration_notifier=migration_manager.notify_migration,
    )

    simulator = ConstellationSimulator(
        tle_path=app.config["TLE_PATH"],
        satellite_ids=satellite_ids,
        constellation_name=constellation_config["constellation"]["name"],
        tick_seconds=app.config["SIMULATOR_TICK_SECONDS"],
        eclipse_search_hours=app.config["ECLIPSE_SEARCH_HOURS"],
        state_listener=score_manager.update_constellation,
    )
    app.extensions["constellation_simulator"] = simulator
    app.extensions["score_manager"] = score_manager
    app.extensions["migration_manager"] = migration_manager

    if app.config["SIMULATOR_AUTOSTART"]:
        migration_manager.start()
        simulator.start()
        atexit.register(migration_manager.stop)
        atexit.register(simulator.close)

    @app.get("/health")
    def health():
        status = "ok" if simulator.ready else "unavailable"
        payload = {
            "service": settings.name,
            "status": status,
            "ready": simulator.ready,
            "running": simulator.running,
            "last_error": simulator.last_error,
        }
        return jsonify(payload), 200 if simulator.ready else 503

    @app.get("/api/v1/constellation")
    def constellation_state():
        return jsonify(simulator.snapshot())

    @app.get("/api/v1/satellites")
    def satellites_state():
        state = simulator.snapshot()
        return jsonify(
            {
                "generated_at": state.get("generated_at"),
                "satellites": state.get("satellites", {}),
            }
        )

    @app.get("/api/v1/satellites/<satellite_id>")
    def satellite_state(satellite_id: str):
        satellite = simulator.satellite_snapshot(satellite_id.upper())
        if satellite is None:
            return jsonify({"error": "satellite_not_found"}), 404
        return jsonify(satellite)

    @app.route("/api/v1/heartbeats", methods=["GET", "POST"])
    def heartbeats():
        if request.method == "GET":
            return jsonify(score_manager.heartbeat_snapshot())
        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify({"error": "invalid_json"}), 400
        try:
            heartbeat = score_manager.record_heartbeat(payload)
        except ScoreManagerError as exc:
            return jsonify({"error": "invalid_heartbeat", "message": str(exc)}), 400
        return jsonify(
            {
                "status": "accepted",
                "heartbeat": heartbeat,
                "evaluation": score_manager.snapshot()["evaluation"],
            }
        ), 202

    @app.get("/api/v1/scores")
    def scores():
        return jsonify(score_manager.snapshot())

    @app.route("/api/v1/migrations", methods=["GET", "POST"])
    def migrations():
        if request.method == "POST":
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
            return jsonify(
                {
                    "status": "queued",
                    "migration_id": migration_id,
                }
            ), 202
        return jsonify(migration_manager.snapshot())

    @app.get("/api/v1/migrations/<migration_id>")
    def migration(migration_id: str):
        state = migration_manager.migration_snapshot(migration_id)
        if state is None:
            return jsonify({"error": "migration_not_found"}), 404
        return jsonify(state)

    return app


def _read_constellation_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"Configurazione non trovata: {config_path}")
    with config_path.open(encoding="utf-8") as stream:
        data = json.load(stream)

    satellites = data.get("satellites", [])
    expected = data.get("constellation", {}).get("satellite_count")
    if expected != 5 or len(satellites) != expected:
        raise ValueError("La configurazione deve descrivere esattamente 5 satelliti")
    if any("id" not in satellite for satellite in satellites):
        raise ValueError("Ogni satellite deve avere un identificatore")
    return data
