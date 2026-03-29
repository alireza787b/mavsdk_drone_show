import importlib.util
import csv
from pathlib import Path

from src.flight_timeout_utils import calculate_swarm_rtl_completion_timeout
from src.params import Params as RepoParams


def _load_validator_module():
    module_path = Path(__file__).resolve().parents[1] / "tools" / "validate_swarm_trajectory_runtime.py"
    spec = importlib.util.spec_from_file_location("validate_swarm_trajectory_runtime", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_validator_uses_repo_timeout_model():
    validator = _load_validator_module()

    assert validator.USING_FALLBACK_TIMEOUT_PARAMS is False
    assert validator.Params.LAND_ACTION_ASSUMED_DESCENT_RATE_MPS == RepoParams.LAND_ACTION_ASSUMED_DESCENT_RATE_MPS

    timeout = validator.estimate_command_completion_timeout(
        500.0,
        end_behavior="return_home",
        relative_altitude_m=1321.946,
    )

    expected = max(
        300,
        int(500.0 + calculate_swarm_rtl_completion_timeout(1321.946) + 180),
    )
    assert timeout == expected


def test_estimate_command_completion_timeout_includes_rtl_window():
    validator = _load_validator_module()

    timeout = validator.estimate_command_completion_timeout(
        500.0,
        end_behavior="return_home",
        relative_altitude_m=250.0,
    )

    assert timeout >= 500 + validator.calculate_swarm_rtl_completion_timeout(250.0)


def test_estimate_command_completion_timeout_for_land_current_is_shorter_than_rtl():
    validator = _load_validator_module()

    rtl_timeout = validator.estimate_command_completion_timeout(
        500.0,
        end_behavior="return_home",
        relative_altitude_m=250.0,
    )
    land_timeout = validator.estimate_command_completion_timeout(
        500.0,
        end_behavior="land_current",
        relative_altitude_m=250.0,
    )

    assert land_timeout < rtl_timeout


def test_max_processed_duration_seconds_filters_to_selected_drones(tmp_path):
    validator = _load_validator_module()
    processed_dir = tmp_path / "shapes_sitl" / "swarm_trajectory" / "processed"
    processed_dir.mkdir(parents=True)

    for drone_id, duration in ((1, 120.0), (2, 240.0), (3, 360.0)):
        with (processed_dir / f"Drone {drone_id}.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["t", "alt"])
            writer.writeheader()
            writer.writerow({"t": 0, "alt": 1200})
            writer.writerow({"t": duration, "alt": 1300})

    assert validator.max_processed_duration_seconds(tmp_path, drone_ids=[1, 2]) == 240.0


def test_max_processed_relative_altitude_uses_processed_peak_over_baseline(tmp_path):
    validator = _load_validator_module()
    processed_dir = tmp_path / "shapes_sitl" / "swarm_trajectory" / "processed"
    processed_dir.mkdir(parents=True)

    with (processed_dir / "Drone 4.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["t", "alt"])
        writer.writeheader()
        writer.writerow({"t": 0, "alt": 1370.0})
        writer.writerow({"t": 50, "alt": 2600.0})

    with (processed_dir / "Drone 5.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["t", "alt"])
        writer.writeheader()
        writer.writerow({"t": 0, "alt": 1369.0})
        writer.writerow({"t": 50, "alt": 2400.0})

    baselines = {4: 1278.0, 5: 1278.0}

    assert validator.max_processed_relative_altitude_m(tmp_path, baselines, drone_ids=[4, 5]) == 1322.0


def test_follower_expectations_filter_to_selected_active_set():
    validator = _load_validator_module()

    assignments = [
        {"hw_id": 1, "follow": 0},
        {"hw_id": 2, "follow": 1, "offset_x": 5, "offset_y": 50, "offset_z": 5, "frame": "ned"},
        {"hw_id": 3, "follow": 1, "offset_x": 25, "offset_y": 0, "offset_z": 15, "frame": "body"},
        {"hw_id": 5, "follow": 4, "offset_x": 15, "offset_y": -5, "offset_z": 0, "frame": "ned"},
    ]

    expectations = validator.follower_expectations(assignments, active_ids=[1, 2, 3])

    assert sorted(expectations.keys()) == [2, 3]
    assert expectations[2]["leader_id"] == 1
    assert expectations[3]["leader_id"] == 1


def test_follower_scope_issues_flags_selected_followers_without_selected_leader():
    validator = _load_validator_module()

    expectations = {
        5: {
            "leader_id": 4,
            "offset_x": 15.0,
            "offset_y": -5.0,
            "offset_z": 0.0,
            "frame": "ned",
        }
    }

    issues = validator.follower_scope_issues(expectations, active_ids=[1, 2, 3, 5])

    assert issues == [
        {
            "follower_id": 5,
            "leader_id": 4,
            "issue": "leader_not_in_active_mission_set",
        }
    ]


def test_selected_top_leaders_filters_to_active_top_leaders():
    validator = _load_validator_module()

    assignments = [
        {"hw_id": 1, "follow": 0},
        {"hw_id": 2, "follow": 1},
        {"hw_id": 3, "follow": 1},
        {"hw_id": 4, "follow": 0},
        {"hw_id": 5, "follow": 4},
    ]

    assert validator.selected_top_leaders(assignments, active_ids=[1, 2, 3]) == [1]
    assert validator.selected_top_leaders(assignments, active_ids=[1, 2, 3, 4, 5]) == [1, 4]


def test_build_short_validation_profile_rows_uses_route_entry_and_leg_defaults():
    validator = _load_validator_module()

    telemetry_row = {
        "position_lat": 35.7262,
        "position_long": 51.2721,
        "position_alt": 1278.2,
    }

    rows = validator.build_short_validation_profile_rows(
        1,
        telemetry_row,
        relative_altitude_m=12.0,
        entry_delay_s=8.0,
        leg_duration_s=10.0,
    )

    assert len(rows) == 3
    assert rows[0]["HeadingMode"] == "manual"
    assert rows[1]["HeadingMode"] == "auto"
    assert rows[0]["TimeFromStart_s"] == 8.0
    assert rows[-1]["TimeFromStart_s"] == 28.0
    assert rows[0]["Altitude_MSL_m"] == 1290.2
    assert rows[1]["EstimatedSpeed_ms"] > 0


def test_write_short_validation_profiles_creates_raw_csvs(tmp_path):
    validator = _load_validator_module()

    prepared = validator.write_short_validation_profiles(
        tmp_path,
        {
            "1": {
                "position_lat": 35.7262,
                "position_long": 51.2721,
                "position_alt": 1278.2,
            }
        },
        [1],
        relative_altitude_m=15.0,
        entry_delay_s=6.0,
        leg_duration_s=9.0,
    )

    csv_path = tmp_path / "shapes_sitl" / "swarm_trajectory" / "raw" / "Drone 1.csv"
    assert csv_path.exists()
    assert prepared == [
        {
            "leader_id": 1,
            "path": str(csv_path),
            "waypoint_count": 3,
            "duration_sec": 24.0,
            "mission_altitude_msl": 1293.2,
        }
    ]

    with csv_path.open() as handle:
        rows = list(csv.DictReader(handle))

    assert rows[0]["HeadingMode"] == "manual"
    assert rows[1]["HeadingMode"] == "auto"
    assert rows[0]["TimeFromStart_s"] == "6.0"
