"""Caricamento e validazione della configurazione della costellazione."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_constellation_config(path: str | Path) -> dict[str, Any]:
    """Carica la configurazione e verifica l'invariante dei cinque satelliti."""

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
