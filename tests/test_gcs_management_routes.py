from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_routes.management import create_management_router


def _make_deps():
    return SimpleNamespace(
        Params=SimpleNamespace(
            sim_mode=False,
            gcs_api_port=5000,
            GIT_AUTO_PUSH=True,
            acceptable_deviation=2.0,
        ),
        get_network_info_from_heartbeats=lambda: [{"hw_id": "1", "wifi": {"ssid": "mds"}}],
    )


def test_management_router_registers_expected_routes():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_management_router(deps))

    routes = {route.path for route in app.routes}

    assert "/get-gcs-config" in routes
    assert "/save-gcs-config" in routes
    assert "/get-network-info" in routes


def test_management_router_get_gcs_config_uses_live_params_after_router_creation():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_management_router(deps))

    deps.Params = SimpleNamespace(
        sim_mode=True,
        gcs_api_port=3030,
        GIT_AUTO_PUSH=False,
        acceptable_deviation=4.5,
    )

    with TestClient(app) as client:
        response = client.get("/get-gcs-config")

    assert response.status_code == 200
    assert response.json() == {
        "sim_mode": True,
        "gcs_port": 3030,
        "git_auto_push": False,
        "acceptable_deviation": 4.5,
    }


def test_management_router_save_gcs_config_returns_explicit_stub_ack():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_management_router(deps))

    with TestClient(app) as client:
        response = client.post("/save-gcs-config", json={"sim_mode": True})

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["status"] == "success"
    assert data["persisted"] is False
    assert data["warnings"]


def test_management_router_save_gcs_config_rejects_non_object_payload():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_management_router(deps))

    with TestClient(app) as client:
        response = client.post("/save-gcs-config", json=["not", "an", "object"])

    assert response.status_code == 400
    assert response.json()["detail"] == "GCS configuration payload must be a JSON object"


def test_management_router_get_network_info_uses_live_dependency_after_router_creation():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_management_router(deps))

    replacement = Mock(return_value=[{"hw_id": "9", "ethernet": {"interface": "eth0"}}])
    deps.get_network_info_from_heartbeats = replacement

    with TestClient(app) as client:
        response = client.get("/get-network-info")

    assert response.status_code == 200
    replacement.assert_called_once()
    assert response.json()[0]["hw_id"] == "9"
