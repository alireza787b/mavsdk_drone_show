import math

import pytest

from smart_swarm_src.motion_state_validity import (
    validate_leader_motion_sample,
    validate_own_motion_state,
)


NOW_MS = 1_800_000_000_000


def _global_sample(**overrides):
    sample = {
        "hw_id": 1,
        "position_lat": 35.7,
        "position_long": 51.3,
        "position_alt": 1_280.0,
        "velocity_north": 0.1,
        "velocity_east": -0.2,
        "velocity_down": 0.0,
        "yaw_deg": 42.0,
        "global_position_valid": True,
        "global_position_timestamp_ms": NOW_MS - 100,
        "source_frame": "local_ned",
    }
    sample.update(overrides)
    return sample


def _local_sample(**overrides):
    sample = {
        "hw_id": 1,
        "local_position_north": 10.0,
        "local_position_east": -2.0,
        "local_position_down": -8.0,
        "local_velocity_north": 0.1,
        "local_velocity_east": -0.2,
        "local_velocity_down": 0.0,
        "yaw_deg": 42.0,
        "source_frame": "local_ned",
        "source_time_boot_ms": 54_321,
        "local_position_timestamp_ms": NOW_MS - 100,
        "global_position_valid": False,
    }
    sample.update(overrides)
    return sample


def _own_state(**overrides):
    state = {
        "pos_n": 1.0,
        "pos_e": 2.0,
        "pos_d": -10.0,
        "vel_n": 0.1,
        "vel_e": 0.2,
        "vel_d": 0.0,
    }
    state.update(overrides)
    return state


def _validate_global(sample):
    return validate_leader_motion_sample(
        sample,
        expected_hw_id=1,
        use_local_ned=False,
        now_epoch_ms=NOW_MS,
        max_source_age_sec=0.75,
    )


def _validate_local(sample):
    return validate_leader_motion_sample(
        sample,
        expected_hw_id="1",
        use_local_ned=True,
        now_epoch_ms=NOW_MS,
        max_source_age_sec=0.75,
    )


def test_global_leader_sample_accepts_fresh_authoritative_motion():
    result = _validate_global(_global_sample())

    assert result.valid is True
    assert result.code == "ok"
    assert result.source == "global_lla_ned"
    assert result.age_sec == pytest.approx(0.1)


def test_global_path_uses_global_evidence_even_when_local_data_is_advertised():
    result = _validate_global(_global_sample(source_frame="local_ned"))

    assert result.valid is True


def test_leader_sample_rejects_unexpected_hardware_identity():
    result = _validate_global(_global_sample(hw_id=2))

    assert result.valid is False
    assert result.code == "leader_mismatch"


def test_global_leader_sample_requires_authoritative_position_validity():
    result = _validate_global(_global_sample(global_position_valid=False))

    assert result.valid is False
    assert result.code == "global_position_invalid"


@pytest.mark.parametrize("field_name", [
    "position_lat",
    "position_long",
    "position_alt",
    "velocity_north",
    "velocity_east",
    "velocity_down",
    "yaw_deg",
])
def test_global_leader_sample_rejects_non_finite_motion(field_name):
    result = _validate_global(_global_sample(**{field_name: math.nan}))

    assert result.valid is False
    assert result.code == "motion_value_invalid"


@pytest.mark.parametrize(
    ("timestamp_ms", "expected_code"),
    [
        (0, "source_timestamp_invalid"),
        (NOW_MS - 751, "source_timestamp_stale"),
        (NOW_MS + 251, "source_timestamp_future"),
    ],
)
def test_global_leader_sample_rejects_bad_source_time(timestamp_ms, expected_code):
    result = _validate_global(_global_sample(global_position_timestamp_ms=timestamp_ms))

    assert result.valid is False
    assert result.code == expected_code


def test_local_leader_sample_accepts_fresh_local_motion_when_explicitly_enabled():
    result = _validate_local(_local_sample())

    assert result.valid is True
    assert result.source == "local_ned"
    assert result.age_sec == pytest.approx(0.1)


def test_local_leader_sample_requires_local_source_frame():
    result = _validate_local(_local_sample(source_frame="global_lla_ned"))

    assert result.valid is False
    assert result.code == "local_frame_unavailable"


@pytest.mark.parametrize("field_name", [
    "local_position_north",
    "local_position_east",
    "local_position_down",
    "local_velocity_north",
    "local_velocity_east",
    "local_velocity_down",
])
def test_local_leader_sample_rejects_non_finite_motion(field_name):
    result = _validate_local(_local_sample(**{field_name: math.inf}))

    assert result.valid is False
    assert result.code == "motion_value_invalid"


@pytest.mark.parametrize("source_time_boot_ms", [0, None, math.nan])
def test_local_leader_sample_rejects_invalid_boot_time(source_time_boot_ms):
    result = _validate_local(_local_sample(source_time_boot_ms=source_time_boot_ms))

    assert result.valid is False
    assert result.code == "source_boot_timestamp_invalid"


@pytest.mark.parametrize(
    ("timestamp_ms", "expected_code"),
    [
        (0, "source_timestamp_invalid"),
        (NOW_MS - 751, "source_timestamp_stale"),
        (NOW_MS + 251, "source_timestamp_future"),
    ],
)
def test_local_leader_sample_rejects_bad_receipt_time(timestamp_ms, expected_code):
    result = _validate_local(_local_sample(local_position_timestamp_ms=timestamp_ms))

    assert result.valid is False
    assert result.code == expected_code


def test_local_data_does_not_bypass_invalid_global_evidence_when_local_path_is_disabled():
    result = _validate_global(_local_sample())

    assert result.valid is False
    assert result.code == "global_position_invalid"


def test_small_cross_node_clock_skew_is_tolerated_without_negative_age():
    result = _validate_global(_global_sample(global_position_timestamp_ms=NOW_MS + 200))

    assert result.valid is True
    assert result.age_sec == 0.0


def test_own_motion_state_accepts_fresh_monotonic_update():
    result = validate_own_motion_state(
        _own_state(),
        updated_monotonic=99.8,
        now_monotonic=100.0,
        max_age_sec=0.75,
    )

    assert result.valid is True
    assert result.age_sec == pytest.approx(0.2)


@pytest.mark.parametrize("field_name", ["pos_n", "pos_e", "pos_d", "vel_n", "vel_e", "vel_d"])
def test_own_motion_state_rejects_non_finite_motion(field_name):
    result = validate_own_motion_state(
        _own_state(**{field_name: math.inf}),
        updated_monotonic=99.8,
        now_monotonic=100.0,
        max_age_sec=0.75,
    )

    assert result.valid is False
    assert result.code == "motion_value_invalid"


@pytest.mark.parametrize(
    ("updated_monotonic", "expected_code"),
    [
        (0, "source_timestamp_invalid"),
        (99.0, "source_timestamp_stale"),
        (100.001, "source_timestamp_future"),
    ],
)
def test_own_motion_state_rejects_bad_monotonic_update_time(updated_monotonic, expected_code):
    result = validate_own_motion_state(
        _own_state(),
        updated_monotonic=updated_monotonic,
        now_monotonic=100.0,
        max_age_sec=0.75,
    )

    assert result.valid is False
    assert result.code == expected_code
