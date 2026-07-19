"""Valutazione geometrica della finestra di contatto inter-satellitare."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any


class ContactWindowError(ValueError):
    """Configurazione o stato orbitale non valido per la contact window."""


@dataclass(frozen=True, slots=True)
class ContactWindowConfig:
    required_alignment_seconds: float
    max_distance_km: float
    require_line_of_sight: bool
    earth_radius_km: float
    max_sample_gap_seconds: float

    @classmethod
    def from_dict(cls, payload: Any) -> "ContactWindowConfig":
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise ContactWindowError("contact_window deve essere un oggetto JSON")
        require_line_of_sight = payload.get("require_line_of_sight", True)
        if not isinstance(require_line_of_sight, bool):
            raise ContactWindowError("require_line_of_sight deve essere booleano")
        return cls(
            required_alignment_seconds=_non_negative_number(
                payload.get("required_alignment_seconds", 60),
                "required_alignment_seconds",
            ),
            max_distance_km=_positive_number(
                payload.get("max_distance_km", 5500), "max_distance_km"
            ),
            require_line_of_sight=require_line_of_sight,
            earth_radius_km=_positive_number(
                payload.get("earth_radius_km", 6378.137), "earth_radius_km"
            ),
            max_sample_gap_seconds=_positive_number(
                payload.get("max_sample_gap_seconds", 2.5),
                "max_sample_gap_seconds",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "required_alignment_seconds": self.required_alignment_seconds,
            "max_distance_km": self.max_distance_km,
            "require_line_of_sight": self.require_line_of_sight,
            "earth_radius_km": self.earth_radius_km,
            "max_sample_gap_seconds": self.max_sample_gap_seconds,
        }


@dataclass(frozen=True, slots=True)
class ContactObservation:
    observed_at: datetime
    distance_km: float | None
    line_of_sight: bool | None
    eligible: bool
    reason: str


def evaluate_contact(
    snapshot: dict[str, Any],
    source_satellite_id: str,
    target_satellite_id: str,
    config: ContactWindowConfig,
) -> ContactObservation:
    """Verifica distanza e occultazione terrestre usando le posizioni GCRS."""

    observed_at = _snapshot_time(snapshot)
    satellites = snapshot.get("satellites", {})
    if not isinstance(satellites, dict):
        return ContactObservation(observed_at, None, None, False, "missing_state")
    source = _position(satellites.get(source_satellite_id))
    target = _position(satellites.get(target_satellite_id))
    if source is None or target is None:
        return ContactObservation(observed_at, None, None, False, "missing_position")

    distance = math.dist(source, target)
    line_of_sight = _has_line_of_sight(source, target, config.earth_radius_km)
    if distance > config.max_distance_km:
        return ContactObservation(
            observed_at, distance, line_of_sight, False, "distance_exceeded"
        )
    if config.require_line_of_sight and not line_of_sight:
        return ContactObservation(
            observed_at, distance, line_of_sight, False, "earth_occlusion"
        )
    return ContactObservation(observed_at, distance, line_of_sight, True, "in_contact")


def _position(satellite: Any) -> tuple[float, float, float] | None:
    if not isinstance(satellite, dict):
        return None
    position = satellite.get("position_km")
    if not isinstance(position, dict):
        return None
    values = (position.get("x"), position.get("y"), position.get("z"))
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        for value in values
    ):
        return None
    return tuple(float(value) for value in values)


def _has_line_of_sight(
    source: tuple[float, float, float],
    target: tuple[float, float, float],
    earth_radius_km: float,
) -> bool:
    direction = tuple(target[index] - source[index] for index in range(3))
    length_squared = sum(value * value for value in direction)
    if length_squared == 0:
        return math.sqrt(sum(value * value for value in source)) > earth_radius_km
    projection = -sum(
        source[index] * direction[index] for index in range(3)
    ) / length_squared
    fraction = min(1.0, max(0.0, projection))
    closest = tuple(
        source[index] + fraction * direction[index] for index in range(3)
    )
    closest_radius = math.sqrt(sum(value * value for value in closest))
    return closest_radius > earth_radius_km


def _snapshot_time(snapshot: dict[str, Any]) -> datetime:
    value = snapshot.get("generated_at")
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _positive_number(value: Any, name: str) -> float:
    result = _non_negative_number(value, name)
    if result == 0:
        raise ContactWindowError(f"{name} deve essere maggiore di zero")
    return result


def _non_negative_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContactWindowError(f"{name} deve essere numerico")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ContactWindowError(f"{name} deve essere finito e non negativo")
    return result
