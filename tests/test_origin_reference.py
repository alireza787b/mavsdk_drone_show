from copy import deepcopy

import pytest

from origin_reference import OriginReferenceError, resolve_origin_reference


NOW_MS = 1_800_000_000_000
MAX_AGE_MS = 15_000


def _valid_telemetry_row(**overrides):
    row = {
        "hw_id": "2",
        "pos_id": 99,
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
    row.update(overrides)
    return row


def _resolve(*, hw_id="2", config=None, telemetry=None, now_ms=NOW_MS, max_age_ms=MAX_AGE_MS):
    return resolve_origin_reference(
        hw_id=hw_id,
        drones_config=config or [{"hw_id": 2, "pos_id": 7}],
        telemetry_snapshot=telemetry or {2: _valid_telemetry_row()},
        now_ms=now_ms,
        max_age_ms=max_age_ms,
    )


def _assert_reference_error(code, **kwargs):
    with pytest.raises(OriginReferenceError) as exc_info:
        _resolve(**kwargs)

    assert exc_info.value.code == code
    return exc_info.value


def test_resolve_origin_reference_returns_fresh_global_position_and_configured_slot():
    reference = _resolve()

    assert reference == {
        "hw_id": "2",
        # The configured assignment is authoritative; the telemetry row's
        # deliberately different pos_id must not choose the show trajectory.
        "pos_id": 7,
        "latitude": 48.8566406,
        "longitude": 2.359282,
        "altitude_msl": 50.704,
        "position_source": "global_position_int",
        "position_timestamp_ms": NOW_MS - 250,
        "position_age_ms": 250,
        "gps_fix_type": 3,
    }


def test_resolve_origin_reference_does_not_treat_raw_3d_fix_as_global_position():
    telemetry = {
        "2": _valid_telemetry_row(
            global_position_valid=False,
            position_lat=0.0,
            position_long=0.0,
            position_alt=0.0,
            position_source="unavailable",
            position_unavailable_reason="GPS fix present, waiting for valid PX4 global position.",
        )
    }

    error = _assert_reference_error(
        "ORIGIN_REFERENCE_GLOBAL_POSITION_UNAVAILABLE",
        telemetry=telemetry,
    )

    assert error.status_code == 409
    assert "GPS receiver fix" in error.message
    assert "waiting for valid PX4 global position" in error.message


def test_resolve_origin_reference_rejects_stale_global_position():
    telemetry = {
        "2": _valid_telemetry_row(
            global_position_timestamp_ms=NOW_MS - MAX_AGE_MS - 1,
        )
    }

    error = _assert_reference_error(
        "ORIGIN_REFERENCE_POSITION_STALE",
        telemetry=telemetry,
    )

    assert "sample no older than 15.0s" in error.message


def test_resolve_origin_reference_rejects_unavailable_telemetry():
    telemetry = {
        "2": _valid_telemetry_row(
            telemetry_available=False,
            telemetry_error="Drone telemetry endpoint timed out.",
        )
    }

    error = _assert_reference_error(
        "ORIGIN_REFERENCE_TELEMETRY_UNAVAILABLE",
        telemetry=telemetry,
    )

    assert "timed out" in error.message


def test_resolve_origin_reference_rejects_armed_drone():
    telemetry = {"2": _valid_telemetry_row(is_armed=True)}

    error = _assert_reference_error(
        "ORIGIN_REFERENCE_ARMED",
        telemetry=telemetry,
    )

    assert "must be disarmed" in error.message


@pytest.mark.parametrize(
    "updates",
    [
        {"position_lat": 0.0, "position_long": 0.0},
        {"position_lat": 91.0},
        {"position_long": -181.0},
        {"position_lat": "not-a-coordinate"},
        {"position_long": float("nan")},
    ],
)
def test_resolve_origin_reference_rejects_invalid_coordinates(updates):
    telemetry = {"2": _valid_telemetry_row(**updates)}

    _assert_reference_error(
        "ORIGIN_REFERENCE_COORDINATES_INVALID",
        telemetry=telemetry,
    )


@pytest.mark.parametrize("altitude", [None, "not-an-altitude", float("nan"), float("inf")])
def test_resolve_origin_reference_rejects_invalid_absolute_msl_altitude(altitude):
    telemetry = {"2": _valid_telemetry_row(position_alt=altitude)}

    _assert_reference_error(
        "ORIGIN_REFERENCE_ALTITUDE_UNAVAILABLE",
        telemetry=telemetry,
    )


def test_resolve_origin_reference_rejects_unknown_hardware_before_using_telemetry():
    telemetry = {"99": deepcopy(_valid_telemetry_row(hw_id="99"))}

    error = _assert_reference_error(
        "ORIGIN_REFERENCE_NOT_CONFIGURED",
        hw_id="99",
        telemetry=telemetry,
    )

    assert error.status_code == 404
    assert "HW 99" in error.message
