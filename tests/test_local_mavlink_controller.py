from collections import OrderedDict
import math
from types import SimpleNamespace
import pytest
from unittest.mock import Mock

from pymavlink import mavutil

from src.local_mavlink_controller import LocalMavlinkController
from src.px4_flight_modes import describe_px4_custom_mode


def build_controller(mock_drone_config):
    controller = LocalMavlinkController.__new__(LocalMavlinkController)
    controller.latest_messages = {}
    controller.debug_enabled = False
    controller.drone_config = mock_drone_config
    controller._initialize_source_binding()
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
    mock_drone_config.base_mode = 29
    mock_drone_config.custom_mode = (4 << 16) | (3 << 24)
    mock_drone_config.is_armed = False
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
    mock_drone_config.heartbeat_timestamp_ms = 0
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


def heartbeat_message(
    *,
    component_type,
    autopilot_type,
    base_mode,
    custom_mode,
    system_status,
    source_system=1,
    source_component=1,
):
    return SimpleNamespace(
        type=component_type,
        autopilot=autopilot_type,
        base_mode=base_mode,
        custom_mode=custom_mode,
        system_status=system_status,
        get_type=lambda: "HEARTBEAT",
        get_srcSystem=lambda: source_system,
        get_srcComponent=lambda: source_component,
    )


def vehicle_heartbeat(**overrides):
    values = dict(component_type=mavutil.mavlink.MAV_TYPE_QUADROTOR,
                  autopilot_type=mavutil.mavlink.MAV_AUTOPILOT_PX4,
                  base_mode=mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
                  custom_mode=(4 << 16) | (3 << 24),
                  system_status=mavutil.mavlink.MAV_STATE_STANDBY)
    values.update(overrides)
    return heartbeat_message(**values)


def state_message(kind, *, system=1, component=1, **fields):
    return SimpleNamespace(get_type=lambda: kind, get_srcSystem=lambda: system,
                           get_srcComponent=lambda: component, **fields)


def test_process_heartbeat_timestamps_the_exact_armed_sample(mock_drone_config, monkeypatch):
    controller = build_controller(mock_drone_config)
    monkeypatch.setattr(controller, "_now_ms", lambda: 1_765_000_000_123)
    msg = vehicle_heartbeat(
        base_mode=128,
        custom_mode=(4 << 16) | (3 << 24),
        system_status=4,
    )

    controller.process_heartbeat(msg)

    assert mock_drone_config.is_armed is True
    assert mock_drone_config.heartbeat_timestamp_ms == 1_765_000_000_123
    assert mock_drone_config.telemetry_timestamp_ms == 1_765_000_000_123
    assert mock_drone_config.telemetry_sequence == 1


def test_extended_sys_state_is_native_timestamped_and_source_bound(mock_drone_config, monkeypatch):
    controller = build_controller(mock_drone_config)
    monkeypatch.setattr(controller, '_now_ms', lambda: 12345)
    controller.process_message(vehicle_heartbeat())
    msg = SimpleNamespace(landed_state=2, get_type=lambda: 'EXTENDED_SYS_STATE',
                          get_srcSystem=lambda: 1, get_srcComponent=lambda: 1)
    controller.process_message(msg)
    assert mock_drone_config.landed_state == 2
    assert mock_drone_config.landed_state_timestamp_ms == 12345
    msg.landed_state = 1
    msg.get_srcComponent = lambda: 190
    controller.process_message(msg)
    assert mock_drone_config.landed_state == 2
    assert mock_drone_config.landed_state_timestamp_ms == 12345


