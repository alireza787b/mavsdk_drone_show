from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import Mock

from src.local_mavlink_controller import LocalMavlinkController


def build_controller(mock_drone_config):
    controller = LocalMavlinkController.__new__(LocalMavlinkController)
    controller.latest_messages = {}
    controller.debug_enabled = False
    controller.drone_config = mock_drone_config
    controller.home_position_logged = False
    controller._status_text_buffers = {}
    controller._status_messages = OrderedDict()
    controller.log_debug = lambda *args, **kwargs: None
    controller.log_info = lambda *args, **kwargs: None
    controller.log_warning = lambda *args, **kwargs: None
    controller.run_telemetry_thread = Mock()
    controller.telemetry_thread = Mock()
    controller.telemetry_thread.is_alive.return_value = False
    mock_drone_config.radian_to_degrees_heading = lambda yaw_radians: yaw_radians * (180.0 / 3.141592653589793)

    mock_drone_config.system_status = 3
    mock_drone_config.custom_mode = 262147
    mock_drone_config.is_gyrometer_calibration_ok = True
    mock_drone_config.is_accelerometer_calibration_ok = True
    mock_drone_config.is_magnetometer_calibration_ok = True
    mock_drone_config.gps_fix_type = 3
    mock_drone_config.hdop = 0.8
    mock_drone_config.vdop = 1.2
    mock_drone_config.last_update_timestamp = 1
    mock_drone_config.status_messages = []
    mock_drone_config.preflight_blockers = []
    mock_drone_config.preflight_warnings = []
    mock_drone_config.readiness_checks = []
    mock_drone_config.readiness_status = "unknown"
    mock_drone_config.readiness_summary = ""
    mock_drone_config.preflight_last_update = 0
    mock_drone_config.home_position = {"lat": 35.0, "long": 51.0, "alt": 1278.0}
    mock_drone_config.px4_home_position_set = True
    mock_drone_config.home_position_source = "px4"
    mock_drone_config.telemetry_timestamp_ms = 0
    mock_drone_config.telemetry_sequence = 0
    mock_drone_config.gps_raw_timestamp_ms = 0
    mock_drone_config.gps_raw_altitude_m = None
    mock_drone_config.global_position_timestamp_ms = 0
    mock_drone_config.global_position_valid = False
    mock_drone_config.relative_altitude_m = None
    mock_drone_config.baro_altitude_m = None
    mock_drone_config.baro_timestamp_ms = 0
    mock_drone_config.position_source = "unavailable"
    mock_drone_config.yaw_rate_deg_s = 0.0

    return controller


def test_update_pre_arm_status_reports_ready(mock_drone_config):
    controller = build_controller(mock_drone_config)

    controller._update_pre_arm_status()

    assert mock_drone_config.is_ready_to_arm is True
    assert mock_drone_config.readiness_status == "ready"
    assert mock_drone_config.readiness_summary == "Ready to fly"
    assert mock_drone_config.preflight_blockers == []


def test_update_pre_arm_status_requires_home_position_before_takeoff(mock_drone_config):
    controller = build_controller(mock_drone_config)
    mock_drone_config.home_position = None
    mock_drone_config.px4_home_position_set = False
    mock_drone_config.is_armed = False
    mock_drone_config.custom_mode = 50593792

    controller._update_pre_arm_status()

    assert mock_drone_config.is_ready_to_arm is False
    assert mock_drone_config.readiness_status == "blocked"
    assert any("home position" in blocker["message"].lower() for blocker in mock_drone_config.preflight_blockers)
    home_check = next(check for check in mock_drone_config.readiness_checks if check["id"] == "home")
    assert home_check["ready"] is False


