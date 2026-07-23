"""Fail-closed finite checks on assistant env float overrides."""

from __future__ import annotations

import pytest

from agent_runtime.assistant import _env_float
from agent_runtime.models import AgentRuntimeError


def test_env_float_missing_returns_default(monkeypatch):
    monkeypatch.delenv("MDS_TEST_ENV_FLOAT", raising=False)
    assert _env_float("MDS_TEST_ENV_FLOAT", 3.5) == 3.5
    monkeypatch.setenv("MDS_TEST_ENV_FLOAT", "")
    assert _env_float("MDS_TEST_ENV_FLOAT", 3.5) == 3.5


def test_env_float_parses_finite(monkeypatch):
    monkeypatch.setenv("MDS_TEST_ENV_FLOAT", "1.5")
    assert _env_float("MDS_TEST_ENV_FLOAT", 0.0) == 1.5
    monkeypatch.setenv("MDS_TEST_ENV_FLOAT", "0")
    assert _env_float("MDS_TEST_ENV_FLOAT", 9.0) == 0.0
    monkeypatch.setenv("MDS_TEST_ENV_FLOAT", "-2.25")
    assert _env_float("MDS_TEST_ENV_FLOAT", 0.0) == -2.25


def test_env_float_rejects_non_finite(monkeypatch):
    for poisoned in ("nan", "NaN", "inf", "+inf", "-inf", "Infinity"):
        monkeypatch.setenv("MDS_TEST_ENV_FLOAT", poisoned)
        with pytest.raises(AgentRuntimeError, match="finite"):
            _env_float("MDS_TEST_ENV_FLOAT", 1.0)


def test_env_float_rejects_non_numeric(monkeypatch):
    monkeypatch.setenv("MDS_TEST_ENV_FLOAT", "nope")
    with pytest.raises(AgentRuntimeError, match="number"):
        _env_float("MDS_TEST_ENV_FLOAT", 1.0)
