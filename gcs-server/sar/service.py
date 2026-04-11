# gcs-server/sar/service.py
"""
QuickScout application service.

This module centralizes QuickScout mission planning, durable operation state,
launch/control orchestration, and findings handling.
"""

from __future__ import annotations

import time
import uuid
import math
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from command_submission import submit_tracked_command
from enums import Mission
from mds_logging import get_logger
from schemas import SubmitCommandRequest, SubmitCommandResponse
from sar.coverage_planner import BoustrophedonPlanner
from sar.schemas import (
    CoveragePlanResponse,
    DroneProgressReport,
    DroneSurveyState,
    QuickScoutFinding,
    QuickScoutFindingCreate,
    QuickScoutFindingUpdate,
    MissionStatus,
    QuickScoutControlAvailability,
    QuickScoutControlEffect,
    QuickScoutLaunchSubmission,
    QuickScoutMissionHandoff,
    QuickScoutMissionHandoffFinding,
    QuickScoutMissionCatalogResponse,
    QuickScoutMissionPhase,
    QuickScoutMissionRequest,
    QuickScoutMissionControlResponse,
    QuickScoutMissionLaunchResponse,
    QuickScoutOperationRecord,
    QuickScoutMissionSummary,
    QuickScoutMissionWorkspaceResponse,
    QuickScoutMissionTemplate,
    ReturnBehavior,
    SearchArea,
    SearchAreaPoint,
    SurveyState,
)
from sar.store import get_quickscout_store
from sar.terrain import apply_terrain_following
import pymap3d

logger = get_logger("quickscout_service")

_service_instance: "QuickScoutService | None" = None


def get_quickscout_service() -> "QuickScoutService":
    global _service_instance
    if _service_instance is None:
        _service_instance = QuickScoutService()
    return _service_instance


