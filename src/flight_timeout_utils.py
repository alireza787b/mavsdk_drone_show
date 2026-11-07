"""
Shared timeout estimators for complete operator-visible flight lifecycles.

These helpers keep action commands, mission end-behavior logic, and runtime
validators aligned on the same conservative timing assumptions instead of
copying slightly different timeout math across the codebase.
"""

from __future__ import annotations

import math

from src.action_safety import (
    ACTION_SAFETY_CLEANUP_TIMEOUT_SEC,
    ACTION_STATE_OBSERVATION_TIMEOUT_SEC,
)
from src.params import Params


def _coerce_non_negative_altitude(relative_altitude_m) -> float | None:
    try:
        altitude_m = float(relative_altitude_m)
    except (TypeError, ValueError):
        return None

    # NaN / ±inf are not credible altitude telemetry. Treat them like parse
    # failures so callers use the intentional minimum-wait defaults instead of
    # letting max(0.0, nan) collapse to 0.0 and quietly inflate the budget.
    if not math.isfinite(altitude_m):
        return None

    return max(0.0, altitude_m)


def _non_negative_param(params, name: str, default: float) -> float:
    try:
        return max(0.0, float(getattr(params, name, default)))
    except (TypeError, ValueError):
        return max(0.0, float(default))


def calculate_takeoff_tracking_timeout(*, params=Params) -> int:
    """Budget the full standalone Take Off lifecycle, including safe failure.

    The command tracker must remain non-terminal until the node can report its
    authoritative result.  Arm retries are the largest conditional phase: each
    attempt may spend both its health wait and its bounded arm RPC timeout.
    Cleanup is included because a failed launch still owes the operator a
    structured recovery result.
    """

    try:
        arm_attempts = max(
            1,
            int(getattr(params, "OFFBOARD_ARM_MAX_ATTEMPTS", 3)),
        )
    except (TypeError, ValueError):
        arm_attempts = 3
    arm_health_sec = _non_negative_param(
        params,
        "OFFBOARD_ARM_HEALTH_TIMEOUT_SEC",
        15.0,
    )
    arm_action_sec = max(
        1.0,
        _non_negative_param(params, "OFFBOARD_ARM_ACTION_TIMEOUT_SEC", 15.0),
    )
    arm_retry_delay_sec = _non_negative_param(
        params,
        "OFFBOARD_ARM_RETRY_DELAY_SEC",
        2.0,
    )
    arm_budget_sec = (
        arm_attempts * (arm_health_sec + arm_action_sec)
        + max(0, arm_attempts - 1) * arm_retry_delay_sec
    )

    phase_budget_sec = sum(
        (
            _non_negative_param(
                params,
                "ACTION_MAVSDK_SERVER_START_TIMEOUT_SEC",
                10.0,
            ),
            _non_negative_param(
                params,
                "ACTION_VEHICLE_CONNECTION_TIMEOUT_SEC",
                10.0,
            ),
            _non_negative_param(params, "TAKEOFF_PREFLIGHT_TIMEOUT_SEC", 30.0),
            ACTION_STATE_OBSERVATION_TIMEOUT_SEC,
            arm_budget_sec,
            _non_negative_param(
                params,
                "TAKEOFF_ARMED_CONFIRM_TIMEOUT_SEC",
                10.0,
            ),
            _non_negative_param(
                params,
                "TAKEOFF_STATE_TRANSITION_TIMEOUT_SEC",
                15.0,
            ),
            _non_negative_param(
                params,
                "TAKEOFF_ALTITUDE_CONFIRM_TIMEOUT_SEC",
                60.0,
            ),
            _non_negative_param(
                params,
                "TAKEOFF_FINAL_STATE_CONFIRM_TIMEOUT_SEC",
                20.0,
            ),
            ACTION_SAFETY_CLEANUP_TIMEOUT_SEC,
            _non_negative_param(
                params,
                "COMMAND_TRACKING_ACTION_BUFFER_SEC",
                30.0,
            ),
        )
    )
    return math.ceil(phase_budget_sec)


