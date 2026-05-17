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
import asyncio
import secrets
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from command_submission import submit_tracked_command
from enums import Mission
from mds_logging import get_logger
from schemas import SubmitCommandRequest, SubmitCommandResponse
from sar.coverage_planner import BoustrophedonPlanner
from sar.schemas import (
    CoveragePlanResponse,
    CoverageWaypoint,
    DroneCoveragePlan,
    DroneProgressReport,
    DroneSurveyState,
    QuickScoutFinding,
    QuickScoutFindingCreate,
    QuickScoutFindingUpdate,
    MissionStatus,
    QuickScoutControlAvailability,
    QuickScoutControlEffect,
    QuickScoutLaunchSubmission,
    QuickScoutLaunchRevalidationResponse,
    QuickScoutMissionHandoff,
    QuickScoutMissionHandoffFinding,
    QuickScoutMissionCatalogResponse,
    QuickScoutMissionPhase,
    QuickScoutPlanningJobResponse,
    QuickScoutPlanningJobState,
    QuickScoutPlanningOrigin,
    QuickScoutPlanningPositionMode,
    QuickScoutPlanningPositionSource,
    QuickScoutPlanningWarning,
    QuickScoutTerrainSummary,
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
from sar.terrain import apply_terrain_following_with_report
import pymap3d

logger = get_logger("quickscout_service")

_service_instance: "QuickScoutService | None" = None
MAX_PLANNING_POSITION_AGE_S = 30.0
CONFIGURED_ORIGIN_REVALIDATION_MAX_DISTANCE_M = 250.0
CONFIGURED_ORIGIN_REVALIDATION_TOKEN_TTL_S = 120.0
CONFIGURED_ORIGIN_CHANGE_TOLERANCE_M = 1.0
CONFIGURED_ORIGIN_ALT_TOLERANCE_M = 2.0
TERMINAL_JOB_STATES = {
    QuickScoutPlanningJobState.SUCCEEDED,
    QuickScoutPlanningJobState.FAILED,
    QuickScoutPlanningJobState.CANCELED,
    QuickScoutPlanningJobState.EXPIRED,
}


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
        self._planning_jobs: Dict[str, Dict[str, Any]] = {}
        self._planning_tasks: Dict[str, asyncio.Task] = {}
        self._launch_revalidation_tokens: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    @staticmethod
    def _normalize_timestamp_ms(value: Any) -> Optional[int]:
        if value in (None, ""):
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if numeric <= 0:
            return None
        if numeric < 1_000_000_000_000:
            numeric *= 1000.0
        return int(numeric)

    @staticmethod
    def _normalize_origin_timestamp_ms(value: Any) -> Optional[int]:
        normalized = QuickScoutService._normalize_timestamp_ms(value)
        if normalized is not None:
            return normalized
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        return int(parsed.timestamp() * 1000)

    @staticmethod
    def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        radius_m = 6_371_000.0
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        d_phi = math.radians(lat2 - lat1)
        d_lambda = math.radians(lng2 - lng1)
        a = (
            math.sin(d_phi / 2.0) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
        )
        return radius_m * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

    @staticmethod
    def _problem_detail(code: str, message: str, *, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = {"code": code, "message": message}
        if details:
            payload["details"] = details
        return payload

    @staticmethod
    def _planning_warning(code: str, message: str, *, details: Optional[Dict[str, Any]] = None) -> QuickScoutPlanningWarning:
        return QuickScoutPlanningWarning(code=code, message=message, details=details)

    def _update_planning_job(
        self,
        job_id: Optional[str],
        *,
        status: Optional[QuickScoutPlanningJobState] = None,
        phase: Optional[str] = None,
        progress_percent: Optional[int] = None,
        message: Optional[str] = None,
        result: Optional[CoveragePlanResponse] = None,
        mission_id: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        warnings: Optional[List[QuickScoutPlanningWarning]] = None,
        completed: bool = False,
    ) -> None:
        if not job_id or job_id not in self._planning_jobs:
            return
        job = self._planning_jobs[job_id]
        now = time.time()
        if status is not None:
            job["status"] = status
            if status == QuickScoutPlanningJobState.RUNNING and job.get("started_at") is None:
                job["started_at"] = now
        if phase is not None:
            job["phase"] = phase
        if progress_percent is not None:
            job["progress_percent"] = max(0, min(100, int(progress_percent)))
        if message is not None:
            job["message"] = message
        if result is not None:
            job["result"] = result
            job["mission_id"] = result.mission_id
        if mission_id is not None:
            job["mission_id"] = mission_id
        if error_code is not None:
            job["error_code"] = error_code
        if error_message is not None:
            job["error_message"] = error_message
        if warnings is not None:
            job["warnings"] = list(warnings)
        if completed:
            job["completed_at"] = now
        job["updated_at"] = now

    def _serialize_planning_job(self, job_id: str) -> QuickScoutPlanningJobResponse:
        if job_id not in self._planning_jobs:
            raise HTTPException(status_code=404, detail="QuickScout planning job not found")
        job = self._planning_jobs[job_id]
        return QuickScoutPlanningJobResponse(
            job_id=job_id,
            status=job["status"],
            phase=job["phase"],
            progress_percent=job["progress_percent"],
            message=job.get("message"),
            mission_id=job.get("mission_id"),
            result=job.get("result"),
            error_code=job.get("error_code"),
            error_message=job.get("error_message"),
            warnings=job.get("warnings") or [],
            cancel_requested=bool(job.get("cancel_requested")),
            created_at=job["created_at"],
            updated_at=job["updated_at"],
            started_at=job.get("started_at"),
            completed_at=job.get("completed_at"),
        )

    def _raise_if_planning_job_canceled(self, job_id: Optional[str]) -> None:
        if job_id and self._planning_jobs.get(job_id, {}).get("cancel_requested"):
            raise asyncio.CancelledError()

    def create_planning_job(self, deps: Any, request: QuickScoutMissionRequest) -> QuickScoutPlanningJobResponse:
        job_id = str(uuid.uuid4())
        now = time.time()
        self._planning_jobs[job_id] = {
            "status": QuickScoutPlanningJobState.QUEUED,
            "phase": "queued",
            "progress_percent": 0,
            "message": "Planning request accepted.",
            "warnings": [],
            "cancel_requested": False,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "completed_at": None,
        }
        task = asyncio.create_task(self._run_planning_job(deps, job_id, request))
        self._planning_tasks[job_id] = task
        return self._serialize_planning_job(job_id)

    async def _run_planning_job(
        self,
        deps: Any,
        job_id: str,
        request: QuickScoutMissionRequest,
    ) -> None:
        try:
            result = await self.plan_mission(deps, request, job_id=job_id)
            self._update_planning_job(
                job_id,
                status=QuickScoutPlanningJobState.SUCCEEDED,
                phase="complete",
                progress_percent=100,
                message="QuickScout plan is ready for review.",
                result=result,
                warnings=result.warnings,
                completed=True,
            )
        except asyncio.CancelledError:
            self._update_planning_job(
                job_id,
                status=QuickScoutPlanningJobState.CANCELED,
                phase="canceled",
                progress_percent=self._planning_jobs.get(job_id, {}).get("progress_percent", 0),
                message="Planning job was canceled before launch package creation.",
                completed=True,
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            self._update_planning_job(
                job_id,
                status=QuickScoutPlanningJobState.FAILED,
                phase="failed",
                progress_percent=self._planning_jobs.get(job_id, {}).get("progress_percent", 100),
                message="QuickScout planning failed.",
                error_code=detail.get("code") or "quickscout_planning_failed",
                error_message=detail.get("message") or str(exc.detail),
                completed=True,
            )
        except Exception as exc:
            logger.error("QuickScout planning job failed: %s", exc, exc_info=True)
            self._update_planning_job(
                job_id,
                status=QuickScoutPlanningJobState.FAILED,
                phase="failed",
                progress_percent=self._planning_jobs.get(job_id, {}).get("progress_percent", 100),
                message="QuickScout planning failed.",
                error_code="quickscout_planning_failed",
                error_message=str(exc),
                completed=True,
            )
        finally:
            self._planning_tasks.pop(job_id, None)

    def get_planning_job(self, job_id: str) -> QuickScoutPlanningJobResponse:
        return self._serialize_planning_job(job_id)

    def cancel_planning_job(self, job_id: str) -> QuickScoutPlanningJobResponse:
        if job_id not in self._planning_jobs:
            raise HTTPException(status_code=404, detail="QuickScout planning job not found")
        job = self._planning_jobs[job_id]
        if job["status"] in TERMINAL_JOB_STATES:
            return self._serialize_planning_job(job_id)
        job["cancel_requested"] = True
        job["updated_at"] = time.time()
        task = self._planning_tasks.get(job_id)
        if task is not None:
            task.cancel()
        self._update_planning_job(
            job_id,
            status=QuickScoutPlanningJobState.CANCELED,
            phase="canceled",
            message="Planning cancellation requested.",
            completed=True,
        )
        return self._serialize_planning_job(job_id)

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
            matched_pos_ids = set()
            for drone in drones_config:
                pid = int(drone.get("pos_id", -1))
                if pid in pos_ids:
                    hw_id = str(drone.get("hw_id", "")).strip()
                    if hw_id:
                        hw_ids.append(hw_id)
                        matched_pos_ids.add(pid)
            missing_pos_ids = sorted(set(int(pos_id) for pos_id in pos_ids) - matched_pos_ids)
            if missing_pos_ids:
                raise HTTPException(
                    status_code=400,
                    detail=self._problem_detail(
                        "quickscout_unknown_pos_ids",
                        "One or more requested QuickScout position IDs are not configured; refusing to target raw IDs.",
                        details={"missing_pos_ids": missing_pos_ids},
                    ),
                )
            return hw_ids
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=503,
                detail=self._problem_detail(
                    "quickscout_target_resolution_unavailable",
                    "Unable to load the drone configuration for QuickScout command target resolution.",
                ),
            )

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

    def _validate_planning_position(
        self,
        data: Dict[str, Any],
        *,
        now_ms: int,
    ) -> Tuple[Optional[Tuple[float, float, int, float]], Optional[Dict[str, Any]]]:
        hw_id = str(data.get("hw_id") or "")
        pos_id = data.get("pos_id")
        context = {"hw_id": hw_id, "pos_id": pos_id}

        if data.get("telemetry_available") is False:
            return None, {**context, "reason": "telemetry_unavailable", "detail": data.get("telemetry_error") or "Telemetry is unavailable"}

        if data.get("global_position_valid") is False:
            return None, {**context, "reason": "global_position_invalid", "detail": data.get("position_unavailable_reason") or "PX4 global position is not valid"}

        try:
            lat = float(data.get("position_lat"))
            lng = float(data.get("position_long"))
        except (TypeError, ValueError):
            return None, {**context, "reason": "position_missing", "detail": "Latitude or longitude is missing"}

        if not all(math.isfinite(value) for value in (lat, lng)):
            return None, {**context, "reason": "position_not_finite", "detail": "Latitude or longitude is not finite"}

        if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
            return None, {**context, "reason": "position_out_of_range", "detail": "Latitude or longitude is outside valid WGS84 bounds"}

        if abs(lat) <= 0.000001 and abs(lng) <= 0.000001:
            return None, {**context, "reason": "default_coordinate", "detail": "Telemetry reported the default 0,0 coordinate"}

        explicit_global = data.get("global_position_valid")
        if not isinstance(explicit_global, bool):
            try:
                gps_fix_type = int(data.get("gps_fix_type") or 0)
            except (TypeError, ValueError):
                gps_fix_type = 0
            if gps_fix_type < 3:
                return None, {**context, "reason": "gps_fix_insufficient", "detail": "A 3D GPS/global position fix is required"}

        timestamp_ms = None
        for key in ("global_position_timestamp_ms", "telemetry_timestamp_ms", "timestamp", "server_time"):
            timestamp_ms = self._normalize_timestamp_ms(data.get(key))
            if timestamp_ms is not None:
                break
        if timestamp_ms is None:
            return None, {**context, "reason": "position_timestamp_missing", "detail": "Telemetry position timestamp is unavailable"}

        age_s = max(0.0, (now_ms - timestamp_ms) / 1000.0)
        if age_s > MAX_PLANNING_POSITION_AGE_S:
            return None, {
                **context,
                "reason": "position_stale",
                "detail": f"Telemetry position is {age_s:.1f}s old; maximum accepted age is {MAX_PLANNING_POSITION_AGE_S:.0f}s",
                "age_s": age_s,
            }

        return (lat, lng, timestamp_ms, age_s), None

    def _get_drone_gps_positions(
        self,
        deps: Any,
        pos_ids: Optional[List[int]] = None,
    ) -> Tuple[Dict[str, Tuple[float, float]], List[QuickScoutPlanningPositionSource], List[QuickScoutPlanningWarning]]:
        """Get validated current GPS positions. Returns positions, sources, warnings."""
        positions: Dict[str, Tuple[float, float]] = {}
        sources: List[QuickScoutPlanningPositionSource] = []
        rejected: List[Dict[str, Any]] = []
        now_ms = self._now_ms()
        requested_ids = set(int(pos_id) for pos_id in pos_ids) if pos_ids is not None else None
        with deps.telemetry_lock:
            for _, data in deps.telemetry_data_all_drones.items():
                if not data:
                    continue
                pos_id = data.get("pos_id")
                try:
                    normalized_pos_id = int(pos_id)
                except (TypeError, ValueError):
                    rejected.append({
                        "hw_id": data.get("hw_id"),
                        "pos_id": pos_id,
                        "reason": "pos_id_invalid",
                        "detail": "Telemetry row has no numeric pos_id",
                    })
                    continue
                if requested_ids is not None and normalized_pos_id not in requested_ids:
                    continue

                accepted, rejection = self._validate_planning_position(data, now_ms=now_ms)
                if rejection is not None:
                    rejected.append(rejection)
                    continue

                lat, lng, timestamp_ms, age_s = accepted
                positions[str(normalized_pos_id)] = (lat, lng)
                sources.append(
                    QuickScoutPlanningPositionSource(
                        pos_id=normalized_pos_id,
                        hw_id=str(data.get("hw_id") or ""),
                        lat=lat,
                        lng=lng,
                        timestamp_ms=timestamp_ms,
                        age_s=age_s,
                        source=str(data.get("position_source") or "global_position"),
                    )
                )

        if requested_ids is not None:
            missing_ids = sorted(requested_ids - {int(key) for key in positions.keys()})
            if missing_ids:
                raise HTTPException(
                    status_code=400,
                    detail=self._problem_detail(
                        "quickscout_position_unavailable",
                        "One or more selected drones do not have fresh valid global positions for QuickScout planning.",
                        details={
                            "missing_pos_ids": missing_ids,
                            "rejected_positions": rejected,
                            "maximum_age_s": MAX_PLANNING_POSITION_AGE_S,
                        },
                    ),
                )

        if not positions:
            raise HTTPException(
                status_code=400,
                detail=self._problem_detail(
                    "quickscout_position_unavailable",
                    "No fresh valid drone global positions are available for QuickScout planning.",
                    details={
                        "rejected_positions": rejected,
                        "maximum_age_s": MAX_PLANNING_POSITION_AGE_S,
                    },
                ),
            )

        warnings: List[QuickScoutPlanningWarning] = []
        if rejected and requested_ids is None:
            warnings.append(
                self._planning_warning(
                    "quickscout_position_skipped",
                    "One or more fleet positions were skipped because they were stale, invalid, or unavailable.",
                    details={"rejected_positions": rejected},
                )
            )

        return positions, sources, warnings

    def _get_configured_origin_positions(
        self,
        deps: Any,
        pos_ids: Optional[List[int]] = None,
    ) -> Tuple[
        Dict[str, Tuple[float, float]],
        List[QuickScoutPlanningPositionSource],
        List[QuickScoutPlanningWarning],
        QuickScoutPlanningOrigin,
    ]:
        """Build planning origins from configured launch slots without using live telemetry."""
        try:
            origin_data = deps.load_origin()
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=self._problem_detail(
                    "quickscout_origin_unavailable",
                    "Configured origin could not be loaded for staged QuickScout planning.",
                    details={"error": str(exc)},
                ),
            ) from exc

        if not origin_data or origin_data.get("lat") in ("", None) or origin_data.get("lon") in ("", None):
            raise HTTPException(
                status_code=400,
                detail=self._problem_detail(
                    "quickscout_origin_unavailable",
                    "Set a configured origin before using staged QuickScout planning.",
                ),
            )

        try:
            origin_lat = float(origin_data["lat"])
            origin_lng = float(origin_data["lon"])
            origin_alt = float(origin_data.get("alt", 0) or 0)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail=self._problem_detail(
                    "quickscout_origin_invalid",
                    "Configured origin has invalid latitude, longitude, or altitude values.",
                ),
            ) from exc

        if (
            not all(math.isfinite(value) for value in (origin_lat, origin_lng, origin_alt))
            or not (-90.0 <= origin_lat <= 90.0)
            or not (-180.0 <= origin_lng <= 180.0)
        ):
            raise HTTPException(
                status_code=400,
                detail=self._problem_detail(
                    "quickscout_origin_invalid",
                    "Configured origin is outside valid WGS84 bounds.",
                ),
            )

        if abs(origin_lat) <= 0.000001 and abs(origin_lng) <= 0.000001:
            raise HTTPException(
                status_code=400,
                detail=self._problem_detail(
                    "quickscout_origin_default_coordinate",
                    "Configured origin is the default 0,0 coordinate. Set the real launch origin before staged planning.",
                ),
            )

        try:
            drones_config = deps.load_config()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to load drone config: {exc}") from exc
        if not drones_config:
            raise HTTPException(
                status_code=404,
                detail=self._problem_detail(
                    "quickscout_config_unavailable",
                    "No drone configuration is available for configured-origin QuickScout planning.",
                ),
            )

        requested_ids = set(int(pos_id) for pos_id in pos_ids) if pos_ids is not None else None
        builder = getattr(deps, "build_desired_launch_positions_report", None)
        if builder is None:
            from origin import build_desired_launch_positions_report as builder

        trajectory_resolver = getattr(deps, "get_expected_position_from_trajectory", None)
        sim_mode = bool(getattr(getattr(deps, "Params", None), "sim_mode", False))
        heading_deg = float(origin_data.get("heading", origin_data.get("heading_deg", 0.0)) or 0.0) % 360.0
        report = builder(
            drones_config,
            origin_lat,
            origin_lng,
            origin_alt,
            heading_deg,
            sim_mode,
            trajectory_resolver=trajectory_resolver,
        )

        positions: Dict[str, Tuple[float, float]] = {}
        sources: List[QuickScoutPlanningPositionSource] = []
        missing_requested = set(requested_ids or [])
        origin_timestamp_ms = self._normalize_origin_timestamp_ms(origin_data.get("timestamp"))
        planning_origin = QuickScoutPlanningOrigin(
            lat=origin_lat,
            lng=origin_lng,
            alt_msl=origin_alt,
            heading_deg=heading_deg,
            timestamp_ms=origin_timestamp_ms,
            source=str(origin_data.get("alt_source") or "configured_origin"),
        )

        for item in report.get("positions", []):
            try:
                normalized_pos_id = int(item.get("pos_id"))
                lat = float(item.get("latitude"))
                lng = float(item.get("longitude"))
            except (TypeError, ValueError):
                continue
            if requested_ids is not None and normalized_pos_id not in requested_ids:
                continue
            if not all(math.isfinite(value) for value in (lat, lng)):
                continue
            positions[str(normalized_pos_id)] = (lat, lng)
            missing_requested.discard(normalized_pos_id)
            sources.append(
                QuickScoutPlanningPositionSource(
                    pos_id=normalized_pos_id,
                    hw_id=str(item.get("hw_id") or ""),
                    lat=lat,
                    lng=lng,
                    timestamp_ms=origin_timestamp_ms or self._now_ms(),
                    age_s=None,
                    source="configured_origin_slot",
                    approximate=True,
                    details={
                        "origin": planning_origin.model_dump(mode="json"),
                        "north_m": item.get("north"),
                        "east_m": item.get("east"),
                        "trajectory_north_m": item.get("trajectory_north"),
                        "trajectory_east_m": item.get("trajectory_east"),
                    },
                )
            )

        if missing_requested:
            raise HTTPException(
                status_code=400,
                detail=self._problem_detail(
                    "quickscout_configured_origin_slots_unavailable",
                    "One or more selected drones do not have configured launch slots for staged planning.",
                    details={"missing_pos_ids": sorted(missing_requested)},
                ),
            )

        if not positions:
            raise HTTPException(
                status_code=400,
                detail=self._problem_detail(
                    "quickscout_configured_origin_slots_unavailable",
                    "No configured launch slots are available for staged QuickScout planning.",
                ),
            )

        warnings = [
            self._planning_warning(
                "quickscout_configured_origin_staged",
                "Plan uses configured origin launch slots; live GPS revalidation is required before launch.",
                details={
                    "origin": planning_origin.model_dump(mode="json"),
                    "slot_count": len(positions),
                },
            )
        ]
        return positions, sources, warnings, planning_origin

    def _resolve_planning_positions(
        self,
        deps: Any,
        request: QuickScoutMissionRequest,
    ) -> Tuple[
        Dict[str, Tuple[float, float]],
        List[QuickScoutPlanningPositionSource],
        List[QuickScoutPlanningWarning],
        Optional[QuickScoutPlanningOrigin],
        bool,
        bool,
    ]:
        if request.position_source_mode == QuickScoutPlanningPositionMode.CONFIGURED_ORIGIN:
            positions, sources, warnings, origin = self._get_configured_origin_positions(deps, request.pos_ids)
            return positions, sources, warnings, origin, False, True

        positions, sources, warnings = self._get_drone_gps_positions(deps, request.pos_ids)
        return positions, sources, warnings, None, True, False

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
            if operation.requires_revalidation:
                return (
                    "Staged package is computed; live GPS revalidation is required before launch.",
                    "Power on assigned aircraft, verify global position, then revalidate from launch review.",
                )
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
    def _get_hw_id_map(deps: Any) -> Dict[str, str]:
        try:
            return {
                str(drone.get("pos_id", "")): str(drone.get("hw_id", ""))
                for drone in deps.load_config()
            }
        except Exception:
            return {}

    def _build_point_dispatch_plans(
        self,
        request: QuickScoutMissionRequest,
        drone_positions: Dict[str, Tuple[float, float]],
        hw_map: Dict[str, str],
    ) -> List[DroneCoveragePlan]:
        center = request.search_area.center
        if center is None:
            raise HTTPException(
                status_code=400,
                detail=self._problem_detail(
                    "quickscout_point_required",
                    "Point-dispatch missions require a selected destination point.",
                ),
            )

        plans: List[DroneCoveragePlan] = []
        cruise_speed_ms = float(request.survey_config.cruise_speed_ms)
        for pos_id_str, (origin_lat, origin_lng) in drone_positions.items():
            pos_id = int(pos_id_str)
            east, north, _ = pymap3d.geodetic2enu(
                center.lat,
                center.lng,
                request.survey_config.cruise_altitude_msl,
                origin_lat,
                origin_lng,
                0,
            )
            distance_m = math.sqrt((east ** 2) + (north ** 2))
            duration_s = distance_m / cruise_speed_ms if cruise_speed_ms > 0 else 0.0
            waypoint = CoverageWaypoint(
                lat=center.lat,
                lng=center.lng,
                alt_msl=request.survey_config.cruise_altitude_msl,
                alt_agl=None,
                ground_elevation=None,
                is_survey_leg=False,
                speed_ms=cruise_speed_ms,
                yaw_deg=None,
                camera_interval_s=None,
                sequence=0,
            )
            plans.append(
                DroneCoveragePlan(
                    hw_id=hw_map.get(pos_id_str) or pos_id_str,
                    pos_id=pos_id,
                    waypoints=[waypoint],
                    assigned_area_sq_m=0.0,
                    estimated_duration_s=duration_s,
                    total_distance_m=distance_m,
                )
            )
        return plans

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

    @staticmethod
    def _aggregate_terrain_summaries(summaries: List[QuickScoutTerrainSummary]) -> Optional[QuickScoutTerrainSummary]:
        if not summaries:
            return None
        queried = sum(summary.queried_waypoints for summary in summaries)
        resolved = sum(summary.resolved_waypoints for summary in summaries)
        missing = sum(summary.missing_waypoints for summary in summaries)
        if missing > 0:
            status = "unavailable" if resolved == 0 else "partial"
            message = (
                "Terrain following requested, but one or more survey waypoint elevations were unavailable."
            )
        else:
            status = "ok"
            message = "Terrain following elevations resolved."
        return QuickScoutTerrainSummary(
            requested=True,
            status=status,
            queried_waypoints=queried,
            resolved_waypoints=resolved,
            missing_waypoints=missing,
            message=message,
        )

    async def plan_mission(
        self,
        deps: Any,
        request: QuickScoutMissionRequest,
        *,
        job_id: Optional[str] = None,
    ) -> CoveragePlanResponse:
        """Compute and persist a QuickScout plan without launching it."""
        warnings: List[QuickScoutPlanningWarning] = []
        self._update_planning_job(
            job_id,
            status=QuickScoutPlanningJobState.RUNNING,
            phase="validating_positions",
            progress_percent=8,
            message=(
                "Loading configured origin launch slots."
                if request.position_source_mode == QuickScoutPlanningPositionMode.CONFIGURED_ORIGIN
                else "Checking selected drone global positions."
            ),
        )
        self._raise_if_planning_job_canceled(job_id)
        (
            drone_positions,
            position_sources,
            position_warnings,
            planning_origin,
            launchable,
            requires_revalidation,
        ) = self._resolve_planning_positions(deps, request)
        warnings.extend(position_warnings)

        self._update_planning_job(
            job_id,
            phase="building_geometry",
            progress_percent=22,
            message="Preparing QuickScout search geometry.",
        )
        self._raise_if_planning_job_canceled(job_id)
        hw_map = self._get_hw_id_map(deps)
        terrain_summary: Optional[QuickScoutTerrainSummary] = None

        if request.mission_template == QuickScoutMissionTemplate.POINT_DISPATCH:
            plans = self._build_point_dispatch_plans(request, drone_positions, hw_map)
            total_area = 0.0
            resolved_search_area = request.search_area
            terrain_summary = QuickScoutTerrainSummary(
                requested=request.survey_config.use_terrain_following,
                status="skipped",
                queried_waypoints=0,
                resolved_waypoints=0,
                missing_waypoints=0,
                message="Point dispatch uses the configured fixed MSL cruise altitude.",
            )
            if len(plans) > 1:
                warnings.append(
                    self._planning_warning(
                        "quickscout_shared_point_dispatch",
                        "Multiple drones are assigned to the same dispatch point; review spacing and timing before launch.",
                        details={"drone_count": len(plans)},
                    )
                )
        else:
            polygon_points, resolved_search_area = self._resolve_search_area_for_planning(request)
            self._update_planning_job(
                job_id,
                phase="computing_coverage",
                progress_percent=42,
                message="Computing coverage tracks.",
            )
            self._raise_if_planning_job_canceled(job_id)
            planner = self.planner_factory()
            plans, total_area = planner.plan(
                polygon_points=polygon_points,
                drone_positions=drone_positions,
                config=request.survey_config,
            )
        if not plans:
            raise HTTPException(status_code=400, detail="Coverage planning produced no plans")

        if request.survey_config.use_terrain_following and request.mission_template != QuickScoutMissionTemplate.POINT_DISPATCH:
            self._update_planning_job(
                job_id,
                phase="terrain_lookup",
                progress_percent=68,
                message="Resolving terrain elevations for survey altitude.",
            )
            self._raise_if_planning_job_canceled(job_id)
            terrain_summaries: List[QuickScoutTerrainSummary] = []
            for plan in plans:
                plan.waypoints = self._apply_camera_interval(plan.waypoints, request.survey_config.camera_interval_s)
                plan.waypoints, plan_terrain_summary = await apply_terrain_following_with_report(
                    plan.waypoints,
                    request.survey_config.survey_altitude_agl,
                    request.survey_config.cruise_altitude_msl,
                )
                terrain_summaries.append(plan_terrain_summary)
            terrain_summary = self._aggregate_terrain_summaries(terrain_summaries)
            if terrain_summary and terrain_summary.missing_waypoints > 0:
                raise HTTPException(
                    status_code=503,
                    detail=self._problem_detail(
                        "quickscout_terrain_unavailable",
                        "Terrain following was requested, but the terrain provider did not resolve every survey waypoint. Use fixed MSL or retry when terrain data is available.",
                        details=terrain_summary.model_dump(),
                    ),
                )
        elif request.mission_template != QuickScoutMissionTemplate.POINT_DISPATCH:
            plan_interval = request.survey_config.camera_interval_s
            for plan in plans:
                plan.waypoints = self._apply_camera_interval(plan.waypoints, plan_interval)
            terrain_summary = QuickScoutTerrainSummary(
                requested=False,
                status="skipped",
                queried_waypoints=0,
                resolved_waypoints=0,
                missing_waypoints=0,
                message="Terrain following disabled; planner used fixed MSL altitude.",
            )

        for plan in plans:
            if str(plan.pos_id) in hw_map:
                plan.hw_id = hw_map[str(plan.pos_id)]

        self._update_planning_job(
            job_id,
            phase="persisting_package",
            progress_percent=88,
            message="Saving mission package for launch review.",
        )
        self._raise_if_planning_job_canceled(job_id)
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
            planning_warnings=warnings,
            position_sources=position_sources,
            position_source_mode=request.position_source_mode,
            planning_origin=planning_origin,
            launchable=launchable,
            requires_revalidation=requires_revalidation,
            terrain_summary=terrain_summary,
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
            warnings=warnings,
            position_sources=position_sources,
            position_source_mode=request.position_source_mode,
            planning_origin=planning_origin,
            launchable=launchable,
            requires_revalidation=requires_revalidation,
            terrain_summary=terrain_summary,
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
                    position_source_mode=operation.position_source_mode,
                    launchable=operation.launchable,
                    requires_revalidation=operation.requires_revalidation,
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

    def _create_launch_revalidation_token(self, mission_id: str) -> Tuple[str, float]:
        token = secrets.token_urlsafe(24)
        expires_at = time.time() + CONFIGURED_ORIGIN_REVALIDATION_TOKEN_TTL_S
        self._launch_revalidation_tokens[mission_id] = {
            "token": token,
            "expires_at": expires_at,
        }
        return token, expires_at

    def _consume_launch_revalidation_token(self, mission_id: str, token: Optional[str]) -> bool:
        if not token:
            return False
        record = self._launch_revalidation_tokens.get(mission_id)
        if not record:
            return False
        if record.get("token") != token:
            return False
        if float(record.get("expires_at") or 0) < time.time():
            self._launch_revalidation_tokens.pop(mission_id, None)
            return False
        self._launch_revalidation_tokens.pop(mission_id, None)
        return True

    def _build_launch_revalidation_required_error(self, operation: QuickScoutOperationRecord) -> HTTPException:
        return HTTPException(
            status_code=400,
            detail=self._problem_detail(
                "quickscout_launch_revalidation_required",
                "This QuickScout package was planned from configured origin slots. Revalidate live drone GPS positions before launch.",
                details={
                    "mission_id": operation.mission_id,
                    "position_source_mode": operation.position_source_mode.value,
                    "requires_revalidation": operation.requires_revalidation,
                    "token_ttl_s": CONFIGURED_ORIGIN_REVALIDATION_TOKEN_TTL_S,
                },
            ),
        )

    def revalidate_launch(self, deps: Any, mission_id: str) -> QuickScoutLaunchRevalidationResponse:
        operation = self.store.get_operation(mission_id)
        if operation is None:
            raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

        if not operation.requires_revalidation:
            return QuickScoutLaunchRevalidationResponse(
                mission_id=mission_id,
                launchable=True,
                token=None,
                expires_at=None,
                max_slot_error_m=CONFIGURED_ORIGIN_REVALIDATION_MAX_DISTANCE_M,
                slot_errors_m={},
                blockers=[],
                warnings=[],
                position_sources=operation.position_sources,
                message="This QuickScout package already uses live validated drone positions.",
            )

        blockers: List[QuickScoutPlanningWarning] = []
        warnings: List[QuickScoutPlanningWarning] = []
        position_sources: List[QuickScoutPlanningPositionSource] = []
        slot_errors_m: Dict[str, float] = {}

        planning_origin = operation.planning_origin
        if planning_origin is not None:
            try:
                origin_data = deps.load_origin()
                current_origin_lat = float(origin_data["lat"])
                current_origin_lng = float(origin_data["lon"])
                current_origin_alt = float(origin_data.get("alt", 0) or 0)
                origin_delta_m = self._haversine_m(
                    planning_origin.lat,
                    planning_origin.lng,
                    current_origin_lat,
                    current_origin_lng,
                )
                origin_alt_delta_m = abs(current_origin_alt - planning_origin.alt_msl)
                if (
                    origin_delta_m > CONFIGURED_ORIGIN_CHANGE_TOLERANCE_M
                    or origin_alt_delta_m > CONFIGURED_ORIGIN_ALT_TOLERANCE_M
                ):
                    blockers.append(
                        self._planning_warning(
                            "quickscout_planning_origin_changed",
                            "Configured origin changed after this QuickScout package was computed. Recompute before launch.",
                            details={
                                "origin_delta_m": origin_delta_m,
                                "origin_alt_delta_m": origin_alt_delta_m,
                            },
                        )
                    )
            except Exception as exc:
                blockers.append(
                    self._planning_warning(
                        "quickscout_origin_unavailable",
                        "Configured origin could not be verified before launch. Recompute or set origin again.",
                        details={"error": str(exc)},
                    )
                )

        try:
            plan_pos_ids = [int(plan.pos_id) for plan in operation.plans]
            live_positions, position_sources, position_warnings = self._get_drone_gps_positions(deps, plan_pos_ids)
            warnings.extend(position_warnings)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            blockers.append(
                self._planning_warning(
                    str(detail.get("code") or "quickscout_position_unavailable"),
                    str(
                        detail.get("message")
                        or "One or more assigned drones do not have fresh valid global positions for launch revalidation."
                    ),
                    details=detail.get("details") if isinstance(detail.get("details"), dict) else None,
                )
            )
            live_positions = {}

        expected_sources = {
            int(source.pos_id): source
            for source in operation.position_sources
            if source.source == "configured_origin_slot"
        }
        for plan in operation.plans:
            expected = expected_sources.get(int(plan.pos_id))
            live = live_positions.get(str(plan.pos_id))
            if expected is None:
                blockers.append(
                    self._planning_warning(
                        "quickscout_configured_slot_missing",
                        f"No configured-origin slot provenance is stored for drone position {plan.pos_id}. Recompute before launch.",
                        details={"pos_id": plan.pos_id, "hw_id": plan.hw_id},
                    )
                )
                continue
            if live is None:
                continue
            error_m = self._haversine_m(expected.lat, expected.lng, live[0], live[1])
            slot_errors_m[str(plan.pos_id)] = error_m
            if error_m > CONFIGURED_ORIGIN_REVALIDATION_MAX_DISTANCE_M:
                blockers.append(
                    self._planning_warning(
                        "quickscout_launch_slot_mismatch",
                        f"Drone position {plan.pos_id} is too far from its planned configured-origin launch slot.",
                        details={
                            "pos_id": plan.pos_id,
                            "hw_id": plan.hw_id,
                            "slot_error_m": error_m,
                            "maximum_error_m": CONFIGURED_ORIGIN_REVALIDATION_MAX_DISTANCE_M,
                        },
                    )
                )

        if blockers:
            return QuickScoutLaunchRevalidationResponse(
                mission_id=mission_id,
                launchable=False,
                token=None,
                expires_at=None,
                max_slot_error_m=CONFIGURED_ORIGIN_REVALIDATION_MAX_DISTANCE_M,
                slot_errors_m=slot_errors_m,
                blockers=blockers,
                warnings=warnings,
                position_sources=position_sources,
                message="Live revalidation failed. Resolve blockers or recompute from live GPS before launch.",
            )

        token, expires_at = self._create_launch_revalidation_token(mission_id)
        return QuickScoutLaunchRevalidationResponse(
            mission_id=mission_id,
            launchable=True,
            token=token,
            expires_at=expires_at,
            max_slot_error_m=CONFIGURED_ORIGIN_REVALIDATION_MAX_DISTANCE_M,
            slot_errors_m=slot_errors_m,
            blockers=[],
            warnings=warnings,
            position_sources=position_sources,
            message="Live GPS positions match the configured-origin QuickScout plan. Launch token issued.",
        )

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

    async def launch_mission(
        self,
        deps: Any,
        mission_id: str,
        *,
        revalidation_token: Optional[str] = None,
    ) -> QuickScoutMissionLaunchResponse:
        operation = self.store.get_operation(mission_id)
        if operation is None:
            raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

        if operation.requires_revalidation and not self._consume_launch_revalidation_token(mission_id, revalidation_token):
            raise self._build_launch_revalidation_required_error(operation)

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

        try:
            resolved_return_behavior = ReturnBehavior(return_behavior)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=self._problem_detail(
                    "quickscout_invalid_return_behavior",
                    "Invalid QuickScout abort return behavior.",
                    details={"allowed": [behavior.value for behavior in ReturnBehavior]},
                ),
            ) from exc
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
