import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_routes.git_status import create_git_router


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
        _config_get_drone_git_status=lambda drone_id: {"branch": "main-candidate", "commit": "abc12345"},
        log_system_event=lambda *args, **kwargs: None,
        log_system_error=lambda *args, **kwargs: None,
    )


def test_git_router_registers_expected_routes():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_git_router(deps))

    routes = {route.path for route in app.routes}

    assert "/api/v1/git/status" in routes
    assert "/git-status" in routes
    assert "/api/v1/git/sync-operations" in routes
    assert "/sync-repos" in routes
    assert "/ws/git-status" in routes
    assert "/get-gcs-git-status" in routes
    assert "/get-drone-git-status/{drone_id}" in routes


def test_git_router_uses_live_verify_dependency_after_router_creation():
    deps = _make_deps()
    initial_verify = deps._verify_sync_targets

    app = FastAPI()
    app.include_router(create_git_router(deps))

    replacement_verify = AsyncMock(return_value=([1], []))
    deps._verify_sync_targets = replacement_verify

    with TestClient(app) as client:
        response = client.post("/api/v1/git/sync-operations", json={})

    assert response.status_code == 200
    initial_verify.assert_not_called()
    replacement_verify.assert_awaited_once()


def test_git_router_get_gcs_status_uses_live_dependency_after_router_creation():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_git_router(deps))

    replacement_report = Mock(return_value={"branch": "release", "commit": "def67890"})
    deps.get_gcs_git_report = replacement_report

    with TestClient(app) as client:
        response = client.get("/api/v1/git/status")

    assert response.status_code == 200
    replacement_report.assert_called_once()
    assert response.json()["gcs_status"]["branch"] == "release"
