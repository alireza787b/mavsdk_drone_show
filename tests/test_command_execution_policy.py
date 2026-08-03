from types import SimpleNamespace

import pytest

from command_execution_policy import (
    CommandSubmissionAuthority,
    CommandSubmissionPolicyError,
    StrictSyncTimingError,
    enforce_command_submission_policy,
    mission_is_recovery,
    resolve_strict_sync_trigger_time,
)
from schemas import SubmitCommandRequest
from src.enums import Mission


def _params(**overrides):
    values = {
        "sim_mode": True,
        "GCS_FLEET_DISPATCH_DEADLINE_SEC": 15.0,
        "trigger_sooner_seconds": 4.0,
        "COMMAND_SYNC_DISPATCH_GUARD_SEC": 1.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_immediate_strict_sync_resolves_one_bounded_post_barrier_trigger():
    trigger = resolve_strict_sync_trigger_time(
        Mission.DRONE_SHOW_FROM_CSV,
        requested_trigger_time=0,
        params=_params(),
        now=100.0,
    )

    assert trigger == 122


def test_explicit_strict_sync_trigger_fails_closed_when_fanout_window_is_too_short():
    with pytest.raises(StrictSyncTimingError, match="Earliest safe trigger_time is 122"):
        resolve_strict_sync_trigger_time(
            Mission.QUICKSCOUT,
            requested_trigger_time=121,
            params=_params(),
            now=100.0,
        )


def test_non_strict_recovery_trigger_is_not_rewritten():
    assert resolve_strict_sync_trigger_time(
        Mission.LAND,
        requested_trigger_time=0,
        params=_params(),
        now=100.0,
    ) == 0


def test_ground_test_is_immediate_only_even_with_valid_sitl_acknowledgement():
    request = SubmitCommandRequest(
        mission_type=Mission.TEST.value,
        trigger_time=200,
        target_drone_ids=["1"],
        ground_test_safety={"mode": "sitl_not_applicable"},
    )

    with pytest.raises(CommandSubmissionPolicyError, match="immediate-only"):
        enforce_command_submission_policy(
            Mission.TEST,
            request,
            params=_params(),
            authority=CommandSubmissionAuthority.OPERATOR_COMMAND,
        )


def test_cancel_mission_uses_reserved_recovery_capacity():
    assert mission_is_recovery(Mission.NONE) is True
