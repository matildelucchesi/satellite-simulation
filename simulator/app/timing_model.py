"""Modello temporale deterministico per i protocolli di migrazione.

Il modello rappresenta i contributi che in una rete LEO influenzano un
handover: propagazione e processing ISL, serializzazione e trasferimento dello
stato, carico CPU del nodo, avvio del servizio e sincronizzazione finale.
Il rumore gaussiano è piccolo, limitato e riproducibile mediante seed; non è
usato per sostituire i parametri fisici della simulazione.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import math
from random import Random
from typing import Any


class TimingModelError(ValueError):
    """Configurazione del modello temporale non valida."""


@dataclass(frozen=True, slots=True)
class MigrationTimingConfig:
    """Parametri configurabili del modello, espressi in millisecondi e Mbps."""

    enabled: bool = False
    seed: int = 20260726
    base_link_latency_ms: float = 90.0
    distance_latency_ms_per_1000_km: float = 3.0
    link_processing_ms: float = 45.0
    bandwidth_mbps: float = 130.0
    bandwidth_variation_percent: float = 8.0
    base_state_bytes: int = 5_000_000
    per_satellite_state_bytes: int = 180_000
    per_route_state_bytes: int = 5_000
    hot_delta_fraction: float = 0.16
    serialization_throughput_mbps: float = 180.0
    deserialization_throughput_mbps: float = 150.0
    control_processing_ms: float = 55.0
    checkpoint_processing_ms: float = 300.0
    target_processing_ms: float = 130.0
    startup_base_ms: float = 1_000.0
    synchronization_base_ms: float = 350.0
    precopy_synchronization_ms: float = 1_100.0
    cold_target_staging_ms: float = 800.0
    cpu_penalty_factor: float = 0.75
    cpu_variation_percent: float = 4.0
    satellite_cpu_load_percent: dict[str, float] = field(default_factory=dict)
    gaussian_noise_stddev_ms: float = 120.0
    gaussian_noise_limit_ms: float = 300.0

    @classmethod
    def from_dict(cls, payload: Any) -> "MigrationTimingConfig":
        if payload is None:
            return cls()
        if not isinstance(payload, dict):
            raise TimingModelError("timing_model deve essere un oggetto JSON")
        network = _mapping(payload.get("network"), "timing_model.network")
        state = _mapping(payload.get("state"), "timing_model.state")
        processing = _mapping(payload.get("processing"), "timing_model.processing")
        jitter = _mapping(payload.get("jitter"), "timing_model.jitter")
        cpu_profiles = _cpu_profiles(payload.get("satellite_cpu_load_percent", {}))
        defaults = cls()
        enabled = payload.get("enabled", True)
        if not isinstance(enabled, bool):
            raise TimingModelError("timing_model.enabled deve essere booleano")
        seed = payload.get("seed", defaults.seed)
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TimingModelError("timing_model.seed deve essere un intero")
        return cls(
            enabled=enabled,
            seed=seed,
            base_link_latency_ms=_non_negative(network.get("base_link_latency_ms", defaults.base_link_latency_ms), "base_link_latency_ms"),
            distance_latency_ms_per_1000_km=_non_negative(network.get("distance_latency_ms_per_1000_km", defaults.distance_latency_ms_per_1000_km), "distance_latency_ms_per_1000_km"),
            link_processing_ms=_non_negative(network.get("link_processing_ms", defaults.link_processing_ms), "link_processing_ms"),
            bandwidth_mbps=_positive(network.get("bandwidth_mbps", defaults.bandwidth_mbps), "bandwidth_mbps"),
            bandwidth_variation_percent=_non_negative(network.get("bandwidth_variation_percent", defaults.bandwidth_variation_percent), "bandwidth_variation_percent"),
            base_state_bytes=_positive_int(state.get("base_state_bytes", defaults.base_state_bytes), "base_state_bytes"),
            per_satellite_state_bytes=_non_negative_int(state.get("per_satellite_state_bytes", defaults.per_satellite_state_bytes), "per_satellite_state_bytes"),
            per_route_state_bytes=_non_negative_int(state.get("per_route_state_bytes", defaults.per_route_state_bytes), "per_route_state_bytes"),
            hot_delta_fraction=_fraction(state.get("hot_delta_fraction", defaults.hot_delta_fraction), "hot_delta_fraction"),
            serialization_throughput_mbps=_positive(processing.get("serialization_throughput_mbps", defaults.serialization_throughput_mbps), "serialization_throughput_mbps"),
            deserialization_throughput_mbps=_positive(processing.get("deserialization_throughput_mbps", defaults.deserialization_throughput_mbps), "deserialization_throughput_mbps"),
            control_processing_ms=_non_negative(processing.get("control_processing_ms", defaults.control_processing_ms), "control_processing_ms"),
            checkpoint_processing_ms=_non_negative(processing.get("checkpoint_processing_ms", defaults.checkpoint_processing_ms), "checkpoint_processing_ms"),
            target_processing_ms=_non_negative(processing.get("target_processing_ms", defaults.target_processing_ms), "target_processing_ms"),
            startup_base_ms=_non_negative(processing.get("startup_base_ms", defaults.startup_base_ms), "startup_base_ms"),
            synchronization_base_ms=_non_negative(processing.get("synchronization_base_ms", defaults.synchronization_base_ms), "synchronization_base_ms"),
            precopy_synchronization_ms=_non_negative(processing.get("precopy_synchronization_ms", defaults.precopy_synchronization_ms), "precopy_synchronization_ms"),
            cold_target_staging_ms=_non_negative(processing.get("cold_target_staging_ms", defaults.cold_target_staging_ms), "cold_target_staging_ms"),
            cpu_penalty_factor=_non_negative(processing.get("cpu_penalty_factor", defaults.cpu_penalty_factor), "cpu_penalty_factor"),
            cpu_variation_percent=_non_negative(processing.get("cpu_variation_percent", defaults.cpu_variation_percent), "cpu_variation_percent"),
            satellite_cpu_load_percent=cpu_profiles,
            gaussian_noise_stddev_ms=_non_negative(jitter.get("gaussian_noise_stddev_ms", defaults.gaussian_noise_stddev_ms), "gaussian_noise_stddev_ms"),
            gaussian_noise_limit_ms=_non_negative(jitter.get("gaussian_noise_limit_ms", defaults.gaussian_noise_limit_ms), "gaussian_noise_limit_ms"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "seed": self.seed,
            "network": {
                "base_link_latency_ms": self.base_link_latency_ms,
                "distance_latency_ms_per_1000_km": self.distance_latency_ms_per_1000_km,
                "link_processing_ms": self.link_processing_ms,
                "bandwidth_mbps": self.bandwidth_mbps,
                "bandwidth_variation_percent": self.bandwidth_variation_percent,
            },
            "state": {
                "base_state_bytes": self.base_state_bytes,
                "per_satellite_state_bytes": self.per_satellite_state_bytes,
                "per_route_state_bytes": self.per_route_state_bytes,
                "hot_delta_fraction": self.hot_delta_fraction,
            },
            "processing": {
                "serialization_throughput_mbps": self.serialization_throughput_mbps,
                "deserialization_throughput_mbps": self.deserialization_throughput_mbps,
                "control_processing_ms": self.control_processing_ms,
                "checkpoint_processing_ms": self.checkpoint_processing_ms,
                "target_processing_ms": self.target_processing_ms,
                "startup_base_ms": self.startup_base_ms,
                "synchronization_base_ms": self.synchronization_base_ms,
                "precopy_synchronization_ms": self.precopy_synchronization_ms,
                "cold_target_staging_ms": self.cold_target_staging_ms,
                "cpu_penalty_factor": self.cpu_penalty_factor,
                "cpu_variation_percent": self.cpu_variation_percent,
            },
            "satellite_cpu_load_percent": self.satellite_cpu_load_percent,
            "jitter": {
                "gaussian_noise_stddev_ms": self.gaussian_noise_stddev_ms,
                "gaussian_noise_limit_ms": self.gaussian_noise_limit_ms,
            },
        }


class MigrationTimingModel:
    """Produce un piano temporale per una migrazione senza alterarne il protocollo."""

    def __init__(self, config: MigrationTimingConfig) -> None:
        self.config = config

    def plan(self, migration: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
        if not self.config.enabled:
            return {
                "enabled": False,
                "step_delays_ms": {},
                "contribution_totals_ms": {},
                "model_parameters": {},
                "estimated_duration_ms": 0.0,
                "estimated_downtime_ms": 0.0,
            }

        source = str(migration["source_satellite_id"])
        target = str(migration["target_satellite_id"])
        mode = str(migration["mode"])
        sequence = int(migration.get("sequence", 1))
        seed = _stable_seed(self.config.seed, sequence, source, target, mode)
        random = Random(seed)
        distance_km = _distance_km(snapshot, source, target, migration)
        source_cpu = self._cpu_load(source, sequence)
        target_cpu = self._cpu_load(target, sequence)
        source_factor = self._cpu_factor(source_cpu)
        target_factor = self._cpu_factor(target_cpu)
        bandwidth_mbps = self._bandwidth(source, target, sequence)
        state_bytes = self._state_bytes(snapshot)
        delta_bytes = max(1, round(state_bytes * self.config.hot_delta_fraction))
        network_latency_ms = self._network_latency(distance_km)

        # Every duration is decomposed once here.  ``cpu_load_contribution_ms``
        # is deliberately separate from the base operation time so the report
        # can explain the effect of the actual CPU profile without recalculating
        # any part of the migration after it has happened.
        def cpu_component(name: str, base_ms: float, cpu_factor: float) -> dict[str, float]:
            return {
                name: base_ms,
                "cpu_load_contribution_ms": base_ms * (cpu_factor - 1.0),
            }

        def combine(*components: dict[str, float]) -> dict[str, float]:
            combined: dict[str, float] = {}
            for component in components:
                for name, value in component.items():
                    combined[name] = combined.get(name, 0.0) + value
            return combined

        network = {"network_latency_ms": network_latency_ms}

        def control(cpu_factor: float) -> dict[str, float]:
            return combine(network, cpu_component("processing_delay_ms", self.config.control_processing_ms, cpu_factor))

        full_checkpoint = combine(
            network,
            {"serialization_time_ms": _transfer_time_ms(state_bytes, self.config.serialization_throughput_mbps)},
            cpu_component("processing_delay_ms", self.config.checkpoint_processing_ms, source_factor),
        )
        delta_checkpoint = combine(
            network,
            {"serialization_time_ms": _transfer_time_ms(delta_bytes, self.config.serialization_throughput_mbps)},
            cpu_component("processing_delay_ms", self.config.checkpoint_processing_ms, source_factor),
        )
        full_transfer = combine(
            network,
            {"state_transfer_time_ms": _transfer_time_ms(state_bytes, bandwidth_mbps)},
            cpu_component("processing_delay_ms", self.config.target_processing_ms, target_factor),
        )
        delta_transfer = combine(
            network,
            {"state_transfer_time_ms": _transfer_time_ms(delta_bytes, bandwidth_mbps)},
            cpu_component("processing_delay_ms", self.config.target_processing_ms, target_factor),
        )
        full_restore = combine(
            network,
            {"deserialization_time_ms": _transfer_time_ms(state_bytes, self.config.deserialization_throughput_mbps)},
            cpu_component("processing_delay_ms", self.config.target_processing_ms, target_factor),
        )
        delta_restore = combine(
            network,
            {"deserialization_time_ms": _transfer_time_ms(delta_bytes, self.config.deserialization_throughput_mbps)},
            cpu_component("processing_delay_ms", self.config.target_processing_ms, target_factor),
        )
        startup = combine(network, cpu_component("startup_delay_ms", self.config.startup_base_ms, target_factor))
        synchronization = combine(network, cpu_component("synchronization_delay_ms", self.config.synchronization_base_ms, target_factor))
        initial_precopy = combine(
            full_transfer,
            cpu_component("synchronization_delay_ms", self.config.precopy_synchronization_ms, target_factor),
        )
        cold_target_staging = combine(
            control(target_factor),
            cpu_component("synchronization_delay_ms", self.config.cold_target_staging_ms, target_factor),
        )
        steps: dict[str, dict[str, float]] = {
            "request_source_migration": control(source_factor),
            "ensure_target_passive": control(target_factor),
            "prepare_target_for_cold_migration": cold_target_staging,
            "transfer_initial_state_to_target": initial_precopy,
            "quiesce_source_controller": control(source_factor),
            "stop_source_controller": control(source_factor),
            "shutdown_controller": control(source_factor),
            "cold_final_checkpoint": full_checkpoint,
            "initial_checkpoint": full_checkpoint,
            "final_checkpoint": delta_checkpoint,
            "transfer_complete_state_and_wait_target_ack": full_transfer,
            "transfer_final_state_and_wait_target_ack": delta_transfer,
            "transfer_state_and_wait_ack": full_restore if mode == "cold" else delta_restore,
            "start_target_controller": startup,
            "update_controller_host": synchronization,
        }
        active_steps = _protocol_steps(mode)
        raw_total = sum(sum(steps[name].values()) for name in active_steps)
        noise = max(
            -self.config.gaussian_noise_limit_ms,
            min(self.config.gaussian_noise_limit_ms, random.gauss(0.0, self.config.gaussian_noise_stddev_ms)),
        )
        step_delays: dict[str, dict[str, float]] = {}
        for name, contribution in steps.items():
            raw_delay = sum(contribution.values())
            step_noise = (
                noise * raw_delay / raw_total
                if raw_total and name in active_steps
                else 0.0
            )
            step_delays[name] = {
                **{key: round(value, 3) for key, value in contribution.items()},
                "gaussian_noise_ms": round(step_noise, 3),
                "simulated_delay_ms": round(max(1.0, raw_delay + step_noise), 3),
            }
        estimated_duration = sum(step_delays[name]["simulated_delay_ms"] for name in active_steps)
        downtime_start = "stop_source_controller" if mode == "cold" else "quiesce_source_controller"
        downtime_steps = active_steps[active_steps.index(downtime_start) :]
        estimated_downtime = sum(step_delays[name]["simulated_delay_ms"] for name in downtime_steps)
        contribution_totals = _contribution_totals(step_delays, active_steps)
        return {
            "enabled": True,
            "seed": self.config.seed,
            "derived_seed": seed,
            "distance_km": round(distance_km, 3),
            "source_cpu_load_percent": round(source_cpu, 3),
            "target_cpu_load_percent": round(target_cpu, 3),
            "available_bandwidth_mbps": round(bandwidth_mbps, 3),
            "network_latency_ms": round(network_latency_ms, 3),
            "effective_state_bytes": state_bytes,
            "effective_delta_state_bytes": delta_bytes,
            "gaussian_noise_ms": round(noise, 3),
            "model_parameters": self._report_parameters(),
            "contribution_totals_ms": contribution_totals,
            "estimated_duration_ms": round(estimated_duration, 3),
            "estimated_downtime_ms": round(estimated_downtime, 3),
            "step_delays_ms": step_delays,
        }

    def delay_for_step(self, plan: dict[str, Any], step_name: str) -> tuple[float, dict[str, Any]]:
        details = plan.get("step_delays_ms", {}).get(step_name, {})
        delay_ms = details.get("simulated_delay_ms", 0.0)
        return float(delay_ms) / 1000.0, dict(details)

    def _network_latency(self, distance_km: float) -> float:
        return self.config.base_link_latency_ms + self.config.link_processing_ms + self.config.distance_latency_ms_per_1000_km * distance_km / 1000.0

    def _bandwidth(self, source: str, target: str, sequence: int) -> float:
        phase = _stable_seed(self.config.seed, source, target) % 628 / 100.0
        variation = math.sin(phase + sequence * 0.71) * self.config.bandwidth_variation_percent / 100.0
        return self.config.bandwidth_mbps * (1.0 + variation)

    def _cpu_load(self, satellite_id: str, sequence: int) -> float:
        base = self.config.satellite_cpu_load_percent.get(satellite_id, 30.0)
        phase = _stable_seed(self.config.seed, satellite_id) % 628 / 100.0
        return min(95.0, max(0.0, base + math.sin(phase + sequence * 0.53) * self.config.cpu_variation_percent))

    def _cpu_factor(self, load_percent: float) -> float:
        return 1.0 + load_percent / 100.0 * self.config.cpu_penalty_factor

    def _state_bytes(self, snapshot: dict[str, Any]) -> int:
        satellites = snapshot.get("satellites", {})
        links = snapshot.get("physical_links", [])
        satellite_count = len(satellites) if isinstance(satellites, dict) else 0
        route_count = satellite_count * max(0, satellite_count - 1)
        if isinstance(links, list):
            route_count += len(links)
        return self.config.base_state_bytes + satellite_count * self.config.per_satellite_state_bytes + route_count * self.config.per_route_state_bytes

    def _report_parameters(self) -> dict[str, float | int]:
        """Return the model inputs that generated a plan, for audit reports."""
        return {
            "base_link_latency_ms": self.config.base_link_latency_ms,
            "distance_latency_ms_per_1000_km": self.config.distance_latency_ms_per_1000_km,
            "link_processing_ms": self.config.link_processing_ms,
            "serialization_throughput_mbps": self.config.serialization_throughput_mbps,
            "deserialization_throughput_mbps": self.config.deserialization_throughput_mbps,
            "cpu_penalty_factor": self.config.cpu_penalty_factor,
            "gaussian_noise_stddev_ms": self.config.gaussian_noise_stddev_ms,
            "gaussian_noise_limit_ms": self.config.gaussian_noise_limit_ms,
        }


def _protocol_steps(mode: str) -> list[str]:
    if mode == "cold":
        return [
            "request_source_migration", "ensure_target_passive", "prepare_target_for_cold_migration",
            "quiesce_source_controller", "cold_final_checkpoint", "stop_source_controller",
            "shutdown_controller", "transfer_complete_state_and_wait_target_ack",
            "transfer_state_and_wait_ack", "start_target_controller", "update_controller_host",
        ]
    return [
        "initial_checkpoint", "request_source_migration", "ensure_target_passive",
        "transfer_initial_state_to_target", "quiesce_source_controller", "final_checkpoint",
        "transfer_final_state_and_wait_target_ack", "stop_source_controller",
        "transfer_state_and_wait_ack", "start_target_controller", "update_controller_host",
    ]


def _distance_km(snapshot: dict[str, Any], source: str, target: str, migration: dict[str, Any]) -> float:
    recorded = migration.get("contact_window", {}).get("current_distance_km")
    if isinstance(recorded, (int, float)) and math.isfinite(recorded):
        return float(recorded)
    satellites = snapshot.get("satellites", {})
    try:
        source_position = satellites[source]["position_km"]
        target_position = satellites[target]["position_km"]
        return math.dist(
            [float(source_position[key]) for key in ("x", "y", "z")],
            [float(target_position[key]) for key in ("x", "y", "z")],
        )
    except (KeyError, TypeError, ValueError):
        return 0.0


def _transfer_time_ms(size_bytes: int, megabits_per_second: float) -> float:
    return size_bytes * 8.0 / (megabits_per_second * 1_000_000.0) * 1000.0


def _contribution_totals(
    step_delays: dict[str, dict[str, float]], active_steps: list[str]
) -> dict[str, float]:
    """Aggregate the already-calculated active step components for export.

    The report consumes this value directly: it never recomputes timing from
    state, CPU or link inputs.  New contributors are included automatically as
    long as they are stored in a step and are not the derived total itself.
    """
    totals: dict[str, float] = {}
    for name in active_steps:
        for component, value in step_delays[name].items():
            if component != "simulated_delay_ms":
                totals[component] = totals.get(component, 0.0) + value
    return {component: round(value, 3) for component, value in totals.items()}


def _stable_seed(*parts: Any) -> int:
    value = "|".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(sha256(value).digest()[:8], "big")


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TimingModelError(f"{name} deve essere un oggetto JSON")
    return value


def _cpu_profiles(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        raise TimingModelError("satellite_cpu_load_percent deve essere un oggetto JSON")
    return {str(satellite_id).strip().upper(): _non_negative(load, f"cpu {satellite_id}") for satellite_id, load in value.items()}


def _positive(value: Any, name: str) -> float:
    result = _non_negative(value, name)
    if result == 0:
        raise TimingModelError(f"{name} deve essere maggiore di zero")
    return result


def _non_negative(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise TimingModelError(f"{name} deve essere un numero finito non negativo")
    return float(value)


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TimingModelError(f"{name} deve essere un intero positivo")
    return value


def _non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TimingModelError(f"{name} deve essere un intero non negativo")
    return value


def _fraction(value: Any, name: str) -> float:
    result = _positive(value, name)
    if result > 1:
        raise TimingModelError(f"{name} deve essere compreso tra 0 e 1")
    return result
