from pydantic import ValidationError
import pytest

from schemas import CommandSubmissionReceipt
from src.enums import Mission
from sar.command_lifecycle import (
    build_queued_command_batch,
    command_batch_has_unresolved_targets,
    project_tracker_status,
    project_tracking_unavailable,
)
from sar.schemas import (
    QuickScoutCommandAction,
    QuickScoutCommandLifecycleState,
)


def _receipt(targets=None):
    target_drones = targets or ["1", "2"]
    return CommandSubmissionReceipt(
        command_id="command-1",
        idempotency_key="quickscout:mission-1:launch:1",
        replayed=False,
        mission_type=Mission.QUICKSCOUT.value,
        mission_name="QUICKSCOUT",
        target_drones=target_drones,
        tracking_url="/api/v1/commands/command-1",
        message="Tracked command queued.",
        timestamp=1_700_000_000_000,
    )


def _status(**overrides):
    payload = {
        "command_id": "command-1",
        "target_drones": ["1", "2"],
        "params": {"trigger_time": 1_700_000_005},
        "phase": "pending_execution",
        "outcome": None,
        "timeout_at": 1_700_000_120_000,
        "preparations": {"details": {}},
        "acks": {
            "details": {
                "1": {"category": "accepted", "delivery_state": "accepted"},
                "2": {"category": "accepted", "delivery_state": "accepted"},
            }
        },
        "executions": {"started_hw_ids": [], "details": {}},
        "late_reports": {
            "acks": {"details": {}},
            "execution_starts": {"details": {}},
            "executions": {"details": {}},
        },
        "progress": {"message": "Waiting for execution evidence."},
        "error_summary": None,
    }
    payload.update(overrides)
    return payload


def _batch():
    return build_queued_command_batch(
        action=QuickScoutCommandAction.LAUNCH,
        attempt=1,
        receipt=_receipt(),
        now_ms=1_700_000_000_000,
    )


def test_ack_projection_persists_shared_schedule_without_execution_evidence():
    projection = project_tracker_status(
        _batch(),
        _status(),
        now_ms=1_700_000_001_000,
    )

    assert projection.batch.state == QuickScoutCommandLifecycleState.ACCEPTED
    assert projection.batch.trigger_time == 1_700_000_005
    assert projection.batch.timeout_at == 1_700_000_120_000
    assert all(
        target.state == QuickScoutCommandLifecycleState.ACCEPTED
        for target in projection.batch.targets.values()
    )
    assert projection.execution.started_hw_ids == frozenset()
    assert projection.execution.succeeded_hw_ids == frozenset()


def test_projection_preserves_exact_partial_execution_truth():
    started = project_tracker_status(
        _batch(),
        _status(
            phase="in_progress",
            executions={"started_hw_ids": ["1"], "details": {}},
        ),
        now_ms=1_700_000_001_000,
    )

    assert started.batch.state == QuickScoutCommandLifecycleState.EXECUTING
    assert started.batch.targets["1"].state == QuickScoutCommandLifecycleState.EXECUTING
    assert started.batch.targets["2"].state == QuickScoutCommandLifecycleState.ACCEPTED
    assert started.execution.started_hw_ids == frozenset({"1"})

    finished = project_tracker_status(
        started.batch,
        _status(
            phase="terminal",
            outcome="partial",
            executions={
                "started_hw_ids": ["1", "2"],
                "details": {
                    "1": {"success": True, "timestamp": 1_700_000_002_000},
                    "2": {
                        "success": False,
                        "error": "runtime failure",
                        "timestamp": 1_700_000_002_000,
                    },
                },
            },
        ),
        now_ms=1_700_000_002_000,
    )

    assert finished.batch.state == QuickScoutCommandLifecycleState.FAILED
    assert finished.batch.targets["1"].state == QuickScoutCommandLifecycleState.COMPLETED
    assert finished.batch.targets["2"].state == QuickScoutCommandLifecycleState.FAILED
    assert finished.execution.succeeded_hw_ids == frozenset({"1"})
    assert finished.execution.failed_hw_ids == frozenset({"2"})


def test_projection_distinguishes_delivery_unknown_from_definite_rejection():
    projection = project_tracker_status(
        _batch(),
        _status(
            phase="terminal",
            outcome="failed",
            acks={
                "details": {
                    "1": {
                        "category": "error",
                        "delivery_state": "delivery_unknown",
                        "message": "Connection closed after dispatch.",
                    },
                    "2": {
                        "category": "rejected",
                        "delivery_state": "rejected",
                        "message": "Aircraft rejected the command.",
                    },
                }
            },
        ),
        now_ms=1_700_000_001_000,
    )

    assert projection.batch.state == QuickScoutCommandLifecycleState.DELIVERY_UNKNOWN
    assert projection.batch.targets["1"].state == QuickScoutCommandLifecycleState.DELIVERY_UNKNOWN
    assert projection.batch.targets["2"].state == QuickScoutCommandLifecycleState.REJECTED
    assert projection.execution.started_hw_ids == frozenset()


