"""Deterministic migration timing model; byte and timing inputs must be measured."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Workload:
    image_bytes: int
    cold_state_bytes: int
    hot_initial_state_bytes: int
    hot_final_delta_bytes: int
    cold_snapshot_s: float
    hot_freeze_s: float
    hot_delta_apply_s: float
    controller_startup_s: float
    api_restore_s: float
    api_verification_s: float
    ack_cutover_s: float


@dataclass(frozen=True)
class MigrationCase:
    method: str
    useful_rate_bps: int
    alignment_s: float
    transfer_bytes: int
    transfer_s: float
    total_operation_s: float
    controller_downtime_s: float
    contact_window_s: float
    deadline_window_s: float
    completes_in_contact: bool
    completes_before_deadline: bool
    orbital_margin_s: float
    migration_margin_s: float


def validate_workload(workload: Workload) -> None:
    for name, value in asdict(workload).items():
        if value < 0:
            raise ValueError(f"{name} must be non-negative")
    if workload.image_bytes == 0:
        raise ValueError("image_bytes must be measured and greater than zero")
    if workload.cold_state_bytes == 0 or workload.hot_initial_state_bytes == 0:
        raise ValueError("cold and hot initial state sizes must be measured and greater than zero")


def evaluate(
    workload: Workload,
    method: str,
    useful_rate_bps: int,
    alignment_s: float,
    contact_window_s: float,
    deadline_window_s: float,
) -> MigrationCase:
    """Evaluate cold or hot timing using measured workload payload and runtimes.

    The alignment interval consumes contact time. M_orbital is contact/deadline
    time left after alignment. M_migration subtracts payload transfer, restore,
    verification and cutover remaining in that post-alignment interval.
    """
    validate_workload(workload)
    if method not in {"cold", "hot"}:
        raise ValueError("method must be 'cold' or 'hot'")
    if useful_rate_bps <= 0 or alignment_s < 0 or contact_window_s < 0 or deadline_window_s < 0:
        raise ValueError("rates must be positive and durations non-negative")

    if method == "cold":
        transfer_bytes = workload.image_bytes + workload.cold_state_bytes
        transfer_s = transfer_bytes * 8 / useful_rate_bps
        after_alignment = (
            workload.cold_snapshot_s + transfer_s + workload.controller_startup_s
            + workload.api_restore_s + workload.api_verification_s + workload.ack_cutover_s
        )
        total = alignment_s + after_alignment
        # The source controller stops after snapshot and before transfer.
        downtime = transfer_s + workload.controller_startup_s + workload.api_restore_s + workload.api_verification_s + workload.ack_cutover_s
        post_align_non_transfer = after_alignment - transfer_s
    else:
        transfer_bytes = workload.image_bytes + workload.hot_initial_state_bytes + workload.hot_final_delta_bytes
        initial_transfer_s = (workload.image_bytes + workload.hot_initial_state_bytes) * 8 / useful_rate_bps
        delta_transfer_s = workload.hot_final_delta_bytes * 8 / useful_rate_bps
        transfer_s = initial_transfer_s + delta_transfer_s
        after_alignment = (
            initial_transfer_s + workload.controller_startup_s + workload.api_restore_s
            + workload.hot_freeze_s + delta_transfer_s
            + workload.hot_delta_apply_s + workload.api_verification_s + workload.ack_cutover_s
        )
        total = alignment_s + after_alignment
        downtime = workload.hot_freeze_s + delta_transfer_s + workload.hot_delta_apply_s + workload.api_verification_s + workload.ack_cutover_s
        post_align_non_transfer = after_alignment - transfer_s

    available = min(contact_window_s, deadline_window_s)
    orbital_margin = available - alignment_s
    migration_margin = orbital_margin - transfer_s - post_align_non_transfer
    return MigrationCase(
        method=method,
        useful_rate_bps=useful_rate_bps,
        alignment_s=alignment_s,
        transfer_bytes=transfer_bytes,
        transfer_s=transfer_s,
        total_operation_s=total,
        controller_downtime_s=downtime,
        contact_window_s=contact_window_s,
        deadline_window_s=deadline_window_s,
        completes_in_contact=total <= contact_window_s,
        completes_before_deadline=total <= deadline_window_s,
        orbital_margin_s=orbital_margin,
        migration_margin_s=migration_margin,
    )
