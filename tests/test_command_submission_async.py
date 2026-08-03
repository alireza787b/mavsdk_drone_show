import asyncio
import time
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from command_submission import submit_tracked_command
from command_submission_coordinator import CommandSubmissionCoordinator
from command_execution_policy import (
    mission_requires_launch_armability_probe,
    resolve_mission_type,
)
from command_tracker import CommandTracker
from src.enums import CommandPhase, Mission
from schemas import SubmitCommandRequest
from tests.helpers.fake_fleet_rpc import FakeFleetRPC


def _submission_deps(*, dispatch=None, estimate=None, preparation=None):
    params = SimpleNamespace(
        sim_mode=False,
        GCS_COMMAND_SUBMISSION_CONCURRENCY=4,
        GCS_COMMAND_RECOVERY_SUBMISSION_CONCURRENCY=2,
        GCS_COMMAND_SUBMISSION_SHUTDOWN_GRACE_SEC=0.1,
        GCS_COMMAND_PREPARATION_PROVISIONAL_TIMEOUT_MS=300_000,
    )
    tracker = CommandTracker(max_commands=32, default_timeout_ms=60_000, mission_enum=Mission)
    coordinator = CommandSubmissionCoordinator(params)
    fleet_rpc = FakeFleetRPC(
        dispatch_impl=dispatch,
        preparation_impl=preparation,
    )
    deps = SimpleNamespace(
        Params=params,
        Mission=Mission,
        get_command_tracker=lambda: tracker,
        get_command_submission_coordinator=lambda: coordinator,
        get_fleet_rpc_service=lambda: fleet_rpc,
        load_config=lambda: [{"hw_id": "1", "pos_id": 1, "ip": "127.0.0.1"}],
        load_origin=lambda: None,
        resolve_mission_type=resolve_mission_type,
        mission_requires_launch_armability_probe=mission_requires_launch_armability_probe,
        estimate_command_tracking_timeout_ms=(estimate or (lambda *_args, **_kwargs: 60_000)),
        skybrush_dir="/tmp/skybrush",
        processed_dir="/tmp/processed",
        shapes_dir="/tmp/shapes",
        get_swarm_trajectory_folders=lambda: {"processed": "/tmp/processed"},
        swarm_trajectory_service=SimpleNamespace(
            get_processing_status_payload=lambda: {
                "status": {"processed_drones": [], "follow_map": {}}
            },
            validate_target_scope_for_swarm_trajectory=lambda **_kwargs: [],
        ),
        telemetry_lock=nullcontext(),
        telemetry_data_all_drones={},
        log_system_event=lambda *_args, **_kwargs: None,
        log_system_warning=lambda *_args, **_kwargs: None,
        log_system_error=lambda *_args, **_kwargs: None,
    )
    return deps, tracker, coordinator