def calculate_land_disarm_timeout(relative_altitude_m, *, params=Params) -> int:
    """
    Estimate a realistic wait budget for LAND to reach full disarm.

    LAND can transition immediately while the vehicle still has a long descent
    ahead. A fixed wait threshold creates false failures for otherwise healthy
    descents, especially in SITL or large-area high-altitude missions.
    """
    minimum_wait = int(getattr(params, "LAND_ACTION_MIN_DISARM_WAIT_SEC", 45))
    altitude_m = _coerce_non_negative_altitude(relative_altitude_m)
    if altitude_m is None:
        return minimum_wait

    descent_rate = max(0.1, float(getattr(params, "LAND_ACTION_ASSUMED_DESCENT_RATE_MPS", 2.5)))
    buffer_sec = max(0, int(getattr(params, "LAND_ACTION_DISARM_BUFFER_SEC", 30)))
    maximum_wait = max(minimum_wait, int(getattr(params, "LAND_ACTION_MAX_DISARM_WAIT_SEC", 900)))
    estimated_wait = math.ceil(minimum_wait + (altitude_m / descent_rate) + buffer_sec)
    return max(minimum_wait, min(maximum_wait, estimated_wait))


def calculate_controlled_landing_timeout(relative_altitude_m, *, params=Params) -> int:
    """
    Estimate how long a low-altitude precision descent may need before touchdown.

    Controlled landing is meant for the final meters near the ground. The timeout
    should scale with the actual remaining altitude instead of using a single
    hard-coded constant that either trips too early or hides real failures.
    """
    minimum_wait = int(getattr(params, "CONTROLLED_LANDING_TIMEOUT", 7))
    altitude_m = _coerce_non_negative_altitude(relative_altitude_m)
    if altitude_m is None:
        return minimum_wait

    descent_rate = max(0.1, abs(float(getattr(params, "CONTROLLED_DESCENT_SPEED", 0.5))))
    buffer_sec = max(0, int(getattr(params, "CONTROLLED_LANDING_BUFFER_SEC", 5)))
    maximum_wait = max(minimum_wait, int(getattr(params, "CONTROLLED_LANDING_MAX_TIMEOUT_SEC", 120)))
    estimated_wait = math.ceil(minimum_wait + (altitude_m / descent_rate) + buffer_sec)
    return max(minimum_wait, min(maximum_wait, estimated_wait))


def _calculate_rtl_completion_timeout(
    relative_altitude_m,
    *,
    params=Params,
    base_timeout_attr: str,
    buffer_attr: str,
    max_timeout_attr: str,
    default_base_timeout: int,
    default_buffer_sec: int,
    default_max_timeout: int,
) -> int:
    """Estimate how long an RTL flow may need to fully return, land, and disarm."""
    base_timeout = int(getattr(params, base_timeout_attr, default_base_timeout))
    rtl_buffer_sec = max(0, int(getattr(params, buffer_attr, default_buffer_sec)))
    maximum_timeout = max(
        base_timeout,
        int(getattr(params, max_timeout_attr, default_max_timeout)),
    )
    landing_timeout = calculate_land_disarm_timeout(relative_altitude_m, params=params)
    estimated_wait = landing_timeout + rtl_buffer_sec
    return max(base_timeout, min(maximum_timeout, estimated_wait))


def calculate_rtl_completion_timeout(relative_altitude_m, *, params=Params) -> int:
    """
    Estimate the full timeout budget for a standalone RETURN_RTL action.

    The vehicle may spend significant time traveling home before the final
    landing and disarm, so completion should not be treated as "mode accepted".
    """
    return _calculate_rtl_completion_timeout(
        relative_altitude_m,
        params=params,
        base_timeout_attr="RTL_ACTION_COMPLETION_TIMEOUT",
        buffer_attr="RTL_ACTION_COMPLETION_BUFFER_SEC",
        max_timeout_attr="RTL_ACTION_COMPLETION_MAX_TIMEOUT",
        default_base_timeout=300,
        default_buffer_sec=120,
        default_max_timeout=1200,
    )


def calculate_swarm_rtl_completion_timeout(relative_altitude_m, *, params=Params) -> int:
    """
    Estimate the full timeout budget for Swarm Trajectory `return_home`.

    This wraps the LAND/disarm estimate with extra time for the RTL leg back to
    home before the aircraft starts the actual descent.
    """
    return _calculate_rtl_completion_timeout(
        relative_altitude_m,
        params=params,
        base_timeout_attr="SWARM_TRAJECTORY_RTL_COMPLETION_TIMEOUT",
        buffer_attr="SWARM_TRAJECTORY_RTL_COMPLETION_BUFFER_SEC",
        max_timeout_attr="SWARM_TRAJECTORY_RTL_COMPLETION_MAX_TIMEOUT",
        default_base_timeout=600,
        default_buffer_sec=180,
        default_max_timeout=1800,
    )
