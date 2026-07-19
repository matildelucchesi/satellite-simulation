"""Propagazione orbitale e stato in memoria della costellazione."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import math
from pathlib import Path
from threading import Event, RLock, Thread
from time import monotonic
from typing import Any, Callable

import numpy as np
from skyfield.api import EarthSatellite, Loader, wgs84
from skyfield.searchlib import find_discrete
from skyfield_data import get_skyfield_data_path

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TrackedSatellite:
    """Associa un identificatore della simulazione a un satellite Skyfield."""

    satellite_id: str
    satellite: EarthSatellite


def load_tle_file(
    path: str | Path,
    expected_count: int | None = None,
    satellite_ids: list[str] | None = None,
) -> tuple[Any, list[TrackedSatellite]]:
    """Carica e valida un file TLE nel formato nome + due righe."""

    tle_path = Path(path)
    if not tle_path.is_file():
        raise FileNotFoundError(f"File TLE non trovato: {tle_path}")

    lines = [line.strip() for line in tle_path.read_text(encoding="utf-8").splitlines()]
    lines = [line for line in lines if line]

    if len(lines) % 3 != 0:
        raise ValueError(
            "Il file TLE deve contenere gruppi di tre righe: nome, line 1, line 2"
        )

    count = len(lines) // 3
    if expected_count is not None and count != expected_count:
        raise ValueError(
            f"Il file TLE contiene {count} satelliti; ne erano attesi {expected_count}"
        )

    ids = satellite_ids or [f"SAT-{index}" for index in range(1, count + 1)]
    if len(ids) != count or len(set(ids)) != count:
        raise ValueError("Gli identificatori dei satelliti devono essere unici e completi")

    loader = Loader(get_skyfield_data_path(), expire=False)
    timescale = loader.timescale(builtin=True)
    tracked: list[TrackedSatellite] = []

    for index in range(count):
        name, line1, line2 = lines[index * 3 : index * 3 + 3]
        if not line1.startswith("1 ") or not line2.startswith("2 "):
            raise ValueError(f"TLE non valido per {name}: prefisso delle righe errato")
        satellite = EarthSatellite(line1, line2, name=name, ts=timescale)
        tracked.append(TrackedSatellite(ids[index], satellite))

    return timescale, tracked


class ConstellationSimulator:
    """Coordina la propagazione periodica e conserva uno snapshot thread-safe."""

    def __init__(
        self,
        tle_path: str | Path,
        satellite_ids: list[str],
        constellation_name: str = "starlink-simulation",
        tick_seconds: float = 1.0,
        eclipse_search_hours: float = 24.0,
        state_listener: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if tick_seconds <= 0:
            raise ValueError("tick_seconds deve essere maggiore di zero")
        if eclipse_search_hours <= 0:
            raise ValueError("eclipse_search_hours deve essere maggiore di zero")

        self.constellation_name = constellation_name
        self.tick_seconds = tick_seconds
        self.eclipse_search_hours = eclipse_search_hours
        self.state_listener = state_listener
        self.timescale, self.satellites = load_tle_file(
            tle_path, expected_count=len(satellite_ids), satellite_ids=satellite_ids
        )

        loader = Loader(get_skyfield_data_path(), expire=False)
        self.ephemeris = loader("de421.bsp")

        self._lock = RLock()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._state: dict[str, Any] = {}
        self._last_error: str | None = None
        self._eclipse_cache: dict[str, dict[str, Any]] = {}

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def ready(self) -> bool:
        with self._lock:
            return bool(self._state) and self._last_error is None

    @property
    def last_error(self) -> str | None:
        with self._lock:
            return self._last_error

    def start(self) -> None:
        """Produce subito uno snapshot e avvia il ciclo con cadenza configurata."""

        if self.running:
            return
        self._stop_event.clear()
        self.update()
        self._thread = Thread(
            target=self._run,
            name="constellation-simulator",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Arresta il ciclo di aggiornamento senza bloccare indefinitamente."""

        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

    def close(self) -> None:
        """Arresta il worker e chiude il file delle effemeridi."""

        self.stop()
        self.ephemeris.close()

    def snapshot(self) -> dict[str, Any]:
        """Restituisce una copia isolata dello stato corrente."""

        with self._lock:
            return deepcopy(self._state)

    def satellite_snapshot(self, satellite_id: str) -> dict[str, Any] | None:
        with self._lock:
            satellite = self._state.get("satellites", {}).get(satellite_id)
            return deepcopy(satellite) if satellite is not None else None

    def update(self, at: datetime | None = None) -> dict[str, Any]:
        """Propaga tutti i TLE allo stesso istante e sostituisce lo snapshot."""

        current_time = at or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            raise ValueError("L'istante di simulazione deve includere il fuso orario")
        current_time = current_time.astimezone(timezone.utc)
        skyfield_time = self.timescale.from_datetime(current_time)

        satellites_state: dict[str, dict[str, Any]] = {}
        position_vectors: dict[str, np.ndarray] = {}

        for tracked in self.satellites:
            state, position = self._propagate_satellite(
                tracked, skyfield_time, current_time
            )
            satellites_state[tracked.satellite_id] = state
            position_vectors[tracked.satellite_id] = position

        distances = self._calculate_distances(position_vectors)
        for satellite_id, state in satellites_state.items():
            state["distances_km"] = distances[satellite_id]

        snapshot = {
            "constellation": self.constellation_name,
            "generated_at": _isoformat(current_time),
            "reference_frame": "GCRS",
            "tick_seconds": self.tick_seconds,
            "satellite_count": len(satellites_state),
            "satellites": satellites_state,
            "distances_km": distances,
        }

        with self._lock:
            self._state = snapshot
            self._last_error = None
        if self.state_listener is not None:
            try:
                self.state_listener(deepcopy(snapshot))
            except Exception:  # pragma: no cover - isolamento del coordinatore
                LOGGER.exception("Il listener dello stato della costellazione è fallito")
        return deepcopy(snapshot)

    def _run(self) -> None:
        next_tick = monotonic() + self.tick_seconds
        while not self._stop_event.wait(max(0.0, next_tick - monotonic())):
            try:
                self.update()
            except Exception as exc:  # pragma: no cover - protezione del worker
                LOGGER.exception("Aggiornamento della costellazione non riuscito")
                with self._lock:
                    self._last_error = str(exc)
            next_tick += self.tick_seconds
            if next_tick < monotonic():
                next_tick = monotonic() + self.tick_seconds

    def _propagate_satellite(
        self,
        tracked: TrackedSatellite,
        skyfield_time: Any,
        current_time: datetime,
    ) -> tuple[dict[str, Any], np.ndarray]:
        geocentric = tracked.satellite.at(skyfield_time)
        position = np.asarray(geocentric.xyz.km, dtype=float)
        velocity = np.asarray(geocentric.velocity.km_per_s, dtype=float)
        if not np.all(np.isfinite(position)) or not np.all(np.isfinite(velocity)):
            raise RuntimeError(
                f"Propagazione SGP4 non valida per {tracked.satellite_id}"
            )

        geographic = wgs84.geographic_position_of(geocentric)
        is_sunlit = bool(geocentric.is_sunlit(self.ephemeris))
        eclipse = self._eclipse_state(tracked, current_time, is_sunlit)
        model = tracked.satellite.model

        state = {
            "id": tracked.satellite_id,
            "name": tracked.satellite.name,
            "norad_id": int(model.satnum),
            "tle_epoch": tracked.satellite.epoch.utc_iso(),
            "position_km": _vector(position),
            "geodetic": {
                "latitude_deg": round(float(geographic.latitude.degrees), 6),
                "longitude_deg": round(float(geographic.longitude.degrees), 6),
                "altitude_km": round(float(geographic.elevation.km), 6),
            },
            "velocity_km_s": _vector(velocity),
            "speed_km_s": round(float(np.linalg.norm(velocity)), 6),
            "illumination": eclipse,
        }
        return state, position

    def _calculate_distances(
        self, positions: dict[str, np.ndarray]
    ) -> dict[str, dict[str, float]]:
        distances: dict[str, dict[str, float]] = {}
        for source_id, source_position in positions.items():
            distances[source_id] = {}
            for target_id, target_position in positions.items():
                distance = float(np.linalg.norm(source_position - target_position))
                distances[source_id][target_id] = round(distance, 3)
        return distances

    def _eclipse_state(
        self,
        tracked: TrackedSatellite,
        current_time: datetime,
        is_sunlit: bool,
    ) -> dict[str, Any]:
        if not is_sunlit:
            cached = self._eclipse_cache.get(tracked.satellite_id)
            if (
                cached is None
                or cached.get("state") != "shadow"
                or cached["valid_until"] <= current_time
            ):
                next_sunlight = self._find_next_sunlight(
                    tracked.satellite, current_time
                )
                cached = {
                    "state": "shadow",
                    "next_sunlight": next_sunlight,
                    "valid_until": (
                        next_sunlight
                        if next_sunlight is not None
                        else current_time + timedelta(minutes=5)
                    ),
                }
                self._eclipse_cache[tracked.satellite_id] = cached
            next_sunlight = cached["next_sunlight"]
            seconds_until_sunlight = (
                max(0.0, (next_sunlight - current_time).total_seconds())
                if next_sunlight is not None
                else None
            )
            return {
                "state": "shadow",
                "is_sunlit": False,
                "seconds_until_eclipse": 0.0,
                "next_eclipse_at": None,
                "next_eclipse_position_km": None,
                "seconds_until_sunlight": (
                    round(seconds_until_sunlight, 3)
                    if seconds_until_sunlight is not None
                    else None
                ),
                "next_sunlight_at": (
                    _isoformat(next_sunlight) if next_sunlight else None
                ),
            }

        cached = self._eclipse_cache.get(tracked.satellite_id)
        if (
            cached is None
            or cached.get("state") != "sunlight"
            or cached["valid_until"] <= current_time
        ):
            next_eclipse = self._find_next_eclipse(tracked.satellite, current_time)
            next_eclipse_position = (
                _vector(
                    np.asarray(
                        tracked.satellite.at(
                            self.timescale.from_datetime(next_eclipse)
                        ).xyz.km,
                        dtype=float,
                    )
                )
                if next_eclipse is not None
                else None
            )
            valid_until = (
                next_eclipse
                if next_eclipse is not None
                else current_time + timedelta(minutes=5)
            )
            cached = {
                "state": "sunlight",
                "next_eclipse": next_eclipse,
                "next_eclipse_position_km": next_eclipse_position,
                "valid_until": valid_until,
            }
            self._eclipse_cache[tracked.satellite_id] = cached

        next_eclipse = cached["next_eclipse"]
        seconds = (
            max(0.0, (next_eclipse - current_time).total_seconds())
            if next_eclipse is not None
            else None
        )
        return {
            "state": "sunlight",
            "is_sunlit": True,
            "seconds_until_eclipse": round(seconds, 3) if seconds is not None else None,
            "next_eclipse_at": _isoformat(next_eclipse) if next_eclipse else None,
            "next_eclipse_position_km": deepcopy(
                cached.get("next_eclipse_position_km")
            ),
            "seconds_until_sunlight": None,
            "next_sunlight_at": None,
        }

    def _find_next_eclipse(
        self, satellite: EarthSatellite, current_time: datetime
    ) -> datetime | None:
        start = self.timescale.from_datetime(current_time)
        end = self.timescale.from_datetime(
            current_time + timedelta(hours=self.eclipse_search_hours)
        )

        def sunlight(time: Any) -> Any:
            return satellite.at(time).is_sunlit(self.ephemeris)

        sunlight.step_days = 60.0 / 86_400.0
        event_times, states = find_discrete(start, end, sunlight)
        for event_time, state in zip(event_times, states):
            if not bool(state):
                result = event_time.utc_datetime().astimezone(timezone.utc)
                if result > current_time:
                    return result
        return None

    def _find_next_sunlight(
        self, satellite: EarthSatellite, current_time: datetime
    ) -> datetime | None:
        start = self.timescale.from_datetime(current_time)
        end = self.timescale.from_datetime(
            current_time + timedelta(hours=self.eclipse_search_hours)
        )

        def sunlight(time: Any) -> Any:
            return satellite.at(time).is_sunlit(self.ephemeris)

        sunlight.step_days = 60.0 / 86_400.0
        event_times, states = find_discrete(start, end, sunlight)
        for event_time, state in zip(event_times, states):
            if bool(state):
                result = event_time.utc_datetime().astimezone(timezone.utc)
                if result > current_time:
                    return result
        return None


def _vector(values: np.ndarray) -> dict[str, float]:
    return {
        "x": round(float(values[0]), 6),
        "y": round(float(values[1]), 6),
        "z": round(float(values[2]), 6),
    }


def _isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
