"""Shared timeout policy for GCS-proxied onboard ULog operations."""

from __future__ import annotations

import math
import os


DEFAULT_DRONE_ULOG_PROXY_TIMEOUT_SECONDS = 30.0
DEFAULT_DRONE_ULOG_SUMMARY_TIMEOUT_SECONDS = 90.0


def drone_ulog_proxy_timeout_seconds() -> float:
    """Return the canonical timeout for ULog inventory and maintenance calls."""

    return DEFAULT_DRONE_ULOG_PROXY_TIMEOUT_SECONDS


def drone_ulog_summary_timeout_seconds() -> float:
    """Return the bounded timeout for staged ULog summary parsing."""

    try:
        value = float(
            os.getenv(
                "MDS_ULOG_SUMMARY_TIMEOUT_SEC",
                str(DEFAULT_DRONE_ULOG_SUMMARY_TIMEOUT_SECONDS),
            )
        )
    except (TypeError, ValueError):
        return DEFAULT_DRONE_ULOG_SUMMARY_TIMEOUT_SECONDS
    # Non-finite or non-positive overrides must not yield unbounded client waits.
    if not math.isfinite(value) or value <= 0:
        return DEFAULT_DRONE_ULOG_SUMMARY_TIMEOUT_SECONDS
    return value