def test_process_message_ignores_ground_station_heartbeat_without_refreshing_vehicle_state(
    mock_drone_config,
    monkeypatch,
):
    controller = build_controller(mock_drone_config)
    accepted_heartbeat = heartbeat_message(
        component_type=mavutil.mavlink.MAV_TYPE_QUADROTOR,
        autopilot_type=mavutil.mavlink.MAV_AUTOPILOT_PX4,
        base_mode=mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
        custom_mode=(4 << 16) | (4 << 24),
        system_status=mavutil.mavlink.MAV_STATE_STANDBY,
    )
    monkeypatch.setattr(controller, "_now_ms", lambda: 1_765_000_000_100)
    controller.process_message(accepted_heartbeat)

    state_before = {
        "base_mode": mock_drone_config.base_mode,
        "custom_mode": mock_drone_config.custom_mode,
        "system_status": mock_drone_config.system_status,
        "is_armed": mock_drone_config.is_armed,
        "heartbeat_timestamp_ms": mock_drone_config.heartbeat_timestamp_ms,
        "telemetry_timestamp_ms": mock_drone_config.telemetry_timestamp_ms,
        "telemetry_sequence": mock_drone_config.telemetry_sequence,
    }

    ground_station_heartbeat = heartbeat_message(
        component_type=mavutil.mavlink.MAV_TYPE_GCS,
        autopilot_type=mavutil.mavlink.MAV_AUTOPILOT_INVALID,
        base_mode=mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED,
        custom_mode=0,
        system_status=mavutil.mavlink.MAV_STATE_ACTIVE,
        source_system=255,
        source_component=190,
    )
    monkeypatch.setattr(controller, "_now_ms", lambda: 1_765_000_000_200)
    controller.process_message(ground_station_heartbeat)

    assert {
        "base_mode": mock_drone_config.base_mode,
        "custom_mode": mock_drone_config.custom_mode,
        "system_status": mock_drone_config.system_status,
        "is_armed": mock_drone_config.is_armed,
        "heartbeat_timestamp_ms": mock_drone_config.heartbeat_timestamp_ms,
        "telemetry_timestamp_ms": mock_drone_config.telemetry_timestamp_ms,
        "telemetry_sequence": mock_drone_config.telemetry_sequence,
    } == state_before
    assert controller.latest_messages["HEARTBEAT"] is accepted_heartbeat


def test_process_message_uses_heartbeat_classification_not_component_id(
    mock_drone_config,
):
    controller = build_controller(mock_drone_config)
    px4_heartbeat = heartbeat_message(
        component_type=mavutil.mavlink.MAV_TYPE_QUADROTOR,
        autopilot_type=mavutil.mavlink.MAV_AUTOPILOT_PX4,
        base_mode=mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
        custom_mode=(4 << 16) | (3 << 24),
        system_status=mavutil.mavlink.MAV_STATE_STANDBY,
        source_component=42,
    )

    controller.process_message(px4_heartbeat)

    assert mock_drone_config.custom_mode == (4 << 16) | (3 << 24)
    assert controller.latest_messages["HEARTBEAT"] is px4_heartbeat


def test_process_message_rejects_companion_heartbeat_with_invalid_autopilot(
    mock_drone_config,
):
    controller = build_controller(mock_drone_config)
    original_mode = mock_drone_config.custom_mode
    companion_heartbeat = heartbeat_message(
        component_type=mavutil.mavlink.MAV_TYPE_ONBOARD_CONTROLLER,
        autopilot_type=mavutil.mavlink.MAV_AUTOPILOT_INVALID,
        base_mode=mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED,
        custom_mode=0,
        system_status=mavutil.mavlink.MAV_STATE_ACTIVE,
        source_component=mavutil.mavlink.MAV_COMP_ID_ONBOARD_COMPUTER,
    )

    controller.process_message(companion_heartbeat)

    assert mock_drone_config.custom_mode == original_mode
    assert "HEARTBEAT" not in controller.latest_messages


@pytest.mark.parametrize('kind,handler', [
    ('GLOBAL_POSITION_INT', 'process_global_position_int'),
    ('HOME_POSITION', 'set_home_position'),
    ('BATTERY_STATUS', 'process_battery_status'),
    ('GPS_GLOBAL_ORIGIN', 'process_gps_global_origin'),
    ('ATTITUDE', 'process_attitude'),
    ('GPS_RAW_INT', 'process_gps_raw_int'),
    ('SYS_STATUS', 'process_sys_status'),
    ('LOCAL_POSITION_NED', 'process_local_position_ned'),
    ('SCALED_PRESSURE', 'process_scaled_pressure'),
    ('STATUSTEXT', 'process_status_text'),
    ('EXTENDED_SYS_STATE', 'process_extended_sys_state'),
])
def test_process_message_never_accepts_unbound_or_foreign_system_state(mock_drone_config, monkeypatch, kind, handler):
    controller = build_controller(mock_drone_config)
    accept = Mock()
    monkeypatch.setattr(controller, handler, accept)
    assert controller.process_message(state_message(kind)) is False
    assert kind not in controller.latest_messages
    assert controller.process_message(vehicle_heartbeat()) is True
    before = (mock_drone_config.telemetry_timestamp_ms, mock_drone_config.telemetry_sequence)
    assert controller.process_message(state_message(kind, system=2)) is False
    accept.assert_not_called()
    assert kind not in controller.latest_messages
    assert (mock_drone_config.telemetry_timestamp_ms, mock_drone_config.telemetry_sequence) == before
    assert controller.process_message(state_message(kind)) is True
    accept.assert_called_once()


