"""Caricamento e validazione della configurazione della costellazione."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_constellation_config(path: str | Path) -> dict[str, Any]:
    """Carica la configurazione e ne verifica consistenza e identificatori."""

    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"Configurazione non trovata: {config_path}")
    with config_path.open(encoding="utf-8") as stream:
        data = json.load(stream)

    satellites = data.get("satellites", [])
    expected = data.get("constellation", {}).get("satellite_count")
    if not isinstance(expected, int) or isinstance(expected, bool) or expected <= 0:
        raise ValueError("satellite_count deve essere un intero maggiore di zero")
    if len(satellites) != expected:
        raise ValueError(
            f"La configurazione dichiara {expected} satelliti ma ne descrive "
            f"{len(satellites)}"
        )
    if any("id" not in satellite for satellite in satellites):
        raise ValueError("Ogni satellite deve avere un identificatore")
    satellite_ids = [satellite["id"] for satellite in satellites]
    if len(set(satellite_ids)) != expected:
        raise ValueError("Gli identificatori dei satelliti devono essere unici")
    controller_id = data.get("constellation", {}).get("controller_satellite_id")
    if controller_id != "AUTO" and controller_id not in satellite_ids:
        raise ValueError("controller_satellite_id deve riferirsi a un satellite noto")
    initial_controller = data.get("constellation", {}).get("initial_controller")
    if controller_id == "AUTO" and not isinstance(initial_controller, dict):
        raise ValueError("initial_controller è obbligatorio quando il Controller è AUTO")
    return data
