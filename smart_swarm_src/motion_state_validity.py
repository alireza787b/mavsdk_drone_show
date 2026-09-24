"""Validity checks for motion state used by Smart Swarm control.

The control loop receives leader state over the network and own state from a
local telemetry task.  This module keeps the admission rules for those two
clock domains explicit: remote source timestamps use epoch milliseconds while
own-state freshness uses the process-local monotonic clock.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence


GLOBAL_MOTION_FIELDS = (
    "position_lat",
    "position_long",
    "position_alt",
    "velocity_north",
    "velocity_east",
    "velocity_down",
)
LOCAL_MOTION_FIELDS = (
    "local_position_north",
    "local_position_east",
    "local_position_down",
    "local_velocity_north",
    "local_velocity_east",
    "local_velocity_down",
)
OWN_MOTION_FIELDS = (
    "pos_n",
    "pos_e",
    "pos_d",
    "vel_n",
    "vel_e",
    "vel_d",
)


@dataclass(frozen=True)
class MotionStateValidity:
    """One deterministic motion-state admission decision."""

    valid: bool
    code: str
    reason: str
    source: str
    age_sec: float | None = None


def _decision(
    valid: bool,
    code: str,
    reason: str,
    source: str,
    *,
    age_sec: float | None = None,
) -> MotionStateValidity:
    return MotionStateValidity(
        valid=valid,
        code=code,
        reason=reason,
        source=source,
        age_sec=age_sec,
    )


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or not numeric.is_integer() or numeric <= 0:
        return None
    return int(numeric)


def _finite_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _first_invalid_numeric_field(sample: Mapping[str, Any], fields: Sequence[str]) -> str | None:
    for field_name in fields:
        if not _finite_number(sample.get(field_name)):
            return field_name
    return None


def _yaw_value(sample: Mapping[str, Any]) -> Any:
    yaw_deg = sample.get("yaw_deg")
    return yaw_deg if yaw_deg is not None else sample.get("yaw")


def _validate_epoch_source_timestamp(
    timestamp_ms: Any,
    *,
    now_epoch_ms: Any,
    max_source_age_sec: float,
    source: str,
    field_name: str,
    max_future_skew_sec: float,
) -> MotionStateValidity:
    if not _finite_number(now_epoch_ms) or float(now_epoch_ms) <= 0:
        return _decision(False, "invalid_now", "Current epoch time is invalid.", source)
    if not _finite_number(max_source_age_sec) or float(max_source_age_sec) < 0:
        return _decision(False, "invalid_age_limit", "Source age limit is invalid.", source)
    if not _finite_number(max_future_skew_sec) or float(max_future_skew_sec) < 0:
        return _decision(False, "invalid_skew_limit", "Source clock-skew limit is invalid.", source)
    if not _finite_number(timestamp_ms) or float(timestamp_ms) <= 0:
        return _decision(
            False,
            "source_timestamp_invalid",
            f"{field_name} must be a positive epoch timestamp.",
            source,
        )

    age_sec = (float(now_epoch_ms) - float(timestamp_ms)) / 1000.0
    if age_sec < -float(max_future_skew_sec):
        return _decision(
            False,
            "source_timestamp_future",
            f"{field_name} is in the future.",
            source,
            age_sec=age_sec,
        )
    if age_sec > float(max_source_age_sec):
        return _decision(
            False,
            "source_timestamp_stale",
            f"{field_name} is stale.",
            source,
            age_sec=age_sec,
        )
    return _decision(True, "ok", "Motion source is fresh.", source, age_sec=max(0.0, age_sec))


def validate_leader_motion_sample(
    sample: Mapping[str, Any],
    *,
    expected_hw_id: Any,
    use_local_ned: bool,
    now_epoch_ms: Any,
    max_source_age_sec: float,
    max_future_skew_sec: float = 0.25,
) -> MotionStateValidity:
    """Validate a leader sample before it becomes a control-loop input.

    ``use_local_ned`` is the caller's explicit frame selection.  The global
    path requires the producer's authoritative global-position validity and
    source timestamp.  The local path independently requires both a fresh
    local receipt timestamp and a positive PX4 boot clock.
    """

    source = "local_ned" if use_local_ned else "global_lla_ned"
    if not isinstance(sample, Mapping):
        return _decision(False, "sample_invalid", "Leader sample is not a mapping.", source)

    expected = _positive_int(expected_hw_id)
    actual = _positive_int(sample.get("hw_id"))
    if expected is None:
        return _decision(False, "expected_leader_invalid", "Expected leader hw_id is invalid.", source)
    if actual != expected:
        return _decision(
            False,
            "leader_mismatch",
            f"Leader sample hw_id {actual!r} does not match expected hw_id {expected}.",
            source,
        )

    if not _finite_number(_yaw_value(sample)):
        return _decision(False, "motion_value_invalid", "Leader yaw is not finite.", source)

    attitude = _validate_epoch_source_timestamp(
        sample.get("attitude_timestamp_ms"),
        now_epoch_ms=now_epoch_ms,
        max_source_age_sec=max_source_age_sec,
        source="attitude",
        field_name="attitude_timestamp_ms",
        max_future_skew_sec=max_future_skew_sec,
    )
    if not attitude.valid:
        return attitude

    if use_local_ned:
        if sample.get("source_frame") != "local_ned":
            return _decision(
                False,
                "local_frame_unavailable",
                "Leader sample does not identify a valid local NED source.",
                source,
            )

        invalid_field = _first_invalid_numeric_field(sample, LOCAL_MOTION_FIELDS)
        if invalid_field is not None:
            return _decision(
                False,
                "motion_value_invalid",
                f"Leader field {invalid_field} is not finite.",
                source,
            )

        source_time_boot_ms = sample.get("source_time_boot_ms")
        if not _finite_number(source_time_boot_ms) or float(source_time_boot_ms) <= 0:
            return _decision(
                False,
                "source_boot_timestamp_invalid",
                "source_time_boot_ms must be positive for local NED control.",
                source,
            )

        return _validate_epoch_source_timestamp(
            sample.get("local_position_timestamp_ms"),
            now_epoch_ms=now_epoch_ms,
            max_source_age_sec=max_source_age_sec,
            source=source,
            field_name="local_position_timestamp_ms",
            max_future_skew_sec=max_future_skew_sec,
        )

    if sample.get("global_position_valid") is not True:
        return _decision(
            False,
            "global_position_invalid",
            "Leader producer does not report a valid global position.",
            source,
        )

    invalid_field = _first_invalid_numeric_field(sample, GLOBAL_MOTION_FIELDS)
    if invalid_field is not None:
        return _decision(
            False,
            "motion_value_invalid",
            f"Leader field {invalid_field} is not finite.",
            source,
        )

    latitude = float(sample["position_lat"])
    longitude = float(sample["position_long"])
    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        return _decision(
            False,
            "global_position_out_of_range",
            "Leader latitude or longitude is outside its valid range.",
            source,
        )

    return _validate_epoch_source_timestamp(
        sample.get("global_position_timestamp_ms"),
        now_epoch_ms=now_epoch_ms,
        max_source_age_sec=max_source_age_sec,
        source=source,
        field_name="global_position_timestamp_ms",
        max_future_skew_sec=max_future_skew_sec,
    )


def validate_own_motion_state(
    state: Mapping[str, Any],
    *,
    updated_monotonic: Any,
    now_monotonic: Any,
    max_age_sec: float,
) -> MotionStateValidity:
    """Validate local follower motion using only the monotonic clock domain."""

    source = "own_local_ned"
    if not isinstance(state, Mapping):
        return _decision(False, "sample_invalid", "Own motion state is not a mapping.", source)

    invalid_field = _first_invalid_numeric_field(state, OWN_MOTION_FIELDS)
    if invalid_field is not None:
        return _decision(
            False,
            "motion_value_invalid",
            f"Own-state field {invalid_field} is not finite.",
            source,
        )

    if not _finite_number(now_monotonic) or float(now_monotonic) <= 0:
        return _decision(False, "invalid_now", "Current monotonic time is invalid.", source)
    if not _finite_number(max_age_sec) or float(max_age_sec) < 0:
        return _decision(False, "invalid_age_limit", "Own-state age limit is invalid.", source)
    if not _finite_number(updated_monotonic) or float(updated_monotonic) <= 0:
        return _decision(
            False,
            "source_timestamp_invalid",
            "Own-state monotonic update time must be positive.",
            source,
        )

    age_sec = float(now_monotonic) - float(updated_monotonic)
    if age_sec < 0:
        return _decision(
            False,
            "source_timestamp_future",
            "Own-state monotonic update time is in the future.",
            source,
            age_sec=age_sec,
        )
    if age_sec > float(max_age_sec):
        return _decision(
            False,
            "source_timestamp_stale",
            "Own motion state is stale.",
            source,
            age_sec=age_sec,
        )
    return _decision(True, "ok", "Own motion state is fresh.", source, age_sec=age_sec)