async def _wait_for_phase(tracker, command_id, phase, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = await tracker.get_status(command_id)
        if status and status["phase"] == phase:
            return status
        await asyncio.sleep(0.01)
    raise AssertionError(f"command {command_id} did not reach phase {phase}")


@pytest.mark.asyncio
async def test_submit_returns_tracker_id_before_slow_dispatch_completes():
    async def slow_dispatch(*_args, **_kwargs):
        await asyncio.sleep(0.25)
        return {
            "success": 1,
            "offline": 0,
            "rejected": 0,
            "errors": 0,
            "results": {
                "1": {
                    "success": True,
                    "category": "accepted",
                    "delivery_state": "accepted",
                }
            },
        }

    deps, tracker, coordinator = _submission_deps(dispatch=slow_dispatch)
    await coordinator.start()
    command = SubmitCommandRequest(
        mission_type=Mission.HOLD.value,
        trigger_time=0,
        target_drone_ids=["1"],
        idempotency_key="prompt-return",
    )

    started = time.monotonic()
    response = await submit_tracked_command(deps, command)
    elapsed = time.monotonic() - started

    assert elapsed < 0.1
    assert response.command_id
    assert response.accepted_for_tracking is True
    assert response.replayed is False
    assert response.tracking_url == f"/api/v1/commands/{response.command_id}"
    assert "accepted for tracked preparation" in response.message.lower()
    assert {
        "success",
        "status",
        "submitted_count",
        "tracking_phase",
        "tracking_timeout_ms",
        "results_summary",
    }.isdisjoint(response.model_dump())

    status = await _wait_for_phase(
        tracker,
        response.command_id,
        CommandPhase.PENDING_EXECUTION.value,
    )
    assert status["acks"]["accepted"] == 1
    assert status["timeout_at"] > status["created_at"]
    assert status["observed_at"] >= status["updated_at"]
    await coordinator.stop()


@pytest.mark.asyncio
async def test_idempotent_replay_during_preparation_keeps_same_command_id():
    gate = asyncio.Event()

    async def blocked_dispatch(*_args, **_kwargs):
        await gate.wait()
        return {
            "success": 1,
            "offline": 0,
            "rejected": 0,
            "errors": 0,
            "results": {"1": {"success": True, "category": "accepted"}},
        }

    deps, _tracker, coordinator = _submission_deps(dispatch=blocked_dispatch)
    await coordinator.start()
    command = SubmitCommandRequest(
        mission_type=Mission.HOLD.value,
        trigger_time=0,
        target_drone_ids=["1"],
        idempotency_key="same-request",
    )

    first = await submit_tracked_command(deps, command)
    replay = await submit_tracked_command(deps, command)

    assert replay.command_id == first.command_id
    assert replay.accepted_for_tracking is True
    assert replay.replayed is True
    assert replay.tracking_url == first.tracking_url
    gate.set()
    await coordinator.stop()


@pytest.mark.asyncio
async def test_pre_dispatch_background_failure_terminalizes_with_reason():
    def broken_estimate(*_args, **_kwargs):
        raise RuntimeError("show metadata unreadable")

    deps, tracker, coordinator = _submission_deps(estimate=broken_estimate)
    await coordinator.start()
    response = await submit_tracked_command(
        deps,
        SubmitCommandRequest(
            mission_type=Mission.HOLD.value,
            trigger_time=0,
            target_drone_ids=["1"],
            idempotency_key="broken-estimate",
        ),
    )

    status = await _wait_for_phase(
        tracker,
        response.command_id,
        CommandPhase.TERMINAL.value,
    )
    assert status["status"] == "failed"
    assert "show metadata unreadable" in status["error_summary"]
    assert status["acks"]["received"] == 0
    await coordinator.stop()


@pytest.mark.asyncio
async def test_post_submit_orchestration_failure_is_delivery_unknown_not_definite_failure():
    async def broken_dispatch(*_args, **_kwargs):
        raise RuntimeError("transport adapter crashed after submission boundary")

    deps, tracker, coordinator = _submission_deps(dispatch=broken_dispatch)
    await coordinator.start()
    response = await submit_tracked_command(
        deps,
        SubmitCommandRequest(
            mission_type=Mission.HOLD.value,
            trigger_time=0,
            target_drone_ids=["1"],
            idempotency_key="uncertain-dispatch",
        ),
    )

    status = await _wait_for_phase(
        tracker,
        response.command_id,
        CommandPhase.PENDING_EXECUTION.value,
    )
    detail = status["acks"]["details"]["1"]
    assert detail["delivery_state"] == "delivery_unknown"
    assert status["outcome"] is None
    await coordinator.stop()


@pytest.mark.asyncio
async def test_failed_all_target_launch_barrier_sends_zero_command_posts():
    async def blocked_preparation(*_args, **_kwargs):
        return {
            "all_prepared": False,
            "blocked_ids": ["1"],
            "unavailable_ids": [],
            "preparation_tokens": {},
            "results": {
                "1": {
                    "success": False,
                    "ready": False,
                    "summary": "waiting for PX4 armability",
                    "category": "blocked",
                    "prepare_state": "blocked",
                    "error_code": "E202",
                    "error_detail": "PX4 armability",
                    "details": {
                        "observation": {
                            "schema_version": 1,
                            "ready": False,
                            "blockers": ["PX4 armability"],
                        }
                    },
                }
            },
        }

    deps, tracker, coordinator = _submission_deps(preparation=blocked_preparation)
    await coordinator.start()
    response = await submit_tracked_command(
        deps,
        SubmitCommandRequest(
            mission_type=Mission.TAKE_OFF.value,
            trigger_time=0,
            target_drone_ids=["1"],
            idempotency_key="blocked-barrier",
        ),
    )

    status = await _wait_for_phase(
        tracker,
        response.command_id,
        CommandPhase.TERMINAL.value,
    )
    fleet_rpc = deps.get_fleet_rpc_service()
    assert len(fleet_rpc.preparation_calls) == 1
    assert fleet_rpc.dispatch_calls == []
    assert status["preparations"]["blocked"] == 1
    assert status["acks"]["received"] == 0
    assert "not dispatched" in status["error_summary"].lower()
    await coordinator.stop()


@pytest.mark.asyncio
async def test_strict_sync_zero_trigger_is_finalized_only_after_prepare_barrier():
    deps, tracker, coordinator = _submission_deps()
    deps.Params.GCS_FLEET_DISPATCH_DEADLINE_SEC = 2.0
    deps.Params.trigger_sooner_seconds = 1.0
    deps.Params.COMMAND_SYNC_DISPATCH_GUARD_SEC = 1.0
    await coordinator.start()
    response = await submit_tracked_command(
        deps,
        SubmitCommandRequest(
            mission_type=Mission.HOVER_TEST.value,
            trigger_time=0,
            target_drone_ids=["1"],
            idempotency_key="post-barrier-trigger",
        ),
    )

    status = await _wait_for_phase(
        tracker,
        response.command_id,
        CommandPhase.PENDING_EXECUTION.value,
    )
    fleet_rpc = deps.get_fleet_rpc_service()
    assert fleet_rpc.preparation_calls[0]["command_data"]["trigger_time"] == 0
    dispatch = fleet_rpc.dispatch_calls[0]
    committed_trigger = dispatch["command_data"]["trigger_time"]
    assert committed_trigger > int(time.time())
    assert dispatch["launch_preparation_tokens"] == {
        "1": "prepare-1-" + ("x" * 48)
    }
    assert status["params"]["trigger_time"] == committed_trigger
    await coordinator.stop()
