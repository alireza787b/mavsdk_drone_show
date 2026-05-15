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


def _recommendation_payload():
    return {
        "action": "safe_incremental",
        "message": "Ready to process trajectories",
        "details": ["No conflicts detected with existing data"],
        "requires_confirmation": False,
        "uploaded_count": 1,
        "changes": {
            "has_previous_session": True,
            "swarm_structure_changed": False,
            "parameters_changed": False,
            "trajectory_files_changed": False,
            "new_uploads": [],
            "missing_uploads": [],
            "leader_structure_changed": False,
            "requires_full_reprocess": False,
            "safe_to_incremental": True,
        },
        "expected_top_leaders": [1, 5],
        "uploaded_leaders": [1],
        "missing_uploaded_leaders": [5],
        "orphan_uploaded_leaders": [],
    }


def _package_stats_payload(*, available=True, drone_ids=None):
    drone_ids = drone_ids or []
    return {
        "available": available,
        "drone_count": len(drone_ids),
        "drone_ids": drone_ids,
        "route_entry_time_s": 10.0 if available else None,
        "mission_clock_s": 70.0 if available else None,
        "route_motion_time_s": 60.0 if available else None,
        "max_altitude_msl_m": 1465.0 if available else None,
        "min_altitude_msl_m": 1450.0 if available else None,
        "altitude_window_m": 15.0 if available else None,
    }


def _status_payload(processed_trajectories=2):
    recommendation = _recommendation_payload()
    return {
        "success": True,
        "status": {
            "raw_trajectories": 1,
            "processed_trajectories": processed_trajectories,
            "generated_plots": 0,
            "raw_leaders": [1],
            "processed_drones": [1, 2] if processed_trajectories else [],
            "processed_leaders": [1] if processed_trajectories else [],
            "processed_followers": [2] if processed_trajectories else [],
            "follow_map": {1: 0, 2: 1},
            "leader_count": 1 if processed_trajectories else 0,
            "follower_count": 1 if processed_trajectories else 0,
            "package_stats": _package_stats_payload(available=processed_trajectories > 0, drone_ids=[1, 2] if processed_trajectories else []),
            "package_drone_stats": {
                1: {
                    "drone_id": 1,
                    "route_entry_time_s": 10.0,
                    "mission_clock_s": 70.0,
                    "route_motion_time_s": 60.0,
                    "max_altitude_msl_m": 1465.0,
                    "min_altitude_msl_m": 1450.0,
                    "altitude_window_m": 15.0,
                },
                2: {
                    "drone_id": 2,
                    "route_entry_time_s": 10.0,
                    "mission_clock_s": 68.0,
                    "route_motion_time_s": 58.0,
                    "max_altitude_msl_m": 1460.0,
                    "min_altitude_msl_m": 1452.0,
                    "altitude_window_m": 8.0,
                },
            } if processed_trajectories else {},
            "has_results": processed_trajectories > 0,
            "plots_available": False,
            "expected_top_leaders": [1, 5],
            "uploaded_leaders": [1],
            "missing_uploaded_leaders": [5],
            "orphan_uploaded_leaders": [],
            "clusters": [
                {
                    "leader_id": 1,
                    "follower_ids": [2],
                    "follower_count": 1,
                    "expected_drone_count": 2,
                    "processed_drone_count": 2 if processed_trajectories else 0,
                    "leader_uploaded": True,
                    "leader_processed": processed_trajectories > 0,
                    "processed_follower_ids": [2] if processed_trajectories else [],
                    "missing_follower_ids": [],
                    "leader_plot_available": False,
                    "cluster_plot_available": False,
                    "package_stats": _package_stats_payload(
                        available=processed_trajectories > 0,
                        drone_ids=[1, 2] if processed_trajectories else [],
                    ),
                    "ready": processed_trajectories > 0,
                    "state": "ready" if processed_trajectories else "needs_processing",
                    "issues": [],
                    "advisories": [],
                },
                {
                    "leader_id": 5,
                    "follower_ids": [6],
                    "follower_count": 1,
                    "expected_drone_count": 2,
                    "processed_drone_count": 0,
                    "leader_uploaded": False,
                    "leader_processed": False,
                    "processed_follower_ids": [],
                    "missing_follower_ids": [6],
                    "leader_plot_available": False,
                    "cluster_plot_available": False,
                    "package_stats": _package_stats_payload(available=False, drone_ids=[]),
                    "ready": False,
                    "state": "missing_upload",
                    "issues": ["Leader trajectory CSV has not been uploaded."],
                    "advisories": [],
                },
            ],
            "cluster_summary": {
                "cluster_count": 2,
                "ready_cluster_count": 1 if processed_trajectories else 0,
                "needs_processing_cluster_count": 0 if processed_trajectories else 1,
                "missing_upload_cluster_count": 1,
                "partial_output_cluster_count": 0,
                "processed_cluster_count": 1 if processed_trajectories else 0,
                "all_clusters_ready": False,
                "overall_state": "partial" if processed_trajectories else "missing_uploads",
            },
            "session": {
                "exists": processed_trajectories > 0,
                "session_id": "session-1" if processed_trajectories else None,
                "timestamp": "2026-04-04T00:00:00" if processed_trajectories else None,
                "processed_leaders": [1] if processed_trajectories else [],
                "total_drones": 2 if processed_trajectories else 0,
            },
            "session_changes": recommendation["changes"],
            "processing_recommendation": recommendation,
        },
        "folders": {
            "base": "/tmp/swarm",
            "raw": "/tmp/swarm/raw",
            "processed": "/tmp/swarm/processed",
            "plots": "/tmp/swarm/plots",
        },
    }