def test_gps_sensor_component_of_bound_system_is_preserved(mock_drone_config, monkeypatch):
    controller = build_controller(mock_drone_config)
    monkeypatch.setattr(controller, '_now_ms', lambda: 1000)
    assert controller.process_message(vehicle_heartbeat(source_system=42, source_component=17)) is True
    sensor = state_message('GPS_RAW_INT', system=42, component=220, eph=80, epv=120,
                           fix_type=6, satellites_visible=17, alt=1280400)
    monkeypatch.setattr(controller, '_now_ms', lambda: 2000)
    assert controller.process_message(sensor) is True
    assert mock_drone_config.gps_fix_type == 6
    assert mock_drone_config.gps_raw_timestamp_ms == 2000
    assert mock_drone_config.gps_raw_altitude_m == 1280.4
    # A GPS sensor is not permitted to become the estimator/home/arming source.
    assert controller.process_message(state_message('HOME_POSITION', system=42, component=220)) is False
    assert controller.process_message(state_message('GLOBAL_POSITION_INT', system=42, component=220)) is False
    assert controller._autopilot_source == (42, 17)
    assert mock_drone_config.heartbeat_timestamp_ms == 1000


@pytest.mark.parametrize('kind', ['GPS_RAW_INT', 'BATTERY_STATUS', 'SCALED_PRESSURE'])
def test_sensor_component_allowance_never_accepts_another_classified_fc(mock_drone_config, kind):
    controller = build_controller(mock_drone_config)
    controller.process_message(vehicle_heartbeat())
    assert controller.process_message(vehicle_heartbeat(source_component=42)) is False
    assert controller.process_message(state_message(kind, component=42)) is False
    assert controller._autopilot_source == (1, 1)


