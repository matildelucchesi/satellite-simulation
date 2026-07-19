"""Application factory del servizio Simulator."""

from __future__ import annotations

import atexit
import json
import logging
import os
from pathlib import Path
from typing import Any

from flask import Flask, jsonify

from common.settings import ServiceSettings

from .orbit_engine import ConstellationSimulator


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
        SIMULATOR_AUTOSTART=os.getenv("SIMULATOR_AUTOSTART", "true").lower()
        in {"1", "true", "yes"},
    )
    if test_config:
        app.config.update(test_config)

    logging.basicConfig(level=settings.log_level.upper())
    constellation_config = _read_constellation_config(app.config["CONFIG_PATH"])
    satellite_ids = [item["id"] for item in constellation_config["satellites"]]

    simulator = ConstellationSimulator(
        tle_path=app.config["TLE_PATH"],
        satellite_ids=satellite_ids,
        constellation_name=constellation_config["constellation"]["name"],
        tick_seconds=app.config["SIMULATOR_TICK_SECONDS"],
        eclipse_search_hours=app.config["ECLIPSE_SEARCH_HOURS"],
    )
    app.extensions["constellation_simulator"] = simulator

    if app.config["SIMULATOR_AUTOSTART"]:
        simulator.start()
        atexit.register(simulator.stop)

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

