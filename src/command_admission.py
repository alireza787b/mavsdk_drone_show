"""Typed advisory admission checks for cached node flight state.

The companion's local MAVLink cache is useful for rejecting obviously unsafe
commands before they are queued, but it is not flight authority. Action
processes must still sample MAVSDK immediately before a safety-critical mode
change. Keeping this distinction explicit prevents cached state from being
mistaken for a successful flight precondition.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

class AirborneAdmissionStatus(str, Enum):
    READY = "ready"
    POLICY_INVALID = "policy_invalid"
    HEARTBEAT_UNAVAILABLE = "heartbeat_unavailable"
    HEARTBEAT_STALE = "heartbeat_stale"
    ARMED_UNAVAILABLE = "armed_unavailable"
    DISARMED = "disarmed"
    HOME_UNAVAILABLE = "home_unavailable"
    ALTITUDE_UNAVAILABLE = "altitude_unavailable"
    ALTITUDE_STALE = "altitude_stale"
    NOT_AIRBORNE = "not_airborne"
    LANDED_STATE_UNAVAILABLE = "landed_state_unavailable"
    LANDED_STATE_STALE = "landed_state_stale"


@dataclass(frozen=True)
class CachedAirborneAdmission:
    """One fail-closed evaluation of timestamped companion telemetry."""

    status: AirborneAdmissionStatus
    detail: str
    observed_at_ms: int
    heartbeat_age_ms: int | None = None
    altitude_age_ms: int | None = None
    armed: bool | None = None
    relative_altitude_m: float | None = None
    landed_state: int | None = None
    landed_state_age_ms: int | None = None
    source: str = "local_mavlink_cache"

    @property
    def accepted(self) -> bool:
        return self.status is AirborneAdmissionStatus.READY


def _timestamp_age_ms(value: Any, *, now_ms: int) -> tuple[int | None, str | None]:
    try:
        timestamp_ms = int(value)
    except (TypeError, ValueError):
        return None, "timestamp is unavailable"
    if timestamp_ms <= 0:
        return None, "timestamp is unavailable"
    if timestamp_ms > now_ms + 1_000:
        return None, "timestamp is in the future"
    return max(0, now_ms - timestamp_ms), None


def evaluate_cached_airborne_admission(
    drone_config: Any,
    *,
    max_age_sec: float,
    now_ms: int | None = None,
) -> CachedAirborneAdmission:
    """Require native armed/IN_AIR evidence and fresh guidance position/home.

    This is an early node admission check only. The action implementation is
    the authoritative last-moment safety boundary and repeats the observation
    from its own MAVSDK connection.
    """

    observed_at_ms = int(now_ms if now_ms is not None else time.time_ns() // 1_000_000)
    try:
        max_age_ms = int(float(max_age_sec) * 1_000)
    except (TypeError, ValueError, OverflowError):
        max_age_ms = 0
    if max_age_ms <= 0:
        return CachedAirborneAdmission(
            status=AirborneAdmissionStatus.POLICY_INVALID,
            detail="Local MAVLink freshness policy is invalid; command admission failed closed.",
            observed_at_ms=observed_at_ms,
        )

    heartbeat_age_ms, heartbeat_error = _timestamp_age_ms(
        getattr(drone_config, "heartbeat_timestamp_ms", 0),
        now_ms=observed_at_ms,
    )
    if heartbeat_error is not None:
        return CachedAirborneAdmission(
            status=AirborneAdmissionStatus.HEARTBEAT_UNAVAILABLE,
            detail=f"Fresh PX4 heartbeat/arming evidence is unavailable ({heartbeat_error}).",
            observed_at_ms=observed_at_ms,
        )
    if heartbeat_age_ms is None or heartbeat_age_ms > max_age_ms:
        age_text = "unknown" if heartbeat_age_ms is None else f"{heartbeat_age_ms / 1000.0:.1f}s"
        return CachedAirborneAdmission(
            status=AirborneAdmissionStatus.HEARTBEAT_STALE,
            detail=(
                f"PX4 heartbeat/arming evidence is stale (age {age_text}; "
                f"limit {max_age_ms / 1000.0:.1f}s)."
            ),
            observed_at_ms=observed_at_ms,
            heartbeat_age_ms=heartbeat_age_ms,
        )

    armed = getattr(drone_config, "is_armed", None)
    if type(armed) is not bool:
        return CachedAirborneAdmission(
            status=AirborneAdmissionStatus.ARMED_UNAVAILABLE,
            detail="PX4 armed state is unavailable in the latest heartbeat.",
            observed_at_ms=observed_at_ms,
            heartbeat_age_ms=heartbeat_age_ms,
        )
    if not armed:
        return CachedAirborneAdmission(
            status=AirborneAdmissionStatus.DISARMED,
            detail="The latest fresh PX4 heartbeat reports the drone is disarmed.",
            observed_at_ms=observed_at_ms,
            heartbeat_age_ms=heartbeat_age_ms,
            armed=False,
        )

    landed_age, landed_error = _timestamp_age_ms(
        getattr(drone_config, "landed_state_timestamp_ms", 0), now_ms=observed_at_ms,
    )
    landed_state = getattr(drone_config, "landed_state", None)
    if landed_error is not None or type(landed_state) is not int or landed_state not in {1, 2, 3, 4}:
        return CachedAirborneAdmission(
            status=AirborneAdmissionStatus.LANDED_STATE_UNAVAILABLE,
            detail="Native PX4 landed-state evidence is unavailable or undefined.",
            observed_at_ms=observed_at_ms, heartbeat_age_ms=heartbeat_age_ms,
            armed=True, landed_state=landed_state, landed_state_age_ms=landed_age,
        )
    if landed_age is None or landed_age > max_age_ms:
        return CachedAirborneAdmission(
            status=AirborneAdmissionStatus.LANDED_STATE_STALE,
            detail="Native PX4 landed-state evidence is stale.",
            observed_at_ms=observed_at_ms, heartbeat_age_ms=heartbeat_age_ms,
            armed=True, landed_state=landed_state, landed_state_age_ms=landed_age,
        )
    if landed_state != 2:  # MAV_LANDED_STATE_IN_AIR
        return CachedAirborneAdmission(
            status=AirborneAdmissionStatus.NOT_AIRBORNE,
            detail="PX4 does not report IN_AIR; climb/landing/ground state is not Start admission.",
            observed_at_ms=observed_at_ms, heartbeat_age_ms=heartbeat_age_ms,
            armed=True, landed_state=landed_state, landed_state_age_ms=landed_age,
        )

    if getattr(drone_config, "px4_home_position_set", False) is not True:
        return CachedAirborneAdmission(
            status=AirborneAdmissionStatus.HOME_UNAVAILABLE,
            detail=(
                "PX4 home position is not established; cached relative altitude "
                "cannot be treated as home-relative evidence."
            ),
            observed_at_ms=observed_at_ms,
            heartbeat_age_ms=heartbeat_age_ms,
            armed=True,
        )

    altitude_age_ms, altitude_error = _timestamp_age_ms(
        getattr(drone_config, "global_position_timestamp_ms", 0),
        now_ms=observed_at_ms,
    )
    raw_altitude = getattr(drone_config, "relative_altitude_m", None)
    try:
        relative_altitude_m = float(raw_altitude)
    except (TypeError, ValueError):
        relative_altitude_m = math.nan
    if altitude_error is not None or not math.isfinite(relative_altitude_m):
        reason = altitude_error or "relative altitude is unavailable"
        return CachedAirborneAdmission(
            status=AirborneAdmissionStatus.ALTITUDE_UNAVAILABLE,
            detail=f"Fresh home-relative altitude evidence is unavailable ({reason}).",
            observed_at_ms=observed_at_ms,
            heartbeat_age_ms=heartbeat_age_ms,
            altitude_age_ms=altitude_age_ms,
            armed=True,
        )
    if altitude_age_ms is None or altitude_age_ms > max_age_ms:
        age_text = "unknown" if altitude_age_ms is None else f"{altitude_age_ms / 1000.0:.1f}s"
        return CachedAirborneAdmission(
            status=AirborneAdmissionStatus.ALTITUDE_STALE,
            detail=(
                f"Home-relative altitude evidence is stale (age {age_text}; "
                f"limit {max_age_ms / 1000.0:.1f}s)."
            ),
            observed_at_ms=observed_at_ms,
            heartbeat_age_ms=heartbeat_age_ms,
            altitude_age_ms=altitude_age_ms,
            armed=True,
            relative_altitude_m=relative_altitude_m,
        )
    return CachedAirborneAdmission(
        status=AirborneAdmissionStatus.READY,
        detail=(
            "Fresh local evidence reports armed and PX4 IN_AIR with guidance position/home."
        ),
        observed_at_ms=observed_at_ms,
        heartbeat_age_ms=heartbeat_age_ms,
        altitude_age_ms=altitude_age_ms,
        armed=True,
        relative_altitude_m=relative_altitude_m,
        landed_state=landed_state,
        landed_state_age_ms=landed_age,
    )


def evaluate_cached_hold_admission(drone_config: Any, *, max_age_sec: float, now_ms: int | None = None) -> CachedAirborneAdmission:
    """Advisory Hold only needs a current heartbeat and known arming bit."""
    now_ms = int(now_ms if now_ms is not None else time.time_ns() // 1_000_000)
    age, error = _timestamp_age_ms(getattr(drone_config, "heartbeat_timestamp_ms", 0), now_ms=now_ms)
    try:
        max_age_ms = int(float(max_age_sec) * 1000)
    except (TypeError, ValueError, OverflowError):
        max_age_ms = 0
    armed = getattr(drone_config, "is_armed", None)
    status, detail = AirborneAdmissionStatus.READY, "Fresh heartbeat/arming evidence; action must confirm live state."
    if max_age_ms <= 0:
        status, detail = AirborneAdmissionStatus.POLICY_INVALID, "Invalid heartbeat freshness policy."
    elif error is not None:
        status, detail = AirborneAdmissionStatus.HEARTBEAT_UNAVAILABLE, "Fresh heartbeat/arming evidence is unavailable."
    elif age is None or age > max_age_ms:
        status, detail = AirborneAdmissionStatus.HEARTBEAT_STALE, "PX4 heartbeat/arming evidence is stale."
    elif type(armed) is not bool:
        status, detail = AirborneAdmissionStatus.ARMED_UNAVAILABLE, "PX4 arming bit is unavailable."
    return CachedAirborneAdmission(status=status, detail=detail, observed_at_ms=now_ms,
                                  heartbeat_age_ms=age, armed=armed if type(armed) is bool else None)
