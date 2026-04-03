from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_routes.swarm import create_swarm_router


def _make_deps():
    return SimpleNamespace(
        load_swarm=lambda: [
            {"hw_id": 1, "follow": 0, "offset_x": 0.0, "offset_y": 0.0, "offset_z": 0.0, "frame": "ned"},
            {"hw_id": 2, "follow": 1, "offset_x": 1.0, "offset_y": 0.0, "offset_z": 0.0, "frame": "ned"},
        ],
        save_swarm=Mock(),
        log_system_event=lambda *args, **kwargs: None,
        Params=SimpleNamespace(GIT_AUTO_PUSH=False),
        git_operations=Mock(return_value={"status": "skipped"}),
        BASE_DIR="/tmp/test-base",
    )


def test_swarm_router_registers_expected_routes():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_swarm_router(deps))

    routes = {route.path for route in app.routes}

    assert "/get-swarm-data" in routes
    assert "/save-swarm-data" in routes
    assert "/request-new-leader" in routes


def test_swarm_router_uses_live_dependency_attributes_after_router_creation():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_swarm_router(deps))

    replacement_load = Mock(return_value=[
        {"hw_id": 1, "follow": 0, "offset_x": 0.0, "offset_y": 0.0, "offset_z": 0.0, "frame": "ned"},
        {"hw_id": 2, "follow": 0, "offset_x": 1.0, "offset_y": 0.0, "offset_z": 0.0, "frame": "ned"},
    ])
    replacement_save = Mock()
    deps.load_swarm = replacement_load
    deps.save_swarm = replacement_save

    with TestClient(app) as client:
        response = client.post("/request-new-leader", json={"hw_id": 2, "follow": 1})

    assert response.status_code == 200
    replacement_load.assert_called_once()
    replacement_save.assert_called_once()
    assert response.json()["assignment"]["follow"] == 1


def test_swarm_router_save_swarm_commit_false_skips_git_operations():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_swarm_router(deps))

    with TestClient(app) as client:
        response = client.post(
            "/save-swarm-data?commit=false",
            json=[{"hw_id": 1, "follow": 0}, {"hw_id": 2, "follow": 1}],
        )

    assert response.status_code == 200
    deps.save_swarm.assert_called_once()
    deps.git_operations.assert_not_called()
