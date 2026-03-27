"""
Shared timeout estimators for long-running landing / return-to-home flows.

These helpers keep action commands, mission end-behavior logic, and runtime
validators aligned on the same conservative timing assumptions instead of
copying slightly different timeout math across the codebase.
"""

from __future__ import annotations

import math

from src.params import Params


def _coerce_non_negative_altitude(relative_altitude_m) -> float | None:
    try:
        return max(0.0, float(relative_altitude_m))
    except (TypeError, ValueError):
        return None


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


def calculate_swarm_rtl_completion_timeout(relative_altitude_m, *, params=Params) -> int:
    """
    Estimate the full timeout budget for Swarm Trajectory `return_home`.

    This wraps the LAND/disarm estimate with extra time for the RTL leg back to
    home before the aircraft starts the actual descent.
    """
    base_timeout = int(getattr(params, "SWARM_TRAJECTORY_RTL_COMPLETION_TIMEOUT", 600))
    rtl_buffer_sec = max(0, int(getattr(params, "SWARM_TRAJECTORY_RTL_COMPLETION_BUFFER_SEC", 180)))
    maximum_timeout = max(
        base_timeout,
        int(getattr(params, "SWARM_TRAJECTORY_RTL_COMPLETION_MAX_TIMEOUT", 1800)),
    )
    landing_timeout = calculate_land_disarm_timeout(relative_altitude_m, params=params)
    estimated_wait = landing_timeout + rtl_buffer_sec
    return max(base_timeout, min(maximum_timeout, estimated_wait))
