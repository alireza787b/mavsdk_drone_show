from src.telemetry_display import build_altitude_report, build_gps_report


def test_altitude_report_prefers_relative_home_altitude():
    report = build_altitude_report(
        position={"alt": 488.5},
        local_position_ned={"time_boot_ms": 1200, "timestamp_ms": 1732270245123, "z": -5.0},
        gps_fix_type=3,
        global_position_timestamp_ms=1732270245123,
        relative_altitude_m=12.3,
        now_ms=1732270245200,
    )

    assert report["available"] is True
    assert report["display_m"] == 12.3
    assert report["source"] == "relative_home"
    assert report["frame"] == "relative_home"
    assert report["msl_m"] == 488.5
    assert report["local_up_m"] == 5.0
    assert report["sources"]["relative_home"]["fresh"] is True
    assert report["stale"] is False


def test_altitude_report_uses_local_ned_without_global_position():
    report = build_altitude_report(
        position={"alt": 0.0},
        local_position_ned={"time_boot_ms": 1200, "timestamp_ms": 1732270245123, "z": -2.5},
        gps_fix_type=0,
        global_position_timestamp_ms=0,
        relative_altitude_m=None,
        now_ms=1732270245200,
    )

    assert report["available"] is True
    assert report["display_m"] == 2.5
    assert report["source"] == "local_ned"
    assert report["requires_global_position"] is False
    assert report["sources"]["local_ned"]["fresh"] is True


def test_altitude_report_uses_baro_before_absolute_msl_when_no_relative_or_local():
    report = build_altitude_report(
        position={"alt": 488.5},
        local_position_ned={"time_boot_ms": 0, "z": 0.0},
        gps_fix_type=0,
        global_position_timestamp_ms=1732270245123,
        relative_altitude_m=None,
        baro_altitude_m=4.2,
        baro_timestamp_ms=1732270245180,
        now_ms=1732270245200,
    )

    assert report["display_m"] == 4.2
    assert report["source"] == "baro"
    assert report["baro_m"] == 4.2


def test_altitude_report_keeps_stale_last_known_value_with_stale_flag():
    report = build_altitude_report(
        position={"alt": 488.5},
        local_position_ned={},
        gps_fix_type=3,
        global_position_timestamp_ms=1732270240000,
        relative_altitude_m=12.3,
        now_ms=1732270245000,
    )

    assert report["available"] is True
    assert report["source"] == "relative_home"
    assert report["display_m"] == 12.3
    assert report["stale"] is True


def test_gps_report_hides_mavlink_sentinel_values():
    report = build_gps_report(
        fix_type=0,
        satellites_visible=255,
        hdop=655.35,
        vdop=655.35,
    )

    assert report["available"] is False
    assert report["satellites_visible"] is None
    assert report["hdop"] is None
    assert report["vdop"] is None
    assert report["fix_label"] == "No GPS"
