from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api_routes.static_assets import create_static_assets_router, _resolve_static_plot_path


def _make_deps(plots_dir: str):
    return SimpleNamespace(
        get_swarm_trajectory_folders=lambda: {"plots": plots_dir},
    )


def test_static_assets_router_registers_expected_routes():
    with TemporaryDirectory() as temp_dir:
        deps = _make_deps(temp_dir)
        app = FastAPI()
        app.include_router(create_static_assets_router(deps))

        routes = {route.path for route in app.routes}

        assert "/api/v1/swarm-trajectories/plots/{filename}" in routes


def test_static_assets_router_serves_existing_plot():
    with TemporaryDirectory() as temp_dir:
        plot_path = Path(temp_dir) / "drone_1.jpg"
        plot_path.write_bytes(b"jpg")

        deps = _make_deps(temp_dir)
        app = FastAPI()
        app.include_router(create_static_assets_router(deps))

        with TestClient(app) as client:
            response = client.get("/api/v1/swarm-trajectories/plots/drone_1.jpg")

        assert response.status_code == 200
        assert response.content == b"jpg"


def test_static_assets_router_uses_live_dependency_after_router_creation():
    with TemporaryDirectory() as initial_dir, TemporaryDirectory() as replacement_dir:
        replacement_plot = Path(replacement_dir) / "leader.jpg"
        replacement_plot.write_bytes(b"leader")

        deps = _make_deps(initial_dir)
        app = FastAPI()
        app.include_router(create_static_assets_router(deps))

        deps.get_swarm_trajectory_folders = lambda: {"plots": replacement_dir}

        with TestClient(app) as client:
            response = client.get("/api/v1/swarm-trajectories/plots/leader.jpg")

        assert response.status_code == 200
        assert response.content == b"leader"


def test_static_assets_router_returns_404_when_missing():
    with TemporaryDirectory() as temp_dir:
        deps = _make_deps(temp_dir)
        app = FastAPI()
        app.include_router(create_static_assets_router(deps))

        with TestClient(app) as client:
            response = client.get("/api/v1/swarm-trajectories/plots/missing.jpg")

        assert response.status_code == 404
        assert response.json()["detail"] == "Plot not found"


def test_resolve_static_plot_path_rejects_path_traversal():
    with TemporaryDirectory() as temp_dir:
        with pytest.raises(HTTPException) as exc_info:
            _resolve_static_plot_path(temp_dir, "../secret.txt")

    assert exc_info.value.status_code == 404
