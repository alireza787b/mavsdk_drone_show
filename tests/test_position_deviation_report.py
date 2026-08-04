import pytest

import origin


NOW_MS = 1_800_000_000_000


def _valid_global_position(**overrides):
    telemetry = {
        "hw_id": "2",
        "telemetry_available": True,
        "telemetry_error": None,
        "is_armed": False,
        "gps_fix_type": 3,
        "global_position_valid": True,
        "position_source": "global_position_int",
        "position_lat": 48.8566406,
        "position_long": 2.359282,
        "position_alt": 50.704,
        "global_position_timestamp_ms": NOW_MS - 250,
    }
    telemetry.update(overrides)
    return telemetry


def _build_report(monkeypatch, telemetry):
    monkeypatch.setattr(origin.time, "time", lambda: NOW_MS / 1000)
    monkeypatch.setattr(origin.Params, "acceptable_deviation", 3.0, raising=False)
    monkeypatch.setattr(origin.Params, "LOCAL_MAVLINK_STALE_TIMEOUT_SEC", 15, raising=False)
    monkeypatch.setattr(origin.Params, "sim_mode", False, raising=False)

    return origin.build_position_deviation_report(
        {"2": telemetry},
        [{"hw_id": "2", "pos_id": 7}],
        origin_lat=48.8566406,
        origin_lon=2.359282,
        origin_alt=50.704,
        trajectory_resolver=lambda pos_id, sim_mode: (0.0, 0.0),
    )


@pytest.mark.parametrize(
    ("telemetry", "message_fragment"),
    [
        pytest.param(
            _valid_global_position(
                global_position_valid=False,
                position_source="unavailable",
                position_lat=0.0,
                position_long=0.0,
                position_alt=0.0,
                position_unavailable_reason=(
                    "GPS fix present, waiting for valid PX4 global position."
                ),
            ),
            "no usable PX4 global position",
            id="raw-3d-fix-without-global-position",
        ),
        pytest.param(
            _valid_global_position(global_position_timestamp_ms=NOW_MS - 15_001),
            "global position is 15.0s old",
            id="stale-global-position",
        ),
        pytest.param(
            _valid_global_position(
                telemetry_available=False,
                telemetry_error="Drone telemetry endpoint timed out.",
            ),
            "timed out",
            id="telemetry-unavailable",
        ),
    ],
)
def test_position_deviation_report_treats_unusable_position_as_no_telemetry(
    monkeypatch,
    telemetry,
    message_fragment,
):
    report = _build_report(monkeypatch, telemetry)

    deviation = report["deviations"]["2"]
    assert deviation["status"] == "no_telemetry"
    assert deviation["current"] is None
    assert deviation["deviation"] is None
    assert message_fragment in deviation["message"]
    assert report["summary"]["online"] == 0
    assert report["summary"]["no_telemetry"] == 1
    assert report["summary"]["within_threshold"] == 0


def test_position_deviation_report_accepts_fresh_in_flight_global_position(monkeypatch):
    report = _build_report(
        monkeypatch,
        _valid_global_position(is_armed=True),
    )

    deviation = report["deviations"]["2"]
    assert deviation["status"] == "ok"
    assert deviation["current"] == {
        "lat": 48.8566406,
        "lon": 2.359282,
        "north": pytest.approx(0.0, abs=1e-6),
        "east": pytest.approx(0.0, abs=1e-6),
        "position_source": "global_position_int",
        "position_age_ms": 250,
    }
    assert deviation["deviation"]["horizontal"] == pytest.approx(0.0, abs=1e-6)
    assert deviation["deviation"]["within_threshold"] is True
    assert report["summary"]["online"] == 1
    assert report["summary"]["no_telemetry"] == 0
    assert report["summary"]["within_threshold"] == 1


def test_position_deviation_report_rejects_cross_hardware_telemetry(monkeypatch):
    report = _build_report(
        monkeypatch,
        _valid_global_position(hw_id="99"),
    )

    deviation = report["deviations"]["2"]
    assert deviation["status"] == "no_telemetry"
    assert deviation["current"] is None
    assert "identity" in deviation["message"].lower()
    assert report["summary"]["online"] == 0
