"""Configuration-related GCS FastAPI routes."""

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from schemas import ConfigUpdateResponse


def create_configuration_router(deps: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/get-config-data", tags=["Configuration"])
    async def get_config():
        """Get current drone configuration."""
        try:
            return JSONResponse(content=deps.load_config())
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Error loading configuration: {exc}") from exc

    @router.post("/save-config-data", response_model=ConfigUpdateResponse, tags=["Configuration"])
    async def save_config_route(request: Request):
        """Validate and save drone configuration."""
        try:
            config_data = await request.json()

            if not config_data:
                raise HTTPException(status_code=400, detail="No configuration data provided")

            deps.log_system_event("💾 Configuration update received", "INFO", "config")

            if not isinstance(config_data, list):
                raise HTTPException(status_code=400, detail="Invalid configuration data format")

            sim_mode = getattr(deps.Params, "sim_mode", False)
            report = deps.validate_and_process_config(config_data, sim_mode)

            deps.save_config(report["updated_config"])
            deps.log_system_event("✅ Configuration saved successfully", "INFO", "config")

            git_result = None
            if deps.Params.GIT_AUTO_PUSH:
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

    @router.post("/validate-config", tags=["Configuration"])
    async def validate_config_route(request: Request):
        """Validate configuration without saving it."""
        try:
            config_data = await request.json()

            if not config_data:
                raise HTTPException(status_code=400, detail="No configuration data provided")

            sim_mode = getattr(deps.Params, "sim_mode", False)
            report = deps.validate_and_process_config(config_data, sim_mode)
            return JSONResponse(content=report)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/get-drone-positions", tags=["Configuration"])
    async def get_drone_positions():
        """Get initial positions for all drones from trajectory CSV files."""
        try:
            return JSONResponse(content=deps.get_all_drone_positions())
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/get-trajectory-first-row", tags=["Configuration"])
    async def get_trajectory_first_row(pos_id: int = Query(..., description="Position ID")):
        """Get the first expected position from a trajectory CSV file."""
        try:
            sim_mode = getattr(deps.Params, "sim_mode", False)
            north, east = deps.get_expected_position_from_trajectory(pos_id, sim_mode)

            if north is None or east is None:
                raise HTTPException(status_code=404, detail=f"Trajectory file not found for pos_id={pos_id}")

            return JSONResponse(content={
                "pos_id": pos_id,
                "north": north,
                "east": east,
                "source": f"Drone {pos_id}.csv (first waypoint)",
            })
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return router
