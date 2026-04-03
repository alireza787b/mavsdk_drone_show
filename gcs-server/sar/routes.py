"""
QuickScout SAR API router.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Query

from .schemas import (
    QuickScoutMissionRequest, CoveragePlanResponse, MissionStatus,
    POI, DroneProgressReport,
)
from .coverage_planner import BoustrophedonPlanner
from .terrain import apply_terrain_following, batch_get_elevations
from .mission_manager import get_mission_manager
from .poi_manager import get_poi_manager

from enums import Mission
from mds_logging import get_logger

logger = get_logger("sar_routes")

def create_sar_router(deps: Any) -> APIRouter:
    """Create the QuickScout SAR router using request-time dependency lookup."""
    router = APIRouter(prefix="/api/sar", tags=["QuickScout SAR"])

    def _resolve_pos_ids_to_hw_ids(pos_ids: Optional[List[int]]) -> Optional[List[str]]:
        """Resolve pos_ids to hw_ids using drone config. None means all drones."""
        if pos_ids is None:
            return None
        try:
            drones_config = deps.load_config()
            hw_ids = []
            for drone in drones_config:
                pid = int(drone.get("pos_id", -1))
                if pid in pos_ids:
                    hw_ids.append(str(drone.get("hw_id", "")))
            return hw_ids if hw_ids else [str(pos_id) for pos_id in pos_ids]
        except Exception:
            return [str(pos_id) for pos_id in pos_ids]

    def _send_control_command(mission_type_value: int, hw_ids: Optional[List[str]] = None):
        """Send a control command (HOLD, RTL, etc.) through the shared command layer."""
        try:
            drones_config = deps.load_config()
        except Exception as exc:
            logger.error(f"Failed to load drone config for control command: {exc}")
            return

        target_ids = hw_ids or [str(drone.get("hw_id", "")) for drone in drones_config]
        command_data = {"missionType": mission_type_value}
        for hw_id in target_ids:
            try:
                deps.send_commands_to_selected(drones_config, command_data, [hw_id])
            except Exception as exc:
                logger.warning(f"Control command {mission_type_value} to {hw_id} failed: {exc}")

    def _get_drone_gps_positions(pos_ids: Optional[List[int]] = None) -> dict:
        """Get current GPS positions. Returns {pos_id_str: (lat, lng)}."""
        positions = {}
        with deps.telemetry_lock:
            for _, data in deps.telemetry_data_all_drones.items():
                if not data:
                    continue
                lat = data.get("position_lat")
                lng = data.get("position_long")
                pos_id = data.get("pos_id")
                if lat is not None and lng is not None and pos_id is not None:
                    if pos_ids is None or int(pos_id) in pos_ids:
                        positions[str(pos_id)] = (float(lat), float(lng))
        if not positions:
            try:
                for drone in deps.load_config():
                    pid = int(drone.get("pos_id", -1))
                    if pos_ids is None or pid in pos_ids:
                        positions[str(pid)] = (0.0, 0.0)
            except Exception:
                pass
        return positions

    @router.post("/mission/plan", response_model=CoveragePlanResponse)
    async def plan_mission(request: QuickScoutMissionRequest):
        """Compute coverage plan without launching."""
        try:
            drone_positions = _get_drone_gps_positions(request.pos_ids)
            if not drone_positions:
                raise HTTPException(status_code=400, detail="No drones available for mission planning")

            planner = BoustrophedonPlanner()
            plans, total_area = planner.plan(
                polygon_points=request.search_area.points,
                drone_positions=drone_positions,
                config=request.survey_config,
            )
            if not plans:
                raise HTTPException(status_code=400, detail="Coverage planning produced no plans")

            if request.survey_config.use_terrain_following:
                for plan in plans:
                    plan.waypoints = await apply_terrain_following(
                        plan.waypoints,
                        request.survey_config.survey_altitude_agl,
                        request.survey_config.cruise_altitude_msl,
                    )

            try:
                hw_map = {
                    str(drone.get("pos_id", "")): str(drone.get("hw_id", ""))
                    for drone in deps.load_config()
                }
                for plan in plans:
                    if str(plan.pos_id) in hw_map:
                        plan.hw_id = hw_map[str(plan.pos_id)]
            except Exception:
                pass

            mission_id = str(uuid.uuid4())
            est_time = max((plan.estimated_duration_s for plan in plans), default=0)

            manager = get_mission_manager()
            manager.create_mission(mission_id, plans, request.survey_config)

            return CoveragePlanResponse(
                mission_id=mission_id,
                plans=plans,
                total_area_sq_m=total_area,
                estimated_coverage_time_s=est_time,
                algorithm_used=request.survey_config.algorithm,
            )
        except HTTPException:
            raise
        except ImportError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.error(f"Coverage planning failed: {exc}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Coverage planning failed: {str(exc)}") from exc

    @router.post("/mission/launch")
    async def launch_mission(mission_id: str = Query(..., description="Mission ID to launch")):
        """Launch a previously planned mission."""
        manager = get_mission_manager()
        plans = manager.get_plans(mission_id)
        config = manager.get_config(mission_id)
        if not plans:
            raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

        try:
            drones_config = deps.load_config()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to load drone config: {exc}") from exc

        trigger_time = int(time.time()) + 5
        return_behavior = config.return_behavior if config and hasattr(config, "return_behavior") else "return_home"
        successes = 0
        failures = 0

        for plan in plans:
            waypoints_data = [waypoint.model_dump() for waypoint in plan.waypoints]
            command_data = {
                "missionType": Mission.QUICKSCOUT.value,
                "triggerTime": trigger_time,
                "mission_id": mission_id,
                "waypoints": waypoints_data,
                "return_behavior": return_behavior,
                "survey_config": config.model_dump() if config else {},
            }
            hw_id = plan.hw_id
            try:
                result = deps.send_commands_to_selected(drones_config, command_data, [hw_id])
                logger.info(f"Command sent to drone {hw_id}: {result.get('result_summary', 'unknown')}")
                successes += 1
            except Exception as exc:
                logger.error(f"Failed to send command to drone {hw_id}: {exc}")
                failures += 1

        if successes == 0:
            raise HTTPException(
                status_code=502,
                detail=f"All {failures} drone(s) failed to accept mission command",
            )

        manager.start_mission(mission_id)
        return {
            "success": True,
            "mission_id": mission_id,
            "drones_launched": successes,
            "drones_failed": failures,
            "trigger_time": trigger_time,
            "message": f"Mission launched with {successes}/{successes + failures} drones",
        }

    @router.get("/mission/{mission_id}/status", response_model=MissionStatus)
    async def get_mission_status(mission_id: str):
        manager = get_mission_manager()
        status = manager.get_status(mission_id)
        if not status:
            raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")
        return status

    @router.post("/mission/{mission_id}/pause")
    async def pause_mission(mission_id: str, pos_ids: Optional[List[int]] = Query(None)):
        hw_ids = _resolve_pos_ids_to_hw_ids(pos_ids)
        manager = get_mission_manager()
        if not manager.pause_mission(mission_id, hw_ids):
            raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")
        _send_control_command(Mission.HOLD.value, hw_ids)
        return {"success": True, "message": "Mission paused"}

    @router.post("/mission/{mission_id}/resume")
    async def resume_mission(mission_id: str, pos_ids: Optional[List[int]] = Query(None)):
        hw_ids = _resolve_pos_ids_to_hw_ids(pos_ids)
        manager = get_mission_manager()
        if not manager.resume_mission(mission_id, hw_ids):
            raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")
        return {
            "success": True,
            "message": "Mission resumed (GCS state updated, drone resume requires FC interaction)",
        }

    @router.post("/mission/{mission_id}/abort")
    async def abort_mission(
        mission_id: str,
        pos_ids: Optional[List[int]] = Query(None),
        return_behavior: str = Query("return_home"),
    ):
        hw_ids = _resolve_pos_ids_to_hw_ids(pos_ids)
        manager = get_mission_manager()
        if not manager.abort_mission(mission_id, hw_ids, return_behavior):
            raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")
        _send_control_command(Mission.RETURN_RTL.value, hw_ids)
        return {"success": True, "message": "Mission aborted", "return_behavior": return_behavior}

    @router.post("/mission/{mission_id}/progress")
    async def report_progress(mission_id: str, report: DroneProgressReport):
        manager = get_mission_manager()
        success = manager.update_drone_progress(
            mission_id=mission_id,
            hw_id=report.hw_id,
            current_waypoint_index=report.current_waypoint_index,
            total_waypoints=report.total_waypoints,
            distance_covered_m=report.distance_covered_m,
            state=report.state,
        )
        if not success:
            raise HTTPException(status_code=404, detail="Mission or drone not found")
        return {"success": True}

    @router.post("/poi", response_model=POI)
    async def create_poi(poi: POI, mission_id: str = Query(..., description="Mission ID")):
        return get_poi_manager().add_poi(mission_id, poi)

    @router.get("/poi", response_model=List[POI])
    async def list_pois(mission_id: str = Query(..., description="Mission ID")):
        return get_poi_manager().get_pois(mission_id)

    @router.patch("/poi/{poi_id}", response_model=POI)
    async def update_poi(poi_id: str, updates: dict):
        poi = get_poi_manager().update_poi(poi_id, updates)
        if not poi:
            raise HTTPException(status_code=404, detail=f"POI {poi_id} not found")
        return poi

    @router.delete("/poi/{poi_id}")
    async def delete_poi(poi_id: str):
        if not get_poi_manager().delete_poi(poi_id):
            raise HTTPException(status_code=404, detail=f"POI {poi_id} not found")
        return {"success": True, "message": f"POI {poi_id} deleted"}

    @router.post("/elevation/batch")
    async def batch_elevation(points: List[dict]):
        try:
            elevations = await batch_get_elevations(points)
            return {"elevations": elevations, "count": len(elevations)}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Elevation query failed: {str(exc)}") from exc

    return router
