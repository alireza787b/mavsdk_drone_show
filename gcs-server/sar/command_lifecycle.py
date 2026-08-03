"""Durable QuickScout projection of the canonical tracked-command lifecycle.

The generic command tracker remains the source of truth.  This module owns the
small, typed projection QuickScout persists so mission recovery never depends
on transient route responses or ACK-derived mission state.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Mapping, Optional

from schemas import CommandSubmissionReceipt
from sar.schemas import (
    QuickScoutCommandAction,
    QuickScoutCommandBatch,
    QuickScoutCommandLifecycleState,
    QuickScoutCommandTargetState,
    ReturnBehavior,
)


_EXECUTION_TERMINAL_STATES = {
    QuickScoutCommandLifecycleState.COMPLETED,
    QuickScoutCommandLifecycleState.FAILED,
}
_TARGET_TERMINAL_STATES = {
    *_EXECUTION_TERMINAL_STATES,
    QuickScoutCommandLifecycleState.REJECTED,
}


def command_batch_has_unresolved_targets(batch: QuickScoutCommandBatch) -> bool:
    """Return whether any target can still have an execution outcome.

    Aggregate batch state is intentionally not used here: a partially rejected
    submission may still contain accepted or delivery-unknown targets whose
    terminal execution truth has not arrived yet.
    """

    return any(
        target.state not in _TARGET_TERMINAL_STATES
        for target in batch.targets.values()
    )


@dataclass(frozen=True)
class QuickScoutExecutionEvidence:
    """Exact target IDs backed by authenticated tracker execution evidence."""

    started_hw_ids: frozenset[str] = frozenset()
    succeeded_hw_ids: frozenset[str] = frozenset()
    failed_hw_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class QuickScoutCommandProjection:
    """Projected batch plus the execution evidence that may mutate mission state."""

    batch: QuickScoutCommandBatch
    execution: QuickScoutExecutionEvidence = QuickScoutExecutionEvidence()


def _now_ms() -> int:
    return int(time.time() * 1000)


def build_queued_command_batch(
    *,
    action: QuickScoutCommandAction,
    attempt: int,
    receipt: CommandSubmissionReceipt,
    return_behavior: Optional[ReturnBehavior] = None,
    now_ms: Optional[int] = None,
) -> QuickScoutCommandBatch:
    """Create the only valid initial QuickScout state after command submission."""

    timestamp = _now_ms() if now_ms is None else now_ms
    targets = {
        hw_id: QuickScoutCommandTargetState(
            hw_id=hw_id,
            state=QuickScoutCommandLifecycleState.QUEUED,
            message="Queued for tracked command processing.",
            updated_at=timestamp,
        )
        for hw_id in receipt.target_drones
    }
    return QuickScoutCommandBatch(
        action=action,
        attempt=attempt,
        state=QuickScoutCommandLifecycleState.QUEUED,
        receipt=receipt,
        targets=targets,
        return_behavior=return_behavior,
        updated_at=timestamp,
    )


def _target_state(
    previous: QuickScoutCommandTargetState,
    *,
    state: QuickScoutCommandLifecycleState,
    message: Optional[str],
    error_code: Optional[str],
    delivery_state: Optional[str],
    now_ms: int,
) -> QuickScoutCommandTargetState:
    material = {
        "hw_id": previous.hw_id,
        "state": state,
        "message": message,
        "error_code": error_code,
        "delivery_state": delivery_state,
    }
    if previous.model_dump(exclude={"updated_at"}) == material:
        return previous
    return QuickScoutCommandTargetState(**material, updated_at=now_ms)


def _aggregate_state(
    target_states: list[QuickScoutCommandLifecycleState],
) -> QuickScoutCommandLifecycleState:
    if not target_states:
        return QuickScoutCommandLifecycleState.TRACKING_UNAVAILABLE
    unique = set(target_states)
    if len(unique) == 1:
        return target_states[0]

    if unique.issubset(_TARGET_TERMINAL_STATES):
        if unique == {QuickScoutCommandLifecycleState.COMPLETED}:
            return QuickScoutCommandLifecycleState.COMPLETED
        return QuickScoutCommandLifecycleState.FAILED

    # Prefer the most safety-relevant aggregate truth while retaining exact
    # per-target states below it.  In particular, never label a mixed
    # accepted/rejected batch as accepted or retained terminal evidence plus a
    # lost tracker as actively executing.
    if QuickScoutCommandLifecycleState.TRACKING_UNAVAILABLE in unique:
        return QuickScoutCommandLifecycleState.TRACKING_UNAVAILABLE
    if unique.intersection(
        {
            QuickScoutCommandLifecycleState.EXECUTING,
            QuickScoutCommandLifecycleState.COMPLETED,
            QuickScoutCommandLifecycleState.FAILED,
        }
    ):
        return QuickScoutCommandLifecycleState.EXECUTING
    if QuickScoutCommandLifecycleState.DELIVERY_UNKNOWN in unique:
        return QuickScoutCommandLifecycleState.DELIVERY_UNKNOWN
    if QuickScoutCommandLifecycleState.REJECTED in unique:
        return QuickScoutCommandLifecycleState.REJECTED
    if QuickScoutCommandLifecycleState.PREPARING in unique:
        return QuickScoutCommandLifecycleState.PREPARING
    if QuickScoutCommandLifecycleState.AWAITING_ACK in unique:
        return QuickScoutCommandLifecycleState.AWAITING_ACK
    if QuickScoutCommandLifecycleState.QUEUED in unique:
        return QuickScoutCommandLifecycleState.QUEUED
    if QuickScoutCommandLifecycleState.ACCEPTED in unique:
        return QuickScoutCommandLifecycleState.ACCEPTED
    return QuickScoutCommandLifecycleState.FAILED


def _replace_batch(
    batch: QuickScoutCommandBatch,
    *,
    targets: dict[str, QuickScoutCommandTargetState],
    trigger_time: Optional[int],
    timeout_at: Optional[int],
    now_ms: int,
) -> QuickScoutCommandBatch:
    state = _aggregate_state([target.state for target in targets.values()])
    material_changed = (
        state != batch.state
        or targets != batch.targets
        or trigger_time != batch.trigger_time
        or timeout_at != batch.timeout_at
    )
    return batch.model_copy(
        update={
            "state": state,
            "targets": targets,
            "trigger_time": trigger_time,
            "timeout_at": timeout_at,
            "updated_at": now_ms if material_changed else batch.updated_at,
        }
    )


def project_tracking_unavailable(
    batch: QuickScoutCommandBatch,
    *,
    message: str = "The command tracker is currently unavailable.",
    now_ms: Optional[int] = None,
) -> QuickScoutCommandProjection:
    """Represent loss of tracker access without inventing delivery or execution truth."""

    timestamp = _now_ms() if now_ms is None else now_ms
    targets = {}
    for hw_id, previous in batch.targets.items():
        if previous.state in _TARGET_TERMINAL_STATES:
            targets[hw_id] = previous
            continue
        targets[hw_id] = _target_state(
            previous,
            state=QuickScoutCommandLifecycleState.TRACKING_UNAVAILABLE,
            message=message,
            error_code=None,
            delivery_state=None,
            now_ms=timestamp,
        )
    return QuickScoutCommandProjection(
        batch=_replace_batch(
            batch,
            targets=targets,
            trigger_time=batch.trigger_time,
            timeout_at=batch.timeout_at,
            now_ms=timestamp,
        )
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _optional_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized >= 0 else None


def _detail_message(detail: Mapping[str, Any], fallback: str) -> str:
    for key in ("message", "error", "error_detail"):
        value = detail.get(key)
        if value not in (None, ""):
            return str(value)
    return fallback


def project_tracker_status(
    batch: QuickScoutCommandBatch,
    status: Mapping[str, Any],
    *,
    now_ms: Optional[int] = None,
) -> QuickScoutCommandProjection:
    """Project an authoritative tracker snapshot without inferring mission success from ACKs."""

    timestamp = _now_ms() if now_ms is None else now_ms
    if str(status.get("command_id") or "") != batch.receipt.command_id:
        return project_tracking_unavailable(
            batch,
            message="The command tracker returned a mismatched command record.",
            now_ms=timestamp,
        )

    tracker_targets = [str(value) for value in status.get("target_drones") or []]
    if (
        len(tracker_targets) != len(batch.targets)
        or len(set(tracker_targets)) != len(tracker_targets)
        or set(tracker_targets) != set(batch.targets)
    ):
        return project_tracking_unavailable(
            batch,
            message="The command tracker target set no longer matches the queued QuickScout batch.",
            now_ms=timestamp,
        )

    phase = str(status.get("phase") or "")
    outcome = str(status.get("outcome") or "")
    progress = _mapping(status.get("progress"))
    progress_message = str(progress.get("message") or "Tracked command state updated.")
    preparations = _mapping(status.get("preparations"))
    preparation_details = _mapping(preparations.get("details"))
    acks = _mapping(status.get("acks"))
    ack_details = _mapping(acks.get("details"))
    executions = _mapping(status.get("executions"))
    execution_details = _mapping(executions.get("details"))
    execution_starts = {str(value) for value in executions.get("started_hw_ids") or []}
    # ``late_reports`` is deliberately not projected.  The generic command
    # tracker retains it as audit evidence after terminalization; applying it
    # here would silently rewrite QuickScout's already-persisted mission truth.

    succeeded: set[str] = set()
    failed: set[str] = set()
    started: set[str] = set()
    targets: dict[str, QuickScoutCommandTargetState] = {}

    for hw_id, previous in batch.targets.items():
        # Terminal target truth is monotonic.  A contradictory later snapshot
        # requires an explicit operator reconciliation workflow; routine status
        # polling must never rewrite it.
        if previous.state in _TARGET_TERMINAL_STATES:
            targets[hw_id] = previous
            continue

        execution = _mapping(execution_details.get(hw_id))
        if execution:
            success = execution.get("success") is True
            (succeeded if success else failed).add(hw_id)
            started.add(hw_id)
            state = (
                QuickScoutCommandLifecycleState.COMPLETED
                if success
                else QuickScoutCommandLifecycleState.FAILED
            )
            targets[hw_id] = _target_state(
                previous,
                state=state,
                message=_detail_message(
                    execution,
                    "Execution completed successfully." if success else "Command execution failed.",
                ),
                error_code=None,
                delivery_state=None,
                now_ms=timestamp,
            )
            continue

        if hw_id in execution_starts:
            started.add(hw_id)
            targets[hw_id] = _target_state(
                previous,
                state=QuickScoutCommandLifecycleState.EXECUTING,
                message="Authenticated command execution has started.",
                error_code=None,
                delivery_state=None,
                now_ms=timestamp,
            )
            continue

        preparation = _mapping(preparation_details.get(hw_id))
        preparation_state = str(preparation.get("state") or "")
        if preparation_state in {"blocked", "unavailable"}:
            targets[hw_id] = _target_state(
                previous,
                state=QuickScoutCommandLifecycleState.REJECTED,
                message=_detail_message(preparation, "Launch preparation did not pass."),
                error_code=(str(preparation.get("error_code")) if preparation.get("error_code") else None),
                delivery_state=None,
                now_ms=timestamp,
            )
            continue

        ack = _mapping(ack_details.get(hw_id))
        delivery_state = str(ack.get("delivery_state") or "") or None
        category = str(ack.get("category") or ack.get("status") or "")
        if delivery_state == QuickScoutCommandLifecycleState.DELIVERY_UNKNOWN.value:
            targets[hw_id] = _target_state(
                previous,
                state=QuickScoutCommandLifecycleState.DELIVERY_UNKNOWN,
                message=_detail_message(ack, "Command delivery could not be proven."),
                error_code=(str(ack.get("error_code")) if ack.get("error_code") else None),
                delivery_state=delivery_state,
                now_ms=timestamp,
            )
            continue
        if category == "accepted":
            state = QuickScoutCommandLifecycleState.ACCEPTED
            targets[hw_id] = _target_state(
                previous,
                state=state,
                message=_detail_message(ack, "Command delivery was accepted; execution evidence is pending."),
                error_code=None,
                delivery_state=delivery_state,
                now_ms=timestamp,
            )
            continue
        if category in {"offline", "rejected", "error"}:
            targets[hw_id] = _target_state(
                previous,
                state=QuickScoutCommandLifecycleState.REJECTED,
                message=_detail_message(ack, "The target did not accept command delivery."),
                error_code=(str(ack.get("error_code")) if ack.get("error_code") else None),
                delivery_state=delivery_state,
                now_ms=timestamp,
            )
            continue

        if phase == "preparing":
            state = QuickScoutCommandLifecycleState.PREPARING
            message = _detail_message(preparation, progress_message)
        elif phase == "awaiting_ack":
            state = QuickScoutCommandLifecycleState.AWAITING_ACK
            message = progress_message
        elif phase == "terminal" or outcome:
            state = QuickScoutCommandLifecycleState.FAILED
            message = str(status.get("error_summary") or progress_message)
        else:
            state = QuickScoutCommandLifecycleState.AWAITING_ACK
            message = progress_message
        targets[hw_id] = _target_state(
            previous,
            state=state,
            message=message,
            error_code=None,
            delivery_state=None,
            now_ms=timestamp,
        )

    raw_trigger_time = _optional_int(_mapping(status.get("params")).get("trigger_time"))
    trigger_time = raw_trigger_time if raw_trigger_time not in (None, 0) else batch.trigger_time
    timeout_at = _optional_int(status.get("timeout_at"))
    return QuickScoutCommandProjection(
        batch=_replace_batch(
            batch,
            targets=targets,
            trigger_time=trigger_time,
            timeout_at=timeout_at,
            now_ms=timestamp,
        ),
        execution=QuickScoutExecutionEvidence(
            started_hw_ids=frozenset(started),
            succeeded_hw_ids=frozenset(succeeded),
            failed_hw_ids=frozenset(failed),
        ),
    )


__all__ = [
    "QuickScoutCommandProjection",
    "QuickScoutExecutionEvidence",
    "build_queued_command_batch",
    "command_batch_has_unresolved_targets",
    "project_tracker_status",
    "project_tracking_unavailable",
]