def test_tracker_unavailable_does_not_erase_terminal_execution_truth():
    completed = project_tracker_status(
        _batch(),
        _status(
            phase="terminal",
            outcome="partial",
            executions={
                "started_hw_ids": ["1"],
                "details": {"1": {"success": True, "timestamp": 1_700_000_001_000}},
            },
            acks={
                "details": {
                    "1": {"category": "accepted", "delivery_state": "accepted"},
                    "2": {"category": "accepted", "delivery_state": "accepted"},
                }
            },
        ),
        now_ms=1_700_000_001_000,
    ).batch

    unavailable = project_tracking_unavailable(completed, now_ms=1_700_000_002_000).batch

    assert unavailable.targets["1"].state == QuickScoutCommandLifecycleState.COMPLETED
    assert unavailable.targets["2"].state == QuickScoutCommandLifecycleState.TRACKING_UNAVAILABLE
    assert unavailable.state == QuickScoutCommandLifecycleState.TRACKING_UNAVAILABLE


def test_mixed_acceptance_and_rejection_never_aggregates_as_accepted():
    projection = project_tracker_status(
        _batch(),
        _status(
            phase="terminal",
            outcome="failed",
            acks={
                "details": {
                    "1": {"category": "accepted", "delivery_state": "accepted"},
                    "2": {"category": "rejected", "delivery_state": "rejected"},
                }
            },
        ),
        now_ms=1_700_000_001_000,
    )

    assert projection.batch.state == QuickScoutCommandLifecycleState.REJECTED
    assert projection.batch.targets["1"].state == QuickScoutCommandLifecycleState.ACCEPTED
    assert projection.batch.targets["2"].state == QuickScoutCommandLifecycleState.REJECTED
    assert command_batch_has_unresolved_targets(projection.batch) is True
    from sar.service import QuickScoutService

    assert QuickScoutService._command_is_pending(projection.batch) is True


def test_command_batch_accepts_reordered_json_map_with_same_target_set():
    batch = _batch()
    payload = batch.model_dump(mode="python")
    payload["targets"] = {"2": payload["targets"]["2"], "1": payload["targets"]["1"]}

    restored = type(batch).model_validate(payload)

    assert set(restored.targets) == {"1", "2"}


def test_command_batch_rejects_target_identity_drift():
    batch = _batch()
    payload = batch.model_dump(mode="python")
    payload["targets"] = {"1": payload["targets"]["1"]}

    with pytest.raises(ValidationError, match="exactly match the receipt target set"):
        type(batch).model_validate(payload)


def test_command_batch_rejects_duplicate_receipt_targets():
    with pytest.raises(ValidationError, match="target_drones must be unique"):
        build_queued_command_batch(
            action=QuickScoutCommandAction.LAUNCH,
            attempt=1,
            receipt=_receipt(["1", "1"]),
            now_ms=1_700_000_000_000,
        )


def test_tracker_target_identity_is_set_based_for_numeric_looking_hardware_ids():
    target_ids = ["1", "2", "10", "100"]
    batch = build_queued_command_batch(
        action=QuickScoutCommandAction.LAUNCH,
        attempt=1,
        receipt=_receipt(target_ids),
        now_ms=1_700_000_000_000,
    )
    status = _status(
        target_drones=["100", "10", "2", "1"],
        acks={
            "details": {
                hw_id: {"category": "accepted", "delivery_state": "accepted"}
                for hw_id in target_ids
            }
        },
    )

    projection = project_tracker_status(batch, status, now_ms=1_700_000_001_000)

    assert projection.batch.state == QuickScoutCommandLifecycleState.ACCEPTED
    assert set(projection.batch.targets) == set(target_ids)


def test_late_reports_are_audit_only_and_do_not_rewrite_terminal_truth():
    rejected = project_tracker_status(
        _batch(),
        _status(
            phase="terminal",
            outcome="failed",
            acks={
                "details": {
                    "1": {"category": "rejected", "delivery_state": "rejected"},
                    "2": {"category": "rejected", "delivery_state": "rejected"},
                }
            },
            late_reports={
                "acks": {"details": {}},
                "execution_starts": {"details": {"1": {"timestamp": 1_700_000_002_000}}},
                "executions": {
                    "details": {
                        "1": {"success": True, "timestamp": 1_700_000_003_000},
                    }
                },
            },
        ),
        now_ms=1_700_000_004_000,
    )

    assert rejected.execution.started_hw_ids == frozenset()
    assert rejected.execution.succeeded_hw_ids == frozenset()
    assert rejected.batch.targets["1"].state == QuickScoutCommandLifecycleState.REJECTED
    assert rejected.batch.targets["2"].state == QuickScoutCommandLifecycleState.REJECTED
    assert command_batch_has_unresolved_targets(rejected.batch) is False


def test_terminal_target_truth_is_monotonic_during_routine_reconciliation():
    completed = project_tracker_status(
        _batch(),
        _status(
            phase="terminal",
            outcome="succeeded",
            executions={
                "started_hw_ids": ["1", "2"],
                "details": {
                    "1": {"success": True},
                    "2": {"success": True},
                },
            },
        ),
        now_ms=1_700_000_001_000,
    ).batch

    contradictory = project_tracker_status(
        completed,
        _status(
            phase="terminal",
            outcome="failed",
            executions={
                "started_hw_ids": ["1", "2"],
                "details": {
                    "1": {"success": False, "error": "late contradiction"},
                    "2": {"success": False, "error": "late contradiction"},
                },
            },
        ),
        now_ms=1_700_000_002_000,
    )

    assert all(
        target.state == QuickScoutCommandLifecycleState.COMPLETED
        for target in contradictory.batch.targets.values()
    )
    assert contradictory.execution.failed_hw_ids == frozenset()
