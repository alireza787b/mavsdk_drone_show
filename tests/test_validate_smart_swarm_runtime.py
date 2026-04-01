import copy
import time

from tools.validate_smart_swarm_runtime import (
    _is_idle_baseline_row,
    _is_idle_reset_row,
    _telemetry_has_ids,
    assignment_snapshot,
    restore_assignments,
)


def test_telemetry_has_ids_requires_full_selected_fleet():
    assert _telemetry_has_ids({"1": {}, "2": {}, "3": {}}, [1, 2, 3]) is True
    assert _telemetry_has_ids({"1": {}, "3": {}}, [1, 2, 3]) is False


def test_idle_baseline_requires_ready_disarmed_idle_and_home():
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


def test_idle_baseline_rejects_airborne_or_missing_home():
    assert _is_idle_baseline_row({
        "update_time": 1774290000,
        "is_ready_to_arm": True,
        "readiness_status": "ready",
        "is_armed": True,
        "mission": 0,
        "state": 0,
        "home_position_set": True,
        "heartbeat_last_seen": int(time.time() * 1000),
    }) is False

    assert _is_idle_baseline_row({
        "update_time": 1774290000,
        "is_ready_to_arm": True,
        "readiness_status": "ready",
        "is_armed": False,
        "mission": 0,
        "state": 0,
        "home_position_set": False,
        "heartbeat_last_seen": int(time.time() * 1000),
    }) is False

    assert _is_idle_baseline_row({
        "update_time": 1774290000,
        "is_ready_to_arm": True,
        "readiness_status": "ready",
        "is_armed": False,
        "mission": 0,
        "state": 0,
        "home_position_set": True,
        "heartbeat_last_seen": int((time.time() - 60) * 1000),
    }) is False

    assert _is_idle_baseline_row({
        "update_time": 1774290000,
        "is_ready_to_arm": True,
        "readiness_status": "ready",
        "is_armed": False,
        "mission": 0,
        "state": 0,
        "home_position_set": True,
        "heartbeat_last_seen": None,
    }) is False


def test_idle_reset_requires_disarmed_mission_and_state_clear():
    assert _is_idle_reset_row({
        "is_armed": False,
        "mission": 0,
        "state": 0,
    }) is True

    assert _is_idle_reset_row({
        "is_armed": False,
        "mission": 101,
        "state": 2,
    }) is False


def test_assignment_snapshot_normalizes_selected_assignments():
    assignments = [
        {"hw_id": 1, "follow": "0", "offset_x": "0", "offset_y": 0, "offset_z": 0, "frame": "BODY"},
        {"hw_id": 2, "follow": "1", "offset_x": "5", "offset_y": "50", "offset_z": "5", "frame": "NED"},
        {"hw_id": 3, "follow": 2, "offset_x": 8, "offset_y": 6, "offset_z": 0, "frame": "body"},
    ]

    assert assignment_snapshot(assignments, [2, 3]) == {
        2: {
            "follow": 1,
            "offset_x": 5.0,
            "offset_y": 50.0,
            "offset_z": 5.0,
            "frame": "ned",
        },
        3: {
            "follow": 2,
            "offset_x": 8.0,
            "offset_y": 6.0,
            "offset_z": 0.0,
            "frame": "body",
        },
    }


class _FakeSwarmClient:
    def __init__(self, assignments):
        self.assignments = copy.deepcopy(assignments)
        self.update_calls = []

    def get_swarm(self):
        return copy.deepcopy(self.assignments)

    def update_assignment(self, hw_id, **kwargs):
        self.update_calls.append((hw_id, kwargs))
        for entry in self.assignments:
            if int(entry["hw_id"]) != int(hw_id):
                continue
            entry.update(kwargs)
            return entry
        entry = {"hw_id": int(hw_id), **kwargs}
        self.assignments.append(entry)
        return entry


def test_restore_assignments_updates_only_changed_rows():
    original = {
        1: {"follow": 0, "offset_x": 0.0, "offset_y": 0.0, "offset_z": 0.0, "frame": "body"},
        2: {"follow": 1, "offset_x": 5.0, "offset_y": 50.0, "offset_z": 5.0, "frame": "ned"},
        3: {"follow": 1, "offset_x": 25.0, "offset_y": 0.0, "offset_z": 15.0, "frame": "body"},
    }
    client = _FakeSwarmClient([
        {"hw_id": 1, "follow": 0, "offset_x": 0.0, "offset_y": 0.0, "offset_z": 0.0, "frame": "body"},
        {"hw_id": 2, "follow": 1, "offset_x": 5.0, "offset_y": 50.0, "offset_z": 5.0, "frame": "ned"},
        {"hw_id": 3, "follow": 2, "offset_x": 8.0, "offset_y": 6.0, "offset_z": 0.0, "frame": "body"},
    ])

    changed_ids = restore_assignments(client, original, timeout=1)

    assert changed_ids == [3]
    assert client.update_calls == [
        (
            3,
            {"follow": 1, "offset_x": 25.0, "offset_y": 0.0, "offset_z": 15.0, "frame": "body"},
        )
    ]
    assert assignment_snapshot(client.get_swarm(), [1, 2, 3]) == original
