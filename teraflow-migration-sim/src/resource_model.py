"""Deterministic background-load profile and forecast trigger."""

from __future__ import annotations

import math


def reference_horizon_s(slowest_completion_s: float, factor: float = 1.20) -> int:
    if slowest_completion_s <= 0 or factor < 1:
        raise ValueError("completion time must be positive and factor must be >= 1")
    return math.ceil(factor * slowest_completion_s)


def sat_a_load_percent(elapsed_s: float, horizon_s: float, start: float = 55.0, end: float = 85.0) -> float:
    if elapsed_s < 0 or horizon_s <= 0 or not 0 <= start <= 100 or not 0 <= end <= 100:
        raise ValueError("invalid load profile parameters")
    fraction = min(elapsed_s / (2.0 * horizon_s), 1.0)
    return start + (end - start) * fraction


def forecast_crossing_s(current_percent: float, rate_percent_per_s: float, threshold_percent: float) -> float | None:
    if not 0 <= current_percent <= 100 or not 0 <= threshold_percent <= 100 or rate_percent_per_s < 0:
        raise ValueError("invalid forecast parameters")
    if current_percent >= threshold_percent:
        return 0.0
    if rate_percent_per_s == 0:
        return None
    return (threshold_percent - current_percent) / rate_percent_per_s


def resource_trigger(
    elapsed_s: float,
    horizon_s: float,
    threshold_percent: float = 80.0,
    persistence_s: int = 30,
    sample_step_s: int = 1,
    start_percent: float = 55.0,
    end_percent: float = 85.0,
) -> bool:
    """Whether the predicted crossing has persisted for the configured samples."""
    if persistence_s <= 0 or sample_step_s <= 0:
        raise ValueError("persistence and sample step must be positive")
    slope = (end_percent - start_percent) / (2.0 * horizon_s)
    first_sample = max(0, int(elapsed_s / sample_step_s) - math.ceil(persistence_s / sample_step_s) + 1)
    required_samples = math.ceil(persistence_s / sample_step_s)
    for offset in range(required_samples):
        sample_time = (first_sample + offset) * sample_step_s
        load = sat_a_load_percent(sample_time, horizon_s, start_percent, end_percent)
        crossing = forecast_crossing_s(load, slope, threshold_percent)
        if crossing is None or crossing > horizon_s:
            return False
    return True


def eclipse_trigger(time_to_eclipse_s: float, horizon_s: float) -> bool:
    """The eclipse deadline triggers once its predicted lead time enters H."""
    if horizon_s <= 0:
        raise ValueError("horizon_s must be positive")
    return 0 <= time_to_eclipse_s <= horizon_s


def resource_clear_condition(recent_load_percent: list[float], threshold_percent: float = 70.0,
                             persistence_s: int = 60, sample_step_s: int = 1) -> bool:
    """Clear the resource trigger only after a full run of below-threshold samples."""
    if persistence_s <= 0 or sample_step_s <= 0:
        raise ValueError("persistence and sample step must be positive")
    required = math.ceil(persistence_s / sample_step_s)
    if len(recent_load_percent) < required:
        return False
    return all(0 <= value < threshold_percent for value in recent_load_percent[-required:])
