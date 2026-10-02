"""Abstract recovery decisions for controlled migration failure trials."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecoveryDecision:
    ack_allowed: bool
    sat_b_may_become_active: bool
    action: str
    retry_allowed: bool


def recovery_decision(
    method: str,
    failure: str,
    sat_a_operational: bool,
    attempts_used: int = 1,
    max_attempts: int = 3,
) -> RecoveryDecision:
    """ACK gates the role transfer; cold and hot retain different rollback paths."""
    if method not in {"cold", "hot"}:
        raise ValueError("method must be 'cold' or 'hot'")
    if failure not in {"fso_loss", "no_progress_timeout", "integrity_error", "sat_b_start_failure", "api_restore_failure"}:
        raise ValueError(f"unsupported injected failure: {failure}")
    if max_attempts < 1 or not 1 <= attempts_used <= max_attempts:
        raise ValueError("attempts_used must be between 1 and max_attempts")
    retry = attempts_used < max_attempts
    if method == "hot":
        action = "abort_target_and_keep_sat_a_active_then_retry" if retry else "abort_target_and_keep_sat_a_active"
        return RecoveryDecision(False, False, action, retry)
    if sat_a_operational:
        action = "restart_sat_a_from_local_state_then_retry" if retry else "restart_sat_a_from_local_state_and_abort"
        return RecoveryDecision(False, False, action, retry)
    action = "select_next_eligible_candidate" if retry else "exhausted_attempts_controller_service_unavailable"
    return RecoveryDecision(False, False, action, retry)
