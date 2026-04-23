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
        log_system_event=lambda *args, **kwargs: None,
        log_system_error=lambda *args, **kwargs: None,
    )


def test_management_router_registers_expected_routes():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_management_router(deps))

    routes = {route.path for route in app.routes}

    assert "/api/v1/system/gcs-config" in routes
    assert "/api/v1/system/runtime-status" in routes
    assert "/api/v1/system/gcs-config/apply" in routes
    assert "/api/v1/system/runtime-update" in routes
    assert "/api/v1/fleet/network-details" in routes


def test_management_router_get_gcs_config_uses_live_params_after_router_creation(monkeypatch, tmp_path):
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_management_router(deps))
    gcs_env = tmp_path / "gcs.env"
    monkeypatch.setattr(management_module, "_get_gcs_config_path", lambda: gcs_env)
    monkeypatch.setattr(management_module, "_list_sitl_instance_count", lambda deps: 0)
    monkeypatch.setattr(
        management_module,
        "resolve_runtime_mode",
        lambda: SimpleNamespace(mode="sitl", sim_mode=True, source="default:sitl"),
    )

    deps.Params = SimpleNamespace(gcs_api_port=3030, GIT_AUTO_PUSH=False, acceptable_deviation=4.5)

    with TestClient(app) as client:
        response = client.get("/api/v1/system/gcs-config")

    assert response.status_code == 200
    assert response.json() == {
        "sim_mode": True,
        "mode": "sitl",
        "mode_source": "default:sitl",
        "configured_mode": "sitl",
        "configured_sim_mode": True,
        "gcs_port": 3030,
        "git_auto_push": False,
        "configured_git_auto_push": False,
        "acceptable_deviation": 4.5,
        "gcs_config_path": str(gcs_env),
        "gcs_config_present": False,
        "sitl_instance_count": 0,
        "restart_required": False,
    }


def test_management_router_save_gcs_config_persists_safe_subset(monkeypatch, tmp_path):
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_management_router(deps))
    gcs_env = tmp_path / "gcs.env"
    gcs_env.write_text("MDS_MODE=real\nMDS_GIT_AUTO_PUSH=true\n", encoding="utf-8")
    monkeypatch.setenv("MDS_GCS_SYSTEM_CONFIG", str(gcs_env))
    monkeypatch.setattr(
        management_module,
        "resolve_runtime_mode",
        lambda: SimpleNamespace(mode="real", sim_mode=False, source="env:MDS_MODE"),
    )

    with TestClient(app) as client:
        response = client.put("/api/v1/system/gcs-config", json={"sim_mode": True, "git_auto_push": False})

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["status"] == "success"
    assert data["persisted"] is True
    assert data["updated_keys"] == ["MDS_MODE", "MDS_GIT_AUTO_PUSH"]
    assert data["configured_mode"] == "sitl"
    assert data["configured_git_auto_push"] is False
    assert data["restart_required"] is True
    assert gcs_env.read_text(encoding="utf-8").splitlines() == [
        "MDS_MODE=sitl",
        "MDS_GIT_AUTO_PUSH=false",
    ]


def test_management_router_save_gcs_config_warns_for_unsupported_fields(monkeypatch, tmp_path):
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_management_router(deps))
    gcs_env = tmp_path / "gcs.env"
    monkeypatch.setenv("MDS_GCS_SYSTEM_CONFIG", str(gcs_env))
    monkeypatch.setattr(
        management_module,
        "resolve_runtime_mode",
        lambda: SimpleNamespace(mode="real", sim_mode=False, source="env:MDS_MODE"),
    )

    with TestClient(app) as client:
        response = client.put(
            "/api/v1/system/gcs-config",
            json={"gcs_port": 9000, "acceptable_deviation": 7.0},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "no_changes"
    assert data["persisted"] is False
    assert data["restart_required"] is False
    assert data["warnings"]


def test_management_router_apply_gcs_config_reports_no_restart_when_running_matches(monkeypatch, tmp_path):
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_management_router(deps))
    gcs_env = tmp_path / "gcs.env"
    gcs_env.write_text("MDS_MODE=real\nMDS_GIT_AUTO_PUSH=true\n", encoding="utf-8")
    monkeypatch.setenv("MDS_GCS_SYSTEM_CONFIG", str(gcs_env))
    monkeypatch.setattr(
        management_module,
        "resolve_runtime_mode",
        lambda: SimpleNamespace(mode="real", sim_mode=False, source="env:MDS_MODE"),
    )

    with TestClient(app) as client:
        response = client.post("/api/v1/system/gcs-config/apply")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "no_restart_required"
    assert data["scheduled"] is False
    assert data["restart_required"] is False


