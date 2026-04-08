"""
QuickScout SAR API router.
"""

from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Query

from api_errors import DEFAULT_ERROR_RESPONSES
from .schemas import (
    QuickScoutMissionRequest, CoveragePlanResponse, MissionStatus,
    QuickScoutFinding, QuickScoutFindingCreate, QuickScoutFindingUpdate, DroneProgressReport,
    QuickScoutMissionHandoff,
    QuickScoutMissionCatalogResponse,
    QuickScoutMissionControlResponse,
    QuickScoutMissionLaunchResponse,
    QuickScoutMissionWorkspaceResponse,
    SurveyState,
)
from .terrain import batch_get_elevations
from .service import get_quickscout_service

from mds_logging import get_logger

logger = get_logger("sar_routes")

def create_sar_router(deps: Any) -> APIRouter:
    """Create the QuickScout SAR router using request-time dependency lookup."""
    router = APIRouter(prefix="/api/sar", tags=["QuickScout SAR"], responses=DEFAULT_ERROR_RESPONSES)

    @router.post("/mission/plan", response_model=CoveragePlanResponse)
    async def plan_mission(request: QuickScoutMissionRequest):
        """Compute coverage plan without launching."""
        try:
            return await get_quickscout_service().plan_mission(deps, request)
        except HTTPException:
            raise
        except ImportError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.error(f"Coverage planning failed: {exc}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Coverage planning failed: {str(exc)}") from exc

    @router.get("/missions", response_model=QuickScoutMissionCatalogResponse)
    async def list_missions(
        limit: int = Query(20, ge=1, le=200, description="Maximum persisted missions to return"),
        state: Optional[SurveyState] = Query(None, description="Optional mission-state filter"),
    ):
        return get_quickscout_service().list_operation_summaries(limit=limit, state=state)

    @router.post("/mission/launch", response_model=QuickScoutMissionLaunchResponse)
    async def launch_mission(mission_id: str = Query(..., description="Mission ID to launch")):
        """Launch a previously planned mission."""
        return await get_quickscout_service().launch_mission(deps, mission_id)

    @router.get("/mission/{mission_id}/workspace", response_model=QuickScoutMissionWorkspaceResponse)
    async def get_mission_workspace(mission_id: str):
        workspace = get_quickscout_service().get_workspace(mission_id)
        if not workspace:
            raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")
        return workspace

    @router.get("/mission/{mission_id}/status", response_model=MissionStatus)
    async def get_mission_status(mission_id: str):
        status = get_quickscout_service().get_status(mission_id)
        if not status:
            raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")
        return status

    @router.get("/mission/{mission_id}/handoff", response_model=QuickScoutMissionHandoff)
    async def get_mission_handoff(mission_id: str):
        handoff = get_quickscout_service().get_mission_handoff(mission_id)
        if not handoff:
            raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")
        return handoff

    @router.post("/mission/{mission_id}/pause", response_model=QuickScoutMissionControlResponse)
    async def pause_mission(mission_id: str, pos_ids: Optional[List[int]] = Query(None)):
        return await get_quickscout_service().pause_and_command(deps, mission_id, pos_ids)

    @router.post("/mission/{mission_id}/resume", response_model=QuickScoutMissionControlResponse)
    async def resume_mission(mission_id: str, pos_ids: Optional[List[int]] = Query(None)):
        return get_quickscout_service().resume_and_record(deps, mission_id, pos_ids)

    @router.post("/mission/{mission_id}/abort", response_model=QuickScoutMissionControlResponse)
    async def abort_mission(
        mission_id: str,
        pos_ids: Optional[List[int]] = Query(None),
        return_behavior: str = Query("return_home"),
    ):
        return await get_quickscout_service().abort_and_command(deps, mission_id, pos_ids, return_behavior)

    @router.post("/mission/{mission_id}/progress")
    async def report_progress(mission_id: str, report: DroneProgressReport):
        return get_quickscout_service().report_progress(mission_id, report)

    async def _create_finding(
        finding: QuickScoutFindingCreate,
        mission_id: str = Query(..., description="Mission ID"),
    ):
        return get_quickscout_service().add_finding(mission_id, finding)

    async def _list_findings(mission_id: str = Query(..., description="Mission ID")):
        return get_quickscout_service().get_findings(mission_id)

    async def _update_finding(finding_id: str, updates: QuickScoutFindingUpdate):
        finding = get_quickscout_service().update_finding(finding_id, updates)
        if not finding:
            raise HTTPException(status_code=404, detail=f"Finding {finding_id} not found")
        return finding

    async def _delete_finding(finding_id: str):
        if not get_quickscout_service().delete_finding(finding_id):
            raise HTTPException(status_code=404, detail=f"Finding {finding_id} not found")
        return {"success": True, "message": f"Finding {finding_id} deleted"}

    router.add_api_route("/findings", _create_finding, methods=["POST"], response_model=QuickScoutFinding)
    router.add_api_route("/findings", _list_findings, methods=["GET"], response_model=List[QuickScoutFinding])
    router.add_api_route("/findings/{finding_id}", _update_finding, methods=["PATCH"], response_model=QuickScoutFinding)
    router.add_api_route("/findings/{finding_id}", _delete_finding, methods=["DELETE"])

    @router.post("/elevation/batch")
    async def batch_elevation(points: List[dict]):
        try:
            elevations = await batch_get_elevations(points)
            return {"elevations": elevations, "count": len(elevations)}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Elevation query failed: {str(exc)}") from exc

    return router
