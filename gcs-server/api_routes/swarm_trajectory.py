"""Swarm Trajectory routes extracted from the GCS FastAPI monolith."""

import asyncio
from functools import partial
from typing import Any

from fastapi import APIRouter, Body, File, Path as PathParam, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from api_errors import DEFAULT_ERROR_RESPONSES, build_error_payload
from schemas import (
    SwarmTrajectoryClearAllResponse,
    SwarmTrajectoryClearDroneResponse,
    SwarmTrajectoryClearLeaderResponse,
    SwarmTrajectoryClearProcessedResponse,
    SwarmTrajectoryCommitRequest,
    SwarmTrajectoryCommitResponse,
    SwarmTrajectoryLeaderListResponse,
    SwarmTrajectoryPolicyResponse,
    SwarmTrajectoryProcessRequest,
    SwarmTrajectoryProcessResponse,
    SwarmTrajectoryRecommendationResponse,
    SwarmTrajectoryRemoveLeaderResponse,
    SwarmTrajectoryStatusResponse,
    SwarmTrajectoryUploadResponse,
)


def _swarm_error_response(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=build_error_payload(
            request,
            status_code=exc.status_code,
            detail=exc.message,
        ),
    )


def _swarm_problem_response(request: Request, *, status_code: int, detail: str | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=build_error_payload(
            request,
            status_code=status_code,
            detail=detail,
        ),
    )


def _log_swarm_internal_error(deps: Any, message: str, exc: Exception) -> None:
    deps.log_system_error(f"{message}: {exc}", "swarm")


def _git_failure_status_code(message: str | None) -> int:
    normalized = (message or "").lower()
    if any(token in normalized for token in ("diverged", "non-fast-forward", "rejected", "conflict")):
        return 409
    if any(token in normalized for token in ("timed out", "authentication", "permission denied", "network error")):
        return 502
    return 500


def _build_swarm_trajectory_policy_payload(params: Any) -> dict[str, Any]:
    return {
        "success": True,
        "policy": {
            "altitude": {
                "default_msl": float(getattr(params, "TRAJECTORY_PLANNER_DEFAULT_MSL", 100.0)),
                "default_target_agl": float(getattr(params, "TRAJECTORY_PLANNER_DEFAULT_TARGET_AGL", 100.0)),
                "min_msl": float(getattr(params, "TRAJECTORY_PLANNER_MIN_MSL", 1.0)),
                "max_msl": float(getattr(params, "TRAJECTORY_PLANNER_MAX_MSL", 10000.0)),
            },
            "speed": {
                "default_preferred": float(getattr(params, "TRAJECTORY_PLANNER_DEFAULT_PREFERRED_SPEED", 8.0)),
                "min_preferred": float(getattr(params, "TRAJECTORY_PLANNER_MIN_PREFERRED_SPEED", 0.5)),
                "optimal_max": float(getattr(params, "TRAJECTORY_PLANNER_OPTIMAL_MAX_SPEED", 12.0)),
                "absolute_max": float(getattr(params, "swarm_trajectory_max_speed", 20.0)),
            },
            "timing": {
                "default_route_entry_delay_s": float(getattr(params, "TRAJECTORY_PLANNER_ROUTE_ENTRY_DELAY_S", 10.0)),
                "default_fallback_leg_duration_s": float(
                    getattr(params, "TRAJECTORY_PLANNER_FALLBACK_LEG_DURATION_S", 10.0)
                ),
                "derived_time_step_s": float(getattr(params, "TRAJECTORY_PLANNER_DERIVED_TIME_STEP_S", 0.1)),
            },
            "terrain": {
                "min_safe_clearance_m": float(getattr(params, "TRAJECTORY_PLANNER_MIN_SAFE_CLEARANCE_M", 50.0)),
                "default_safe_clearance_m": float(
                    getattr(params, "TRAJECTORY_PLANNER_DEFAULT_SAFE_CLEARANCE_M", 100.0)
                ),
            },
        },
    }


