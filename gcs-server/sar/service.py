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
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from enums import Mission
from mds_logging import get_logger
from sar.coverage_planner import BoustrophedonPlanner
from sar.schemas import (
    CoveragePlanResponse,
    DroneProgressReport,
    DroneSurveyState,
    MissionStatus,
    POI,
    QuickScoutMissionRequest,
    QuickScoutOperationRecord,
    ReturnBehavior,
    SurveyState,
)
from sar.store import get_quickscout_store
from sar.terrain import apply_terrain_following

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

    def _resolve_pos_ids_to_hw_ids(self, deps: Any, pos_ids: Optional[List[int]]) -> Optional[List[str]]:
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

    def _send_control_command(self, deps: Any, mission_type_value: int, hw_ids: Optional[List[str]] = None) -> None:
        """Send a control command (HOLD, RTL, etc.) through the shared command layer."""
        try:
            drones_config = deps.load_config()
        except Exception as exc:
            logger.error(f"Failed to load drone config for control command: {exc}")
            return

        target_ids = hw_ids or [str(drone.get("hw_id", "")) for drone in drones_config]
        command_data = {"mission_type": mission_type_value}
        for hw_id in target_ids:
            try:
                deps.send_commands_to_selected(drones_config, command_data, [hw_id])
            except Exception as exc:
                logger.warning(f"Control command {mission_type_value} to {hw_id} failed: {exc}")

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

    async def plan_mission(self, deps: Any, request: QuickScoutMissionRequest) -> CoveragePlanResponse:
        """Compute and persist a QuickScout plan without launching it."""
        drone_positions = self._get_drone_gps_positions(deps, request.pos_ids)
        if not drone_positions:
            raise HTTPException(
                status_code=400,
                detail="No live drone GPS positions available for mission planning",
            )

        planner = self.planner_factory()
        plans, total_area = planner.plan(
            polygon_points=request.search_area.points,
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
            state=SurveyState.READY,
            search_area=request.search_area,
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

    def launch_mission(self, deps: Any, mission_id: str) -> Dict[str, Any]:
        operation = self.store.get_operation(mission_id)
        if operation is None:
            raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

        try:
            drones_config = deps.load_config()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to load drone config: {exc}") from exc

        trigger_time = int(time.time()) + 5
        return_behavior = operation.return_behavior.value
        successes = 0
        failures = 0
        launched_hw_ids: List[str] = []
        failed_hw_ids: List[str] = []

        for plan in operation.plans:
            waypoints_data = [waypoint.model_dump(mode="json") for waypoint in plan.waypoints]
            command_data = {
                "mission_type": Mission.QUICKSCOUT.value,
                "trigger_time": trigger_time,
                "mission_id": mission_id,
                "waypoints": waypoints_data,
                "return_behavior": return_behavior,
            }
            hw_id = plan.hw_id
            try:
                result = deps.send_commands_to_selected(drones_config, command_data, [hw_id])
                logger.info(f"Command sent to drone {hw_id}: {result.get('result_summary', 'unknown')}")
                if result.get("success", 0) > 0:
                    successes += 1
                    launched_hw_ids.append(hw_id)
                else:
                    failures += 1
                    failed_hw_ids.append(hw_id)
            except Exception as exc:
                logger.error(f"Failed to send command to drone {hw_id}: {exc}")
                failures += 1
                failed_hw_ids.append(hw_id)

        if successes == 0:
            raise HTTPException(
                status_code=502,
                detail=f"All {failures} drone(s) failed to accept mission command",
            )

        summary = {
            "success": True,
            "mission_id": mission_id,
            "drones_launched": successes,
            "drones_failed": failures,
            "trigger_time": trigger_time,
            "message": f"Mission launched with {successes}/{successes + failures} drones",
        }
        self.start_mission(
            mission_id,
            launched_hw_ids=launched_hw_ids,
            failed_hw_ids=failed_hw_ids,
            launch_summary=summary,
        )
        return summary

    def pause_and_command(self, deps: Any, mission_id: str, pos_ids: Optional[List[int]] = None) -> Dict[str, Any]:
        hw_ids = self._resolve_pos_ids_to_hw_ids(deps, pos_ids)
        if not self.pause_mission(mission_id, hw_ids):
            raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")
        self._send_control_command(deps, Mission.HOLD.value, hw_ids)
        return {"success": True, "message": "Mission paused"}

    def resume_and_record(self, deps: Any, mission_id: str, pos_ids: Optional[List[int]] = None) -> Dict[str, Any]:
        hw_ids = self._resolve_pos_ids_to_hw_ids(deps, pos_ids)
        if not self.resume_mission(mission_id, hw_ids):
            raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")
        return {
            "success": True,
            "message": "Mission resumed (GCS state updated, drone resume requires FC interaction)",
        }

    def abort_and_command(
        self,
        deps: Any,
        mission_id: str,
        pos_ids: Optional[List[int]] = None,
        return_behavior: str = "return_home",
    ) -> Dict[str, Any]:
        hw_ids = self._resolve_pos_ids_to_hw_ids(deps, pos_ids)
        if not self.abort_mission(mission_id, hw_ids, return_behavior):
            raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")
        self._send_control_command(deps, Mission.RETURN_RTL.value, hw_ids)
        return {"success": True, "message": "Mission aborted", "return_behavior": return_behavior}

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
