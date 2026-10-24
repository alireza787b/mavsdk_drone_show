"""Keep exact bounded action observations through authenticated reporting."""
import pytest
from pydantic import ValidationError

from command_tracker import CommandTracker
from schemas import ExecutionReportRequest
from src.enums import Mission
from src.execution_evidence import ActionResultEvidence


def failed_action():
    return {
        "schema_version": 1, "success": False,
        "code": "TAKEOFF_REQUIRES_SAFE_GROUND_STATE", "phase": "precondition",
        "operator_message": "PX4 reports IN_AIR", "retryable": True,
        "evidence": {"failed_checks": ["on_ground"]},
        "final_vehicle_state": {"armed": False, "landed_state": "IN_AIR", "relative_altitude_m": -4.2},
    }


def test_evidence_uses_existing_bounded_terminal_contract():
    assert ActionResultEvidence.model_validate(failed_action()).final_vehicle_state["relative_altitude_m"] == -4.2
    oversized = failed_action()
    oversized["evidence"] = {"unbounded": "x" * 5000}
    with pytest.raises(ValidationError):
        ActionResultEvidence.model_validate(oversized)


@pytest.mark.parametrize("key,value", [("hw_id", "2"), ("command_id", "old")])
def test_release_identity_must_match_callback(key, value):
    release = {"command_id": "current", "ownership_token": "owner", "hw_id": "1",
        "producers_stopped": True, "offboard_stop_completed": True,
        "hold_accepted": True, "external_control_preserved": False}
    release[key] = value
    with pytest.raises(ValidationError):
        ExecutionReportRequest(command_id="current", hw_id="1", success=False,
            outcome="superseded", control_release=release)


@pytest.mark.asyncio
async def test_exact_action_evidence_survives_tracker_and_restart(tmp_path):
    tracker = CommandTracker(state_dir=str(tmp_path))
    created = await tracker.create_or_replay_command(mission_type=Mission.TAKE_OFF.value, target_drones=["1"])
    capabilities = await tracker.get_callback_capabilities(created.command_id)
    await tracker.mark_submitted(created.command_id)
    await tracker.record_ack(created.command_id, "1", category="accepted")
    await tracker.record_execution(created.command_id, "1", False,
        error_message="PX4 reports IN_AIR", action_result=failed_action(),
        callback_capability=capabilities["1"])
    detail = (await tracker.get_status(created.command_id))["executions"]["details"]["1"]
    assert detail["action_result"] == failed_action()
    tracker.close()
    restored = CommandTracker(state_dir=str(tmp_path))
    try:
        detail = (await restored.get_status(created.command_id))["executions"]["details"]["1"]
        assert detail["action_result"]["final_vehicle_state"]["landed_state"] == "IN_AIR"
        assert detail["action_result"]["evidence"]["failed_checks"] == ["on_ground"]
    finally:
        restored.close()


@pytest.mark.asyncio
async def test_hold_fences_older_unstarted_launch_without_touching_newer_intent():
    tracker = CommandTracker()
    try:
        old = await tracker.create_or_replay_command(mission_type=Mission.TAKE_OFF.value, target_drones=["1"])
        hold = await tracker.create_or_replay_command(mission_type=Mission.HOLD.value, target_drones=["1"])
        newer = await tracker.create_or_replay_command(mission_type=Mission.TAKE_OFF.value, target_drones=["1"])
        assert await tracker.supersede_pending_flight_commands(hold.command_id, ["1"]) == 1
        assert (await tracker.get_status(old.command_id))["outcome"] == "superseded"
        assert await tracker.mark_submitted(old.command_id) is False
        assert (await tracker.get_status(newer.command_id))["phase"] != "terminal"
    finally:
        tracker.close()
