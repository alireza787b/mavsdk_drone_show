"""Restart-safety contract tests for the generic tracked-command lifecycle."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import stat
from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api_routes.commands import create_command_router
from command_execution_policy import (
    mission_requires_launch_armability_probe,
    resolve_mission_type,
)
from command_journal import CALLBACK_KEY_FILENAME, DATABASE_FILENAME
from command_tracker import CommandCompletionAuthority, CommandTracker
from src.enums import CommandPhase, Mission
from tests.helpers.command_submission import DeferredSubmissionCoordinator
from tests.helpers.fake_fleet_rpc import FakeFleetRPC


def _deps(tracker: CommandTracker):
    coordinator = DeferredSubmissionCoordinator()
    fleet_rpc = FakeFleetRPC()
    params = SimpleNamespace(
        sim_mode=False,
        GCS_COMMAND_PREPARATION_PROVISIONAL_TIMEOUT_MS=300_000,
    )
    deps = SimpleNamespace(
        Params=params,
        Mission=Mission,
        current_tracker=tracker,
        command_submission_coordinator=coordinator,
        fleet_rpc=fleet_rpc,
        load_config=lambda: [{"hw_id": "1", "pos_id": 1, "ip": "127.0.0.1"}],
        load_origin=lambda: None,
        resolve_mission_type=resolve_mission_type,
        mission_requires_launch_armability_probe=mission_requires_launch_armability_probe,
        estimate_command_tracking_timeout_ms=lambda *_args, **_kwargs: 60_000,
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
    deps.get_command_tracker = lambda: deps.current_tracker
    deps.get_command_submission_coordinator = lambda: deps.command_submission_coordinator
    deps.get_fleet_rpc_service = lambda: deps.fleet_rpc
    return deps


def _command_app(deps) -> FastAPI:
    app = FastAPI()
    app.include_router(create_command_router(deps))
    return app


def _hold_payload(idempotency_key: str) -> dict:
    return {
        "mission_type": Mission.HOLD.value,
        "trigger_time": 0,
        "target_drone_ids": ["1"],
        "idempotency_key": idempotency_key,
    }


def test_http_202_command_remains_queryable_after_restart(tmp_path):
    state_dir = tmp_path / "command-state"
    first_tracker = CommandTracker(state_dir=str(state_dir))
    first_deps = _deps(first_tracker)
    with TestClient(_command_app(first_deps)) as client:
        submitted = client.post(
            "/api/v1/commands",
            json=_hold_payload("restart-after-202"),
        )

    assert submitted.status_code == 202
    command_id = submitted.json()["command_id"]
    assert first_deps.fleet_rpc.dispatch_calls == []
    first_tracker.close()  # Simulate process loss before its queued task runs.

    restored_tracker = CommandTracker(state_dir=str(state_dir))
    reconciliation = asyncio.run(restored_tracker.reconcile_after_restart())
    restored_deps = _deps(restored_tracker)
    with TestClient(_command_app(restored_deps)) as client:
        restored = client.get(f"/api/v1/commands/{command_id}")

    assert reconciliation["failed_before_dispatch"] == 1
    assert restored.status_code == 200
    assert restored.json()["command_id"] == command_id
    assert restored.json()["phase"] == CommandPhase.TERMINAL.value
    assert "dispatch had not begun" in restored.json()["error_summary"]
    restored_tracker.close()


@pytest.mark.asyncio
async def test_callback_capability_remains_valid_after_restart(tmp_path):
    state_dir = tmp_path / "command-state"
    first_tracker = CommandTracker(state_dir=str(state_dir))
    command_id = await first_tracker.create_command(
        mission_type=Mission.HOLD.value,
        target_drones=["1"],
    )
    capability = (await first_tracker.get_callback_capabilities(command_id))["1"]
    assert await first_tracker.mark_submitted(command_id) is True
    assert await first_tracker.record_ack(
        command_id,
        "1",
        category="accepted",
        delivery_state="accepted",
    ) is True
    first_tracker.close()

    restored_tracker = CommandTracker(state_dir=str(state_dir))
    await restored_tracker.reconcile_after_restart()
    assert await restored_tracker.record_execution_start(
        command_id,
        "1",
        callback_capability=capability,
    ) is True
    assert await restored_tracker.record_execution(
        command_id,
        "1",
        True,
        outcome="completed",
        callback_capability=capability,
    ) is True
    status = await restored_tracker.get_status(command_id)
    assert status["outcome"] == "completed"
    assert status["executions"]["details"]["1"]["outcome"] == "completed"
    restored_tracker.close()

    final_tracker = CommandTracker(state_dir=str(state_dir))
    restored_status = await final_tracker.get_status(command_id)
    assert restored_status["outcome"] == "completed"
    assert restored_status["executions"]["details"]["1"]["outcome"] == "completed"

    key_payload = json.loads(
        (state_dir / CALLBACK_KEY_FILENAME).read_text(encoding="utf-8")
    )
    assert key_payload["version"] == 1
    assert key_payload["key_id"]
    assert stat.S_IMODE((state_dir / CALLBACK_KEY_FILENAME).stat().st_mode) == 0o600
    final_tracker.close()


def test_idempotency_replay_after_restart_never_redispatches(tmp_path):
    state_dir = tmp_path / "command-state"
    payload = _hold_payload("lost-http-response-retry")
    first_tracker = CommandTracker(state_dir=str(state_dir))
    first_deps = _deps(first_tracker)
    with TestClient(_command_app(first_deps)) as client:
        first = client.post("/api/v1/commands", json=payload)
    assert first.status_code == 202
    command_id = first.json()["command_id"]
    first_tracker.close()

    restored_tracker = CommandTracker(state_dir=str(state_dir))
    asyncio.run(restored_tracker.reconcile_after_restart())
    restored_deps = _deps(restored_tracker)
    with TestClient(_command_app(restored_deps)) as client:
        replay = client.post("/api/v1/commands", json=payload)

    assert replay.status_code == 202
    assert replay.json()["command_id"] == command_id
    assert replay.json()["replayed"] is True
    assert restored_deps.command_submission_coordinator.operations == {}
    assert restored_deps.fleet_rpc.dispatch_calls == []
    restored_tracker.close()


@pytest.mark.asyncio
async def test_restart_mid_fanout_marks_only_missing_targets_delivery_unknown(tmp_path):
    state_dir = tmp_path / "command-state"
    first_tracker = CommandTracker(state_dir=str(state_dir))
    creation = await first_tracker.create_or_replay_command(
        mission_type=Mission.HOLD.value,
        target_drones=["1", "2", "3"],
        idempotency_key="mid-fanout",
        request_fingerprint="same-payload",
        start_preparing=True,
    )
    capabilities = await first_tracker.get_callback_capabilities(creation.command_id)
    assert await first_tracker.mark_submitted(creation.command_id) is True
    assert await first_tracker.record_ack(
        creation.command_id,
        "1",
        category="accepted",
        delivery_state="accepted",
    ) is True
    first_tracker.close()

    restored_tracker = CommandTracker(state_dir=str(state_dir))
    reconciliation = await restored_tracker.reconcile_after_restart()
    status = await restored_tracker.get_status(creation.command_id)

    assert reconciliation["delivery_unknown_targets"] == 2
    assert status["acks"]["details"]["1"]["delivery_state"] == "accepted"
    assert status["acks"]["details"]["2"]["delivery_state"] == "delivery_unknown"
    assert status["acks"]["details"]["3"]["delivery_state"] == "delivery_unknown"
    assert status["phase"] == CommandPhase.PENDING_EXECUTION.value
    assert await restored_tracker.record_execution_start(
        creation.command_id,
        "2",
        callback_capability=capabilities["2"],
    ) is True
    promoted = await restored_tracker.get_status(creation.command_id)
    assert promoted["acks"]["details"]["2"]["delivery_state"] == "accepted_via_execution"

    with sqlite3.connect(state_dir / DATABASE_FILENAME) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        event_types = {
            row[0]
            for row in connection.execute(
                "SELECT event_type FROM command_events WHERE command_id=?",
                (creation.command_id,),
            )
        }
    assert {"commands", "command_targets", "command_events"}.issubset(tables)
    assert "restart_delivery_reconciled" in event_types
    restored_tracker.close()


@pytest.mark.asyncio
async def test_postcondition_authority_and_node_diagnostics_survive_restart(tmp_path):
    """Journal restoration must preserve both terminal truth and conflicting node evidence."""

    state_dir = tmp_path / "command-state"
    first_tracker = CommandTracker(state_dir=str(state_dir))
    creation = await first_tracker.create_or_replay_command(
        mission_type=Mission.UPDATE_CODE.value,
        target_drones=["1", "2"],
        completion_authority=CommandCompletionAuthority.FLEET_GIT_POSTCONDITION,
    )
    capabilities = await first_tracker.get_callback_capabilities(creation.command_id)
    assert await first_tracker.mark_submitted(creation.command_id) is True
    for hw_id in ("1", "2"):
        assert await first_tracker.record_ack(
            creation.command_id,
            hw_id,
            category="accepted",
        ) is True

    assert await first_tracker.record_execution(
        creation.command_id,
        "1",
        False,
        error_message="legacy callback lost its restart response",
        callback_capability=capabilities["1"],
    ) is True
    assert await first_tracker.record_authoritative_completion(
        creation.command_id,
        {
            "1": {"success": True},
            "2": {"success": False, "error_message": "runtime commit did not load"},
        },
        completion_authority=CommandCompletionAuthority.FLEET_GIT_POSTCONDITION,
        callback_capabilities=capabilities,
    ) is True
    first_tracker.close()

    restored_tracker = CommandTracker(state_dir=str(state_dir))
    status = await restored_tracker.get_status(creation.command_id)
    serialized = json.dumps(status)

    assert status["completion_authority"] == "fleet_git_postcondition"
    assert status["status"] == "partial"
    assert status["phase"] == "terminal"
    assert status["outcome"] == "partial"
    assert status["executions"]["details"]["1"]["success"] is True
    assert status["executions"]["details"]["2"]["success"] is False
    assert status["node_execution_reports"]["details"]["1"]["success"] is False
    assert "1" in status["completion_discrepancies"]
    assert capabilities["1"] not in serialized
    assert capabilities["2"] not in serialized
    assert "callback_capability" not in serialized
    restored_tracker.close()