def test_update_pre_arm_status_allows_missing_home_when_already_airborne(mock_drone_config):
    controller = build_controller(mock_drone_config)
    mock_drone_config.home_position = None
    mock_drone_config.px4_home_position_set = False
    mock_drone_config.is_armed = True
    mock_drone_config.custom_mode = 50593792

    controller._update_pre_arm_status()

    assert mock_drone_config.is_ready_to_arm is True
    assert mock_drone_config.readiness_status == "ready"
    home_check = next(check for check in mock_drone_config.readiness_checks if check["id"] == "home")
    assert home_check["ready"] is True


def test_update_pre_arm_status_treats_uninit_system_state_as_advisory_when_px4_health_is_good(mock_drone_config):
    controller = build_controller(mock_drone_config)
    mock_drone_config.system_status = 0
    mock_drone_config.base_mode = 29
    mock_drone_config.custom_mode = 100925440
    mock_drone_config.home_position = {"lat": 35.0, "long": 51.0, "alt": 1278.0}
    mock_drone_config.is_armed = False

    controller._update_pre_arm_status()

    assert mock_drone_config.is_ready_to_arm is True
    assert mock_drone_config.readiness_status == "ready"
    assert "telemetry advisory" in mock_drone_config.readiness_summary.lower()
    assert mock_drone_config.preflight_blockers == []
    assert any(
        "system state reports uninit" in warning["message"].lower()
        for warning in mock_drone_config.preflight_warnings
    )
    system_check = next(check for check in mock_drone_config.readiness_checks if check["id"] == "system")
    assert system_check["ready"] is True
    assert "treated as advisory" in system_check["detail"].lower()


def test_process_status_text_surfaces_px4_blocker(mock_drone_config):
    controller = build_controller(mock_drone_config)
    msg = SimpleNamespace(
        text="Preflight Fail: ekf2 missing data",
        severity=4,
        id=0,
        chunk_seq=0,
    )

    controller.process_status_text(msg)

    assert mock_drone_config.is_ready_to_arm is False
    assert mock_drone_config.readiness_status == "blocked"
    assert mock_drone_config.preflight_blockers
    assert "ekf2 missing data" in mock_drone_config.preflight_blockers[0]["message"].lower()
    assert mock_drone_config.status_messages


def test_open_mavlink_connection_uses_explicit_udpin(mock_drone_config, monkeypatch):
    controller = build_controller(mock_drone_config)
    controller.local_mavlink_port = 12550

    captured = {}

    def fake_connection(connection_string):
        captured["connection_string"] = connection_string
        return object()

    monkeypatch.setattr("src.local_mavlink_controller.mavutil.mavlink_connection", fake_connection)

    controller._open_mavlink_connection()

    assert captured["connection_string"] == "udpin:127.0.0.1:12550"


def test_reset_mavlink_connection_reopens_listener(mock_drone_config, monkeypatch):
    controller = build_controller(mock_drone_config)
    controller.local_mavlink_port = 12550
    closed = {"called": False}

    class FakeMav:
        def close(self):
            closed["called"] = True

    controller.mav = FakeMav()
    new_connection = object()
    monkeypatch.setattr(controller, "_open_mavlink_connection", lambda: new_connection)

    controller._reset_mavlink_connection("test")

    assert closed["called"] is True
    assert controller.mav is new_connection


def test_process_global_position_int_sets_fallback_home_without_px4_truth(mock_drone_config):
    controller = build_controller(mock_drone_config)
    mock_drone_config.home_position = None
    mock_drone_config.px4_home_position_set = False
    mock_drone_config.home_position_source = "unknown"
    msg = SimpleNamespace(
        lat=int(35.123456 * 1E7),
        lon=int(51.2721 * 1E7),
        alt=int(1278.5 * 1E3),
        relative_alt=int(12.3 * 1E3),
        vx=0,
        vy=0,
        vz=0,
    )

    controller.process_global_position_int(msg)

    assert mock_drone_config.home_position == {
        "lat": 35.123456,
        "long": 51.2721,
        "alt": 1278.5,
    }
    assert mock_drone_config.px4_home_position_set is False
    assert mock_drone_config.home_position_source == "fallback_position"
    assert mock_drone_config.telemetry_timestamp_ms > 0
    assert mock_drone_config.telemetry_sequence == 1
    assert mock_drone_config.global_position_valid is True
    assert mock_drone_config.global_position_timestamp_ms > 0
    assert mock_drone_config.relative_altitude_m == 12.3
    assert mock_drone_config.position_source == "global_position_int"