class QuickScoutService:
    """Application service for QuickScout mission planning and persistence."""

    def __init__(self, store=None, planner_factory=BoustrophedonPlanner):
        self.store = store or get_quickscout_store()
        self.planner_factory = planner_factory

    def _resolve_pos_ids_to_hw_ids(
        self,
        deps: Any,
        pos_ids: Optional[List[int]],
        *,
        default_hw_ids: Optional[List[str]] = None,
    ) -> Optional[List[str]]:
        """Resolve pos_ids to hw_ids using drone config."""
        if pos_ids is None:
            return list(default_hw_ids) if default_hw_ids is not None else None
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

    @staticmethod
    def _build_operator_label(action: str, mission_id: str, hw_id: Optional[str] = None) -> str:
        suffix = f" {hw_id}" if hw_id else ""
        return f"QuickScout {action} {mission_id[:8]}{suffix}"

    @staticmethod
    def _accepted_hw_ids_from_response(
        response: SubmitCommandResponse,
        fallback_targets: List[str],
    ) -> List[str]:
        ack_summary = response.ack_summary
        details = ack_summary.details if ack_summary is not None else {}
        accepted_hw_ids = [
            str(hw_id)
            for hw_id, detail in details.items()
            if getattr(detail, "category", None) == "accepted"
        ]
        if accepted_hw_ids:
            return accepted_hw_ids
        if response.success and len(fallback_targets) == 1:
            return list(fallback_targets)
        return []

    @staticmethod
    def _summarize_command_response(response: Optional[SubmitCommandResponse]) -> Optional[Dict[str, Any]]:
        if response is None:
            return None
        return {
            "command_id": response.command_id,
            "status": response.status,
            "mission_type": response.mission_type,
            "mission_name": response.mission_name,
            "target_drones": list(response.target_drones),
            "submitted_count": response.submitted_count,
            "tracking_status": response.tracking_status.value if response.tracking_status else None,
            "tracking_phase": response.tracking_phase.value if response.tracking_phase else None,
            "tracking_outcome": response.tracking_outcome.value if response.tracking_outcome else None,
            "tracking_timeout_ms": response.tracking_timeout_ms,
            "message": response.message,
            "timestamp": response.timestamp,
        }

    @staticmethod
    def _resolve_abort_mission_type(return_behavior: ReturnBehavior) -> Mission:
        if return_behavior == ReturnBehavior.LAND_CURRENT:
            return Mission.LAND
        if return_behavior == ReturnBehavior.HOLD_POSITION:
            return Mission.HOLD
        return Mission.RETURN_RTL

    async def _submit_control_command(
        self,
        deps: Any,
        *,
        mission_type: Mission,
        mission_id: str,
        hw_ids: List[str],
        action: str,
    ) -> SubmitCommandResponse:
        request = SubmitCommandRequest(
            mission_type=mission_type.value,
            trigger_time=0,
            mission_id=mission_id,
            target_drone_ids=hw_ids,
            operator_label=self._build_operator_label(action, mission_id),
        )
        return await submit_tracked_command(deps, request)

    def _get_drone_gps_positions(self, deps: Any, pos_ids: Optional[List[int]] = None) -> Dict[str, Tuple[float, float]]:
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
        return positions

    @staticmethod
    def _build_ready_drone_states(operation: QuickScoutOperationRecord) -> Dict[str, DroneSurveyState]:
        now = time.time()
        states = {}
        for plan in operation.plans:
            states[plan.hw_id] = DroneSurveyState(
                hw_id=plan.hw_id,
                pos_id=plan.pos_id,
                state=SurveyState.READY,
                total_waypoints=len(plan.waypoints),
                status_note="Package ready for launch",
                last_update_at=now,
            )
        return states

    @staticmethod
    def _calculate_total_coverage(drone_states: Dict[str, DroneSurveyState]) -> float:
        if not drone_states:
            return 0.0
        return sum(state.coverage_percent for state in drone_states.values()) / len(drone_states)

    @staticmethod
    def _return_behavior_label(return_behavior: ReturnBehavior) -> str:
        if return_behavior == ReturnBehavior.HOLD_POSITION:
            return "hold position"
        if return_behavior == ReturnBehavior.LAND_CURRENT:
            return "land at current position"
        return "return home"

    def _derive_operation_phase(self, operation: QuickScoutOperationRecord) -> QuickScoutMissionPhase:
        if operation.state == SurveyState.PLANNING:
            return QuickScoutMissionPhase.PLANNING
        if operation.state == SurveyState.READY:
            return QuickScoutMissionPhase.READY_TO_LAUNCH
        if operation.state == SurveyState.PAUSED:
            return QuickScoutMissionPhase.HOLDING
        if operation.state == SurveyState.COMPLETED:
            return QuickScoutMissionPhase.COMPLETED
        if operation.state == SurveyState.ABORTED:
            last_action = (operation.last_command_summary or {}).get("action")
            if last_action == "abort":
                return QuickScoutMissionPhase.RETURN_COMMANDED
            return QuickScoutMissionPhase.ABORTED
        if operation.state == SurveyState.EXECUTING:
            launch_summary = operation.launch_summary or {}
            launched = int(launch_summary.get("drones_launched") or 0)
            failed = int(launch_summary.get("drones_failed") or 0)
            if launched > 0 and failed > 0:
                return QuickScoutMissionPhase.LAUNCH_PARTIAL
            return QuickScoutMissionPhase.SEARCHING
        return QuickScoutMissionPhase.PLANNING

    def _build_control_availability(
        self,
        operation: QuickScoutOperationRecord,
        phase: QuickScoutMissionPhase,
    ) -> QuickScoutControlAvailability:
        if phase in (QuickScoutMissionPhase.SEARCHING, QuickScoutMissionPhase.LAUNCH_PARTIAL):
            return QuickScoutControlAvailability(
                pause_enabled=True,
                replan_enabled=phase == QuickScoutMissionPhase.LAUNCH_PARTIAL,
                replan_reason=(
                    "Review the failed launch assignments and build a reduced follow-up package."
                    if phase == QuickScoutMissionPhase.LAUNCH_PARTIAL
                    else "Follow-up planning is typically used after hold, return, or completion."
                ),
                abort_enabled=True,
            )

        if phase == QuickScoutMissionPhase.HOLDING:
            return QuickScoutControlAvailability(
                pause_enabled=False,
                pause_reason="Aircraft are already holding on operator command.",
                replan_enabled=True,
                replan_reason="Plan a follow-up package from the current aircraft state.",
                abort_enabled=True,
            )

        if phase in (
            QuickScoutMissionPhase.RETURN_COMMANDED,
            QuickScoutMissionPhase.ABORTED,
            QuickScoutMissionPhase.COMPLETED,
        ):
            return QuickScoutControlAvailability(
                pause_enabled=False,
                pause_reason="Active hold is only available while the search package is executing.",
                replan_enabled=True,
                replan_reason="Build a follow-up package if the search problem is still active.",
                abort_enabled=False,
                abort_reason="The mission is no longer in an active execution state.",
            )

        return QuickScoutControlAvailability(
            pause_enabled=False,
            pause_reason="Pause becomes available only after a launch is executing.",
            replan_enabled=False,
            replan_reason="Replan becomes relevant after hold, abort, or completion.",
            abort_enabled=False,
            abort_reason="Abort becomes available only after a launch is executing.",
        )

    def _build_status_summary(
        self,
        operation: QuickScoutOperationRecord,
        phase: QuickScoutMissionPhase,
    ) -> Tuple[str, Optional[str]]:
        drone_count = len(operation.drone_states)
        executing_count = sum(1 for state in operation.drone_states.values() if state.state == SurveyState.EXECUTING)
        completed_count = sum(1 for state in operation.drone_states.values() if state.state == SurveyState.COMPLETED)
        paused_count = sum(1 for state in operation.drone_states.values() if state.state == SurveyState.PAUSED)

        if phase == QuickScoutMissionPhase.PLANNING:
            return ("Define the search problem and compute a QuickScout package.", None)

        if phase == QuickScoutMissionPhase.READY_TO_LAUNCH:
            return ("Package is computed and ready for launch review.", None)

        if phase == QuickScoutMissionPhase.LAUNCH_PARTIAL:
            launch_summary = operation.launch_summary or {}
            launched = int(launch_summary.get("drones_launched") or 0)
            failed = int(launch_summary.get("drones_failed") or 0)
            return (
                f"Search package is running on {launched}/{drone_count} assigned drone(s); {failed} launch assignment(s) did not accept dispatch.",
                "Review failed assets or generate a reduced follow-up package before expanding the search.",
            )

        if phase == QuickScoutMissionPhase.SEARCHING:
            return (
                f"Search package is executing on {executing_count or drone_count}/{drone_count} assigned drone(s).",
                None,
            )

        if phase == QuickScoutMissionPhase.HOLDING:
            return (
                f"{paused_count or drone_count} assigned drone(s) are holding on operator command.",
                "QuickScout V1 does not support direct resume; generate a follow-up package from current state.",
            )

        if phase == QuickScoutMissionPhase.RETURN_COMMANDED:
            return (
                f"Mission end command issued; affected drones will {self._return_behavior_label(operation.return_behavior)}.",
                "Monitor the return and build a follow-up package if search coverage is still required.",
            )

        if phase == QuickScoutMissionPhase.COMPLETED:
            return (
                f"All assigned drones reported package completion ({completed_count}/{drone_count}).",
                "Review findings and extend the search only if the problem set changed.",
            )

        return (
            "Mission is no longer executing.",
            "Review the last command result and plan a follow-up package if the search is still active.",
        )

    @staticmethod
    def _build_last_known_point_polygon(
        center: SearchAreaPoint,
        radius_m: float,
        *,
        vertices: int = 8,
    ) -> List[SearchAreaPoint]:
        if radius_m <= 0:
            raise HTTPException(status_code=400, detail="Last-known-point radius must be positive")

        points: List[SearchAreaPoint] = []
        for index in range(max(6, vertices)):
            angle = (2 * math.pi * index) / max(6, vertices)
            east = radius_m * math.cos(angle)
            north = radius_m * math.sin(angle)
            lat, lng, _ = pymap3d.enu2geodetic(east, north, 0, center.lat, center.lng, 0)
            points.append(SearchAreaPoint(lat=float(lat), lng=float(lng)))
        return points

    def _resolve_search_area_for_planning(
        self,
        request: QuickScoutMissionRequest,
    ) -> Tuple[List[SearchAreaPoint], SearchArea]:
        if request.mission_template == QuickScoutMissionTemplate.CORRIDOR_SEARCH:
            path_points = list(request.search_area.path or [])
            corridor_width_m = float(request.search_area.corridor_width_m or 0)
            if len(path_points) < 2 or corridor_width_m <= 0:
                raise HTTPException(
                    status_code=400,
                    detail="Corridor-search missions require at least 2 route points and a positive corridor width",
                )

            polygon_points, corridor_area_sq_m = self._build_corridor_search_polygon(path_points, corridor_width_m)
            resolved_area = request.search_area.model_copy(
                update={
                    "points": polygon_points,
                    "area_sq_m": corridor_area_sq_m,
                }
            )
            return polygon_points, resolved_area

        if request.mission_template == QuickScoutMissionTemplate.LAST_KNOWN_POINT:
            center = request.search_area.center
            radius_m = float(request.search_area.radius_m or 0)
            if center is None or radius_m <= 0:
                raise HTTPException(
                    status_code=400,
                    detail="Last-known-point missions require a center point and positive radius",
                )

            polygon_points = self._build_last_known_point_polygon(center, radius_m)
            resolved_area = request.search_area.model_copy(
                update={
                    "points": polygon_points,
                    "area_sq_m": request.search_area.area_sq_m or math.pi * radius_m * radius_m,
                }
            )
            return polygon_points, resolved_area

        return request.search_area.points, request.search_area

    @staticmethod
    def _build_corridor_search_polygon(
        path_points: List[SearchAreaPoint],
        corridor_width_m: float,
    ) -> Tuple[List[SearchAreaPoint], float]:
        if corridor_width_m <= 0:
            raise HTTPException(status_code=400, detail="Corridor-search width must be positive")

        try:
            from shapely.geometry import LineString
        except ImportError as exc:
            raise HTTPException(
                status_code=500,
                detail="shapely is required for corridor-search planning on the GCS server",
            ) from exc

        if len(path_points) < 2:
            raise HTTPException(
                status_code=400,
                detail="Corridor-search missions require at least 2 route points",
            )

        origin_lat = sum(point.lat for point in path_points) / len(path_points)
        origin_lng = sum(point.lng for point in path_points) / len(path_points)
        origin_alt = 0.0

        enu_path = []
        for point in path_points:
            east, north, _ = pymap3d.geodetic2enu(
                point.lat,
                point.lng,
                0,
                origin_lat,
                origin_lng,
                origin_alt,
            )
            enu_path.append((east, north))

        buffered = LineString(enu_path).buffer(
            corridor_width_m / 2.0,
            cap_style=2,
            join_style=2,
            resolution=8,
        )
        if buffered.is_empty:
            raise HTTPException(status_code=400, detail="Corridor-search geometry produced no searchable area")

        polygon_coords = list(buffered.exterior.coords)[:-1]
        polygon_points = []
        for east, north in polygon_coords:
            lat, lng, _ = pymap3d.enu2geodetic(east, north, 0, origin_lat, origin_lng, origin_alt)
            polygon_points.append(SearchAreaPoint(lat=float(lat), lng=float(lng)))

        return polygon_points, float(buffered.area)

    async def plan_mission(self, deps: Any, request: QuickScoutMissionRequest) -> CoveragePlanResponse:
        """Compute and persist a QuickScout plan without launching it."""
        drone_positions = self._get_drone_gps_positions(deps, request.pos_ids)
        if not drone_positions:
            raise HTTPException(
                status_code=400,
                detail="No live drone GPS positions available for mission planning",
            )

        polygon_points, resolved_search_area = self._resolve_search_area_for_planning(request)
        planner = self.planner_factory()
        plans, total_area = planner.plan(
            polygon_points=polygon_points,
            drone_positions=drone_positions,
            config=request.survey_config,
        )
        if not plans:
            raise HTTPException(status_code=400, detail="Coverage planning produced no plans")

        if request.survey_config.use_terrain_following:
            for plan in plans:
                plan.waypoints = self._apply_camera_interval(plan.waypoints, request.survey_config.camera_interval_s)
                plan.waypoints = await apply_terrain_following(
                    plan.waypoints,
                    request.survey_config.survey_altitude_agl,
                    request.survey_config.cruise_altitude_msl,
                )
        else:
            plan_interval = request.survey_config.camera_interval_s
            for plan in plans:
                plan.waypoints = self._apply_camera_interval(plan.waypoints, plan_interval)

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
        est_time = max((plan.estimated_duration_s for plan in plans), default=0.0)
        now = time.time()
        operation = QuickScoutOperationRecord(
            mission_id=mission_id,
            mission_template=request.mission_template,
            mission_label=request.mission_label,
            mission_profile=request.mission_profile,
            mission_brief=request.mission_brief,
            state=SurveyState.READY,
            search_area=resolved_search_area.model_copy(update={"area_sq_m": total_area}),
            survey_config=request.survey_config,
            pos_ids=request.pos_ids,
            return_behavior=request.return_behavior,
            plans=plans,
            total_area_sq_m=total_area,
            estimated_coverage_time_s=est_time,
            algorithm_used=request.survey_config.algorithm,
            created_at=now,
            updated_at=now,
        )
        operation.drone_states = self._build_ready_drone_states(operation)
        self.store.save_operation(operation)

        return CoveragePlanResponse(
            mission_id=operation.mission_id,
            plans=operation.plans,
            total_area_sq_m=operation.total_area_sq_m,
            estimated_coverage_time_s=operation.estimated_coverage_time_s,
            algorithm_used=operation.algorithm_used,
        )

    @staticmethod
    def _apply_camera_interval(waypoints, camera_interval_s: float):
        updated = []
        for waypoint in waypoints:
            payload = waypoint.model_dump()
            payload["camera_interval_s"] = camera_interval_s
            updated.append(type(waypoint).model_validate(payload))
        return updated

    def get_operation(self, mission_id: str) -> Optional[QuickScoutOperationRecord]:
        return self.store.get_operation(mission_id)

    def get_plans(self, mission_id: str):
        operation = self.store.get_operation(mission_id)
        return operation.plans if operation else None

    def get_config(self, mission_id: str):
        operation = self.store.get_operation(mission_id)
        return operation.survey_config if operation else None

    def get_status(self, mission_id: str) -> Optional[MissionStatus]:
        operation = self.store.get_operation(mission_id)
        if operation is None:
            return None

        elapsed_time_s = time.time() - operation.started_at if operation.started_at else 0.0
        findings = self.store.list_findings(mission_id)
        phase = self._derive_operation_phase(operation)
        status_summary, recommended_action = self._build_status_summary(operation, phase)
        return MissionStatus(
            mission_id=mission_id,
            state=operation.state,
            operation_phase=phase,
            drone_states=operation.drone_states,
            findings=findings,
            total_coverage_percent=self._calculate_total_coverage(operation.drone_states),
            elapsed_time_s=max(0.0, elapsed_time_s),
            started_at=operation.started_at,
            status_summary=status_summary,
            recommended_operator_action=recommended_action,
            control_availability=self._build_control_availability(operation, phase),
            launch_summary=operation.launch_summary,
            last_command_summary=operation.last_command_summary,
        )

    def list_operation_summaries(
        self,
        *,
        limit: int = 20,
        state: Optional[SurveyState] = None,
    ) -> QuickScoutMissionCatalogResponse:
        operations = list(self.store.list_operations())
        if state is not None:
            operations = [operation for operation in operations if operation.state == state]
        operations.sort(key=lambda operation: (operation.updated_at, operation.created_at, operation.mission_id), reverse=True)

        summaries: List[QuickScoutMissionSummary] = []
        for operation in operations[: max(1, limit)]:
            finding_count = len(self.store.list_findings(operation.mission_id))
            summaries.append(
                QuickScoutMissionSummary(
                    mission_id=operation.mission_id,
                    mission_template=operation.mission_template,
                    mission_label=operation.mission_label,
                    mission_profile=operation.mission_profile,
                    state=operation.state,
                    created_at=operation.created_at,
                    updated_at=operation.updated_at,
                    started_at=operation.started_at,
                    drone_count=len(operation.plans),
                    pos_ids=operation.pos_ids,
                    total_area_sq_m=operation.total_area_sq_m,
                    estimated_coverage_time_s=operation.estimated_coverage_time_s,
                    algorithm_used=operation.algorithm_used,
                    return_behavior=operation.return_behavior,
                    total_coverage_percent=self._calculate_total_coverage(operation.drone_states),
                    finding_count=finding_count,
                    last_command_summary=operation.last_command_summary,
                )
            )

        return QuickScoutMissionCatalogResponse(missions=summaries, count=len(summaries))

    def get_workspace(self, mission_id: str) -> Optional[QuickScoutMissionWorkspaceResponse]:
        operation = self.store.get_operation(mission_id)
        status = self.get_status(mission_id)
        if operation is None or status is None:
            return None
        return QuickScoutMissionWorkspaceResponse(operation=operation, status=status)

    @staticmethod
    def _handoff_sort_key(finding: QuickScoutFinding) -> Tuple[int, int, float]:
        priority_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        status_rank = {
            "confirmed": 0,
            "under_review": 1,
            "new": 2,
            "handed_off": 3,
            "dismissed": 4,
        }
        return (
            priority_rank.get(getattr(finding.priority, "value", str(finding.priority)), 99),
            status_rank.get(getattr(finding.status, "value", str(finding.status)), 99),
            -(finding.timestamp or 0.0),
        )

    @staticmethod
    def _build_handoff_brief(
        operation: QuickScoutOperationRecord,
        status: MissionStatus,
        findings: List[QuickScoutFinding],
        *,
        unresolved_finding_count: int,
        confirmed_finding_count: int,
        handed_off_finding_count: int,
    ) -> str:
        mission_name = operation.mission_label or operation.mission_id
        state_label = str(status.state).replace("_", " ")
        phase_label = str(status.operation_phase).replace("_", " ")
        brief_parts = [
            f"{mission_name} is {state_label} in {phase_label} phase.",
            (
                f"{len(findings)} findings logged; {confirmed_finding_count} confirmed, "
                f"{unresolved_finding_count} unresolved, {handed_off_finding_count} handed off."
            ),
        ]

        highest_priority = next(
            (
                finding
                for finding in findings
                if getattr(finding.status, "value", str(finding.status)) != "dismissed"
            ),
            None,
        )
        if highest_priority is not None:
            finding_label = highest_priority.summary or getattr(
                highest_priority.type,
                "value",
                str(highest_priority.type),
            ).replace("_", " ")
            brief_parts.append(
                "Highest-priority finding: "
                f"{finding_label} ("
                f"{getattr(highest_priority.priority, 'value', str(highest_priority.priority)).replace('_', ' ')}, "
                f"{getattr(highest_priority.status, 'value', str(highest_priority.status)).replace('_', ' ')})."
            )

        if status.recommended_operator_action:
            brief_parts.append(status.recommended_operator_action)

        return " ".join(brief_parts)

    def get_mission_handoff(self, mission_id: str) -> Optional[QuickScoutMissionHandoff]:
        operation = self.store.get_operation(mission_id)
        status = self.get_status(mission_id)
        if operation is None or status is None:
            return None

        findings = sorted(self.store.list_findings(mission_id), key=self._handoff_sort_key)
        reviewed_finding_count = sum(
            1
            for finding in findings
            if getattr(finding.status, "value", str(finding.status)) != "new"
        )
        unresolved_finding_count = sum(
            1
            for finding in findings
            if getattr(finding.status, "value", str(finding.status)) in {"new", "under_review"}
        )
        confirmed_finding_count = sum(
            1
            for finding in findings
            if getattr(finding.status, "value", str(finding.status)) == "confirmed"
        )
        handed_off_finding_count = sum(
            1
            for finding in findings
            if getattr(finding.status, "value", str(finding.status)) == "handed_off"
        )
        evidence_ref_count = sum(len(finding.evidence_refs or []) for finding in findings)

        brief_text = self._build_handoff_brief(
            operation,
            status,
            findings,
            unresolved_finding_count=unresolved_finding_count,
            confirmed_finding_count=confirmed_finding_count,
            handed_off_finding_count=handed_off_finding_count,
        )

        return QuickScoutMissionHandoff(
            mission_id=operation.mission_id,
            mission_label=operation.mission_label,
            mission_template=operation.mission_template,
            mission_state=operation.state,
            operation_phase=status.operation_phase,
            mission_brief=operation.mission_brief,
            generated_at=time.time(),
            drone_count=len(operation.plans),
            total_area_sq_m=operation.total_area_sq_m,
            estimated_coverage_time_s=operation.estimated_coverage_time_s,
            total_coverage_percent=status.total_coverage_percent,
            status_summary=status.status_summary,
            recommended_operator_action=status.recommended_operator_action,
            finding_count=len(findings),
            reviewed_finding_count=reviewed_finding_count,
            unresolved_finding_count=unresolved_finding_count,
            confirmed_finding_count=confirmed_finding_count,
            handed_off_finding_count=handed_off_finding_count,
            evidence_ref_count=evidence_ref_count,
            last_command_summary=status.last_command_summary,
            brief_text=brief_text,
            findings=[
                QuickScoutMissionHandoffFinding(
                    id=str(finding.id),
                    summary=finding.summary,
                    type=finding.type,
                    priority=finding.priority,
                    confidence=finding.confidence,
                    status=finding.status,
                    lat=finding.lat,
                    lng=finding.lng,
                    reported_by_drone=finding.reported_by_drone,
                    notes=finding.notes,
                    evidence_refs=list(finding.evidence_refs or []),
                )
                for finding in findings
            ],
        )

    def start_mission(
        self,
        mission_id: str,
        *,
        launched_hw_ids: Optional[List[str]] = None,
        failed_hw_ids: Optional[List[str]] = None,
        launch_summary: Optional[Dict[str, Any]] = None,
    ) -> Optional[MissionStatus]:
        operation = self.store.get_operation(mission_id)
        if operation is None:
            return None

        now = time.time()
        operation.started_at = operation.started_at or now
        operation.updated_at = now
        operation.state = SurveyState.EXECUTING
        launched = set(launched_hw_ids or operation.drone_states.keys())
        failed = set(failed_hw_ids or [])

        for hw_id, drone_state in operation.drone_states.items():
            if hw_id in launched:
                drone_state.state = SurveyState.EXECUTING
                drone_state.status_note = "Search package dispatched"
                drone_state.last_update_at = now
            elif hw_id in failed:
                drone_state.state = SurveyState.READY
                drone_state.status_note = "Launch not accepted"
                drone_state.last_update_at = now

        if launch_summary is not None:
            operation.launch_summary = launch_summary

        self.store.save_operation(operation)
        return self.get_status(mission_id)

    def update_drone_progress(
        self,
        mission_id: str,
        hw_id: str,
        current_waypoint_index: int,
        total_waypoints: int,
        distance_covered_m: float = 0.0,
        state: Optional[SurveyState] = None,
    ) -> bool:
        operation = self.store.get_operation(mission_id)
        if operation is None or hw_id not in operation.drone_states:
            return False

        drone_state = operation.drone_states[hw_id]
        drone_state.current_waypoint_index = current_waypoint_index
        drone_state.total_waypoints = total_waypoints
        drone_state.distance_covered_m = distance_covered_m
        drone_state.last_update_at = time.time()
        if total_waypoints > 0:
            drone_state.coverage_percent = min(100.0, (current_waypoint_index / total_waypoints) * 100.0)
        plan = next((candidate for candidate in operation.plans if candidate.hw_id == hw_id), None)
        if plan is not None and total_waypoints > 0:
            remaining_ratio = max(0.0, 1.0 - min(current_waypoint_index, total_waypoints) / total_waypoints)
            drone_state.estimated_remaining_s = round(plan.estimated_duration_s * remaining_ratio, 1)
        if state is not None:
            drone_state.state = state
            if state == SurveyState.EXECUTING:
                drone_state.status_note = "Executing assigned search track"
            elif state == SurveyState.PAUSED:
                drone_state.status_note = "Holding on operator command"
            elif state == SurveyState.COMPLETED:
                drone_state.status_note = "Search package complete"
            elif state == SurveyState.ABORTED:
                drone_state.status_note = f"Mission ended: {self._return_behavior_label(operation.return_behavior)}"
        elif total_waypoints > 0 and current_waypoint_index >= total_waypoints:
            drone_state.state = SurveyState.COMPLETED
            drone_state.status_note = "Search package complete"
        elif total_waypoints > 0 and current_waypoint_index > 0:
            drone_state.status_note = "Executing assigned search track"

        if operation.drone_states and all(
            current.state == SurveyState.COMPLETED for current in operation.drone_states.values()
        ):
            operation.state = SurveyState.COMPLETED
        elif any(current.state == SurveyState.PAUSED for current in operation.drone_states.values()) and not any(
            current.state == SurveyState.EXECUTING for current in operation.drone_states.values()
        ):
            operation.state = SurveyState.PAUSED
        elif any(current.state == SurveyState.EXECUTING for current in operation.drone_states.values()):
            operation.state = SurveyState.EXECUTING

        operation.updated_at = time.time()
        self.store.save_operation(operation)
        return True

    def pause_mission(self, mission_id: str, hw_ids: Optional[List[str]] = None) -> bool:
        operation = self.store.get_operation(mission_id)
        if operation is None:
            return False

        targets = set(hw_ids or operation.drone_states.keys())
        now = time.time()
        for hw_id, drone_state in operation.drone_states.items():
            if hw_id in targets and drone_state.state == SurveyState.EXECUTING:
                drone_state.state = SurveyState.PAUSED
                drone_state.status_note = "Holding on operator command"
                drone_state.last_update_at = now

        if operation.drone_states and not any(
            state.state == SurveyState.EXECUTING for state in operation.drone_states.values()
        ) and any(state.state == SurveyState.PAUSED for state in operation.drone_states.values()):
            operation.state = SurveyState.PAUSED
        operation.updated_at = now
        self.store.save_operation(operation)
        return True

    def resume_mission(self, mission_id: str, hw_ids: Optional[List[str]] = None) -> bool:
        operation = self.store.get_operation(mission_id)
        if operation is None:
            return False

        targets = set(hw_ids or operation.drone_states.keys())
        for hw_id, drone_state in operation.drone_states.items():
            if hw_id in targets and drone_state.state == SurveyState.PAUSED:
                drone_state.state = SurveyState.EXECUTING

        if any(state.state == SurveyState.EXECUTING for state in operation.drone_states.values()):
            operation.state = SurveyState.EXECUTING
        operation.updated_at = time.time()
        self.store.save_operation(operation)
        return True

    def abort_mission(
        self,
        mission_id: str,
        hw_ids: Optional[List[str]] = None,
        return_behavior: str = "return_home",
    ) -> bool:
        operation = self.store.get_operation(mission_id)
        if operation is None:
            return False

        targets = set(hw_ids or operation.drone_states.keys())
        now = time.time()
        for hw_id, drone_state in operation.drone_states.items():
            if hw_id in targets:
                drone_state.state = SurveyState.ABORTED
                drone_state.status_note = f"Mission ended: {self._return_behavior_label(ReturnBehavior(return_behavior))}"
                drone_state.last_update_at = now

        if operation.drone_states and all(state.state == SurveyState.ABORTED for state in operation.drone_states.values()):
            operation.state = SurveyState.ABORTED
        elif any(state.state == SurveyState.EXECUTING for state in operation.drone_states.values()):
            operation.state = SurveyState.EXECUTING
        elif any(state.state == SurveyState.PAUSED for state in operation.drone_states.values()):
            operation.state = SurveyState.PAUSED
        operation.return_behavior = ReturnBehavior(return_behavior)
        operation.updated_at = now
        operation.launch_summary = {
            **(operation.launch_summary or {}),
            "last_abort_return_behavior": return_behavior,
        }
        self.store.save_operation(operation)
        return True

    def _persist_last_command_summary(
        self,
        mission_id: str,
        summary: Dict[str, Any],
        *,
        update_launch_summary: bool = False,
    ) -> None:
        operation = self.store.get_operation(mission_id)
        if operation is None:
            return
        operation.last_command_summary = summary
        if update_launch_summary:
            operation.launch_summary = summary
        operation.updated_at = time.time()
        self.store.save_operation(operation)

    def _build_launch_summary_payload(
        self,
        response: QuickScoutMissionLaunchResponse,
    ) -> Dict[str, Any]:
        return {
            "action": "launch",
            "timestamp": time.time(),
            "success": response.success,
            "mission_id": response.mission_id,
            "trigger_time": response.trigger_time,
            "drones_requested": response.drones_requested,
            "drones_launched": response.drones_launched,
            "drones_failed": response.drones_failed,
            "launched_hw_ids": list(response.launched_hw_ids),
            "failed_hw_ids": list(response.failed_hw_ids),
            "message": response.message,
            "submissions": [
                {
                    "hw_id": submission.hw_id,
                    "pos_id": submission.pos_id,
                    "accepted": submission.accepted,
                    "error": submission.error,
                    "command": self._summarize_command_response(submission.command),
                }
                for submission in response.submissions
            ],
        }

    def _build_control_summary_payload(
        self,
        response: QuickScoutMissionControlResponse,
    ) -> Dict[str, Any]:
        return {
            "action": response.action,
            "timestamp": time.time(),
            "success": response.success,
            "mission_id": response.mission_id,
            "effect": response.effect.value,
            "state_changed": response.state_changed,
            "target_hw_ids": list(response.target_hw_ids),
            "accepted_hw_ids": list(response.accepted_hw_ids),
            "failed_hw_ids": list(response.failed_hw_ids),
            "return_behavior": response.return_behavior,
            "message": response.message,
            "operator_guidance": response.operator_guidance,
            "command": self._summarize_command_response(response.command),
        }

    async def launch_mission(self, deps: Any, mission_id: str) -> QuickScoutMissionLaunchResponse:
        operation = self.store.get_operation(mission_id)
        if operation is None:
            raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

        try:
            deps.load_config()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to load drone config: {exc}") from exc

        trigger_time = int(time.time()) + 5
        return_behavior = operation.return_behavior.value
        successes = 0
        failures = 0
        submissions: List[QuickScoutLaunchSubmission] = []
        launched_hw_ids: List[str] = []
        failed_hw_ids: List[str] = []

        for plan in operation.plans:
            hw_id = plan.hw_id
            waypoints_data = [waypoint.model_dump(mode="json") for waypoint in plan.waypoints]
            try:
                response = await submit_tracked_command(
                    deps,
                    SubmitCommandRequest(
                        mission_type=Mission.QUICKSCOUT.value,
                        trigger_time=trigger_time,
                        mission_id=mission_id,
                        waypoints=waypoints_data,
                        return_behavior=return_behavior,
                        target_drone_ids=[hw_id],
                        operator_label=self._build_operator_label("launch", mission_id, hw_id),
                    ),
                )
                accepted_hw_ids = self._accepted_hw_ids_from_response(response, [hw_id])
                accepted = hw_id in accepted_hw_ids
                if accepted:
                    successes += 1
                    launched_hw_ids.append(hw_id)
                else:
                    failures += 1
                    failed_hw_ids.append(hw_id)
                submissions.append(
                    QuickScoutLaunchSubmission(
                        hw_id=hw_id,
                        pos_id=plan.pos_id,
                        accepted=accepted,
                        command=response,
                    )
                )
            except HTTPException as exc:
                logger.warning("QuickScout launch submission failed for hw_id=%s: %s", hw_id, exc.detail)
                failures += 1
                failed_hw_ids.append(hw_id)
                submissions.append(
                    QuickScoutLaunchSubmission(
                        hw_id=hw_id,
                        pos_id=plan.pos_id,
                        accepted=False,
                        error=str(exc.detail),
                    )
                )
            except Exception as exc:
                logger.error(f"Failed to send command to drone {hw_id}: {exc}")
                failures += 1
                failed_hw_ids.append(hw_id)
                submissions.append(
                    QuickScoutLaunchSubmission(
                        hw_id=hw_id,
                        pos_id=plan.pos_id,
                        accepted=False,
                        error=str(exc),
                    )
                )

        response = QuickScoutMissionLaunchResponse(
            success=successes > 0,
            mission_id=mission_id,
            trigger_time=trigger_time,
            drones_requested=len(operation.plans),
            drones_launched=successes,
            drones_failed=failures,
            launched_hw_ids=launched_hw_ids,
            failed_hw_ids=failed_hw_ids,
            submissions=submissions,
            message=(
                f"QuickScout launch accepted by {successes}/{len(operation.plans)} planned drone(s)."
                if successes > 0
                else f"QuickScout launch was not accepted by any of the {len(operation.plans)} planned drone(s)."
            ),
        )

        summary = self._build_launch_summary_payload(response)
        if successes > 0:
            self.start_mission(
                mission_id,
                launched_hw_ids=launched_hw_ids,
                failed_hw_ids=failed_hw_ids,
                launch_summary=summary,
            )
        self._persist_last_command_summary(
            mission_id,
            summary,
            update_launch_summary=successes > 0,
        )
        return response

    async def pause_and_command(
        self,
        deps: Any,
        mission_id: str,
        pos_ids: Optional[List[int]] = None,
    ) -> QuickScoutMissionControlResponse:
        operation = self.store.get_operation(mission_id)
        if operation is None:
            raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

        hw_ids = self._resolve_pos_ids_to_hw_ids(
            deps,
            pos_ids,
            default_hw_ids=list(operation.drone_states.keys()),
        )
        if not hw_ids:
            raise HTTPException(status_code=400, detail="No mission drones resolved for pause command")

        response = await self._submit_control_command(
            deps,
            mission_type=Mission.HOLD,
            mission_id=mission_id,
            hw_ids=hw_ids,
            action="pause",
        )
        accepted_hw_ids = self._accepted_hw_ids_from_response(response, hw_ids)
        failed_hw_ids = [hw_id for hw_id in hw_ids if hw_id not in accepted_hw_ids]
        if accepted_hw_ids:
            self.pause_mission(mission_id, accepted_hw_ids)

        payload = QuickScoutMissionControlResponse(
            success=bool(accepted_hw_ids),
            mission_id=mission_id,
            action="pause",
            effect=(
                QuickScoutControlEffect.COMMAND_ACCEPTED
                if accepted_hw_ids
                else QuickScoutControlEffect.COMMAND_REJECTED
            ),
            state_changed=bool(accepted_hw_ids),
            target_hw_ids=hw_ids,
            accepted_hw_ids=accepted_hw_ids,
            failed_hw_ids=failed_hw_ids,
            command=response,
            message=(
                f"Pause accepted by {len(accepted_hw_ids)}/{len(hw_ids)} targeted drone(s)."
                if accepted_hw_ids
                else "Pause command was not accepted by any targeted drone."
            ),
            operator_guidance=(
                "Monitor the hold, then generate a follow-up package from current state if the search must continue."
                if accepted_hw_ids
                else "Check live command status and aircraft readiness before retrying pause."
            ),
        )
        self._persist_last_command_summary(mission_id, self._build_control_summary_payload(payload))
        return payload

    def resume_and_record(
        self,
        deps: Any,
        mission_id: str,
        pos_ids: Optional[List[int]] = None,
    ) -> QuickScoutMissionControlResponse:
        operation = self.store.get_operation(mission_id)
        if operation is None:
            raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

        hw_ids = self._resolve_pos_ids_to_hw_ids(
            deps,
            pos_ids,
            default_hw_ids=list(operation.drone_states.keys()),
        )
        payload = QuickScoutMissionControlResponse(
            success=False,
            mission_id=mission_id,
            action="resume",
            effect=QuickScoutControlEffect.REPLAN_REQUIRED,
            state_changed=False,
            target_hw_ids=hw_ids or [],
            accepted_hw_ids=[],
            failed_hw_ids=hw_ids or [],
            command=None,
            message="QuickScout coverage missions do not support direct resume in V1.",
            operator_guidance="Open plan mode and generate a follow-up package from the current aircraft state.",
        )
        self._persist_last_command_summary(
            mission_id,
            self._build_control_summary_payload(payload),
        )
        return payload

    async def abort_and_command(
        self,
        deps: Any,
        mission_id: str,
        pos_ids: Optional[List[int]] = None,
        return_behavior: str = "return_home",
    ) -> QuickScoutMissionControlResponse:
        operation = self.store.get_operation(mission_id)
        if operation is None:
            raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

        resolved_return_behavior = ReturnBehavior(return_behavior)
        hw_ids = self._resolve_pos_ids_to_hw_ids(
            deps,
            pos_ids,
            default_hw_ids=list(operation.drone_states.keys()),
        )
        if not hw_ids:
            raise HTTPException(status_code=400, detail="No mission drones resolved for abort command")

        response = await self._submit_control_command(
            deps,
            mission_type=self._resolve_abort_mission_type(resolved_return_behavior),
            mission_id=mission_id,
            hw_ids=hw_ids,
            action="abort",
        )
        accepted_hw_ids = self._accepted_hw_ids_from_response(response, hw_ids)
        failed_hw_ids = [hw_id for hw_id in hw_ids if hw_id not in accepted_hw_ids]
        if accepted_hw_ids:
            self.abort_mission(mission_id, accepted_hw_ids, resolved_return_behavior.value)

        payload = QuickScoutMissionControlResponse(
            success=bool(accepted_hw_ids),
            mission_id=mission_id,
            action="abort",
            effect=(
                QuickScoutControlEffect.COMMAND_ACCEPTED
                if accepted_hw_ids
                else QuickScoutControlEffect.COMMAND_REJECTED
            ),
            state_changed=bool(accepted_hw_ids),
            target_hw_ids=hw_ids,
            accepted_hw_ids=accepted_hw_ids,
            failed_hw_ids=failed_hw_ids,
            command=response,
            message=(
                f"Abort accepted by {len(accepted_hw_ids)}/{len(hw_ids)} targeted drone(s)."
                if accepted_hw_ids
                else "Abort command was not accepted by any targeted drone."
            ),
            operator_guidance=(
                f"Monitor the aircraft as they {self._return_behavior_label(resolved_return_behavior)}."
                if accepted_hw_ids
                else "Check live command status and aircraft readiness before retrying mission end control."
            ),
            return_behavior=resolved_return_behavior.value,
        )
        self._persist_last_command_summary(mission_id, self._build_control_summary_payload(payload))
        return payload

    def report_progress(self, mission_id: str, report: DroneProgressReport) -> Dict[str, Any]:
        success = self.update_drone_progress(
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

    def add_finding(
        self,
        mission_id: str,
        finding: QuickScoutFindingCreate | QuickScoutFinding,
    ) -> QuickScoutFinding:
        operation = self.store.get_operation(mission_id)
        if operation is None:
            raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

        if isinstance(finding, QuickScoutFindingCreate):
            finding = QuickScoutFinding.model_validate(finding.model_dump())

        now = time.time()
        if not finding.id:
            finding.id = str(uuid.uuid4())
        if not finding.timestamp:
            finding.timestamp = now
        finding.updated_at = now
        finding.mission_id = mission_id
        self.store.save_finding(mission_id, finding)
        return finding

    def get_findings(self, mission_id: str) -> List[QuickScoutFinding]:
        return self.store.list_findings(mission_id)

    def update_finding(
        self,
        finding_id: str,
        updates: QuickScoutFindingUpdate | Dict[str, Any],
    ) -> Optional[QuickScoutFinding]:
        finding = self.store.get_finding(finding_id)
        if finding is None:
            return None

        resolved_updates = updates
        if isinstance(updates, QuickScoutFindingUpdate):
            resolved_updates = updates.model_dump(exclude_unset=True)

        merged_payload = finding.model_dump(mode="python")
        for key, value in resolved_updates.items():
            if key in ("id", "mission_id", "timestamp"):
                continue
            if key in merged_payload:
                merged_payload[key] = value
        merged_payload["updated_at"] = time.time()

        updated_finding = QuickScoutFinding.model_validate(merged_payload)
        self.store.save_finding(updated_finding.mission_id or "", updated_finding)
        return updated_finding

    def delete_finding(self, finding_id: str) -> bool:
        return self.store.delete_finding(finding_id)
