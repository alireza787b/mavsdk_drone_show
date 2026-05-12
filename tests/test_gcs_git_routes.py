import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI

from api_routes.git_status import create_git_router
import api_routes.git_status as git_routes
from tests.conftest import SyncASGITestClient

MUTATION_HEADERS = {"x-fleet-ops-token": "test-token"}


def _make_deps():
    return SimpleNamespace(
        Params=SimpleNamespace(GIT_BRANCH="main-candidate"),
        GitStatus=None,
        load_config=lambda: [{"hw_id": "1", "pos_id": 1, "ip": "10.0.0.1"}],
        get_gcs_git_report=lambda: {"branch": "main-candidate", "commit": "abc12345"},
        git_status_data_all_drones={
            "1": {"status": "clean", "branch": "main-candidate", "commit": "abc12345", "uncommitted_changes": []}
        },
        data_lock_git_status=threading.Lock(),
        _sync_state={"active": False, "started_at": None, "results": None},
        _sync_lock=asyncio.Lock(),
        _select_sync_target_drones=lambda drones_config, pos_ids: (drones_config, []),
        _verify_sync_targets=AsyncMock(return_value=([1], [])),
        send_commands_to_all=Mock(return_value={"results": {"1": {"category": "accepted"}}}),
        send_commands_to_selected=Mock(return_value={"results": {"1": {"category": "accepted"}}}),
        log_system_event=lambda *args, **kwargs: None,
        log_system_error=lambda *args, **kwargs: None,
    )


def test_git_router_registers_expected_routes():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_git_router(deps))

    routes = {route.path for route in app.routes}

    assert "/api/v1/git/status" in routes
    assert "/api/v1/git/sync-operations" in routes
    assert "/api/v1/fleet/git-sync" in routes
    assert "/api/v1/fleet/git-sync/dry-run" in routes
    assert "/api/v1/fleet/git-sync/apply" in routes
    assert "/ws/git-status" in routes


def test_fleet_git_sync_apply_uses_live_verify_dependency_after_router_creation(monkeypatch):
    deps = _make_deps()
    deps.get_all_heartbeats = lambda: {"1": {"timestamp": int(time.time() * 1000), "hw_id": "1"}}
    monkeypatch.setenv("MDS_FLEET_OPS_MUTATION_TOKEN", "test-token")
    git_routes._git_sync_jobs.clear()
    initial_verify = deps._verify_sync_targets

    app = FastAPI()
    app.include_router(create_git_router(deps))

    replacement_verify = AsyncMock(return_value=([1], []))
    deps._verify_sync_targets = replacement_verify

    client = SyncASGITestClient(app)
    dry_run = client.post("/api/v1/fleet/git-sync/dry-run", headers=MUTATION_HEADERS, json={"pos_ids": [1]})
    assert dry_run.status_code == 200
    response = client.post(
        "/api/v1/fleet/git-sync/apply",
        headers=MUTATION_HEADERS,
        json={
            "dry_run_id": dry_run.json()["job_id"],
            "confirmation": {
                "acknowledged_risks": True,
                "confirmation_token": dry_run.json()["confirmation_token"],
            },
        },
    )

    assert response.status_code == 200
    initial_verify.assert_not_called()
    replacement_verify.assert_awaited_once()


def test_selected_git_sync_keeps_routing_ids_out_of_drone_command_payload(monkeypatch):
    deps = _make_deps()
    deps.get_all_heartbeats = lambda: {"1": {"timestamp": int(time.time() * 1000), "hw_id": "1"}}
    monkeypatch.setenv("MDS_FLEET_OPS_MUTATION_TOKEN", "test-token")
    git_routes._git_sync_jobs.clear()
    app = FastAPI()
    app.include_router(create_git_router(deps))

    client = SyncASGITestClient(app)
    dry_run = client.post("/api/v1/fleet/git-sync/dry-run", headers=MUTATION_HEADERS, json={"pos_ids": [1]})
    response = client.post(
        "/api/v1/fleet/git-sync/apply",
        headers=MUTATION_HEADERS,
        json={
            "dry_run_id": dry_run.json()["job_id"],
            "confirmation": {
                "acknowledged_risks": True,
                "confirmation_token": dry_run.json()["confirmation_token"],
            },
        },
    )

    assert response.status_code == 200
    deps.send_commands_to_selected.assert_called_once()
    _, command_data, target_hw_ids = deps.send_commands_to_selected.call_args.args
    assert target_hw_ids == ["1"]
    assert command_data["mission_type"] == 103
    assert command_data["update_branch"] == "main-candidate"
    assert "pos_ids" not in command_data