@pytest.mark.parametrize('system,component', [(2, 1), (1, 42)])
def test_second_fc_collision_is_explicit_and_never_switches_on_silence(mock_drone_config, monkeypatch, caplog, system, component):
    controller = build_controller(mock_drone_config)
    monkeypatch.setattr(controller, '_now_ms', lambda: 1000)
    accepted = vehicle_heartbeat()
    controller.process_message(accepted)
    before = (mock_drone_config.is_armed, mock_drone_config.heartbeat_timestamp_ms,
              mock_drone_config.telemetry_sequence)
    monkeypatch.setattr(controller, '_now_ms', lambda: 1_000_000)
    other = vehicle_heartbeat(source_system=system, source_component=component,
                              base_mode=mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
    assert controller.process_message(other) is False
    assert controller.process_message(other) is False
    assert (mock_drone_config.is_armed, mock_drone_config.heartbeat_timestamp_ms,
            mock_drone_config.telemetry_sequence) == before
    assert controller.latest_messages['HEARTBEAT'] is accepted
    assert controller._autopilot_source == (1, 1)
    assert sum('Multiple FC MAVLink sources' in record.message for record in caplog.records) == 1


def test_explicit_mav_sys_id_is_independent_of_node_hw_id(mock_drone_config, caplog):
    mock_drone_config.hw_id = '7'
    mock_drone_config.config['mav_sys_id'] = '42'
    controller = build_controller(mock_drone_config)
    assert controller.process_message(vehicle_heartbeat(source_system=7)) is False
    assert controller._autopilot_source is None
    assert controller.process_message(vehicle_heartbeat(source_system=42)) is True
    assert controller._autopilot_source == (42, 1)
    assert 'configured mav_sys_id=42' in caplog.text


def test_first_ground_station_packet_cannot_select_vehicle_source(mock_drone_config):
    controller = build_controller(mock_drone_config)
    gcs = vehicle_heartbeat(component_type=mavutil.mavlink.MAV_TYPE_GCS,
                            autopilot_type=mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                            source_system=255, source_component=190)
    assert controller.process_message(gcs) is False
    assert controller._autopilot_source is None
    assert controller.process_message(vehicle_heartbeat(source_system=42, source_component=17)) is True
    assert controller._autopilot_source == (42, 17)


@pytest.mark.parametrize('expected', [None, '', 0, 256, True, '1.5'])
def test_invalid_explicit_mav_sys_id_fails_closed(mock_drone_config, expected, caplog):
    mock_drone_config.config['mav_sys_id'] = expected
    controller = build_controller(mock_drone_config)
    assert controller.process_message(vehicle_heartbeat()) is False
    assert controller._autopilot_source is None
    assert 'Invalid configured mav_sys_id' in caplog.text


@pytest.mark.parametrize('msg', [
    SimpleNamespace(get_type=lambda: 'HEARTBEAT', base_mode=128, custom_mode=1, system_status=4),
    state_message('HEARTBEAT'),
    vehicle_heartbeat(source_system=0),
    vehicle_heartbeat(source_component=0),
    vehicle_heartbeat(source_system=True),
    vehicle_heartbeat(autopilot_type=255),
    vehicle_heartbeat(component_type=255),
])
def test_incomplete_heartbeat_or_invalid_header_never_binds(mock_drone_config, msg):
    controller = build_controller(mock_drone_config)
    assert controller.process_message(msg) is False
    assert controller._autopilot_source is None
    assert mock_drone_config.heartbeat_timestamp_ms == 0
    assert 'HEARTBEAT' not in controller.latest_messages


def test_get_flight_mode_name_decodes_px4_wire_layout(mock_drone_config):
    controller = build_controller(mock_drone_config)

    assert controller._get_flight_mode_name((4 << 16) | (2 << 24)) == "Takeoff"
    assert controller._get_flight_mode_name((4 << 16) | (3 << 24)) == "Hold"
    assert controller._get_flight_mode_name((4 << 16) | (4 << 24)) == "Mission"
    assert controller._get_flight_mode_name((4 << 16) | (5 << 24)) == "Return"
    assert controller._get_flight_mode_name((4 << 16) | (6 << 24)) == "Land"
    assert controller._get_flight_mode_name((3 << 16) | (1 << 24)) == "Orbit"
    assert controller._get_flight_mode_name((3 << 16) | (2 << 24)) == "Position Slow"


def test_get_flight_mode_name_does_not_treat_reserved_bits_as_sub_mode(mock_drone_config):
    controller = build_controller(mock_drone_config)

    assert controller._get_flight_mode_name((4 << 16) | 4) == "Auto"


def test_shared_px4_mode_description_covers_mission_diagnostics():
    assert describe_px4_custom_mode((4 << 16) | (3 << 24)) == "Hold"
    assert describe_px4_custom_mode((4 << 16) | (5 << 24)) == "Return"
    assert describe_px4_custom_mode((4 << 16) | (6 << 24)) == "Land"
    assert describe_px4_custom_mode(6 << 16) == "Offboard"


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


@pytest.mark.parametrize('message,preflight,blocked', [
    ('Disarming denied: not landed', False, False),
    ('Disarm denied: airborne', False, False),
    ('Arming denied: heading estimate unstable', True, True),
    ('Arm denied: GPS invalid', True, True),
    ('Takeoff denied: not ready', True, True),
    ('Preflight Fail: GPS drift', True, True),
    ('Prearm check: sensors warming', True, False),
])
def test_status_text_classification_matches_complete_phrases(message, preflight, blocked):
    result = LocalMavlinkController._classify_status_text(message, 'warning')
    assert result == {'category': 'preflight' if preflight else 'system', 'blocks_readiness': blocked}


def test_disarming_denied_is_retained_without_becoming_preflight_blocker(mock_drone_config):
    controller = build_controller(mock_drone_config)
    controller.process_status_text(SimpleNamespace(
        text='Disarming denied: not landed', severity=2, id=0, chunk_seq=0,
    ))
    assert any(row['message'] == 'Disarming denied: not landed'
               and row['category'] == 'system' for row in mock_drone_config.status_messages)
    assert not any('disarming denied' in row['message'].lower()
                   for row in mock_drone_config.preflight_blockers)


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


def test_listener_reconnect_keeps_original_fc_and_collision_exclusions(mock_drone_config, monkeypatch):
    controller = build_controller(mock_drone_config)
    controller.local_mavlink_port = 12550
    controller.mav = Mock()
    controller.process_message(vehicle_heartbeat(source_system=42, source_component=17))
    controller.process_message(vehicle_heartbeat(source_system=42, source_component=220))
    original = controller.latest_messages['HEARTBEAT']
    timestamp = mock_drone_config.heartbeat_timestamp_ms
    monkeypatch.setattr(controller, '_open_mavlink_connection', lambda: Mock())
    controller._reset_mavlink_connection('original FC silent')
    assert controller._autopilot_source == (42, 17)
    assert controller._foreign_fc_components == {220}
    assert controller.process_message(vehicle_heartbeat(source_system=99)) is False
    assert controller.process_message(state_message('GPS_RAW_INT', system=42, component=220)) is False
    assert controller.latest_messages['HEARTBEAT'] is original
    assert mock_drone_config.heartbeat_timestamp_ms == timestamp
    monkeypatch.setattr(controller, '_now_ms', lambda: timestamp + 10000)
    assert controller.process_message(vehicle_heartbeat(source_system=42, source_component=17)) is True
    assert mock_drone_config.heartbeat_timestamp_ms == timestamp + 10000


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


def test_process_battery_status_preserves_operator_safety_evidence(mock_drone_config):
    controller = build_controller(mock_drone_config)
    msg = SimpleNamespace(
        voltages=[15300, 65535, 65535],
        battery_remaining=42,
        charge_state=1,
        fault_bitmask=4,
    )

    controller.process_battery_status(msg)

    assert mock_drone_config.battery == 15.3
    assert mock_drone_config.battery_remaining_percent == 42.0
    assert mock_drone_config.battery_charge_state == 1
    assert mock_drone_config.battery_fault_bitmask == 4
    assert mock_drone_config.battery_timestamp_ms > 0


def test_process_battery_status_marks_unknown_optional_values_unavailable(mock_drone_config):
    controller = build_controller(mock_drone_config)
    msg = SimpleNamespace(
        voltages=[16000],
        battery_remaining=-1,
    )

    controller.process_battery_status(msg)

    assert mock_drone_config.battery_remaining_percent is None
    assert mock_drone_config.battery_charge_state is None
    assert mock_drone_config.battery_fault_bitmask is None
    assert mock_drone_config.battery_timestamp_ms > 0


def test_process_attitude_tracks_yaw_rate(mock_drone_config):
    controller = build_controller(mock_drone_config)
    msg = SimpleNamespace(yaw=1.0, roll=0.0, pitch=0.0, pitchspeed=0.0, yawspeed=0.5)

    controller.process_attitude(msg)

    assert mock_drone_config.yaw > 0
    assert mock_drone_config.yaw_rate_deg_s > 28.0
    assert mock_drone_config.attitude_timestamp_ms > 0


def test_process_attitude_reports_euler_heading_rate_not_tilted_body_z_rate(mock_drone_config):
    controller = build_controller(mock_drone_config)
    msg = SimpleNamespace(yaw=1.0, roll=math.pi / 6, pitch=math.pi / 4,
                          pitchspeed=0.4, yawspeed=0.5)
    controller.process_attitude(msg)
    expected = math.degrees((0.4 * math.sin(msg.roll) + 0.5 * math.cos(msg.roll)) / math.cos(msg.pitch))
    assert mock_drone_config.yaw_rate_deg_s == pytest.approx(expected)


def test_process_attitude_marks_singular_heading_rate_unavailable(mock_drone_config):
    controller = build_controller(mock_drone_config)
    controller.process_attitude(SimpleNamespace(
        yaw=1.0, roll=0.0, pitch=math.pi / 2, pitchspeed=0.0, yawspeed=0.5))
    assert mock_drone_config.yaw_rate_deg_s is None


@pytest.mark.parametrize("yaw", [None, float('nan'), float('inf')])
def test_invalid_attitude_does_not_refresh_heading_age(mock_drone_config, yaw):
    controller = build_controller(mock_drone_config)
    mock_drone_config.attitude_timestamp_ms = 123
    controller.process_attitude(SimpleNamespace(yaw=yaw, yawspeed=0.5))
    assert mock_drone_config.attitude_timestamp_ms == 123


def test_invalid_yaw_rate_is_unavailable_not_nan_or_fake_zero(mock_drone_config):
    controller = build_controller(mock_drone_config)
    controller.process_attitude(SimpleNamespace(yaw=1.0, yawspeed=float('nan')))
    assert mock_drone_config.yaw_rate_deg_s is None
