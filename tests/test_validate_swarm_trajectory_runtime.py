import importlib.util
import csv
import itertools
from pathlib import Path

import pytest

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


def test_max_selected_horizontal_offset_uses_active_followers_of_selected_leaders():
    validator = _load_validator_module()

    assignments = [
        {"hw_id": 1, "follow": 0},
        {"hw_id": 2, "follow": 1, "offset_x": 5, "offset_y": 50},
        {"hw_id": 3, "follow": 1, "offset_x": 25, "offset_y": 0},
        {"hw_id": 5, "follow": 4, "offset_x": 100, "offset_y": 0},
    ]

    offset = validator.max_selected_horizontal_offset_m(
        assignments,
        leader_ids=[1],
        active_ids=[1, 2, 3],
    )

    assert offset == pytest.approx(50.2493781056)


def test_recommend_short_profile_entry_delay_scales_with_offset_and_altitude():
    validator = _load_validator_module()

    assert validator.recommend_short_profile_entry_delay(
        default_entry_delay_s=8.0,
        relative_altitude_m=12.0,
        max_horizontal_offset_m=50.0,
    ) == 26.3

    assert validator.recommend_short_profile_entry_delay(
        default_entry_delay_s=30.0,
        relative_altitude_m=12.0,
        max_horizontal_offset_m=50.0,
    ) == 30.0


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


def test_command_summary_includes_normalized_progress_snapshot():
    validator = _load_validator_module()

    summary = validator.command_summary(
        {
            "status": "executing",
            "phase": "in_progress",
            "outcome": None,
            "progress": {
                "stage": "finishing",
                "label": "Finishing on remaining drones",
                "message": "2/3 accepted drone(s) have reported completion. Waiting for 1 remaining drone(s).",
                "active": 1,
                "remaining": 1,
            },
            "acks": {
                "expected": 3,
                "accepted": 3,
                "offline": 0,
                "rejected": 0,
                "errors": 0,
            },
            "executions": {
                "expected": 3,
                "received": 2,
                "started": 3,
                "active": 1,
                "succeeded": 2,
                "failed": 0,
            },
        }
    )

    assert summary["progress"] == {
        "stage": "finishing",
        "label": "Finishing on remaining drones",
        "active": 1,
        "remaining": 1,
        "message": "2/3 accepted drone(s) have reported completion. Waiting for 1 remaining drone(s).",
    }


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