def _make_service(tmp_path: Path):
    csv_path = tmp_path / "Drone 7.csv"
    csv_path.write_text("t,px,py\n0,0,0\n", encoding="utf-8")

    return SimpleNamespace(
        SwarmTrajectoryError=_DummySwarmTrajectoryError,
        get_swarm_leaders_payload=lambda: {
            "success": True,
            "leaders": [1, 5],
            "hierarchies": {1: 1, 5: 1},
            "follower_details": {1: [2], 5: [6]},
            "uploaded_leaders": [1],
            "simulation_mode": True,
        },
        save_uploaded_trajectory=lambda leader_id, filename, content: {
            "success": True,
            "message": f"Drone {leader_id} trajectory uploaded successfully",
            "filepath": str(tmp_path / f"Drone {leader_id}.csv"),
        },
        process_trajectories_payload=lambda force_clear=False, auto_reload=True: {
            "success": True,
            "outcome": "success",
            "message": "Formation outputs ready",
            "processed_drones": 2,
            "processed_drone_list": [1, 2],
            "expected_drone_list": [1, 2],
            "skipped_drone_ids": [],
            "statistics": {"leaders": 1, "followers": 1, "errors": 0},
            "session_id": "session-1",
            "recommendation": _recommendation_payload(),
            "processed_leaders": [1],
            "missing_leaders": [],
            "auto_reloaded": [1] if auto_reload else [],
            "ignored_leaders": [],
        },
        get_processing_recommendation_payload=lambda: {
            "success": True,
            "recommendation": _recommendation_payload(),
        },
        get_processing_status_payload=lambda: _status_payload(),
        get_validation_payload=lambda: {
            "success": True,
            "ready": False,
            "state": "partial",
            "blockers": [{
                "code": "swarm_trajectory_cluster_missing_upload",
                "message": "Cluster 5 is not ready: missing upload.",
                "severity": "blocker",
                "leader_id": 5,
            }],
            "warnings": [],
            "advisories": [],
            "processed_drone_ids": [1, 2],
            "expected_drone_ids": [1, 2, 5, 6],
            "missing_drone_ids": [5, 6],
            "cluster_summary": _status_payload()["status"]["cluster_summary"],
            "package_stats": _package_stats_payload(available=True, drone_ids=[1, 2]),
        },
        get_preview_payload=lambda max_points_per_drone=500: {
            "success": True,
            "generated_at": "2026-05-15T00:00:00Z",
            "drones": [{
                "drone_id": 1,
                "role": "leader",
                "top_leader_id": 1,
                "direct_leader_id": None,
                "point_count": 1,
                "preview_point_count": 1,
                "global_coordinates_available": True,
                "points": [{
                    "sequence": 0,
                    "time_s": 0.0,
                    "lat": 35.0,
                    "lng": 51.0,
                    "alt_msl": 1200.0,
                    "yaw_deg": 0.0,
                }],
                "warnings": [],
                "package_stats": _package_stats_payload(available=True, drone_ids=[1]),
            }],
            "clusters": [{
                "leader_id": 1,
                "drone_ids": [1, 2],
                "expected_drone_ids": [1, 2],
                "ready": True,
                "state": "ready",
                "issues": [],
                "advisories": [],
            }],
            "summary": {
                "processed_drone_count": 1,
                "cluster_summary": _status_payload()["status"]["cluster_summary"],
                "package_stats": _package_stats_payload(available=True, drone_ids=[1]),
                "has_results": True,
                "global_preview_drone_count": 1,
            },
            "blockers": [],
            "warnings": [],
            "advisories": [],
        },
        get_elevation_batch_payload=lambda points, elevation_provider: {
            "success": True,
            "results": [
                {
                    "id": point.get("id"),
                    "lat": point["lat"],
                    "lng": point["lng"],
                    "elevation_m": elevation_provider(point["lat"], point["lng"])["elevation"],
                    "status": "ok",
                    "source": "test-provider",
                    "message": None,
                }
                for point in points
            ],
            "summary": {"requested": len(points), "resolved": len(points), "unavailable": 0, "status": "ok"},
        },
        create_processing_job_payload=lambda force_clear=False, auto_reload=True: {
            "job_id": "job-1",
            "status": "queued",
            "phase": "queued",
            "progress_percent": 0,
            "message": "Queued Swarm Trajectory processing job.",
            "result": None,
            "error_code": None,
            "error_message": None,
            "cancel_requested": False,
            "created_at": 1770000000.0,
            "updated_at": 1770000000.0,
            "started_at": None,
            "completed_at": None,
        },
        get_processing_job_payload=lambda job_id: {
            "job_id": job_id,
            "status": "running",
            "phase": "processing",
            "progress_percent": 20,
            "message": "Processing leader/follower trajectories.",
            "result": None,
            "error_code": None,
            "error_message": None,
            "cancel_requested": False,
            "created_at": 1770000000.0,
            "updated_at": 1770000001.0,
            "started_at": 1770000001.0,
            "completed_at": None,
        },
        cancel_processing_job_payload=lambda job_id: {
            "job_id": job_id,
            "status": "running",
            "phase": "processing",
            "progress_percent": 20,
            "message": "Cancellation requested. The active processor cannot be interrupted safely; wait for terminal status.",
            "result": None,
            "error_code": None,
            "error_message": None,
            "cancel_requested": True,
            "created_at": 1770000000.0,
            "updated_at": 1770000002.0,
            "started_at": 1770000001.0,
            "completed_at": None,
        },
        clear_processed_payload=lambda: {
            "success": True,
            "cleared_items": ["processed/Drone 1.csv", "plots/combined_swarm.jpg"],
            "message": "Cleared 2 items successfully",
        },
        clear_all_payload=lambda: {
            "success": True,
            "message": "All trajectory files cleared successfully from 2 locations",
            "cleared_directories": ["raw/Drone 1.csv", "processed/Drone 1.csv"],
        },
        clear_leader_trajectory_payload=lambda leader_id: {
            "success": True,
            "message": f"Drone {leader_id} and associated trajectories cleared successfully",
            "removed_files": [f"processed/Drone {leader_id}.csv"],
        },
        remove_leader_trajectory_payload=lambda leader_id: {
            "success": True,
            "message": f"Removed trajectory for Drone {leader_id}",
            "removed_files": [f"raw/Drone {leader_id}.csv"],
            "files_removed": 1,
        },
        get_processed_trajectory_download=lambda drone_id: (str(csv_path), f"Drone {drone_id}.csv"),
        get_drone_kml_download=lambda drone_id: ("<kml/>", f"Drone {drone_id}.kml"),
        get_cluster_kml_download=lambda leader_id: ("<kml/>", f"Cluster {leader_id}.kml"),
        clear_individual_drone_payload=lambda drone_id: {
            "success": True,
            "message": f"Drone {drone_id} trajectory files removed successfully",
            "removed_files": [f"processed/Drone {drone_id}.csv"],
        },
        commit_trajectory_changes_payload=lambda message=None: {
            "success": True,
            "message": message or "ok",
            "git_info": {"message": "Committed successfully"},
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
        get_elevation=lambda lat, lon: {"elevation": 123.4, "source": "test-provider"},
        log_system_event=lambda *args, **kwargs: None,
        log_system_error=lambda *args, **kwargs: None,
    )


def test_swarm_trajectory_router_registers_expected_routes(tmp_path):
    deps = _make_deps(tmp_path)
    app = FastAPI()
    app.include_router(create_swarm_trajectory_router(deps))

    routes = {route.path for route in app.routes}

    assert "/api/v1/swarm-trajectories/leaders" in routes
    assert "/api/v1/swarm-trajectories/upload/{leader_id}" in routes
    assert "/api/v1/swarm-trajectories/process" in routes
    assert "/api/v1/swarm-trajectories/process/jobs" in routes
    assert "/api/v1/swarm-trajectories/process/jobs/{job_id}" in routes
    assert "/api/v1/swarm-trajectories/process/jobs/{job_id}/cancel" in routes
    assert "/api/v1/swarm-trajectories/recommendation" in routes
    assert "/api/v1/swarm-trajectories/status" in routes
    assert "/api/v1/swarm-trajectories/validate" in routes
    assert "/api/v1/swarm-trajectories/preview" in routes
    assert "/api/v1/swarm-trajectories/elevation/batch" in routes
    assert "/api/v1/swarm-trajectories/policy" in routes
    assert "/api/v1/swarm-trajectories/clear-processed" in routes
    assert "/api/v1/swarm-trajectories/clear" in routes
    assert "/api/v1/swarm-trajectories/clear-leader/{leader_id}" in routes
    assert "/api/v1/swarm-trajectories/remove/{leader_id}" in routes
    assert "/api/v1/swarm-trajectories/download/{drone_id}" in routes
    assert "/api/v1/swarm-trajectories/download-kml/{drone_id}" in routes
    assert "/api/v1/swarm-trajectories/download-cluster-kml/{leader_id}" in routes
    assert "/api/v1/swarm-trajectories/clear-drone/{drone_id}" in routes
    assert "/api/v1/swarm-trajectories/commit" in routes


def test_swarm_trajectory_router_policy_uses_live_params_after_router_creation(tmp_path):
    deps = _make_deps(tmp_path)
    app = FastAPI()
    app.include_router(create_swarm_trajectory_router(deps))

    deps.Params.TRAJECTORY_PLANNER_DEFAULT_MSL = 155.0
    deps.Params.swarm_trajectory_max_speed = 24.5

    with TestClient(app) as client:
        response = client.get("/api/v1/swarm-trajectories/policy")

    assert response.status_code == 200
    payload = response.json()
    assert payload["policy"]["altitude"]["default_msl"] == 155.0
    assert payload["policy"]["speed"]["absolute_max"] == 24.5


def test_swarm_trajectory_router_status_uses_live_service_after_router_creation(tmp_path):
    deps = _make_deps(tmp_path)
    app = FastAPI()
    app.include_router(create_swarm_trajectory_router(deps))

    deps.swarm_trajectory_service.get_processing_status_payload = lambda: {
        **_status_payload(processed_trajectories=9),
    }

    with TestClient(app) as client:
        response = client.get("/api/v1/swarm-trajectories/status")

    assert response.status_code == 200
    assert response.json()["status"]["processed_trajectories"] == 9


def test_swarm_trajectory_router_validation_preview_and_elevation_are_typed(tmp_path):
    deps = _make_deps(tmp_path)
    app = FastAPI()
    app.include_router(create_swarm_trajectory_router(deps))

    with TestClient(app) as client:
        validation = client.get("/api/v1/swarm-trajectories/validate")
        preview = client.get("/api/v1/swarm-trajectories/preview?max_points_per_drone=50")
        elevation = client.post(
            "/api/v1/swarm-trajectories/elevation/batch",
            json={"points": [{"id": "wp-1", "lat": 35.0, "lng": 51.0}]},
        )

    assert validation.status_code == 200
    assert validation.json()["blockers"][0]["code"] == "swarm_trajectory_cluster_missing_upload"
    assert preview.status_code == 200
    assert preview.json()["drones"][0]["points"][0]["lat"] == 35.0
    assert elevation.status_code == 200
    assert elevation.json()["results"][0]["elevation_m"] == 123.4


def test_swarm_trajectory_router_processing_job_contract(tmp_path):
    deps = _make_deps(tmp_path)
    app = FastAPI()
    app.include_router(create_swarm_trajectory_router(deps))

    with TestClient(app) as client:
        created = client.post("/api/v1/swarm-trajectories/process/jobs", json={"force_clear": True})
        status = client.get("/api/v1/swarm-trajectories/process/jobs/job-1")
        canceled = client.post("/api/v1/swarm-trajectories/process/jobs/job-1/cancel")

    assert created.status_code == 202
    assert created.json()["status"] == "queued"
    assert status.status_code == 200
    assert status.json()["phase"] == "processing"
    assert canceled.status_code == 200
    assert canceled.json()["cancel_requested"] is True


def test_swarm_trajectory_router_process_rejects_malformed_json(tmp_path):
    deps = _make_deps(tmp_path)
    app = FastAPI()
    app.include_router(create_swarm_trajectory_router(deps))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/swarm-trajectories/process",
            data="{bad",
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 422
    payload = response.json()
    assert isinstance(payload["detail"], list)
    assert payload["detail"][0]["loc"][0] == "body"


def test_swarm_trajectory_router_commit_rejects_non_object_json(tmp_path):
    deps = _make_deps(tmp_path)
    app = FastAPI()
    app.include_router(create_swarm_trajectory_router(deps))

    with TestClient(app) as client:
        response = client.post("/api/v1/swarm-trajectories/commit", json=["not", "an", "object"])

    assert response.status_code == 422
    payload = response.json()
    assert isinstance(payload["detail"], list)
    assert payload["detail"][0]["loc"][0] == "body"


def test_swarm_trajectory_router_service_error_uses_shared_problem_envelope(tmp_path):
    deps = _make_deps(tmp_path)

    def _missing_status():
        raise _DummySwarmTrajectoryError("Processed outputs not found", 404)

    deps.swarm_trajectory_service.get_processing_status_payload = _missing_status

    app = FastAPI()
    app.include_router(create_swarm_trajectory_router(deps))

    with TestClient(app) as client:
        response = client.get("/api/v1/swarm-trajectories/status")

    assert response.status_code == 404
    payload = response.json()
    assert payload["error"] == "Not found"
    assert payload["detail"] == "Processed outputs not found"
    assert payload["path"] == "/api/v1/swarm-trajectories/status"


def test_swarm_trajectory_router_commit_git_failure_maps_to_operation_error(tmp_path):
    deps = _make_deps(tmp_path)
    deps.swarm_trajectory_service.commit_trajectory_changes_payload = lambda message=None: {
        "success": False,
        "error": "Git push failed: network error. Check internet connectivity.",
        "git_info": {"message": "Git push failed: network error. Check internet connectivity."},
    }

    app = FastAPI()
    app.include_router(create_swarm_trajectory_router(deps))

    with TestClient(app) as client:
        response = client.post("/api/v1/swarm-trajectories/commit", json={"message": "sync outputs"})

    assert response.status_code == 502
    payload = response.json()
    assert payload["error"] == "Bad gateway"
    assert payload["detail"] == "Git push failed: network error. Check internet connectivity."
    assert payload["path"] == "/api/v1/swarm-trajectories/commit"


def test_swarm_trajectory_router_openapi_exposes_typed_contracts(tmp_path):
    deps = _make_deps(tmp_path)
    app = FastAPI()
    app.include_router(create_swarm_trajectory_router(deps))

    schema = app.openapi()
    process_spec = schema["paths"]["/api/v1/swarm-trajectories/process"]["post"]
    process_job_spec = schema["paths"]["/api/v1/swarm-trajectories/process/jobs"]["post"]
    commit_spec = schema["paths"]["/api/v1/swarm-trajectories/commit"]["post"]
    status_spec = schema["paths"]["/api/v1/swarm-trajectories/status"]["get"]
    validation_spec = schema["paths"]["/api/v1/swarm-trajectories/validate"]["get"]
    preview_spec = schema["paths"]["/api/v1/swarm-trajectories/preview"]["get"]
    elevation_spec = schema["paths"]["/api/v1/swarm-trajectories/elevation/batch"]["post"]
    process_request_schema = process_spec["requestBody"]["content"]["application/json"]["schema"]
    process_job_request_schema = process_job_spec["requestBody"]["content"]["application/json"]["schema"]
    commit_request_schema = commit_spec["requestBody"]["content"]["application/json"]["schema"]

    assert process_request_schema["anyOf"][0]["$ref"].endswith(
        "/SwarmTrajectoryProcessRequest"
    )
    assert process_request_schema["anyOf"][1]["type"] == "null"
    assert process_spec["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/SwarmTrajectoryProcessResponse"
    )
    assert process_job_request_schema["anyOf"][0]["$ref"].endswith(
        "/SwarmTrajectoryProcessRequest"
    )
    assert process_job_spec["responses"]["202"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/SwarmTrajectoryProcessingJobResponse"
    )
    assert commit_request_schema["anyOf"][0]["$ref"].endswith(
        "/SwarmTrajectoryCommitRequest"
    )
    assert commit_request_schema["anyOf"][1]["type"] == "null"
    assert commit_spec["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/SwarmTrajectoryCommitResponse"
    )
    assert status_spec["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/SwarmTrajectoryStatusResponse"
    )
    assert validation_spec["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/SwarmTrajectoryValidationResponse"
    )
    assert preview_spec["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/SwarmTrajectoryPreviewResponse"
    )
    assert elevation_spec["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/SwarmTrajectoryElevationBatchRequest"
    )
    assert elevation_spec["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/SwarmTrajectoryElevationBatchResponse"
    )
