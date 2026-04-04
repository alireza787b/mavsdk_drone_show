"""Configuration-related GCS FastAPI routes."""

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Path as PathParam, Query
from fastapi.responses import JSONResponse

from schemas import ConfigUpdateResponse, FleetConfigEntryPayload


def _get_trajectory_start_position_payload(deps: Any, pos_id: int) -> dict[str, Any]:
    sim_mode = getattr(deps.Params, "sim_mode", False)
    north, east = deps.get_expected_position_from_trajectory(pos_id, sim_mode)

    if north is None or east is None:
        raise HTTPException(status_code=404, detail=f"Trajectory file not found for pos_id={pos_id}")

    return {
        "pos_id": pos_id,
        "x": north,
        "y": east,
        "source": f"Drone {pos_id}.csv (first waypoint)",
    }


def create_configuration_router(deps: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/config/fleet", response_model=list[FleetConfigEntryPayload], tags=["Configuration"])
    async def get_config():
        """Get current drone configuration."""
        try:
            return deps.load_config()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Error loading configuration: {exc}") from exc

    @router.put("/api/v1/config/fleet", response_model=ConfigUpdateResponse, tags=["Configuration"])
    async def save_config_route(
        config_data: list[FleetConfigEntryPayload],
        commit: bool | None = Query(None),
    ):
        """Validate and save drone configuration."""
        try:
            if not config_data:
                raise HTTPException(status_code=400, detail="No configuration data provided")

            deps.log_system_event("💾 Configuration update received", "INFO", "config")
            normalized_config = [entry.model_dump(exclude_none=True) for entry in config_data]

            sim_mode = getattr(deps.Params, "sim_mode", False)
            report = deps.validate_and_process_config(normalized_config, sim_mode)

            deps.save_config(report["updated_config"])
            deps.log_system_event("✅ Configuration saved successfully", "INFO", "config")

            should_commit = commit if commit is not None else deps.Params.GIT_AUTO_PUSH
            git_result = None
            if should_commit:
                drone_count = len(report["updated_config"])
                loop = asyncio.get_running_loop()
                git_result = await loop.run_in_executor(
                    None,
                    deps.git_operations,
                    deps.BASE_DIR,
                    f"config: update config.json via dashboard ({drone_count} drones updated)",
                )

            return ConfigUpdateResponse(
                success=True,
                message="Configuration saved successfully",
                updated_count=len(report["updated_config"]),
                git_result=git_result,
            )
        except HTTPException:
            raise
        except Exception as exc:
            deps.log_system_error(f"Error saving configuration: {exc}", "config")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.post("/api/v1/config/fleet/validation", tags=["Configuration"])
    async def validate_config_route(config_data: list[FleetConfigEntryPayload]):
        """Validate configuration without saving it."""
        try:
            if not config_data:
                raise HTTPException(status_code=400, detail="No configuration data provided")

            sim_mode = getattr(deps.Params, "sim_mode", False)
            report = deps.validate_and_process_config(
                [entry.model_dump(exclude_none=True) for entry in config_data],
                sim_mode,
            )
            return JSONResponse(content=report)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/api/v1/config/fleet/trajectory-start-positions", tags=["Configuration"])
    async def get_drone_positions():
        """Get initial positions for all drones from trajectory CSV files."""
        try:
            return JSONResponse(content=deps.get_all_drone_positions())
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/api/v1/config/fleet/trajectory-start-positions/{pos_id}", tags=["Configuration"])
    async def get_trajectory_start_position(
        pos_id: int = PathParam(..., description="Position ID"),
    ):
        """Get the first expected position from a trajectory CSV file using canonical x/y naming."""
        try:
            return JSONResponse(content=_get_trajectory_start_position_payload(deps, pos_id))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return router
