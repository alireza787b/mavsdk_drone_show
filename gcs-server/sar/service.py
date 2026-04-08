# gcs-server/sar/service.py
"""
QuickScout application service.

This module centralizes QuickScout mission planning, durable operation state,
launch/control orchestration, and POI handling. The current public API surface
stays backward-compatible while the subsystem is migrated away from the earlier
in-memory PoC managers.
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
    MissionStatus,
    POI,
    QuickScoutLaunchSubmission,
    QuickScoutMissionCatalogResponse,
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
        states = {}
        for plan in operation.plans:
            states[plan.hw_id] = DroneSurveyState(
                hw_id=plan.hw_id,
                state=SurveyState.READY,
                total_waypoints=len(plan.waypoints),
            )
        return states

    @staticmethod
    def _calculate_total_coverage(drone_states: Dict[str, DroneSurveyState]) -> float:
        if not drone_states:
            return 0.0
        return sum(state.coverage_percent for state in drone_states.values()) / len(drone_states)

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
        pois = self.store.list_pois(mission_id)
        return MissionStatus(
            mission_id=mission_id,
            state=operation.state,
            drone_states=operation.drone_states,
            pois=pois,
            total_coverage_percent=self._calculate_total_coverage(operation.drone_states),
            elapsed_time_s=max(0.0, elapsed_time_s),
            started_at=operation.started_at,
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
            poi_count = len(self.store.list_pois(operation.mission_id))
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
                    poi_count=poi_count,
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

        for hw_id, drone_state in operation.drone_states.items():
            if hw_id in launched:
                drone_state.state = SurveyState.EXECUTING

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
        if total_waypoints > 0:
            drone_state.coverage_percent = min(100.0, (current_waypoint_index / total_waypoints) * 100.0)
        if state is not None:
            drone_state.state = state
        elif total_waypoints > 0 and current_waypoint_index >= total_waypoints:
            drone_state.state = SurveyState.COMPLETED

        if operation.drone_states and all(
            current.state == SurveyState.COMPLETED for current in operation.drone_states.values()
        ):
            operation.state = SurveyState.COMPLETED
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
        for hw_id, drone_state in operation.drone_states.items():
            if hw_id in targets and drone_state.state == SurveyState.EXECUTING:
                drone_state.state = SurveyState.PAUSED

        if operation.drone_states and all(state.state == SurveyState.PAUSED for state in operation.drone_states.values()):
            operation.state = SurveyState.PAUSED
        operation.updated_at = time.time()
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
        for hw_id, drone_state in operation.drone_states.items():
            if hw_id in targets:
                drone_state.state = SurveyState.ABORTED

        if operation.drone_states and all(state.state == SurveyState.ABORTED for state in operation.drone_states.values()):
            operation.state = SurveyState.ABORTED
        operation.return_behavior = ReturnBehavior(return_behavior)
        operation.updated_at = time.time()
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
            "target_hw_ids": list(response.target_hw_ids),
            "accepted_hw_ids": list(response.accepted_hw_ids),
            "failed_hw_ids": list(response.failed_hw_ids),
            "return_behavior": response.return_behavior,
            "message": response.message,
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
            target_hw_ids=hw_ids,
            accepted_hw_ids=accepted_hw_ids,
            failed_hw_ids=failed_hw_ids,
            command=response,
            message=(
                f"Pause accepted by {len(accepted_hw_ids)}/{len(hw_ids)} targeted drone(s)."
                if accepted_hw_ids
                else "Pause command was not accepted by any targeted drone."
            ),
        )
        self._persist_last_command_summary(mission_id, self._build_control_summary_payload(payload))
        return payload

    def resume_and_record(self, deps: Any, mission_id: str, pos_ids: Optional[List[int]] = None) -> Dict[str, Any]:
        operation = self.store.get_operation(mission_id)
        if operation is None:
            raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

        hw_ids = self._resolve_pos_ids_to_hw_ids(
            deps,
            pos_ids,
            default_hw_ids=list(operation.drone_states.keys()),
        )
        if not self.resume_mission(mission_id, hw_ids):
            raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")
        payload = {
            "success": True,
            "message": "Mission resumed (GCS state updated, drone resume requires FC interaction)",
            "mission_id": mission_id,
            "target_hw_ids": hw_ids or [],
        }
        self._persist_last_command_summary(
            mission_id,
            {"action": "resume_state_only", "timestamp": time.time(), **payload},
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
            target_hw_ids=hw_ids,
            accepted_hw_ids=accepted_hw_ids,
            failed_hw_ids=failed_hw_ids,
            command=response,
            message=(
                f"Abort accepted by {len(accepted_hw_ids)}/{len(hw_ids)} targeted drone(s)."
                if accepted_hw_ids
                else "Abort command was not accepted by any targeted drone."
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

    def add_poi(self, mission_id: str, poi: POI) -> POI:
        operation = self.store.get_operation(mission_id)
        if operation is None:
            raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

        if not poi.id:
            poi.id = str(uuid.uuid4())
        if not poi.timestamp:
            poi.timestamp = time.time()
        poi.mission_id = mission_id
        self.store.save_poi(mission_id, poi)
        return poi

    def get_pois(self, mission_id: str) -> List[POI]:
        return self.store.list_pois(mission_id)

    def update_poi(self, poi_id: str, updates: Dict[str, Any]) -> Optional[POI]:
        poi = self.store.get_poi(poi_id)
        if poi is None:
            return None
        for key, value in updates.items():
            if hasattr(poi, key) and key not in ("id", "mission_id"):
                setattr(poi, key, value)
        self.store.save_poi(poi.mission_id or "", poi)
        return poi

    def delete_poi(self, poi_id: str) -> bool:
        return self.store.delete_poi(poi_id)