def test_processed_formation_expectations_use_processed_tracks(tmp_path):
    validator = _load_validator_module()
    processed_dir = tmp_path / "shapes_sitl" / "swarm_trajectory" / "processed"
    processed_dir.mkdir(parents=True)

    for drone_id in (1, 2):
        with (processed_dir / f"Drone {drone_id}.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["t", "lat", "lon", "alt"])
            writer.writeheader()
            writer.writerow({"t": 10.0, "lat": 35.0, "lon": 51.0, "alt": 100.0 + drone_id})
            writer.writerow({"t": 20.0, "lat": 35.0, "lon": 51.0, "alt": 110.0 + drone_id})

    expectations = validator.processed_formation_expectations(
        tmp_path,
        {2: {"leader_id": 1, "offset_x": 5.0, "offset_y": 50.0, "offset_z": 5.0, "frame": "ned"}},
    )

    assert sorted(expectations.keys()) == [2]
    assert expectations[2]["leader_id"] == 1
    assert expectations[2]["window_start_s"] == 10.0
    assert expectations[2]["window_end_s"] == 20.0
    assert expectations[2]["leader_track"]["drone_id"] == 1
    assert expectations[2]["follower_track"]["drone_id"] == 2


def test_evaluate_formation_snapshot_uses_processed_package_truth(tmp_path):
    validator = _load_validator_module()
    processed_dir = tmp_path / "shapes_sitl" / "swarm_trajectory" / "processed"
    processed_dir.mkdir(parents=True)

    with (processed_dir / "Drone 1.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["t", "lat", "lon", "alt"])
        writer.writeheader()
        writer.writerow({"t": 10.0, "lat": 35.0, "lon": 51.0, "alt": 100.0})
        writer.writerow({"t": 20.0, "lat": 35.00008983, "lon": 51.0, "alt": 110.0})

    with (processed_dir / "Drone 2.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["t", "lat", "lon", "alt"])
        writer.writeheader()
        writer.writerow({"t": 10.0, "lat": 35.000044915, "lon": 51.00054916, "alt": 105.0})
        writer.writerow({"t": 20.0, "lat": 35.000134745, "lon": 51.00054916, "alt": 115.0})

    processed = validator.processed_formation_expectations(
        tmp_path,
        {2: {"leader_id": 1, "offset_x": 5.0, "offset_y": 50.0, "offset_z": 5.0, "frame": "ned"}},
    )

    telemetry = {
        "1": {"position_lat": 35.00008983, "position_long": 51.0, "position_alt": 110.0},
        "2": {"position_lat": 35.000134745, "position_long": 51.00054916, "position_alt": 115.0},
    }

    ok, diagnostics = validator.evaluate_formation_snapshot(
        telemetry,
        processed,
        mission_elapsed_s=20.0,
        horiz_tolerance=2.0,
        vert_tolerance=1.0,
    )

    assert ok is True
    assert diagnostics[0]["expected_alt_delta_m"] == pytest.approx(5.0)
    assert diagnostics[0]["horizontal_error_m"] == pytest.approx(0.0, abs=0.2)


def test_wait_for_formation_reports_inactive_mission_state_when_geometry_window_is_missed(monkeypatch):
    validator = _load_validator_module()

    class SequencedClient:
        def __init__(self, snapshots):
            self._snapshots = list(snapshots)
            self._index = 0

        def get_telemetry(self):
            snapshot = self._snapshots[min(self._index, len(self._snapshots) - 1)]
            self._index += 1
            return snapshot

    client = SequencedClient(
        [
            {
                "1": {"mission": 4, "state": 2, "is_armed": True, "position_lat": 35.0, "position_long": 51.0, "position_alt": 100.0},
                "2": {"mission": 4, "state": 2, "is_armed": True, "position_lat": 35.0, "position_long": 51.0, "position_alt": 100.0},
            },
            {
                "1": {"mission": 0, "state": 0, "is_armed": False, "position_lat": 35.0, "position_long": 51.0, "position_alt": 100.0},
                "2": {"mission": 0, "state": 0, "is_armed": False, "position_lat": 35.0, "position_long": 51.0, "position_alt": 100.0},
            },
        ]
    )
    fake_time = itertools.count(start=0, step=1)

    monkeypatch.setattr(validator.time, "time", lambda: next(fake_time))
    monkeypatch.setattr(validator.time, "sleep", lambda _seconds: None)

    expectations = {
        2: {
            "leader_id": 1,
            "leader_track": {
                "samples": [{"t": 0.0, "lat": 35.0, "lon": 51.0, "alt": 100.0}],
                "times": [0.0],
                "start_t": 0.0,
                "end_t": 30.0,
            },
            "follower_track": {
                "samples": [{"t": 0.0, "lat": 35.0, "lon": 51.0, "alt": 100.0}],
                "times": [0.0],
                "start_t": 0.0,
                "end_t": 30.0,
            },
            "start_t": 0.0,
            "end_t": 30.0,
        }
    }

    with pytest.raises(RuntimeError, match="Last mission-state issues"):
        validator.wait_for_formation(
            client,
            expectations,
            execution_started_at_ms=1000,
            horiz_tolerance=5.0,
            vert_tolerance=5.0,
            timeout=4,
        )


def test_wait_for_altitude_gain_tracks_per_drone_peak_over_time(monkeypatch):
    validator = _load_validator_module()

    class SequencedClient:
        def __init__(self, snapshots):
            self._snapshots = list(snapshots)
            self._index = 0

        def get_telemetry(self):
            snapshot = self._snapshots[min(self._index, len(self._snapshots) - 1)]
            self._index += 1
            return snapshot

    client = SequencedClient(
        [
            {
                "1": {"position_alt": 100.5},
                "2": {"position_alt": 200.4},
            },
            {
                "1": {"position_alt": 102.6},
                "2": {"position_alt": 200.9},
            },
            {
                "1": {"position_alt": 101.0},
                "2": {"position_alt": 202.4},
            },
        ]
    )
    baselines = {1: 100.0, 2: 200.0}
    fake_time = itertools.count(start=0, step=1)

    monkeypatch.setattr(validator.time, "time", lambda: next(fake_time))
    monkeypatch.setattr(validator.time, "sleep", lambda _seconds: None)

    telemetry = validator.wait_for_altitude_gain(client, baselines, min_gain=2.0, timeout=10)

    assert telemetry["1"]["position_alt"] == 101.0
    assert telemetry["2"]["position_alt"] == 202.4


def test_wait_for_altitude_gain_reports_peak_gains_on_timeout(monkeypatch):
    validator = _load_validator_module()

    class StaticClient:
        def get_telemetry(self):
            return {
                "1": {"position_alt": 101.2},
                "2": {"position_alt": 200.8},
            }

    fake_time = itertools.count(start=0, step=1)
    monkeypatch.setattr(validator.time, "time", lambda: next(fake_time))
    monkeypatch.setattr(validator.time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match=r"Peak gains: \{1: 1.2, 2: 0.8\}"):
        validator.wait_for_altitude_gain(StaticClient(), {1: 100.0, 2: 200.0}, min_gain=2.0, timeout=3)


def test_format_http_error_prefers_json_detail_message():
    validator = _load_validator_module()

    class FakeHttpError:
        code = 400
        reason = "Bad Request"

        def __init__(self, payload: str):
            self._payload = payload.encode("utf-8")

        def read(self):
            return self._payload

    exc = FakeHttpError('{"detail":"Unsafe Swarm Trajectory target set"}')

    assert validator.format_http_error(exc) == "HTTP 400: Unsafe Swarm Trajectory target set"


def test_collect_live_armability_results_uses_selected_telemetry_rows(monkeypatch):
    validator = _load_validator_module()

    class FakeClient:
        def get_telemetry(self):
            return {
                "1": {"ip": "10.0.0.1"},
                "2": {"ip": "10.0.0.2"},
                "9": {"ip": "10.0.0.9"},
            }

    def fake_probe(drone_id, drone_ip, **_kwargs):
        return {
            "drone_id": drone_id,
            "drone_ip": drone_ip,
            "success": True,
            "ready": drone_id == 1,
            "summary": "ok" if drone_id == 1 else "blocked",
            "category": "ready" if drone_id == 1 else "blocked",
            "details": {"ready": drone_id == 1},
        }

    monkeypatch.setattr(validator, "probe_live_armability_for_drone", fake_probe)

    results = validator.collect_live_armability_results(FakeClient(), [1, 2])

    assert results["all_ready"] is False
    assert results["blocked_ids"] == [2]
    assert results["unavailable_ids"] == []
    assert set(results["results"].keys()) == {"1", "2"}
    assert results["results"]["1"]["drone_ip"] == "10.0.0.1"


def test_wait_for_live_launch_readiness_reports_last_probe(monkeypatch):
    validator = _load_validator_module()

    snapshot = {
        "all_ready": False,
        "blocked_ids": [3],
        "unavailable_ids": [],
        "results": {
            "3": {
                "drone_id": 3,
                "summary": "waiting for PX4 armability",
                "category": "blocked",
            }
        },
    }

    monkeypatch.setattr(validator, "collect_live_armability_results", lambda client, ids: snapshot)

    def fake_wait_for(predicate, **_kwargs):
        predicate()
        raise RuntimeError("timeout")

    monkeypatch.setattr(validator, "wait_for", fake_wait_for)

    with pytest.raises(RuntimeError) as exc_info:
        validator.wait_for_live_launch_readiness(object(), [1, 2, 3], timeout=5)

    assert "waiting for PX4 armability" in str(exc_info.value)
