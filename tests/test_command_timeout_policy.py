import os
import sys
from enum import Enum

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gcs-server"))

from command_timeout_policy import estimate_command_tracking_timeout_ms
from src.enums import Mission


class _MockParams:
    COMMAND_TRACKING_DEFAULT_TIMEOUT_MS = 60_000
    COMMAND_TRACKING_ACTION_BUFFER_SEC = 30
    COMMAND_TRACKING_MISSION_BUFFER_SEC = 120
    COMMAND_TRACKING_HOVER_TEST_TIMEOUT_SEC = 180
    COMMAND_TRACKING_QUICKSCOUT_TIMEOUT_SEC = 900
    TAKEOFF_PREFLIGHT_TIMEOUT_SEC = 30
    TAKEOFF_ALTITUDE_CONFIRM_TIMEOUT_SEC = 60
    LAND_ACTION_MIN_DISARM_WAIT_SEC = 45
    LAND_ACTION_ASSUMED_DESCENT_RATE_MPS = 1.5
    LAND_ACTION_DISARM_BUFFER_SEC = 30
    LAND_ACTION_MAX_DISARM_WAIT_SEC = 900
    RTL_ACTION_COMPLETION_TIMEOUT = 300
    RTL_ACTION_COMPLETION_BUFFER_SEC = 120
    RTL_ACTION_COMPLETION_MAX_TIMEOUT = 1200
    SWARM_TRAJECTORY_TIMEOUT_MULTIPLIER = 1.2
    SWARM_TRAJECTORY_END_BEHAVIOR = "return_home"


def test_estimate_command_tracking_timeout_for_takeoff_uses_prefight_and_climb_budget():
    timeout_ms = estimate_command_tracking_timeout_ms(Mission.TAKE_OFF, params=_MockParams)

    assert timeout_ms == (30 + 60 + 30) * 1000


def test_estimate_command_tracking_timeout_includes_future_trigger_delay(monkeypatch):
    fake_now = 1_700_000_000.0
    monkeypatch.setattr("command_timeout_policy.time.time", lambda: fake_now)

    timeout_ms = estimate_command_tracking_timeout_ms(
        Mission.TAKE_OFF,
        command_data={"triggerTime": int(fake_now) + 45},
        params=_MockParams,
    )

    assert timeout_ms == 45_000 + ((30 + 60 + 30) * 1000)


def test_estimate_command_tracking_timeout_for_drone_show_uses_show_duration(tmp_path):
    skybrush_dir = tmp_path / "skybrush"
    skybrush_dir.mkdir()
    (skybrush_dir / "Drone 1.csv").write_text("t,x,y,z\n0,0,0,0\n125000,0,0,1\n", encoding="utf-8")

    timeout_ms = estimate_command_tracking_timeout_ms(
        Mission.DRONE_SHOW_FROM_CSV,
        skybrush_dir=skybrush_dir,
        params=_MockParams,
    )

    assert timeout_ms == 125_000 + (120 * 1000)


def test_estimate_command_tracking_timeout_for_swarm_trajectory_adds_end_behavior_budget(tmp_path):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    (processed_dir / "Drone 1.csv").write_text("t,alt\n0,10\n100,25\n", encoding="utf-8")

    timeout_ms = estimate_command_tracking_timeout_ms(
        Mission.SWARM_TRAJECTORY,
        processed_dir=processed_dir,
        command_data={"return_behavior": "return_home"},
        params=_MockParams,
    )

    expected_duration_s = (100 * _MockParams.SWARM_TRAJECTORY_TIMEOUT_MULTIPLIER) + 120 + 300
    assert timeout_ms == int(expected_duration_s * 1000)


def test_estimate_command_tracking_timeout_accepts_foreign_enum_like_objects(tmp_path):
    class ForeignMission(Enum):
        SWARM_TRAJECTORY = 4

    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    (processed_dir / "Drone 1.csv").write_text("t,alt\n0,10\n100,25\n", encoding="utf-8")

    timeout_ms = estimate_command_tracking_timeout_ms(
        ForeignMission.SWARM_TRAJECTORY,
        processed_dir=processed_dir,
        command_data={"return_behavior": "return_home"},
        params=_MockParams,
    )

    expected_duration_s = (100 * _MockParams.SWARM_TRAJECTORY_TIMEOUT_MULTIPLIER) + 120 + 300
    assert timeout_ms == int(expected_duration_s * 1000)


def test_estimate_command_tracking_timeout_for_swarm_trajectory_filters_target_drones(tmp_path):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    (processed_dir / "Drone 1.csv").write_text("t,alt\n0,10\n100,25\n", encoding="utf-8")
    (processed_dir / "Drone 4.csv").write_text("t,alt\n0,10\n500,25\n", encoding="utf-8")

    timeout_ms = estimate_command_tracking_timeout_ms(
        Mission.SWARM_TRAJECTORY,
        processed_dir=processed_dir,
        target_drone_ids=["1"],
        command_data={"return_behavior": "return_home"},
        params=_MockParams,
    )

    expected_duration_s = (100 * _MockParams.SWARM_TRAJECTORY_TIMEOUT_MULTIPLIER) + 120 + 300
    assert timeout_ms == int(expected_duration_s * 1000)


def test_estimate_command_tracking_timeout_for_custom_show_uses_active_csv_duration(tmp_path):
    shapes_dir = tmp_path / "shapes"
    shapes_dir.mkdir()
    (shapes_dir / "active.csv").write_text(
        "t,px,py,pz,vx,vy,vz,ax,ay,az,yaw,mode\n0,0,0,-1,0,0,0,0,0,0,0,70\n32.5,1,1,-2,0,0,0,0,0,0,0,70\n",
        encoding="utf-8",
    )

    timeout_ms = estimate_command_tracking_timeout_ms(
        Mission.CUSTOM_CSV_DRONE_SHOW,
        shapes_dir=shapes_dir,
        params=_MockParams,
    )

    assert timeout_ms == 32_500 + (120 * 1000)