def test_deprecated_git_sync_operation_no_longer_dispatches_update_code():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_git_router(deps))

    client = SyncASGITestClient(app)
    response = client.post("/api/v1/git/sync-operations", json={"pos_ids": [1]})

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert "dry-run" in response.json()["message"]
    deps.send_commands_to_selected.assert_not_called()
    deps.send_commands_to_all.assert_not_called()


def test_fleet_git_sync_dry_run_requires_operator_token(monkeypatch):
    deps = _make_deps()
    monkeypatch.setenv("MDS_FLEET_OPS_MUTATION_TOKEN", "test-token")
    app = FastAPI()
    app.include_router(create_git_router(deps))

    client = SyncASGITestClient(app)
    response = client.post("/api/v1/fleet/git-sync/dry-run", json={"pos_ids": [1]})

    assert response.status_code == 403


def test_git_router_get_gcs_status_uses_live_dependency_after_router_creation():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_git_router(deps))

    replacement_report = Mock(return_value={"branch": "release", "commit": "def67890"})
    deps.get_gcs_git_report = replacement_report

    client = SyncASGITestClient(app)
    response = client.get("/api/v1/git/status")

    assert response.status_code == 200
    replacement_report.assert_called_once()
    assert response.json()["gcs_status"]["branch"] == "release"


def test_git_status_exposes_read_only_node_env_posture():
    deps = _make_deps()
    deps.git_status_data_all_drones = {
        "1": {
            "status": "clean",
            "branch": "main-candidate",
            "commit": "abc12345",
            "uncommitted_changes": [],
            "env_runtime": {
                "status_source": "registry",
                "registry_version": 1,
                "registry_hash": "abc123",
                "local_env_path": "/etc/mds/local.env",
                "local_env_present": True,
                "node_identity_path": "/etc/mds/node_identity.json",
                "node_identity_present": True,
                "runtime_mode": "real",
                "runtime_mode_source": "env:MDS_MODE",
                "hw_id": 1,
                "hw_id_source": "env:MDS_HW_ID",
                "configured_key_count": 7,
                "configured_node_key_count": 5,
                "registered_node_key_count": 20,
                "unknown_keys": ["OLD_KEY"],
                "deprecated_keys": [],
                "warnings": ["Node local.env contains unregistered keys."],
            },
        },
    }

    app = FastAPI()
    app.include_router(create_git_router(deps))

    client = SyncASGITestClient(app)
    response = client.get("/api/v1/git/status")

    assert response.status_code == 200
    env_runtime = response.json()["git_status"]["1"]["env_runtime"]
    assert env_runtime["registry_hash"] == "abc123"
    assert env_runtime["runtime_mode"] == "real"
    assert env_runtime["unknown_keys"] == ["OLD_KEY"]


def test_git_status_keeps_stale_offline_drift_out_of_global_sync_warning():
    deps = _make_deps()
    deps.Params.TELEMETRY_POLLING_TIMEOUT = 5
    deps.get_gcs_git_report = lambda: {"branch": "main-candidate", "commit": "new67890"}
    deps.git_status_data_all_drones = {
        "1": {
            "status": "clean",
            "branch": "main-candidate",
            "commit": "old12345",
            "uncommitted_changes": [],
        },
    }
    deps.get_all_heartbeats = lambda: {
        "1": {
            "timestamp": int((time.time() - 60) * 1000),
            "hw_id": "1",
        },
    }

    app = FastAPI()
    app.include_router(create_git_router(deps))

    client = SyncASGITestClient(app)
    response = client.get("/api/v1/git/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["git_status"]["1"]["in_sync_with_gcs"] is False
    assert payload["total_drones"] == 1
    assert payload["needs_sync_count"] == 0


def test_git_status_empty_heartbeat_set_suppresses_global_sync_warning():
    deps = _make_deps()
    deps.get_gcs_git_report = lambda: {"branch": "main-candidate", "commit": "new67890"}
    deps.git_status_data_all_drones = {
        "1": {
            "status": "clean",
            "branch": "main-candidate",
            "commit": "old12345",
            "uncommitted_changes": [],
        },
    }
    deps.get_all_heartbeats = lambda: {}

    app = FastAPI()
    app.include_router(create_git_router(deps))

    client = SyncASGITestClient(app)
    response = client.get("/api/v1/git/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["git_status"]["1"]["in_sync_with_gcs"] is False
    assert payload["total_drones"] == 1
    assert payload["needs_sync_count"] == 0