def test_process_global_position_int_ignores_zero_zero_without_marking_live(mock_drone_config):
    controller = build_controller(mock_drone_config)
    mock_drone_config.position = {"lat": 47.0, "long": 8.0, "alt": 500.0}
    mock_drone_config.global_position_valid = True
    mock_drone_config.telemetry_timestamp_ms = 0
    msg = SimpleNamespace(
        lat=0,
        lon=0,
        alt=0,
        vx=0,
        vy=0,
        vz=0,
    )

    controller.process_global_position_int(msg)

    assert mock_drone_config.position == {"lat": 47.0, "long": 8.0, "alt": 500.0}
    assert mock_drone_config.global_position_valid is False
    assert mock_drone_config.telemetry_timestamp_ms == 0
    assert mock_drone_config.position_source == "invalid_global_position"


def test_process_gps_raw_int_records_raw_msl_altitude(mock_drone_config):
    controller = build_controller(mock_drone_config)
    msg = SimpleNamespace(
        eph=80,
        epv=120,
        fix_type=3,
        satellites_visible=14,
        alt=int(1280.4 * 1E3),
    )

    controller.process_gps_raw_int(msg)

    assert mock_drone_config.gps_fix_type == 3
    assert mock_drone_config.satellites_visible == 14
    assert mock_drone_config.gps_raw_altitude_m == 1280.4
    assert mock_drone_config.gps_raw_timestamp_ms > 0


def test_set_home_position_marks_px4_home_truth(mock_drone_config):
    controller = build_controller(mock_drone_config)
    mock_drone_config.px4_home_position_set = False
    mock_drone_config.home_position_source = "unknown"
    msg = SimpleNamespace(
        latitude=int(35.123456 * 1E7),
        longitude=int(51.2721 * 1E7),
        altitude=int(1278.5 * 1E3),
    )

    controller.set_home_position(msg)

    assert mock_drone_config.home_position == {
        "lat": 35.123456,
        "long": 51.2721,
        "alt": 1278.5,
    }
    assert mock_drone_config.px4_home_position_set is True
    assert mock_drone_config.home_position_source == "px4"


def test_process_local_position_ned_marks_high_res_telemetry_update(mock_drone_config):
    controller = build_controller(mock_drone_config)
    msg = SimpleNamespace(
        time_boot_ms=1234,
        x=1.0,
        y=2.0,
        z=-3.0,
        vx=0.1,
        vy=0.2,
        vz=-0.3,
    )

    controller.process_local_position_ned(msg)

    assert mock_drone_config.local_position_ned["time_boot_ms"] == 1234
    assert mock_drone_config.local_position_ned["timestamp_ms"] > 0
    assert mock_drone_config.telemetry_timestamp_ms > 0
    assert mock_drone_config.telemetry_sequence == 1


def test_process_scaled_pressure_records_baro_altitude(mock_drone_config):
    controller = build_controller(mock_drone_config)
    msg = SimpleNamespace(press_abs=1013.25)

    controller.process_scaled_pressure(msg)

    assert abs(mock_drone_config.baro_altitude_m) < 0.01
    assert mock_drone_config.baro_timestamp_ms > 0
    assert mock_drone_config.telemetry_sequence == 1


def test_process_attitude_tracks_yaw_rate(mock_drone_config):
    controller = build_controller(mock_drone_config)
    msg = SimpleNamespace(yaw=1.0, yawspeed=0.5)

    controller.process_attitude(msg)

    assert mock_drone_config.yaw > 0
    assert mock_drone_config.yaw_rate_deg_s > 28.0
