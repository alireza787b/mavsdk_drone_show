from types import SimpleNamespace

from src.drone_communicator import DroneCommunicator


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
        swarm={"follow": 1},
        last_update_timestamp=1234567890,
        telemetry_timestamp_ms=1234567890123,
        telemetry_sequence=12,
        yaw_rate_deg_s=4.5,
        local_position_ned={
            "time_boot_ms": 4567,
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
    assert communicator._get_live_swarm_assignment()["follow"] == 0


def test_get_drone_state_reports_distance_to_home():
    drone_config = build_drone_config(follow_value=0)
    drone_config.home_position = {"lat": 35.7244359, "long": 51.2766087, "alt": 1286.0}
    params = SimpleNamespace(enable_udp_telemetry=False, enable_default_subscriptions=False)

    communicator = DroneCommunicator(drone_config=drone_config, params=params, drones={})
    state = communicator.get_drone_state()

    assert 90 <= state["distance_to_home_m"] <= 92


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
    assert state["yaw_rate_deg_s"] == 4.5
