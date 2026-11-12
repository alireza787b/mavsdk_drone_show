import argparse
import time

import pytest
from tools import validate_actions_runtime as validator

from tools.validate_actions_runtime import (
    _is_safe_interrupted_terminal_status,
    _is_idle_baseline_row,
    _is_hold_ready_row,
    _is_idle_reset_row,
    _telemetry_has_ids,
    choose_override_targets,
    resolve_selected_ids,
)


def test_telemetry_has_ids_requires_full_selected_fleet():
    assert _telemetry_has_ids({"1": {}, "2": {}, "3": {}}, [1, 2, 3]) is True
    assert _telemetry_has_ids({"1": {}, "3": {}}, [1, 2, 3]) is False


def test_idle_baseline_requires_recent_heartbeat_ready_idle_and_disarmed():
    row = {
        "update_time": 1774290000,
        "is_ready_to_arm": True,
        "readiness_status": "ready",
        "is_armed": False,
        "mission": 0,
        "state": 0,
        "home_position_set": True,
        "heartbeat_last_seen": int(time.time() * 1000),
    }

    assert _is_idle_baseline_row(row) is True
    assert _is_idle_baseline_row({**row, "heartbeat_last_seen": None}) is False
    assert _is_idle_baseline_row({**row, "heartbeat_last_seen": int((time.time() - 60) * 1000)}) is False
    assert _is_idle_baseline_row({**row, "is_ready_to_arm": False}) is False
    assert _is_idle_baseline_row({**row, "is_armed": True}) is False


def test_idle_reset_requires_disarmed_mission_and_state_clear():
    assert _is_idle_reset_row({"is_armed": False, "mission": 0, "state": 0}) is True
    assert _is_idle_reset_row({"is_armed": False, "mission": 101, "state": 2}) is False


def test_hold_ready_depends_on_airborne_outcome_not_transient_mission_code():
    row = {
        "is_armed": True,
        "position_alt": 101.2,
        "mission": 0,
    }

    assert _is_hold_ready_row(row, 100.0, min_gain=1.0) is True
    assert _is_hold_ready_row({**row, "position_alt": 100.4}, 100.0, min_gain=1.0) is False


def test_choose_override_targets_prefers_single_rtl_target_when_possible():
    assert choose_override_targets([1]) == ([1], [])
    assert choose_override_targets([3, 2, 2, 1]) == ([1], [2, 3])


def test_resolve_selected_ids_prefers_space_separated_drone_ids():
    args = argparse.Namespace(drone_ids=[3, 2, 2, 1], drones="9,8,7")
    assert resolve_selected_ids(args) == [1, 2, 3]


def test_resolve_selected_ids_falls_back_to_csv_argument_and_default():
    csv_args = argparse.Namespace(drone_ids=None, drones="3, 1,2")
    default_args = argparse.Namespace(drone_ids=None, drones=None)

    assert resolve_selected_ids(csv_args) == [1, 2, 3]
    assert resolve_selected_ids(default_args) == [1, 2, 3]


def test_launch_probe_timeout_preserves_native_blocker_without_accepting_it(monkeypatch):
    class Client:
        def get_telemetry(self):
            return {"1": {"ip": "127.0.0.1"}}

        def probe_live_armability(self, ip, **kwargs):
            return {"success": True, "ready": False, "summary": "waiting for health stream",
                    "blockers": ["health stream"]}

    def expire(predicate, **kwargs):
        assert predicate() is False
        raise RuntimeError("Timed out")

    monkeypatch.setattr(validator, "wait_for", expire)
    with pytest.raises(RuntimeError, match='Last native probes:.*health stream'):
        validator.wait_for_live_launch_readiness(Client(), [1], timeout=1)


@pytest.mark.parametrize(
    ("status", "outcome", "expected"),
    [
        ("cancelled", "superseded", True),
        ("completed", "completed", True),
        ("completed", "failed", False),
        ("failed", "failed", False),
        ("completed", None, True),
        ("superseded", None, True),
        ("cancelled", None, False),
    ],
)
def test_interrupted_terminal_status_prefers_explicit_outcome(
    status,
    outcome,
    expected,
):
    payload = {"status": status}
    if outcome is not None:
        payload["outcome"] = outcome
    assert _is_safe_interrupted_terminal_status(payload) is expected


@pytest.mark.parametrize("state", sorted(validator.TERMINAL_STATUSES))
def test_phase_wait_fails_immediately_on_terminal_receipt(monkeypatch, state):
    class Client:
        def get_json(self, _path):
            return {"status": state, "phase": "terminal", "error_summary": "native ground check",
                    "preparations": {"blocked": 1}}

    monkeypatch.setattr(validator.time, "sleep", lambda _: pytest.fail("Terminal receipt must not poll"))
    with pytest.raises(RuntimeError, match="ended before phase=in_progress.*native ground check"):
        validator.wait_for_command(Client(), "receipt-1", desired_phase="in_progress")


def test_terminal_wait_and_matching_phase_still_return_receipt():
    class Client:
        def get_json(self, _path):
            return {"status": "failed", "phase": "terminal"}

    assert validator.wait_for_command(Client(), "receipt-1", terminal=True)["status"] == "failed"
    assert validator.wait_for_command(Client(), "receipt-1", desired_phase="terminal")["status"] == "failed"
