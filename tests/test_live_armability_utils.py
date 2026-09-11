"""Tests for live armability timeout helper."""

import math
from types import SimpleNamespace

from src.live_armability_utils import calculate_live_armability_request_timeout


def test_happy_path_sums_components():
    params = SimpleNamespace(
        LIVE_ARMABILITY_PROBE_CONNECT_TIMEOUT_SEC=5.0,
        LIVE_ARMABILITY_PROBE_TIMEOUT_SEC=6.0,
        LIVE_ARMABILITY_PROBE_HTTP_BUFFER_SEC=2.0,
    )
    assert calculate_live_armability_request_timeout(params=params) == 13.0


def test_applies_minimum_floors():
    params = SimpleNamespace(
        LIVE_ARMABILITY_PROBE_CONNECT_TIMEOUT_SEC=0.01,
        LIVE_ARMABILITY_PROBE_TIMEOUT_SEC=0.01,
        LIVE_ARMABILITY_PROBE_HTTP_BUFFER_SEC=0.01,
    )
    assert calculate_live_armability_request_timeout(params=params) == 0.1 + 0.1 + 0.5


def test_non_finite_falls_back_to_defaults():
    params = SimpleNamespace(
        LIVE_ARMABILITY_PROBE_CONNECT_TIMEOUT_SEC=math.inf,
        LIVE_ARMABILITY_PROBE_TIMEOUT_SEC=math.nan,
        LIVE_ARMABILITY_PROBE_HTTP_BUFFER_SEC=float("-inf"),
    )
    assert calculate_live_armability_request_timeout(params=params) == 5.0 + 6.0 + 2.0


def test_invalid_type_falls_back():
    params = SimpleNamespace(
        LIVE_ARMABILITY_PROBE_CONNECT_TIMEOUT_SEC="bad",
        LIVE_ARMABILITY_PROBE_TIMEOUT_SEC=None,
        LIVE_ARMABILITY_PROBE_HTTP_BUFFER_SEC=object(),
    )
    assert calculate_live_armability_request_timeout(params=params) == 13.0
