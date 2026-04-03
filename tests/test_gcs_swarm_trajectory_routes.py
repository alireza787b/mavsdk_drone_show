from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_routes.swarm_trajectory import create_swarm_trajectory_router


class _DummySwarmTrajectoryError(Exception):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _make_service(tmp_path: Path):
    csv_path = tmp_path / "Drone 7.csv"
    csv_path.write_text("t,px,py\n0,0,0\n", encoding="utf-8")

    return SimpleNamespace(
        SwarmTrajectoryError=_DummySwarmTrajectoryError,
        get_swarm_leaders_payload=lambda: {"success": True, "leaders": [1, 5]},
        save_uploaded_trajectory=lambda leader_id, filename, content: {
            "success": True,
            "leader_id": leader_id,
            "filename": filename,
            "bytes": len(content),
        },
        process_trajectories_payload=lambda force_clear=False, auto_reload=True: {
            "success": True,
            "force_clear": force_clear,
            "auto_reload": auto_reload,
        },
        get_processing_recommendation_payload=lambda: {
            "success": True,
            "recommendation": {"action": "recommended_full_reprocess"},
        },
        get_processing_status_payload=lambda: {
            "success": True,
            "status": {"processed_trajectories": 2},
        },
        clear_processed_payload=lambda: {"success": True},
        clear_all_payload=lambda: {"success": True},
        clear_leader_trajectory_payload=lambda leader_id: {"success": True, "leader_id": leader_id},
        remove_leader_trajectory_payload=lambda leader_id: {"success": True, "leader_id": leader_id},
        get_processed_trajectory_download=lambda drone_id: (str(csv_path), f"Drone {drone_id}.csv"),
        get_drone_kml_download=lambda drone_id: ("<kml/>", f"Drone {drone_id}.kml"),
        get_cluster_kml_download=lambda leader_id: ("<kml/>", f"Cluster {leader_id}.kml"),
        clear_individual_drone_payload=lambda drone_id: {"success": True, "drone_id": drone_id},
        commit_trajectory_changes_payload=lambda message=None: {
            "success": True,
            "message": message or "ok",
        },
    )


def _make_deps(tmp_path: Path):
    return SimpleNamespace(
        Params=SimpleNamespace(
            TRAJECTORY_PLANNER_DEFAULT_MSL=100.0,
            TRAJECTORY_PLANNER_DEFAULT_TARGET_AGL=100.0,
            TRAJECTORY_PLANNER_MIN_MSL=1.0,
            TRAJECTORY_PLANNER_MAX_MSL=10000.0,
            TRAJECTORY_PLANNER_DEFAULT_PREFERRED_SPEED=8.0,
            TRAJECTORY_PLANNER_MIN_PREFERRED_SPEED=0.5,
            TRAJECTORY_PLANNER_OPTIMAL_MAX_SPEED=12.0,
            swarm_trajectory_max_speed=20.0,
            TRAJECTORY_PLANNER_ROUTE_ENTRY_DELAY_S=10.0,
            TRAJECTORY_PLANNER_FALLBACK_LEG_DURATION_S=10.0,
            TRAJECTORY_PLANNER_DERIVED_TIME_STEP_S=0.1,
            TRAJECTORY_PLANNER_MIN_SAFE_CLEARANCE_M=50.0,
            TRAJECTORY_PLANNER_DEFAULT_SAFE_CLEARANCE_M=100.0,
        ),
        swarm_trajectory_service=_make_service(tmp_path),
        log_system_event=lambda *args, **kwargs: None,
        log_system_error=lambda *args, **kwargs: None,
    )


def test_swarm_trajectory_router_registers_expected_routes(tmp_path):
    deps = _make_deps(tmp_path)
    app = FastAPI()
    app.include_router(create_swarm_trajectory_router(deps))

    routes = {route.path for route in app.routes}

    assert "/api/swarm/leaders" in routes
    assert "/api/swarm/trajectory/upload/{leader_id}" in routes
    assert "/api/swarm/trajectory/process" in routes
    assert "/api/swarm/trajectory/recommendation" in routes
    assert "/api/swarm/trajectory/status" in routes
    assert "/api/swarm/trajectory/policy" in routes
    assert "/api/swarm/trajectory/clear-processed" in routes
    assert "/api/swarm/trajectory/clear" in routes
    assert "/api/swarm/trajectory/clear-leader/{leader_id}" in routes
    assert "/api/swarm/trajectory/remove/{leader_id}" in routes
    assert "/api/swarm/trajectory/download/{drone_id}" in routes
    assert "/api/swarm/trajectory/download-kml/{drone_id}" in routes
    assert "/api/swarm/trajectory/download-cluster-kml/{leader_id}" in routes
    assert "/api/swarm/trajectory/clear-drone/{drone_id}" in routes
    assert "/api/swarm/trajectory/commit" in routes


def test_swarm_trajectory_router_policy_uses_live_params_after_router_creation(tmp_path):
    deps = _make_deps(tmp_path)
    app = FastAPI()
    app.include_router(create_swarm_trajectory_router(deps))

    deps.Params.TRAJECTORY_PLANNER_DEFAULT_MSL = 155.0
    deps.Params.swarm_trajectory_max_speed = 24.5

    with TestClient(app) as client:
        response = client.get("/api/swarm/trajectory/policy")

    assert response.status_code == 200
    payload = response.json()
    assert payload["policy"]["altitude"]["default_msl"] == 155.0
    assert payload["policy"]["speed"]["absolute_max"] == 24.5


def test_swarm_trajectory_router_status_uses_live_service_after_router_creation(tmp_path):
    deps = _make_deps(tmp_path)
    app = FastAPI()
    app.include_router(create_swarm_trajectory_router(deps))

    deps.swarm_trajectory_service.get_processing_status_payload = lambda: {
        "success": True,
        "status": {"processed_trajectories": 9},
    }

    with TestClient(app) as client:
        response = client.get("/api/swarm/trajectory/status")

    assert response.status_code == 200
    assert response.json()["status"]["processed_trajectories"] == 9


def test_swarm_trajectory_router_process_rejects_malformed_json(tmp_path):
    deps = _make_deps(tmp_path)
    app = FastAPI()
    app.include_router(create_swarm_trajectory_router(deps))

    with TestClient(app) as client:
        response = client.post(
            "/api/swarm/trajectory/process",
            data="{bad",
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 400
    assert response.json() == {"success": False, "error": "Malformed JSON request body"}


def test_swarm_trajectory_router_commit_rejects_non_object_json(tmp_path):
    deps = _make_deps(tmp_path)
    app = FastAPI()
    app.include_router(create_swarm_trajectory_router(deps))

    with TestClient(app) as client:
        response = client.post("/api/swarm/trajectory/commit", json=["not", "an", "object"])

    assert response.status_code == 400
    assert response.json() == {"success": False, "error": "Request body must be a JSON object"}