def test_management_router_apply_gcs_config_schedules_restart(monkeypatch, tmp_path):
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_management_router(deps))
    gcs_env = tmp_path / "gcs.env"
    gcs_env.write_text("MDS_MODE=real\nMDS_GIT_AUTO_PUSH=false\n", encoding="utf-8")
    monkeypatch.setenv("MDS_GCS_SYSTEM_CONFIG", str(gcs_env))
    monkeypatch.setattr(
        management_module,
        "resolve_runtime_mode",
        lambda: SimpleNamespace(mode="sitl", sim_mode=True, source="env:MDS_MODE"),
    )
    monkeypatch.setattr(management_module, "_schedule_gcs_restart", lambda *, target_mode: True)
    monkeypatch.setattr(management_module, "_list_sitl_instance_count", lambda deps: 4)

    with TestClient(app) as client:
        response = client.post("/api/v1/system/gcs-config/apply")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "scheduled"
    assert data["scheduled"] is True
    assert data["configured_mode"] == "real"
    assert data["configured_git_auto_push"] is False
    assert data["restart_required"] is True
    assert data["restart_delay_ms"] == management_module._RESTART_DELAY_MS
    assert data["warnings"]


def test_management_router_runtime_update_schedules_safe_fast_forward(monkeypatch):
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_management_router(deps))
    monkeypatch.setattr(
        management_module,
        "_build_runtime_status_response",
        lambda deps: SimpleNamespace(
            mode="real",
            restart_required=False,
            repo_sync_status=SimpleNamespace(
                commit="abc12345",
                tracking_branch="origin/customer-demo",
                update_readiness="ready_to_fast_forward",
            ),
        ),
    )
    monkeypatch.setattr(
        management_module,
        "_refresh_repo_sync_status",
        lambda deps: management_module.RuntimeRepoSyncStatusResponse(
            branch="customer-demo",
            commit="abc12345",
            remote_url="https://github.com/demo/customer-mds.git",
            tracking_branch="origin/customer-demo",
            status="clean",
            commits_ahead=0,
            commits_behind=2,
            update_readiness="ready_to_fast_forward",
            update_summary="Tracking branch is ahead by 2 commit(s); a controlled fast-forward update is available.",
            fast_forward_update_available=True,
        ),
    )
    monkeypatch.setattr(
        management_module,
        "_list_pending_update_paths",
        lambda tracking_branch: ["src/runtime.py", "docs/guides/runtime.md"],
    )
    monkeypatch.setattr(management_module, "_blocked_gcs_update_paths", lambda paths: [])
    monkeypatch.setattr(management_module, "_resolve_target_commit", lambda tracking_branch: "fedcba98")
    monkeypatch.setattr(management_module, "_schedule_gcs_runtime_update", lambda *, target_mode, tracking_branch: True)

    with TestClient(app) as client:
        response = client.post("/api/v1/system/runtime-update")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "scheduled"
    assert data["scheduled"] is True
    assert data["target_commit"] == "fedcba98"
    assert data["pending_paths_count"] == 2
    assert data["blocked_paths"] == []
    assert data["restart_delay_ms"] == management_module._UPDATE_DELAY_MS


def test_management_router_runtime_update_blocks_manual_paths(monkeypatch):
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_management_router(deps))
    monkeypatch.setattr(
        management_module,
        "_build_runtime_status_response",
        lambda deps: SimpleNamespace(
            mode="real",
            restart_required=False,
            repo_sync_status=SimpleNamespace(
                commit="abc12345",
                tracking_branch="origin/customer-demo",
                update_readiness="ready_to_fast_forward",
            ),
        ),
    )
    monkeypatch.setattr(
        management_module,
        "_refresh_repo_sync_status",
        lambda deps: management_module.RuntimeRepoSyncStatusResponse(
            branch="customer-demo",
            commit="abc12345",
            remote_url="https://github.com/demo/customer-mds.git",
            tracking_branch="origin/customer-demo",
            status="clean",
            commits_ahead=0,
            commits_behind=2,
            update_readiness="ready_to_fast_forward",
            update_summary="Tracking branch is ahead by 2 commit(s); a controlled fast-forward update is available.",
            fast_forward_update_available=True,
        ),
    )
    monkeypatch.setattr(
        management_module,
        "_list_pending_update_paths",
        lambda tracking_branch: ["app/dashboard/drone-dashboard/src/App.js", "src/runtime.py"],
    )
    monkeypatch.setattr(
        management_module,
        "_blocked_gcs_update_paths",
        lambda paths: ["app/dashboard/drone-dashboard/src/App.js"],
    )
    monkeypatch.setattr(management_module, "_resolve_target_commit", lambda tracking_branch: "fedcba98")

    with TestClient(app) as client:
        response = client.post("/api/v1/system/runtime-update")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "manual_update_required"
    assert data["scheduled"] is False
    assert data["pending_paths_count"] == 2
    assert data["blocked_paths"] == ["app/dashboard/drone-dashboard/src/App.js"]
    assert data["warnings"]