def create_swarm_trajectory_router(deps: Any) -> APIRouter:
    router = APIRouter(responses=DEFAULT_ERROR_RESPONSES)

    @router.get(
        "/api/v1/swarm-trajectories/leaders",
        response_model=SwarmTrajectoryLeaderListResponse,
        tags=["Swarm Trajectories"],
    )
    async def get_swarm_leaders(request: Request):
        """Get list of top leaders from swarm configuration."""
        try:
            return SwarmTrajectoryLeaderListResponse.model_validate(
                deps.swarm_trajectory_service.get_swarm_leaders_payload()
            )
        except deps.swarm_trajectory_service.SwarmTrajectoryError as exc:
            return _swarm_error_response(request, exc)
        except Exception as exc:
            _log_swarm_internal_error(deps, "Failed to get swarm leaders", exc)
            return _swarm_problem_response(request, status_code=500)

    @router.post(
        "/api/v1/swarm-trajectories/upload/{leader_id}",
        response_model=SwarmTrajectoryUploadResponse,
        tags=["Swarm Trajectories"],
    )
    async def upload_leader_trajectory(
        request: Request,
        leader_id: int = PathParam(..., description="Leader drone ID"),
        file: UploadFile = File(...),
    ):
        """Upload CSV trajectory for a specific top-level leader."""
        try:
            payload = deps.swarm_trajectory_service.save_uploaded_trajectory(
                leader_id=leader_id,
                filename=file.filename or "",
                content=await file.read(),
            )
            return SwarmTrajectoryUploadResponse.model_validate(payload)
        except deps.swarm_trajectory_service.SwarmTrajectoryError as exc:
            return _swarm_error_response(request, exc)
        except Exception as exc:
            _log_swarm_internal_error(deps, f"Failed to upload swarm trajectory for leader {leader_id}", exc)
            return _swarm_problem_response(request, status_code=500)

    @router.post(
        "/api/v1/swarm-trajectories/process",
        response_model=SwarmTrajectoryProcessResponse,
        tags=["Swarm Trajectories"],
    )
    async def process_trajectories(
        request: Request,
        payload: SwarmTrajectoryProcessRequest | None = Body(default=None),
    ):
        """Smart processing with automatic change detection."""
        try:
            process_request = payload or SwarmTrajectoryProcessRequest()

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                partial(
                    deps.swarm_trajectory_service.process_trajectories_payload,
                    force_clear=process_request.force_clear,
                    auto_reload=process_request.auto_reload,
                ),
            )
            return SwarmTrajectoryProcessResponse.model_validate(result)
        except deps.swarm_trajectory_service.SwarmTrajectoryError as exc:
            return _swarm_error_response(request, exc)
        except Exception as exc:
            _log_swarm_internal_error(deps, "Failed to process swarm trajectories", exc)
            return _swarm_problem_response(request, status_code=500)

    @router.get(
        "/api/v1/swarm-trajectories/recommendation",
        response_model=SwarmTrajectoryRecommendationResponse,
        tags=["Swarm Trajectories"],
    )
    async def get_trajectory_recommendation(request: Request):
        """Get smart processing recommendation based on current state."""
        try:
            loop = asyncio.get_running_loop()
            payload = await loop.run_in_executor(
                None,
                deps.swarm_trajectory_service.get_processing_recommendation_payload,
            )
            deps.log_system_event(
                f"Processing recommendation: {payload['recommendation']['action']}",
                "INFO",
                "swarm",
            )
            return SwarmTrajectoryRecommendationResponse.model_validate(payload)
        except deps.swarm_trajectory_service.SwarmTrajectoryError as exc:
            return _swarm_error_response(request, exc)
        except Exception as exc:
            _log_swarm_internal_error(deps, "Failed to get recommendation", exc)
            return _swarm_problem_response(request, status_code=500)

    @router.get(
        "/api/v1/swarm-trajectories/status",
        response_model=SwarmTrajectoryStatusResponse,
        tags=["Swarm Trajectories"],
    )
    async def get_processing_status(request: Request):
        """Get current processing status and file counts."""
        try:
            return SwarmTrajectoryStatusResponse.model_validate(
                deps.swarm_trajectory_service.get_processing_status_payload()
            )
        except deps.swarm_trajectory_service.SwarmTrajectoryError as exc:
            return _swarm_error_response(request, exc)
        except Exception as exc:
            _log_swarm_internal_error(deps, "Failed to get swarm trajectory status", exc)
            return _swarm_problem_response(request, status_code=500)

    @router.get(
        "/api/v1/swarm-trajectories/policy",
        response_model=SwarmTrajectoryPolicyResponse,
        tags=["Swarm Trajectories"],
    )
    async def get_swarm_trajectory_policy(_request: Request):
        """Return the operator-facing trajectory planning envelope sourced from Params."""
        return SwarmTrajectoryPolicyResponse.model_validate(_build_swarm_trajectory_policy_payload(deps.Params))

    @router.post(
        "/api/v1/swarm-trajectories/clear-processed",
        response_model=SwarmTrajectoryClearProcessedResponse,
        tags=["Swarm Trajectories"],
    )
    async def clear_processed_trajectories(request: Request):
        """Explicitly clear all processed data and plots."""
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, deps.swarm_trajectory_service.clear_processed_payload)
            return SwarmTrajectoryClearProcessedResponse.model_validate(result)
        except deps.swarm_trajectory_service.SwarmTrajectoryError as exc:
            return _swarm_error_response(request, exc)
        except Exception as exc:
            _log_swarm_internal_error(deps, "Failed to clear processed swarm trajectories", exc)
            return _swarm_problem_response(request, status_code=500)

    @router.post(
        "/api/v1/swarm-trajectories/clear",
        response_model=SwarmTrajectoryClearAllResponse,
        tags=["Swarm Trajectories"],
    )
    async def clear_all_trajectories(request: Request):
        """Clear all raw, processed, and generated swarm trajectory artifacts."""
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, deps.swarm_trajectory_service.clear_all_payload)
            return SwarmTrajectoryClearAllResponse.model_validate(result)
        except deps.swarm_trajectory_service.SwarmTrajectoryError as exc:
            return _swarm_error_response(request, exc)
        except Exception as exc:
            _log_swarm_internal_error(deps, "Failed to clear all swarm trajectories", exc)
            return _swarm_problem_response(request, status_code=500)

    @router.post(
        "/api/v1/swarm-trajectories/clear-leader/{leader_id}",
        response_model=SwarmTrajectoryClearLeaderResponse,
        tags=["Swarm Trajectories"],
    )
    async def clear_leader_trajectory(
        request: Request,
        leader_id: int = PathParam(..., description="Leader drone ID"),
    ):
        """Clear a leader upload together with all cluster outputs."""
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                partial(deps.swarm_trajectory_service.clear_leader_trajectory_payload, leader_id),
            )
            return SwarmTrajectoryClearLeaderResponse.model_validate(result)
        except deps.swarm_trajectory_service.SwarmTrajectoryError as exc:
            return _swarm_error_response(request, exc)
        except Exception as exc:
            _log_swarm_internal_error(deps, f"Failed to clear leader trajectory for drone {leader_id}", exc)
            return _swarm_problem_response(request, status_code=500)

    @router.delete(
        "/api/v1/swarm-trajectories/remove/{leader_id}",
        response_model=SwarmTrajectoryRemoveLeaderResponse,
        tags=["Swarm Trajectories"],
    )
    async def remove_leader_trajectory(
        request: Request,
        leader_id: int = PathParam(..., description="Leader drone ID"),
    ):
        """Remove a leader upload together with all cluster outputs."""
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                partial(deps.swarm_trajectory_service.remove_leader_trajectory_payload, leader_id),
            )
            return SwarmTrajectoryRemoveLeaderResponse.model_validate(result)
        except deps.swarm_trajectory_service.SwarmTrajectoryError as exc:
            return _swarm_error_response(request, exc)
        except Exception as exc:
            _log_swarm_internal_error(deps, f"Failed to remove leader trajectory for drone {leader_id}", exc)
            return _swarm_problem_response(request, status_code=500)

    @router.get("/api/v1/swarm-trajectories/download/{drone_id}", tags=["Swarm Trajectories"])
    async def download_drone_trajectory(
        request: Request,
        drone_id: int = PathParam(..., description="Drone ID"),
    ):
        """Download a processed drone trajectory CSV."""
        try:
            file_path, filename = deps.swarm_trajectory_service.get_processed_trajectory_download(drone_id)
            return FileResponse(file_path, filename=filename, media_type="text/csv")
        except deps.swarm_trajectory_service.SwarmTrajectoryError as exc:
            return _swarm_error_response(request, exc)
        except Exception as exc:
            _log_swarm_internal_error(deps, f"Failed to download trajectory for drone {drone_id}", exc)
            return _swarm_problem_response(request, status_code=500)

    @router.get("/api/v1/swarm-trajectories/download-kml/{drone_id}", tags=["Swarm Trajectories"])
    async def download_drone_kml(
        request: Request,
        drone_id: int = PathParam(..., description="Drone ID"),
    ):
        """Generate and download a KML file for a single drone trajectory."""
        try:
            loop = asyncio.get_running_loop()
            content, filename = await loop.run_in_executor(
                None,
                partial(deps.swarm_trajectory_service.get_drone_kml_download, drone_id),
            )
            return Response(
                content=content,
                media_type="application/vnd.google-earth.kml+xml",
                headers={"Content-Disposition": f"attachment; filename={filename}"},
            )
        except deps.swarm_trajectory_service.SwarmTrajectoryError as exc:
            return _swarm_error_response(request, exc)
        except Exception as exc:
            _log_swarm_internal_error(deps, f"Failed to generate KML for drone {drone_id}", exc)
            return _swarm_problem_response(request, status_code=500)

    @router.get("/api/v1/swarm-trajectories/download-cluster-kml/{leader_id}", tags=["Swarm Trajectories"])
    async def download_cluster_kml(
        request: Request,
        leader_id: int = PathParam(..., description="Leader drone ID"),
    ):
        """Generate and download a KML file for a full cluster."""
        try:
            loop = asyncio.get_running_loop()
            content, filename = await loop.run_in_executor(
                None,
                partial(deps.swarm_trajectory_service.get_cluster_kml_download, leader_id),
            )
            return Response(
                content=content,
                media_type="application/vnd.google-earth.kml+xml",
                headers={"Content-Disposition": f"attachment; filename={filename}"},
            )
        except deps.swarm_trajectory_service.SwarmTrajectoryError as exc:
            return _swarm_error_response(request, exc)
        except Exception as exc:
            _log_swarm_internal_error(deps, f"Failed to generate cluster KML for leader {leader_id}", exc)
            return _swarm_problem_response(request, status_code=500)

    @router.post(
        "/api/v1/swarm-trajectories/clear-drone/{drone_id}",
        response_model=SwarmTrajectoryClearDroneResponse,
        tags=["Swarm Trajectories"],
    )
    async def clear_individual_drone(
        request: Request,
        drone_id: int = PathParam(..., description="Drone ID"),
    ):
        """Clear a single follower trajectory and invalidate stale plots."""
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                partial(deps.swarm_trajectory_service.clear_individual_drone_payload, drone_id),
            )
            return SwarmTrajectoryClearDroneResponse.model_validate(result)
        except deps.swarm_trajectory_service.SwarmTrajectoryError as exc:
            return _swarm_error_response(request, exc)
        except Exception as exc:
            _log_swarm_internal_error(deps, f"Failed to clear trajectory for drone {drone_id}", exc)
            return _swarm_problem_response(request, status_code=500)

    @router.post(
        "/api/v1/swarm-trajectories/commit",
        response_model=SwarmTrajectoryCommitResponse,
        tags=["Swarm Trajectories"],
    )
    async def commit_trajectory_changes(
        request: Request,
        payload: SwarmTrajectoryCommitRequest | None = Body(default=None),
    ):
        """Commit and push swarm trajectory changes to git."""
        try:
            commit_request = payload or SwarmTrajectoryCommitRequest()

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                partial(deps.swarm_trajectory_service.commit_trajectory_changes_payload, commit_request.message),
            )
            if result.get("success"):
                return SwarmTrajectoryCommitResponse.model_validate(result)
            return _swarm_problem_response(
                request,
                status_code=_git_failure_status_code(result.get("error")),
                detail=result.get("error", "Git operations failed"),
            )
        except deps.swarm_trajectory_service.SwarmTrajectoryError as exc:
            return _swarm_error_response(request, exc)
        except Exception as exc:
            _log_swarm_internal_error(deps, "Failed to commit swarm trajectory changes", exc)
            return _swarm_problem_response(request, status_code=500)

    return router
