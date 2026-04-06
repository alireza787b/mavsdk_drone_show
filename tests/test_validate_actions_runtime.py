import argparse
import time

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


def test_interrupted_terminal_status_accepts_superseded_outcome_even_if_status_is_cancelled():
    assert _is_safe_interrupted_terminal_status({"status": "cancelled", "outcome": "superseded"}) is True
    assert _is_safe_interrupted_terminal_status({"status": "completed", "outcome": "completed"}) is True
    assert _is_safe_interrupted_terminal_status({"status": "failed", "outcome": "failed"}) is False