def test_management_router_save_gcs_config_rejects_conflicting_mode_inputs(monkeypatch, tmp_path):
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_management_router(deps))
    monkeypatch.setenv("MDS_GCS_SYSTEM_CONFIG", str(tmp_path / "gcs.env"))

    with TestClient(app) as client:
        response = client.put("/api/v1/system/gcs-config", json={"mode": "real", "sim_mode": True})

    assert response.status_code == 422
    assert response.json()["detail"] == "mode and sim_mode describe different runtime modes"


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
            smart_wifi_manager_mode="manage",
            smart_wifi_manager_import_mode="merge",
            smart_wifi_manager_install_dir="/opt/demo-smartwifi",
            smart_wifi_manager_dashboard_listen="0.0.0.0:9080",
            smart_wifi_manager_profile_path="deployment/connectivity/demo/profile.json",
            mavlink_management_mode="managed",
            mavlink_anywhere_repo_url_https="https://github.com/demo/mavlink-anywhere.git",
            mavlink_anywhere_ref="v9.9.9",
            mavlink_anywhere_install_dir="/opt/demo-mavlink",
            mavlink_anywhere_dashboard_listen="0.0.0.0:9070",
            mavlink_anywhere_skip_dashboard=False,
        ),
    )
    monkeypatch.setattr(
        management_module,
        "_build_mavlink_runtime_status",
        lambda profile: {
            "status_source": "script",
            "management_mode": profile.mavlink_management_mode,
            "repo_url": profile.mavlink_anywhere_repo_url_https,
            "ref": profile.mavlink_anywhere_ref,
            "repo_web_url": "https://github.com/demo/mavlink-anywhere/tree/v9.9.9",
            "install_dir": profile.mavlink_anywhere_install_dir,
            "install_dir_present": True,
            "runtime_present": True,
            "runtime_head": "abc1234",
            "router_binary_present": True,
            "router_service_status": "active",
            "dashboard_enabled": True,
            "dashboard_listen": profile.mavlink_anywhere_dashboard_listen,
            "dashboard_service_status": "active",
        },
    )
    monkeypatch.setattr(
        management_module,
        "_build_connectivity_runtime_status",
        lambda profile: {
            "status_source": "script",
            "backend": profile.connectivity_backend,
            "repo_url": profile.smart_wifi_manager_repo_url_https,
            "ref": profile.smart_wifi_manager_ref,
            "repo_web_url": "https://github.com/demo/smart-wifi-manager/tree/v1.2.3",
            "install_dir": profile.smart_wifi_manager_install_dir,
            "install_dir_present": True,
            "mode": profile.smart_wifi_manager_mode,
            "import_mode": profile.smart_wifi_manager_import_mode,
            "profile_path": "/tmp/demo-profile.json",
            "profile_present": True,
            "dashboard_listen": profile.smart_wifi_manager_dashboard_listen,
            "service_status": "active",
        },
    )
    monkeypatch.setenv("MDS_GCS_SYSTEM_CONFIG", str(gcs_env))
    monkeypatch.setenv("MDS_INSTALL_DIR", "/opt/demo-gcs")
    monkeypatch.setenv("MDS_GIT_AUTH_TOKEN_FILE", str(token_file))
    monkeypatch.delenv("MDS_GIT_SSH_KEY_FILE", raising=False)
    monkeypatch.setattr(management_module, "_list_sitl_instance_count", lambda deps: 3)
    deps.get_gcs_git_report = lambda: {
        "branch": "customer-demo",
        "commit": "abcdef12",
        "remote_url": "https://github.com/demo/customer-mds.git",
        "tracking_branch": "origin/customer-demo",
        "status": "clean",
        "commits_ahead": 0,
        "commits_behind": 2,
    }

    with TestClient(app) as client:
        response = client.get("/api/v1/system/runtime-status")

    assert response.status_code == 200
    data = response.json()
    assert data["version"] == "5.2"
    assert data["mode"] == "real"
    assert data["mode_source"] == "env:MDS_MODE"
    assert data["configured_mode"] == "real"
    assert data["configured_sim_mode"] is False
    assert data["repo_url"] == "https://github.com/demo/customer-mds.git"
    assert data["repo_branch"] == "customer-demo"
    assert data["repo_access_mode"] == "https_token_file"
    assert data["configured_git_auto_push"] is True
    assert data["restart_required"] is False
    assert data["sitl_instance_count"] == 3
    assert data["gcs_config_path"] == str(gcs_env)
    assert data["gcs_config_present"] is True
    assert data["git_auth_token_file"] == str(token_file)
    assert data["git_auth_token_file_readable"] is True
    assert data["git_auth_health"]["status"] == "healthy"
    assert data["repo_sync_status"]["update_readiness"] == "ready_to_fast_forward"
    assert data["repo_sync_status"]["fast_forward_update_available"] is True
    assert data["fleet_defaults"]["connectivity_backend"] == "smart-wifi-manager"
    assert data["fleet_defaults"]["smart_wifi_manager_mode"] == "manage"
    assert data["fleet_defaults"]["mavlink_anywhere_ref"] == "v9.9.9"
    assert data["mavlink_runtime"]["router_service_status"] == "active"
    assert data["connectivity_runtime"]["service_status"] == "active"
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
