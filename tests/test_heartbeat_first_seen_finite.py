"""Unit tests for non-finite heartbeat first_seen normalization."""

from __future__ import annotations

import math

import telemetry as tel


def test_normalize_heartbeat_first_seen_rejects_non_finite() -> None:
    assert tel._normalize_heartbeat_first_seen(float("inf")) is None
    assert tel._normalize_heartbeat_first_seen(float("nan")) is None
    assert tel._normalize_heartbeat_first_seen("inf") is None
    assert tel._normalize_heartbeat_first_seen("nan") is None


def test_normalize_heartbeat_first_seen_rejects_non_positive_and_garbage() -> None:
    assert tel._normalize_heartbeat_first_seen(-1) is None
    assert tel._normalize_heartbeat_first_seen(0) is None
    assert tel._normalize_heartbeat_first_seen("") is None
    assert tel._normalize_heartbeat_first_seen(None) is None
    assert tel._normalize_heartbeat_first_seen("nope") is None


def test_normalize_heartbeat_first_seen_seconds_to_ms() -> None:
    assert tel._normalize_heartbeat_first_seen(1699999999.0) == 1699999999000
    assert tel._normalize_heartbeat_first_seen(1699999999000) == 1699999999000
    assert math.isfinite(float(tel._normalize_heartbeat_first_seen(1700000000.0)))
