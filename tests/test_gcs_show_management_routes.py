from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api_routes.show_management import create_show_management_router
from show_management import resolve_show_plot_path


class _DummyMetricsEngine:
    def __init__(self, processed_dir):
        self.processed_dir = processed_dir

    def calculate_comprehensive_metrics(self):
        return {"basic_metrics": {"drone_count": 1}}

    def save_metrics_to_file(self, *args, **kwargs):
        return None

    def load_drone_data(self):
        return True

    def calculate_safety_metrics(self):
        return {"safety_status": "SAFE", "collision_warnings_count": 0}


def _make_deps():
    return SimpleNamespace(
        BASE_DIR="/tmp/mds-show-tests",
        Params=SimpleNamespace(GIT_AUTO_PUSH=False),
        METRICS_AVAILABLE=True,
        DroneShowMetrics=_DummyMetricsEngine,
        skybrush_dir="/tmp/mds-show-tests/skybrush",
        processed_dir="/tmp/mds-show-tests/processed",
        plots_directory="/tmp/mds-show-tests/plots",
        shapes_dir="/tmp/mds-show-tests/shapes",
        allowed_file=lambda filename: filename.lower().endswith(".zip"),
        run_formation_process=lambda *args, **kwargs: {"success": True},
        clear_show_directories=lambda base_dir: None,
        git_operations=lambda base_dir, message: {"success": True, "message": "ok"},
        zip_directory=lambda source_dir, output_prefix: f"{output_prefix}.zip",
        log_system_event=lambda *args, **kwargs: None,
        log_system_warning=lambda *args, **kwargs: None,
        log_system_error=lambda *args, **kwargs: None,
        datetime=datetime,
        _inspect_custom_show_csv=None,
        _generate_custom_show_preview=None,
        _load_saved_metrics_if_current=lambda: None,
        _refresh_saved_show_metrics=lambda: {"basic_metrics": {"drone_count": 1}},
    )


def test_show_management_router_registers_expected_routes():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_show_management_router(deps))

    routes = {route.path for route in app.routes}

    assert "/import-show" in routes
    assert "/download-raw-show" in routes
    assert "/download-processed-show" in routes
    assert "/get-show-info" in routes
    assert "/get-custom-show-info" in routes
    assert "/import-custom-show" in routes
    assert "/get-comprehensive-metrics" in routes
    assert "/get-safety-report" in routes
    assert "/validate-trajectory" in routes
    assert "/deploy-show" in routes
    assert "/get-show-plots" in routes
    assert "/get-show-plots/{filename}" in routes
    assert "/get-custom-show-image" in routes


def test_show_management_router_get_show_info_uses_live_directory_after_router_creation(tmp_path):
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_show_management_router(deps))

    live_skybrush = tmp_path / "skybrush"
    live_skybrush.mkdir(parents=True, exist_ok=True)
    (live_skybrush / "Drone 1.csv").write_text(
        "t [ms],x [m],y [m],z [m],yaw [deg]\n0,0,0,0,0\n60000,1,1,5,0\n",
        encoding="utf-8",
    )
    deps.skybrush_dir = str(live_skybrush)

    with TestClient(app) as client:
        response = client.get("/get-show-info")

    assert response.status_code == 200
    assert response.json()["drone_count"] == 1
    assert response.json()["max_altitude"] == 5.0


def test_show_management_router_get_custom_show_info_uses_live_directory_after_router_creation(tmp_path):
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_show_management_router(deps))

    live_shapes = tmp_path / "shapes"
    live_shapes.mkdir(parents=True, exist_ok=True)
    (live_shapes / "active.csv").write_text(
        "t,px,py,pz,vx,vy,vz,ax,ay,az,yaw,mode\n0,0,0,-0,0,0,0,0,0,0,0,70\n",
        encoding="utf-8",
    )
    (live_shapes / "trajectory_plot.png").write_bytes(b"png")
    deps.shapes_dir = str(live_shapes)

    with TestClient(app) as client:
        response = client.get("/get-custom-show-info")

    assert response.status_code == 200
    assert response.json()["exists"] is True
    assert response.json()["preview_exists"] is True


def test_show_management_router_get_show_plot_uses_live_directory_after_router_creation(tmp_path):
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_show_management_router(deps))

    live_plots = tmp_path / "plots"
    live_plots.mkdir(parents=True, exist_ok=True)
    (live_plots / "combined_drone_paths.jpg").write_bytes(b"jpg")
    deps.plots_directory = str(live_plots)

    with TestClient(app) as client:
        response = client.get("/get-show-plots/combined_drone_paths.jpg")

    assert response.status_code == 200
    assert response.content == b"jpg"


def test_resolve_show_plot_path_rejects_path_traversal(tmp_path):
    plots_dir = tmp_path / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    with pytest.raises(HTTPException) as exc_info:
        resolve_show_plot_path(str(plots_dir), "../secret.jpg")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Plot image not found"
