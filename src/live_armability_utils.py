"""Shared helpers for live armability probe timing."""

from __future__ import annotations

import math
from typing import Any


def _finite_component(value: Any, default: float) -> float:
    """Coerce to float; non-finite or invalid values use default."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def calculate_live_armability_request_timeout(*, params) -> float:
    """
    Total HTTP budget needed for the on-demand live armability endpoint.

    The probe may spend time both establishing a local MAVSDK connection and
    then waiting for PX4 health to become armable, so callers must budget for
    both phases plus a small transport margin.
    """
    connect_timeout = max(
        0.1,
        _finite_component(
            getattr(params, "LIVE_ARMABILITY_PROBE_CONNECT_TIMEOUT_SEC", 5.0),
            5.0,
        ),
    )
    probe_timeout = max(
        0.1,
        _finite_component(
            getattr(params, "LIVE_ARMABILITY_PROBE_TIMEOUT_SEC", 6.0),
            6.0,
        ),
    )
    http_buffer_sec = max(
        0.5,
        _finite_component(
            getattr(params, "LIVE_ARMABILITY_PROBE_HTTP_BUFFER_SEC", 2.0),
            2.0,
        ),
    )
    return connect_timeout + probe_timeout + http_buffer_sec
