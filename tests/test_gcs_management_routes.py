from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import api_routes.management as management_module
from api_routes.management import create_management_router


def _make_deps():
    return SimpleNamespace(
        MDS_VERSION="5.2",
        Params=SimpleNamespace(
            sim_mode=False,
            gcs_api_port=5000,
            GIT_AUTO_PUSH=True,
            acceptable_deviation=2.0,
            GIT_REPO_URL="https://github.com/demo/customer-mds.git",
            GIT_BRANCH="customer-demo",
        ),
        get_network_info_from_heartbeats=lambda: [{"hw_id": "1", "wifi": {"ssid": "mds"}}],
    )


def test_management_router_registers_expected_routes():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_management_router(deps))

    routes = {route.path for route in app.routes}

    assert "/api/v1/system/gcs-config" in routes
    assert "/api/v1/system/runtime-status" in routes
    assert "/api/v1/fleet/network-details" in routes


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
        response = client.get("/api/v1/system/gcs-config")

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
        response = client.put("/api/v1/system/gcs-config", json={"sim_mode": True})

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["status"] == "success"
    assert data["persisted"] is False
    assert data["warnings"]


def test_management_router_runtime_status_uses_live_runtime_and_profile(monkeypatch, tmp_path):
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_management_router(deps))

    gcs_env = tmp_path / "gcs.env"
    gcs_env.write_text("MDS_MODE=real\n", encoding="utf-8")
    token_file = tmp_path / "token.txt"
    token_file.write_text("demo", encoding="utf-8")

    monkeypatch.setattr(
        management_module,
        "resolve_runtime_mode",
        lambda: SimpleNamespace(mode="real", sim_mode=False, source="env:MDS_MODE"),
    )
    monkeypatch.setattr(
        management_module,
        "load_deployment_profile",
        lambda: SimpleNamespace(
            profile_id="customer-alpha",
            source="file:/tmp/deployment.env",
            connectivity_backend="smart-wifi-manager",
            smart_wifi_manager_repo_url_https="https://github.com/demo/smart-wifi-manager.git",
            smart_wifi_manager_ref="v1.2.3",
            mavlink_management_mode="managed",
            mavlink_anywhere_repo_url_https="https://github.com/demo/mavlink-anywhere.git",
            mavlink_anywhere_ref="v9.9.9",
            mavlink_anywhere_install_dir="/opt/demo-mavlink",
            mavlink_anywhere_dashboard_listen="0.0.0.0:9070",
            mavlink_anywhere_skip_dashboard=False,
        ),
    )
    monkeypatch.setenv("MDS_GCS_SYSTEM_CONFIG", str(gcs_env))
    monkeypatch.setenv("MDS_INSTALL_DIR", "/opt/demo-gcs")
    monkeypatch.setenv("MDS_GIT_AUTH_TOKEN_FILE", str(token_file))
    monkeypatch.delenv("MDS_GIT_SSH_KEY_FILE", raising=False)

    with TestClient(app) as client:
        response = client.get("/api/v1/system/runtime-status")

    assert response.status_code == 200
    data = response.json()
    assert data["version"] == "5.2"
    assert data["mode"] == "real"
    assert data["mode_source"] == "env:MDS_MODE"
    assert data["repo_url"] == "https://github.com/demo/customer-mds.git"
    assert data["repo_branch"] == "customer-demo"
    assert data["repo_access_mode"] == "https_token_file"
    assert data["gcs_config_path"] == str(gcs_env)
    assert data["gcs_config_present"] is True
    assert data["git_auth_token_file"] == str(token_file)
    assert data["git_auth_token_file_readable"] is True
    assert data["fleet_defaults"]["connectivity_backend"] == "smart-wifi-manager"
    assert data["fleet_defaults"]["mavlink_anywhere_ref"] == "v9.9.9"
    assert data["docs"]["mds_init_setup"] == "https://github.com/demo/customer-mds/blob/customer-demo/docs/guides/mds-init-setup.md"


def test_management_router_save_gcs_config_rejects_non_object_payload():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_management_router(deps))

    with TestClient(app) as client:
        response = client.put("/api/v1/system/gcs-config", json=["not", "an", "object"])

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "model_attributes_type"


def test_management_router_get_network_info_uses_live_dependency_after_router_creation():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_management_router(deps))

    replacement = Mock(return_value=[{"hw_id": "9", "ethernet": {"interface": "eth0"}}])
    deps.get_network_info_from_heartbeats = replacement

    with TestClient(app) as client:
        response = client.get("/api/v1/fleet/network-details")

    assert response.status_code == 200
    replacement.assert_called_once()
    assert response.json()[0]["hw_id"] == "9"
