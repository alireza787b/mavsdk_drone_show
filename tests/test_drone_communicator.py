import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.command_installation import CommandInstallationRejected
from src.drone_communicator import DroneCommunicator
from src.enums import Mission


def build_drone_config(follow_value=1):
    def read_swarm():
        return {"follow": follow_value}

    return SimpleNamespace(
        hw_id=3,
        pos_id=3,
        detected_pos_id=0,
        state=2,
        mission=2,
        last_mission=10,
        trigger_time=0,
        position={"lat": 35.7244359, "long": 51.2756087, "alt": 1286.0},
        home_position={"lat": 35.7244359, "long": 51.2756087, "alt": 1286.0},
        velocity={"north": 0.0, "east": 0.0, "down": 0.0},
        yaw=100.0,
        battery=15.3,
        battery_remaining_percent=78.0,
        battery_charge_state=2,
        battery_fault_bitmask=0,
        battery_timestamp_ms=1234567890123,
        swarm={"follow": 1},
        last_update_timestamp=1234567890,
        telemetry_timestamp_ms=1234567890123,
        telemetry_sequence=12,
        heartbeat_timestamp_ms=1234567890123,
        global_position_valid=True,
        global_position_timestamp_ms=1234567890123,
        gps_raw_timestamp_ms=1234567890123,
        gps_raw_altitude_m=1286.0,
        relative_altitude_m=8.4,
        baro_altitude_m=7.9,
        baro_timestamp_ms=1234567890123,
        position_source="global_position_int",
        yaw_rate_deg_s=4.5,
        local_position_ned={
            "time_boot_ms": 4567,
            "timestamp_ms": 1234567890123,
            "x": 1.2,
            "y": -0.5,
            "z": -3.4,
            "vx": 0.6,
            "vy": 0.2,
            "vz": -0.1,
        },
        custom_mode=50593792,
        base_mode=29,
        system_status=3,
        is_armed=True,
        is_ready_to_arm=True,
        px4_home_position_set=True,
        home_position_source="px4",
        readiness_status="ready",
        readiness_summary="Ready to fly",
        readiness_checks=[],
        preflight_blockers=[],
        preflight_warnings=[],
        status_messages=[],
        preflight_last_update=1234567890,
        hdop=0.7,
        vdop=1.1,
        gps_fix_type=3,
        satellites_visible=10,
        config={"ip": "172.18.0.4", "mavlink_port": 14552},
        read_swarm=read_swarm,
    )


def test_get_drone_state_prefers_live_swarm_assignment():
    drone_config = build_drone_config(follow_value=0)
    params = SimpleNamespace(enable_udp_telemetry=False, enable_default_subscriptions=False)

    communicator = DroneCommunicator(drone_config=drone_config, params=params, drones={})
    state = communicator.get_drone_state()

    assert state["follow_mode"] == 0
    assert state["distance_to_home_m"] == 0
    assert state["altitude_report"]["source"] == "relative_home"
    assert state["altitude_display_m"] == 8.4
    assert state["battery_remaining_percent"] == 78.0
    assert state["battery_charge_state"] == 2
    assert state["battery_fault_bitmask"] == 0
    assert state["battery_timestamp_ms"] == 1234567890123
    assert state["battery_age_ms"] is not None
    assert state["heartbeat_timestamp_ms"] == 1234567890123
    assert state["heartbeat_age_ms"] is not None
    assert communicator._get_live_swarm_assignment()["follow"] == 0


def test_get_drone_state_reports_distance_to_home():
    drone_config = build_drone_config(follow_value=0)
    drone_config.home_position = {"lat": 35.7244359, "long": 51.2766087, "alt": 1286.0}
    params = SimpleNamespace(enable_udp_telemetry=False, enable_default_subscriptions=False)

    communicator = DroneCommunicator(drone_config=drone_config, params=params, drones={})
    state = communicator.get_drone_state()

    assert 90 <= state["distance_to_home_m"] <= 92


