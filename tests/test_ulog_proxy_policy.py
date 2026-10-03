"""Unit tests for shared ULog proxy timeout policy."""

from __future__ import annotations

import math

import pytest

from src.ulog_proxy_policy import (
    DEFAULT_DRONE_ULOG_SUMMARY_TIMEOUT_SECONDS,
    drone_ulog_summary_timeout_seconds,
)


def test_summary_timeout_default_without_env(monkeypatch):
    monkeypatch.delenv("MDS_ULOG_SUMMARY_TIMEOUT_SEC", raising=False)
    assert drone_ulog_summary_timeout_seconds() == DEFAULT_DRONE_ULOG_SUMMARY_TIMEOUT_SECONDS


def test_summary_timeout_accepts_positive_finite(monkeypatch):
    monkeypatch.setenv("MDS_ULOG_SUMMARY_TIMEOUT_SEC", "12.5")
    assert drone_ulog_summary_timeout_seconds() == pytest.approx(12.5)


@pytest.mark.parametrize("raw", ["0", "-1", "nan", "inf", "-inf", "invalid"])
def test_summary_timeout_rejects_bad_overrides(monkeypatch, raw):
    monkeypatch.setenv("MDS_ULOG_SUMMARY_TIMEOUT_SEC", raw)
    assert drone_ulog_summary_timeout_seconds() == DEFAULT_DRONE_ULOG_SUMMARY_TIMEOUT_SECONDS
