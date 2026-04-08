import argparse
import time

from tools.validate_quickscout_runtime import (
    _is_idle_baseline_row,
    _is_idle_reset_row,
    _telemetry_has_ids,
    build_last_known_point_request,
    resolve_selected_ids,
    select_primary_target,
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
    assert _is_idle_baseline_row({**row, "is_armed": True}) is False


def test_idle_reset_requires_disarmed_with_no_mission_state():
    assert _is_idle_reset_row({"is_armed": False, "mission": 0, "state": 0}) is True
    assert _is_idle_reset_row({"is_armed": False, "mission": 501, "state": 3}) is False


def test_resolve_selected_ids_prefers_space_separated_drone_ids():
    args = argparse.Namespace(drone_ids=[3, 2, 2, 1], drones="9,8,7")
    assert resolve_selected_ids(args) == [1, 2, 3]


def test_resolve_selected_ids_falls_back_to_csv_and_default():
    csv_args = argparse.Namespace(drone_ids=None, drones="3, 1,2")
    default_args = argparse.Namespace(drone_ids=None, drones=None)

    assert resolve_selected_ids(csv_args) == [1, 2, 3]
    assert resolve_selected_ids(default_args) == [1, 2, 3]


def test_select_primary_target_uses_first_selected_drone_with_gps_and_pos_id():
    telemetry = {
        "1": {"position_lat": None, "position_long": None, "pos_id": 1},
        "2": {"position_lat": 47.0, "position_long": 8.0, "pos_id": 22},
    }

    drone_id, row = select_primary_target(telemetry, [1, 2])

    assert drone_id == 2
    assert row["pos_id"] == 22


def test_build_last_known_point_request_tracks_live_center_pos_id_and_altitude():
    row = {
        "position_lat": 47.1,
        "position_long": 8.2,
        "position_alt": 510.0,
    }

    payload = build_last_known_point_request(
        row,
        pos_id=7,
        radius_m=125.0,
        altitude_gain_m=20.0,
        sweep_width_m=25.0,
        overlap_percent=15.0,
        cruise_speed_ms=8.0,
        survey_speed_ms=4.0,
    )

    assert payload["mission_template"] == "last_known_point"
    assert payload["search_area"] == {
        "type": "point",
        "center": {"lat": 47.1, "lng": 8.2},
        "radius_m": 125.0,
    }
    assert payload["pos_ids"] == [7]
    assert payload["survey_config"]["cruise_altitude_msl"] == 530.0
    assert payload["survey_config"]["survey_altitude_agl"] == 20.0