def test_get_drone_state_hides_fallback_home_relative_values_without_px4_home():
    drone_config = build_drone_config(follow_value=0)
    drone_config.px4_home_position_set = False
    drone_config.home_position_source = "fallback_position"
    drone_config.relative_altitude_m = 1286.0
    params = SimpleNamespace(enable_udp_telemetry=False, enable_default_subscriptions=False)

    communicator = DroneCommunicator(drone_config=drone_config, params=params, drones={})
    state = communicator.get_drone_state()
    swarm_state = communicator.get_swarm_state()

    assert state["home_position_set"] is False
    assert state["distance_to_home_m"] is None
    assert state["relative_altitude_m"] is None
    assert state["altitude_report"]["sources"]["relative_home"]["valid"] is False
    assert state["altitude_source"] == "local_ned"
    assert state["altitude_display_m"] == 3.4
    assert swarm_state["relative_altitude_m"] is None
    assert swarm_state["altitude_source"] == "local_ned"


def test_get_drone_state_falls_back_to_cached_swarm_assignment():
    drone_config = build_drone_config(follow_value=1)

    def broken_read_swarm():
        raise RuntimeError("swarm file unavailable")

    drone_config.read_swarm = broken_read_swarm
    params = SimpleNamespace(enable_udp_telemetry=False, enable_default_subscriptions=False)

    communicator = DroneCommunicator(drone_config=drone_config, params=params, drones={})
    state = communicator.get_drone_state()

    assert state["follow_mode"] == 1


def test_get_swarm_state_exposes_realtime_fields():
    drone_config = build_drone_config(follow_value=0)
    params = SimpleNamespace(enable_udp_telemetry=False, enable_default_subscriptions=False)

    communicator = DroneCommunicator(drone_config=drone_config, params=params, drones={})
    state = communicator.get_swarm_state()

    assert state["hw_id"] == 3
    assert state["follow_mode"] == 0
    assert state["stream_seq"] == 12
    assert state["telemetry_timestamp_ms"] == 1234567890123
    assert state["source_frame"] == "local_ned"
    assert state["local_position_north"] == 1.2
    assert state["altitude_source"] == "relative_home"
    assert state["yaw_rate_deg_s"] == 4.5


def _command_params(*, sim_mode, command_runtime_dir=None):
    return SimpleNamespace(
        enable_udp_telemetry=False,
        enable_default_subscriptions=False,
        sim_mode=sim_mode,
        default_takeoff_alt=10.0,
        max_takeoff_alt=100.0,
        command_runtime_dir=command_runtime_dir,
    )


def test_ground_test_install_revalidates_runtime_and_preserves_prior_command_on_failure(
    tmp_path,
):
    drone_config = build_drone_config()
    drone_config.ground_test_request_file = "/previous/ground-test.json"
    previous = {
        "state": drone_config.state,
        "mission": drone_config.mission,
        "trigger_time": drone_config.trigger_time,
        "ground_test_request_file": drone_config.ground_test_request_file,
    }
    communicator = DroneCommunicator(
        drone_config=drone_config,
        params=_command_params(sim_mode=False, command_runtime_dir=str(tmp_path)),
        drones={drone_config.hw_id: drone_config},
    )

    with pytest.raises(CommandInstallationRejected, match="Real-aircraft"):
        communicator.process_command(
            {
                "mission_type": Mission.TEST.value,
                "trigger_time": 0,
                "ground_test_safety": {"mode": "sitl_not_applicable"},
            }
        )

    assert {
        "state": drone_config.state,
        "mission": drone_config.mission,
        "trigger_time": drone_config.trigger_time,
        "ground_test_request_file": drone_config.ground_test_request_file,
    } == previous


def test_ground_test_install_publishes_only_validated_acknowledgement(tmp_path):
    drone_config = build_drone_config()
    communicator = DroneCommunicator(
        drone_config=drone_config,
        params=_command_params(sim_mode=False, command_runtime_dir=str(tmp_path)),
        drones={drone_config.hw_id: drone_config},
    )
    acknowledgement = {
        "mode": "operator_acknowledged",
        "props_removed": True,
        "airframe_secured": True,
        "area_clear": True,
    }

    result = communicator.process_command(
        {
            "mission_type": Mission.TEST.value,
            "trigger_time": 0,
            "command_id": "ground-test-1",
            "ground_test_safety": acknowledgement,
        }
    )

    assert result.committed is True
    request_file = Path(drone_config.ground_test_request_file)
    assert request_file.is_file()
    assert json.loads(request_file.read_text(encoding="utf-8")) == {
        "ground_test_safety": acknowledgement,
    }
    assert drone_config.mission == Mission.TEST.value

    communicator.process_command(
        {
            "mission_type": Mission.LAND.value,
            "trigger_time": 0,
            "command_id": "land-1",
        }
    )
    assert drone_config.ground_test_request_file is None
