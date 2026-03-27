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
    mock_drone_config.is_armed = True
    mock_drone_config.custom_mode = 50593792

    controller._update_pre_arm_status()

    assert mock_drone_config.is_ready_to_arm is True
    assert mock_drone_config.readiness_status == "ready"
    home_check = next(check for check in mock_drone_config.readiness_checks if check["id"] == "home")
    assert home_check["ready"] is True


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
