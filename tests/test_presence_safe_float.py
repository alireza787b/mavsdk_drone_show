"""Unit tests for gcs-server presence threshold float sanitization."""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gcs-server"))

from presence import _safe_float, resolve_presence_thresholds


def test_safe_float_rejects_non_finite_and_negative():
    assert _safe_float("inf", 7.0) == 7.0
    assert _safe_float("-inf", 7.0) == 7.0
    assert _safe_float("nan", 7.0) == 7.0
    assert _safe_float(-1, 7.0) == 7.0
    assert _safe_float("nope", 7.0) == 7.0
    assert _safe_float("12.5", 7.0) == 12.5
    assert _safe_float(0, 7.0) == 0.0


def test_resolve_presence_thresholds_env_inf_falls_back(monkeypatch):
    params = SimpleNamespace(
        TELEMETRY_POLLING_TIMEOUT=5.0,
        heartbeat_interval=5.0,
        PRESENCE_RECENT_LOSS_SEC=30.0,
        PRESENCE_STALE_SEC=60.0,
        PRESENCE_LONG_OFFLINE_SEC=300.0,
    )
    monkeypatch.setenv("MDS_PRESENCE_STALE_SEC", "inf")
    monkeypatch.delenv("MDS_PRESENCE_RECENT_LOSS_SEC", raising=False)
    monkeypatch.delenv("MDS_PRESENCE_LONG_OFFLINE_SEC", raising=False)
    thresholds = resolve_presence_thresholds(params)
    assert thresholds.stale_sec == 60.0
    assert thresholds.live_sec == 10.0  # max(5, 5*2)
