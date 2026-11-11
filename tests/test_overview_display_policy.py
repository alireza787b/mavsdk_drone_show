from types import SimpleNamespace

import pytest

from overview_display_policy import resolve_overview_display_policy
from presence import resolve_presence_thresholds


@pytest.fixture(autouse=True)
def clean_display_policy_environment(monkeypatch):
    for key in (
        "MDS_OVERVIEW_STALE_SEC",
        "MDS_PRESENCE_RECENT_LOSS_SEC",
        "MDS_PRESENCE_STALE_SEC",
        "MDS_PRESENCE_LONG_OFFLINE_SEC",
    ):
        monkeypatch.delenv(key, raising=False)


def test_display_policy_defaults():
    assert resolve_overview_display_policy() == {"stale_sec": 10.0, "available_sec": 60.0}


def test_display_policy_uses_params_and_environment_precedence(monkeypatch):
    params = SimpleNamespace(OVERVIEW_STALE_SEC=15, PRESENCE_STALE_SEC=90)
    assert resolve_overview_display_policy(params) == {"stale_sec": 15.0, "available_sec": 90.0}

    monkeypatch.setenv("MDS_OVERVIEW_STALE_SEC", "12.5")
    monkeypatch.setenv("MDS_PRESENCE_STALE_SEC", "75")
    assert resolve_overview_display_policy(params) == {"stale_sec": 12.5, "available_sec": 75.0}


@pytest.mark.parametrize("value", ["", "invalid", "NaN", "inf", "-inf", "0", "-1"])
def test_invalid_stale_environment_uses_valid_params(monkeypatch, value):
    monkeypatch.setenv("MDS_OVERVIEW_STALE_SEC", value)
    assert resolve_overview_display_policy(SimpleNamespace(OVERVIEW_STALE_SEC=14))["stale_sec"] == 14.0


@pytest.mark.parametrize("value", [None, "invalid", float("nan"), float("inf"), -float("inf"), 0, -1])
def test_invalid_stale_params_use_default(value):
    assert resolve_overview_display_policy(SimpleNamespace(OVERVIEW_STALE_SEC=value))["stale_sec"] == 10.0


def test_stale_cue_cannot_exceed_available_window(monkeypatch):
    monkeypatch.setenv("MDS_OVERVIEW_STALE_SEC", "200")
    monkeypatch.setenv("MDS_PRESENCE_STALE_SEC", "80")
    assert resolve_overview_display_policy() == {"stale_sec": 80.0, "available_sec": 80.0}


def test_available_window_uses_canonical_presence_normalization(monkeypatch):
    monkeypatch.setenv("MDS_PRESENCE_STALE_SEC", "5")
    params = SimpleNamespace(TELEMETRY_POLLING_TIMEOUT=10, heartbeat_interval=10)
    canonical = resolve_presence_thresholds(params)
    assert canonical.stale_sec == 30.0
    assert resolve_overview_display_policy(params)["available_sec"] == canonical.stale_sec
    assert resolve_presence_thresholds(params) == canonical


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 0, -1])
def test_invalid_resolved_available_window_has_finite_display_fallback(monkeypatch, value):
    monkeypatch.setattr(
        "overview_display_policy.resolve_presence_thresholds",
        lambda params: SimpleNamespace(stale_sec=value),
    )
    assert resolve_overview_display_policy() == {"stale_sec": 10.0, "available_sec": 60.0}


def test_typed_telemetry_policy_is_additive_for_legacy_construction():
    from schemas import TelemetryResponse

    payload = TelemetryResponse(telemetry={}, total_drones=0, online_drones=0, timestamp=1).model_dump()
    assert payload["telemetry"] == {}
    assert payload["display_policy"] == {"stale_sec": 10.0, "available_sec": 60.0}


@pytest.mark.parametrize(
    "policy",
    [
        {"stale_sec": float("nan"), "available_sec": 60},
        {"stale_sec": 10, "available_sec": float("inf")},
        {"stale_sec": 0, "available_sec": 60},
        {"stale_sec": 10, "available_sec": -1},
        {"stale_sec": 61, "available_sec": 60},
    ],
)
def test_typed_display_policy_rejects_invalid_windows(policy):
    from pydantic import ValidationError

    from schemas import OverviewDisplayPolicy

    with pytest.raises(ValidationError):
        OverviewDisplayPolicy(**policy)


def test_typed_telemetry_route_publishes_effective_policy(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api_routes.core import create_core_router

    monkeypatch.setenv("MDS_OVERVIEW_STALE_SEC", "18")
    deps = SimpleNamespace(
        telemetry_data_all_drones={},
        Params=SimpleNamespace(PRESENCE_STALE_SEC=95),
    )
    app = FastAPI()
    app.include_router(create_core_router(deps))

    with TestClient(app) as client:
        response = client.get("/api/v1/fleet/telemetry")

    assert response.status_code == 200
    assert response.headers["X-MDS-Server-Time"].isdigit()
    assert response.json()["display_policy"] == {"stale_sec": 18.0, "available_sec": 95.0}
    assert response.json()["telemetry"] == {}
    assert response.json()["online_drones"] == 0
