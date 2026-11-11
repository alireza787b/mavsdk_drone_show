"""Overview heartbeat-display windows, never flight/command admission policy."""

from __future__ import annotations

import math
import os
from typing import Any

from presence import resolve_presence_thresholds


def _positive_finite(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if math.isfinite(parsed) and parsed > 0 else default


def resolve_overview_display_policy(params: Any | None = None) -> dict[str, float]:
    """Publish one bounded display policy without changing canonical presence.

    Availability retains heartbeat-observed aircraft using the existing presence
    stale window. Its earlier stale cue is an independent, display-only setting;
    neither window establishes telemetry freshness, readiness or armability.
    """

    available_sec = _positive_finite(resolve_presence_thresholds(params).stale_sec, 60.0)
    default_stale_sec = _positive_finite(getattr(params, "OVERVIEW_STALE_SEC", 10.0), 10.0)
    stale_sec = _positive_finite(os.environ.get("MDS_OVERVIEW_STALE_SEC"), default_stale_sec)
    return {"stale_sec": min(stale_sec, available_sec), "available_sec": available_sec}
