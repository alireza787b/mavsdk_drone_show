import argparse
import time

from tools.validate_quickscout_runtime import (
    _is_idle_baseline_row,
    _is_idle_reset_row,
    _telemetry_has_ids,
    build_area_sweep_request,
    build_corridor_search_request,
    build_last_known_point_request,
    detect_foreign_active_commands,
    resolve_selected_ids,
    select_target_drones,
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


def test_select_target_drones_uses_first_selected_drones_with_gps_and_pos_id():
    telemetry = {
        "1": {"position_lat": None, "position_long": None, "pos_id": 1},
        "2": {"position_lat": 47.0, "position_long": 8.0, "pos_id": 22},
        "3": {"position_lat": 48.0, "position_long": 9.0, "pos_id": 33},
    }

    targets = select_target_drones(telemetry, [1, 2, 3], target_count=2)

    assert [drone_id for drone_id, _ in targets] == [2, 3]
    assert [row["pos_id"] for _, row in targets] == [22, 33]


def test_build_last_known_point_request_tracks_multi_drone_center_pos_ids_and_altitude():
    rows = [
        {
            "position_lat": 47.1,
            "position_long": 8.2,
            "position_alt": 510.0,
        },
        {
            "position_lat": 47.3,
            "position_long": 8.4,
            "position_alt": 512.0,
        },
    ]

    payload = build_last_known_point_request(
        rows,
        pos_ids=[7, 8],
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
        "center": {"lat": 47.2, "lng": 8.3},
        "radius_m": 125.0,
    }
    assert payload["pos_ids"] == [7, 8]
    assert payload["survey_config"]["cruise_altitude_msl"] == 532.0
    assert payload["survey_config"]["survey_altitude_agl"] == 20.0


def test_build_area_sweep_request_tracks_polygon_dimensions_and_template():
    rows = [
        {
            "position_lat": 47.2,
            "position_long": 8.3,
            "position_alt": 500.0,
        }
    ]

    payload = build_area_sweep_request(
        rows,
        pos_ids=[5],
        area_width_m=180.0,
        area_height_m=140.0,
        altitude_gain_m=20.0,
        sweep_width_m=25.0,
        overlap_percent=10.0,
        cruise_speed_ms=8.0,
        survey_speed_ms=4.0,
    )

    assert payload["mission_template"] == "area_sweep"
    assert payload["search_area"]["type"] == "polygon"
    assert len(payload["search_area"]["points"]) == 4
    assert payload["pos_ids"] == [5]
    assert payload["mission_profile"] == "runtime_area_sweep"


def test_build_corridor_search_request_tracks_path_width_and_template():
    rows = [
        {
            "position_lat": 47.2,
            "position_long": 8.3,
            "position_alt": 500.0,
        }
    ]

    payload = build_corridor_search_request(
        rows,
        pos_ids=[9],
        corridor_leg_length_m=220.0,
        corridor_width_m=80.0,
        altitude_gain_m=20.0,
        sweep_width_m=25.0,
        overlap_percent=10.0,
        cruise_speed_ms=8.0,
        survey_speed_ms=4.0,
    )

    assert payload["mission_template"] == "corridor_search"
    assert payload["search_area"]["type"] == "line"
    assert len(payload["search_area"]["path"]) == 3
    assert payload["search_area"]["corridor_width_m"] == 80.0
    assert payload["pos_ids"] == [9]
    assert payload["mission_profile"] == "runtime_corridor_search"


def test_detect_foreign_active_commands_ignores_allowed_ids_and_unwatched_targets():
    payload = {
        "commands": [
            {
                "command_id": "known-launch",
                "mission_name": "QUICKSCOUT",
                "target_drones": ["1", "2"],
                "status": "executing",
                "phase": "in_progress",
            },
            {
                "command_id": "other-scope",
                "mission_name": "DRONE_SHOW_FROM_CSV",
                "target_drones": ["9"],
                "status": "executing",
                "phase": "in_progress",
            },
        ]
    }

    conflicts = detect_foreign_active_commands(
        payload,
        allowed_command_ids={"known-launch"},
        watch_drone_ids=[1, 2, 3],
    )

    assert conflicts == []


def test_detect_foreign_active_commands_reports_overlap_with_watched_drones():
    payload = {
        "commands": [
            {
                "command_id": "foreign-show",
                "mission_name": "DRONE_SHOW_FROM_CSV",
                "mission_type": 1,
                "target_drones": ["2", "3"],
                "status": "executing",
                "phase": "in_progress",
            }
        ]
    }

    conflicts = detect_foreign_active_commands(
        payload,
        allowed_command_ids={"known-launch"},
        watch_drone_ids=[3],
    )

    assert conflicts == [
        {
            "command_id": "foreign-show",
            "mission_name": "DRONE_SHOW_FROM_CSV",
            "mission_type": 1,
            "status": "executing",
            "phase": "in_progress",
            "target_drones": ["2", "3"],
        }
    ]
