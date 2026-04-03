"""Swarm Trajectory routes extracted from the GCS FastAPI monolith."""

import asyncio
import json
from functools import partial
from typing import Any

from fastapi import APIRouter, File, Path as PathParam, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response


def _swarm_error_response(exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": exc.message},
    )


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


def _is_json_content_type(content_type: str) -> bool:
    return content_type.split(";", 1)[0].strip().lower() == "application/json"


async def _parse_optional_json_object(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if not _is_json_content_type(content_type):
        return {}

    raw_body = await request.body()
    if not raw_body or not raw_body.strip():
        return {}

    try:
        payload = json.loads(raw_body)
    except (TypeError, ValueError) as exc:
        raise ValueError("Malformed JSON request body") from exc

    if payload is None:
        return {}

    if not isinstance(payload, dict):
        raise TypeError("Request body must be a JSON object")

    return payload


def create_swarm_trajectory_router(deps: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/swarm-trajectories/leaders", tags=["Swarm Trajectories"])
    async def get_swarm_leaders():
        """Get list of top leaders from swarm configuration."""
        try:
            return JSONResponse(content=deps.swarm_trajectory_service.get_swarm_leaders_payload())
        except deps.swarm_trajectory_service.SwarmTrajectoryError as exc:
            return _swarm_error_response(exc)
        except Exception as exc:
            deps.log_system_error(f"Failed to get swarm leaders: {exc}", "swarm")
            return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})

    @router.post("/api/v1/swarm-trajectories/upload/{leader_id}", tags=["Swarm Trajectories"])
    async def upload_leader_trajectory(
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
            return JSONResponse(content=payload)
        except deps.swarm_trajectory_service.SwarmTrajectoryError as exc:
            return _swarm_error_response(exc)
        except Exception as exc:
            deps.log_system_error(f"Failed to upload swarm trajectory for leader {leader_id}: {exc}", "swarm")
            return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})

    @router.post("/api/v1/swarm-trajectories/process", tags=["Swarm Trajectories"])
    async def process_trajectories(request: Request):
        """Smart processing with automatic change detection."""
        try:
            data = await _parse_optional_json_object(request)
            force_clear = bool(data.get("force_clear", False))
            auto_reload = bool(data.get("auto_reload", True))

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                partial(
                    deps.swarm_trajectory_service.process_trajectories_payload,
                    force_clear=force_clear,
                    auto_reload=auto_reload,
                ),
            )
            return JSONResponse(content=result)
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})
        except deps.swarm_trajectory_service.SwarmTrajectoryError as exc:
            return _swarm_error_response(exc)
        except Exception as exc:
            deps.log_system_error(f"Failed to process swarm trajectories: {exc}", "swarm")
            return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})

    @router.get("/api/v1/swarm-trajectories/recommendation", tags=["Swarm Trajectories"])
    async def get_trajectory_recommendation():
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
            return JSONResponse(content=payload)
        except deps.swarm_trajectory_service.SwarmTrajectoryError as exc:
            return _swarm_error_response(exc)
        except Exception as exc:
            deps.log_system_error(f"Failed to get recommendation: {exc}", "swarm")
            return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})

    @router.get("/api/v1/swarm-trajectories/status", tags=["Swarm Trajectories"])
    async def get_processing_status():
        """Get current processing status and file counts."""
        try:
            return JSONResponse(content=deps.swarm_trajectory_service.get_processing_status_payload())
        except deps.swarm_trajectory_service.SwarmTrajectoryError as exc:
            return _swarm_error_response(exc)
        except Exception as exc:
            deps.log_system_error(f"Failed to get swarm trajectory status: {exc}", "swarm")
            return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})

    @router.get("/api/v1/swarm-trajectories/policy", tags=["Swarm Trajectories"])
    async def get_swarm_trajectory_policy():
        """Return the operator-facing trajectory planning envelope sourced from Params."""
        return JSONResponse(content=_build_swarm_trajectory_policy_payload(deps.Params))

    @router.post("/api/v1/swarm-trajectories/clear-processed", tags=["Swarm Trajectories"])
    async def clear_processed_trajectories():
        """Explicitly clear all processed data and plots."""
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, deps.swarm_trajectory_service.clear_processed_payload)
            return JSONResponse(content=result)
        except deps.swarm_trajectory_service.SwarmTrajectoryError as exc:
            return _swarm_error_response(exc)
        except Exception as exc:
            deps.log_system_error(f"Failed to clear processed swarm trajectories: {exc}", "swarm")
            return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})

    @router.post("/api/v1/swarm-trajectories/clear", tags=["Swarm Trajectories"])
    async def clear_all_trajectories():
        """Clear all raw, processed, and generated swarm trajectory artifacts."""
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, deps.swarm_trajectory_service.clear_all_payload)
            return JSONResponse(content=result)
        except deps.swarm_trajectory_service.SwarmTrajectoryError as exc:
            return _swarm_error_response(exc)
        except Exception as exc:
            deps.log_system_error(f"Failed to clear all swarm trajectories: {exc}", "swarm")
            return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})

    @router.post("/api/v1/swarm-trajectories/clear-leader/{leader_id}", tags=["Swarm Trajectories"])
    async def clear_leader_trajectory(
        leader_id: int = PathParam(..., description="Leader drone ID"),
    ):
        """Clear a leader upload together with all cluster outputs."""
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                partial(deps.swarm_trajectory_service.clear_leader_trajectory_payload, leader_id),
            )
            return JSONResponse(content=result)
        except deps.swarm_trajectory_service.SwarmTrajectoryError as exc:
            return _swarm_error_response(exc)
        except Exception as exc:
            deps.log_system_error(f"Failed to clear leader trajectory for drone {leader_id}: {exc}", "swarm")
            return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})

    @router.delete("/api/v1/swarm-trajectories/remove/{leader_id}", tags=["Swarm Trajectories"])
    async def remove_leader_trajectory(
        leader_id: int = PathParam(..., description="Leader drone ID"),
    ):
        """Remove a leader upload together with all cluster outputs."""
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                partial(deps.swarm_trajectory_service.remove_leader_trajectory_payload, leader_id),
            )
            return JSONResponse(content=result)
        except deps.swarm_trajectory_service.SwarmTrajectoryError as exc:
            return _swarm_error_response(exc)
        except Exception as exc:
            deps.log_system_error(f"Failed to remove leader trajectory for drone {leader_id}: {exc}", "swarm")
            return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})

    @router.get("/api/v1/swarm-trajectories/download/{drone_id}", tags=["Swarm Trajectories"])
    async def download_drone_trajectory(
        drone_id: int = PathParam(..., description="Drone ID"),
    ):
        """Download a processed drone trajectory CSV."""
        try:
            file_path, filename = deps.swarm_trajectory_service.get_processed_trajectory_download(drone_id)
            return FileResponse(file_path, filename=filename, media_type="text/csv")
        except deps.swarm_trajectory_service.SwarmTrajectoryError as exc:
            return _swarm_error_response(exc)
        except Exception as exc:
            deps.log_system_error(f"Failed to download trajectory for drone {drone_id}: {exc}", "swarm")
            return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})

    @router.get("/api/v1/swarm-trajectories/download-kml/{drone_id}", tags=["Swarm Trajectories"])
    async def download_drone_kml(
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
            return _swarm_error_response(exc)
        except Exception as exc:
            deps.log_system_error(f"Failed to generate KML for drone {drone_id}: {exc}", "swarm")
            return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})

    @router.get("/api/v1/swarm-trajectories/download-cluster-kml/{leader_id}", tags=["Swarm Trajectories"])
    async def download_cluster_kml(
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
            return _swarm_error_response(exc)
        except Exception as exc:
            deps.log_system_error(f"Failed to generate cluster KML for leader {leader_id}: {exc}", "swarm")
            return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})

    @router.post("/api/v1/swarm-trajectories/clear-drone/{drone_id}", tags=["Swarm Trajectories"])
    async def clear_individual_drone(
        drone_id: int = PathParam(..., description="Drone ID"),
    ):
        """Clear a single follower trajectory and invalidate stale plots."""
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                partial(deps.swarm_trajectory_service.clear_individual_drone_payload, drone_id),
            )
            return JSONResponse(content=result)
        except deps.swarm_trajectory_service.SwarmTrajectoryError as exc:
            return _swarm_error_response(exc)
        except Exception as exc:
            deps.log_system_error(f"Failed to clear trajectory for drone {drone_id}: {exc}", "swarm")
            return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})

    @router.post("/api/v1/swarm-trajectories/commit", tags=["Swarm Trajectories"])
    async def commit_trajectory_changes(request: Request):
        """Commit and push swarm trajectory changes to git."""
        try:
            data = await _parse_optional_json_object(request)
            commit_message = data.get("message")

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                partial(deps.swarm_trajectory_service.commit_trajectory_changes_payload, commit_message),
            )
            status_code = 200 if result.get("success") else 500
            return JSONResponse(status_code=status_code, content=result)
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})
        except deps.swarm_trajectory_service.SwarmTrajectoryError as exc:
            return _swarm_error_response(exc)
        except Exception as exc:
            deps.log_system_error(f"Failed to commit swarm trajectory changes: {exc}", "swarm")
            return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})

    return router
