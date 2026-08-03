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
import threading
import weakref
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from command_submission import submit_tracked_command
from src.enums import Mission
from mds_logging import get_logger
from schemas import CommandSubmissionReceipt, SubmitCommandRequest
from sar.command_lifecycle import (
    QuickScoutCommandProjection,
    build_queued_command_batch,
    command_batch_has_unresolved_targets,
    project_tracker_status,
    project_tracking_unavailable,
)
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
    QuickScoutCommandAction,
    QuickScoutCommandBatch,
    QuickScoutCommandLifecycleState,
    QuickScoutCommandQueuedResponse,
    QuickScoutLaunchRevalidationResponse,
    QuickScoutMissionHandoff,
    QuickScoutMissionHandoffFinding,
    QuickScoutMissionCatalogResponse,
    QuickScoutMissionPhase,
    QuickScoutPlanningJobResponse,
    QuickScoutPlanningJobState,
    QuickScoutProgressReceipt,
    QuickScoutPlanningOrigin,
    QuickScoutPlanningPositionMode,
    QuickScoutPlanningPositionSource,
    QuickScoutPlanningWarning,
    QuickScoutTerrainSummary,
    QuickScoutMissionRequest,
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
        self._mission_command_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )
        self._mission_command_locks_guard = threading.Lock()

    def _mission_command_lock(self, mission_id: str) -> asyncio.Lock:
        """Return the process-local serializer for one mission's command flow.

        MDS has one command-owning GCS service process.  The lock prevents two
        pause/abort/launch submissions for the same mission from crossing an
        ``await`` boundary, while the SQLite mutation API protects every durable
        merge from stale whole-record replacement.
        """

        with self._mission_command_locks_guard:
            lock = self._mission_command_locks.get(mission_id)
            if lock is None:
                lock = asyncio.Lock()
                self._mission_command_locks[mission_id] = lock
            return lock

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
    def _build_operator_label(action: str, mission_id: str) -> str:
        return f"QuickScout {action} {mission_id[:8]}"

    @staticmethod
    def _command_idempotency_key(
        mission_id: str,
        action: QuickScoutCommandAction,
        attempt: int,
    ) -> str:
        return f"quickscout:{mission_id}:{action.value}:{attempt}"

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
        action: QuickScoutCommandAction,
        attempt: int,
    ) -> CommandSubmissionReceipt:
        request = SubmitCommandRequest(
            mission_type=mission_type.value,
            trigger_time=0,
            mission_id=mission_id,
            target_drone_ids=hw_ids,
            operator_label=self._build_operator_label(action.value, mission_id),
            idempotency_key=self._command_idempotency_key(mission_id, action, attempt),
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
            batch = operation.latest_command_batch
            if (
                batch is not None
                and batch.action == QuickScoutCommandAction.LAUNCH
                and self._command_is_pending(batch)
            ):
                return QuickScoutMissionPhase.LAUNCH_QUEUED
            return QuickScoutMissionPhase.READY_TO_LAUNCH
        if operation.state == SurveyState.PAUSED:
            return QuickScoutMissionPhase.HOLDING
        if operation.state == SurveyState.COMPLETED:
            return QuickScoutMissionPhase.COMPLETED
        if operation.state == SurveyState.ABORTED:
            batch = operation.latest_command_batch
            if (
                batch is not None
                and batch.action == QuickScoutCommandAction.ABORT
                and batch.state == QuickScoutCommandLifecycleState.COMPLETED
            ):
                return QuickScoutMissionPhase.RETURN_COMMANDED
            return QuickScoutMissionPhase.ABORTED
        if operation.state == SurveyState.EXECUTING:
            active = sum(
                state.state in {SurveyState.EXECUTING, SurveyState.COMPLETED}
                for state in operation.drone_states.values()
            )
            batch = operation.latest_command_batch
            if (
                batch is not None
                and batch.action == QuickScoutCommandAction.LAUNCH
                and 0 < active < len(operation.drone_states)
            ):
                return QuickScoutMissionPhase.LAUNCH_PARTIAL
            if any(
                state.state in {SurveyState.PAUSED, SurveyState.ABORTED}
                for state in operation.drone_states.values()
            ):
                return QuickScoutMissionPhase.MIXED_CONTROL
            return QuickScoutMissionPhase.SEARCHING
        return QuickScoutMissionPhase.PLANNING

    def _build_control_availability(
        self,
        operation: QuickScoutOperationRecord,
        phase: QuickScoutMissionPhase,
    ) -> QuickScoutControlAvailability:
        batch = operation.latest_command_batch
        command_pending = (
            batch is not None
            and batch.action in {QuickScoutCommandAction.PAUSE, QuickScoutCommandAction.ABORT}
            and self._command_is_pending(batch)
        )
        if command_pending:
            action = batch.action.value.replace("_", " ")
            reason = f"The {action} command is still being tracked."
            return QuickScoutControlAvailability(
                pause_enabled=False,
                pause_reason=reason,
                replan_enabled=False,
                replan_reason="Wait for execution evidence before changing the mission package.",
                abort_enabled=False,
                abort_reason=reason,
            )

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

        if phase == QuickScoutMissionPhase.MIXED_CONTROL:
            active_count = sum(
                state.state == SurveyState.EXECUTING
                for state in operation.drone_states.values()
            )
            return QuickScoutControlAvailability(
                pause_enabled=active_count > 0,
                pause_reason=(
                    None
                    if active_count > 0
                    else "No assigned aircraft is currently searching."
                ),
                replan_enabled=True,
                replan_reason="Build a follow-up package for the mixed active/holding mission state.",
                abort_enabled=any(
                    state.state in {SurveyState.EXECUTING, SurveyState.PAUSED}
                    for state in operation.drone_states.values()
                ),
                abort_reason="Mission end is unavailable when every assignment is already terminal.",
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

        if phase == QuickScoutMissionPhase.LAUNCH_QUEUED:
            batch = operation.latest_command_batch
            target_counts: Dict[str, int] = {}
            if batch is not None:
                for target in batch.targets.values():
                    label = target.state.value.replace("_", " ")
                    target_counts[label] = target_counts.get(label, 0) + 1
            target_summary = ", ".join(
                f"{count} {label}"
                for label, count in sorted(target_counts.items())
            ) or "queued"
            return (
                f"Launch target state: {target_summary}; unresolved targets retain the command slot until terminal evidence arrives.",
                "Monitor the tracked command and do not infer launch from delivery or ACK state.",
            )

        if phase == QuickScoutMissionPhase.LAUNCH_PARTIAL:
            launched = sum(
                state.state in {SurveyState.EXECUTING, SurveyState.COMPLETED}
                for state in operation.drone_states.values()
            )
            failed = max(0, drone_count - launched)
            return (
                f"Search package has execution evidence on {launched}/{drone_count} assigned drone(s); {failed} assignment(s) are not executing.",
                "Review failed assets or generate a reduced follow-up package before expanding the search.",
            )

        if phase == QuickScoutMissionPhase.SEARCHING:
            return (
                f"Search package is executing on {executing_count or drone_count}/{drone_count} assigned drone(s).",
                None,
            )

        if phase == QuickScoutMissionPhase.MIXED_CONTROL:
            aborted_count = sum(
                state.state == SurveyState.ABORTED
                for state in operation.drone_states.values()
            )
            return (
                f"Mixed assignment state: {executing_count} searching, {paused_count} holding, "
                f"{aborted_count} ended, {completed_count} completed.",
                "Review target states before issuing another subset control or build a follow-up package.",
            )

        if phase == QuickScoutMissionPhase.HOLDING:
            return (
                f"{paused_count or drone_count} assigned drone(s) are holding on operator command.",
                "Generate a follow-up package from current aircraft state when the search should continue.",
            )

        if phase == QuickScoutMissionPhase.RETURN_COMMANDED:
            return (
                f"Mission end command executed successfully; affected drones will {self._return_behavior_label(operation.return_behavior)}.",
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

    @staticmethod
    def _recompute_operation_state(
        operation: QuickScoutOperationRecord,
        batch: Optional[QuickScoutCommandBatch] = None,
    ) -> None:
        states = [drone.state for drone in operation.drone_states.values()]
        if not states:
            return
        if all(state == SurveyState.COMPLETED for state in states):
            operation.state = SurveyState.COMPLETED
        elif all(state in {SurveyState.COMPLETED, SurveyState.ABORTED} for state in states):
            operation.state = SurveyState.ABORTED
        elif any(state == SurveyState.EXECUTING for state in states):
            operation.state = SurveyState.EXECUTING
        elif any(state == SurveyState.PAUSED for state in states):
            operation.state = SurveyState.PAUSED
        elif (
            batch is not None
            and batch.action == QuickScoutCommandAction.LAUNCH
            and batch.state
            in {
                QuickScoutCommandLifecycleState.FAILED,
                QuickScoutCommandLifecycleState.REJECTED,
            }
            and any(state in {SurveyState.COMPLETED, SurveyState.ABORTED} for state in states)
        ):
            operation.state = SurveyState.ABORTED

    def _apply_execution_evidence(
        self,
        operation: QuickScoutOperationRecord,
        projection: QuickScoutCommandProjection,
    ) -> bool:
        """Mutate survey state only from authenticated execution evidence."""

        batch = projection.batch
        evidence = projection.execution
        changed = False
        now = time.time()
        original_state = operation.state
        original_started_at = operation.started_at
        if batch.action == QuickScoutCommandAction.LAUNCH and evidence.started_hw_ids:
            operation.started_at = operation.started_at or now
            operation.state = SurveyState.EXECUTING

        for hw_id in batch.targets:
            drone = operation.drone_states.get(hw_id)
            if drone is None:
                continue

            previous = drone.model_dump()
            target = batch.targets[hw_id]
            if batch.action == QuickScoutCommandAction.LAUNCH:
                if hw_id in evidence.succeeded_hw_ids:
                    drone.state = SurveyState.COMPLETED
                    drone.current_waypoint_index = drone.total_waypoints
                    drone.coverage_percent = 100.0
                    drone.estimated_remaining_s = 0.0
                    drone.status_note = "Search package execution completed"
                elif hw_id in evidence.failed_hw_ids:
                    drone.state = SurveyState.ABORTED
                    drone.status_note = target.message or "Search package execution failed"
                elif hw_id in evidence.started_hw_ids:
                    drone.state = SurveyState.EXECUTING
                    drone.status_note = "Executing assigned search track"
            elif batch.action == QuickScoutCommandAction.PAUSE:
                if hw_id in evidence.succeeded_hw_ids:
                    drone.state = SurveyState.PAUSED
                    drone.status_note = "Holding on operator command"
            elif batch.action == QuickScoutCommandAction.ABORT:
                if hw_id in evidence.succeeded_hw_ids:
                    drone.state = SurveyState.ABORTED
                    resolved_behavior = batch.return_behavior or operation.return_behavior
                    drone.status_note = f"Mission ended: {self._return_behavior_label(resolved_behavior)}"

            if drone.model_dump() != previous:
                drone.last_update_at = now
                changed = True

        self._recompute_operation_state(operation, batch)
        if operation.state != original_state or operation.started_at != original_started_at:
            changed = True
        if (
            batch.action == QuickScoutCommandAction.ABORT
            and evidence.succeeded_hw_ids
            and batch.return_behavior is not None
            and operation.return_behavior != batch.return_behavior
        ):
            operation.return_behavior = batch.return_behavior
            changed = True
        return changed

    async def reconcile_latest_command(self, deps: Any, mission_id: str) -> Optional[MissionStatus]:
        """Refresh QuickScout's durable projection from the authoritative command tracker."""

        operation = self.store.get_operation(mission_id)
        if operation is None:
            return None
        batch = operation.latest_command_batch
        if batch is None:
            return self.get_status(mission_id)

        tracker_status_payload: Optional[Any] = None
        unavailable_message = "The tracked command is not available in this GCS process."
        try:
            tracker_getter = getattr(deps, "get_command_tracker", None)
            if not callable(tracker_getter):
                raise RuntimeError("command tracker dependency is unavailable")
            tracker = tracker_getter()
            tracker_status_payload = await tracker.get_status(batch.receipt.command_id)
            if hasattr(tracker_status_payload, "model_dump"):
                tracker_status_payload = tracker_status_payload.model_dump(mode="json")
        except Exception as exc:
            logger.debug(
                "QuickScout command reconciliation unavailable for mission_id=%s command_id=%s: %s",
                mission_id,
                batch.receipt.command_id,
                exc,
            )
            unavailable_message = "The command tracker is currently unavailable."

        expected_command_id = batch.receipt.command_id

        def apply_projection(current: QuickScoutOperationRecord) -> QuickScoutOperationRecord:
            current_batch = current.latest_command_batch
            if (
                current_batch is None
                or current_batch.receipt.command_id != expected_command_id
            ):
                # A newer launch/control command won the mission slot while the
                # tracker read was in flight.  Never project the stale snapshot
                # onto that newer durable command.
                return current

            projection = (
                project_tracker_status(current_batch, tracker_status_payload)
                if tracker_status_payload is not None
                else project_tracking_unavailable(
                    current_batch,
                    message=unavailable_message,
                )
            )
            batch_changed = projection.batch != current_batch
            state_changed = self._apply_execution_evidence(current, projection)
            if batch_changed or state_changed:
                current.latest_command_batch = projection.batch
                current.updated_at = time.time()
            return current

        self.store.mutate_operation(mission_id, apply_projection)
        return self.get_status(mission_id)

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
            latest_command_batch=operation.latest_command_batch,
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
                    latest_command_batch=operation.latest_command_batch,
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
            latest_command_batch=status.latest_command_batch,
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

    def update_drone_progress(
        self,
        mission_id: str,
        hw_id: str,
        current_waypoint_index: int,
        total_waypoints: int,
        distance_covered_m: float = 0.0,
    ) -> bool:
        result = {"applied": False, "target_exists": False}

        def apply_progress(operation: QuickScoutOperationRecord) -> QuickScoutOperationRecord:
            if hw_id not in operation.drone_states:
                return operation
            result["target_exists"] = True

            drone_state = operation.drone_states[hw_id]
            if drone_state.state not in {SurveyState.EXECUTING, SurveyState.COMPLETED}:
                raise HTTPException(
                    status_code=409,
                    detail=self._problem_detail(
                        "quickscout_progress_before_execution",
                        "Progress metrics are accepted only after tracker-backed execution evidence.",
                        details={"hw_id": hw_id, "state": drone_state.state.value},
                    ),
                )

            expected_total = int(drone_state.total_waypoints)
            if total_waypoints != expected_total:
                raise HTTPException(
                    status_code=409,
                    detail=self._problem_detail(
                        "quickscout_progress_plan_mismatch",
                        "Progress total does not match the persisted QuickScout assignment.",
                        details={
                            "hw_id": hw_id,
                            "expected_total_waypoints": expected_total,
                            "reported_total_waypoints": total_waypoints,
                        },
                    ),
                )

            if (
                current_waypoint_index < drone_state.current_waypoint_index
                or distance_covered_m < drone_state.distance_covered_m
            ):
                return operation

            drone_state.current_waypoint_index = current_waypoint_index
            drone_state.distance_covered_m = distance_covered_m
            drone_state.last_update_at = time.time()
            if total_waypoints > 0:
                drone_state.coverage_percent = min(
                    100.0,
                    (current_waypoint_index / total_waypoints) * 100.0,
                )
            plan = next(
                (candidate for candidate in operation.plans if candidate.hw_id == hw_id),
                None,
            )
            if plan is not None and total_waypoints > 0:
                remaining_ratio = max(
                    0.0,
                    1.0 - min(current_waypoint_index, total_waypoints) / total_waypoints,
                )
                drone_state.estimated_remaining_s = round(
                    plan.estimated_duration_s * remaining_ratio,
                    1,
                )
            operation.updated_at = time.time()
            result["applied"] = True
            return operation

        operation = self.store.mutate_operation(mission_id, apply_progress)
        if operation is None or not result["target_exists"]:
            return False
        return result["applied"]

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

    @staticmethod
    def _command_is_pending(batch: Optional[QuickScoutCommandBatch]) -> bool:
        return bool(batch is not None and command_batch_has_unresolved_targets(batch))

    @staticmethod
    def _next_command_attempt(
        operation: QuickScoutOperationRecord,
        action: QuickScoutCommandAction,
    ) -> int:
        batch = operation.latest_command_batch
        if batch is not None and batch.action == action:
            return batch.attempt + 1
        return 1

    def _recover_pending_command(
        self,
        operation: QuickScoutOperationRecord,
        action: QuickScoutCommandAction,
    ) -> Optional[QuickScoutCommandQueuedResponse]:
        batch = operation.latest_command_batch
        if not self._command_is_pending(batch) or batch.action != action:
            return None
        return QuickScoutCommandQueuedResponse(
            mission_id=operation.mission_id,
            latest_command_batch=batch,
            message=(
                f"QuickScout {action.value} is already queued as command "
                f"{batch.receipt.command_id}; monitor its tracking URL."
            ),
        )

    def _ensure_command_slot_available(
        self,
        operation: QuickScoutOperationRecord,
        action: QuickScoutCommandAction,
    ) -> None:
        batch = operation.latest_command_batch
        # A QuickScout launch executor owns the aircraft for the duration of
        # the survey, so its tracked command legitimately remains EXECUTING
        # while pause/end controls are needed.  Once tracker evidence has
        # moved the launch into EXECUTING, a control command may replace the
        # latest projection.  Pre-execution launch states remain protected so
        # HOLD/RTL/LAND cannot race aircraft whose launch outcome is unknown.
        launch_is_controllable = bool(
            batch is not None
            and batch.action == QuickScoutCommandAction.LAUNCH
            and batch.state == QuickScoutCommandLifecycleState.EXECUTING
            and action in {
                QuickScoutCommandAction.PAUSE,
                QuickScoutCommandAction.ABORT,
            }
        )
        if launch_is_controllable:
            return
        if self._command_is_pending(batch) and batch.action != action:
            raise HTTPException(
                status_code=409,
                detail=self._problem_detail(
                    "quickscout_command_in_progress",
                    f"A QuickScout {batch.action.value} command is still being tracked.",
                    details={
                        "command_id": batch.receipt.command_id,
                        "state": batch.state.value,
                        "tracking_url": batch.receipt.tracking_url,
                    },
                ),
            )

    @staticmethod
    def _validate_plan_target_ids(operation: QuickScoutOperationRecord) -> List[str]:
        hw_ids = [plan.hw_id for plan in operation.plans]
        if not hw_ids:
            raise HTTPException(status_code=409, detail="QuickScout mission has no launch plans")
        if any(not hw_id or hw_id != hw_id.strip() for hw_id in hw_ids):
            raise HTTPException(status_code=409, detail="QuickScout plan contains a non-canonical hardware ID")
        if len(set(hw_ids)) != len(hw_ids):
            raise HTTPException(status_code=409, detail="QuickScout plan contains duplicate hardware IDs")
        return hw_ids

    def _resolve_control_targets(
        self,
        deps: Any,
        operation: QuickScoutOperationRecord,
        pos_ids: Optional[List[int]],
        action: QuickScoutCommandAction,
    ) -> List[str]:
        eligible_states = (
            {SurveyState.EXECUTING}
            if action == QuickScoutCommandAction.PAUSE
            else {SurveyState.EXECUTING, SurveyState.PAUSED}
        )
        assigned_hw_ids = list(operation.drone_states)
        default_hw_ids = [
            hw_id
            for hw_id, state in operation.drone_states.items()
            if state.state in eligible_states
        ]
        hw_ids = self._resolve_pos_ids_to_hw_ids(
            deps,
            pos_ids,
            default_hw_ids=default_hw_ids,
        )
        if not hw_ids:
            raise HTTPException(
                status_code=409,
                detail=self._problem_detail(
                    "quickscout_no_actionable_targets",
                    f"No assigned aircraft is currently eligible for QuickScout {action.value}.",
                ),
            )
        unassigned = sorted(set(hw_ids) - set(assigned_hw_ids))
        if unassigned:
            raise HTTPException(
                status_code=400,
                detail=self._problem_detail(
                    "quickscout_unassigned_targets",
                    "QuickScout controls may target only drones assigned to this mission.",
                    details={"unassigned_hw_ids": unassigned},
                ),
            )
        ineligible = sorted(
            hw_id
            for hw_id in hw_ids
            if operation.drone_states[hw_id].state not in eligible_states
        )
        if ineligible:
            raise HTTPException(
                status_code=409,
                detail=self._problem_detail(
                    "quickscout_control_targets_not_actionable",
                    f"QuickScout {action.value} may target only aircraft in an actionable mission state.",
                    details={
                        "ineligible_hw_ids": ineligible,
                        "states": {
                            hw_id: operation.drone_states[hw_id].state.value
                            for hw_id in ineligible
                        },
                    },
                ),
            )
        return hw_ids

    def _persist_queued_batch(
        self,
        operation: QuickScoutOperationRecord,
        *,
        action: QuickScoutCommandAction,
        attempt: int,
        receipt: CommandSubmissionReceipt,
        message: str,
        return_behavior: Optional[ReturnBehavior] = None,
    ) -> QuickScoutCommandQueuedResponse:
        persisted_batch: list[QuickScoutCommandBatch] = []

        def persist(current: QuickScoutOperationRecord) -> QuickScoutOperationRecord:
            existing = current.latest_command_batch
            if existing is not None and existing.receipt.command_id == receipt.command_id:
                batch = existing.model_copy(update={"receipt": receipt})
            else:
                batch = build_queued_command_batch(
                    action=action,
                    attempt=attempt,
                    receipt=receipt,
                    return_behavior=return_behavior,
                )
            current.latest_command_batch = batch
            current.updated_at = time.time()
            persisted_batch.append(batch)
            return current

        persisted = self.store.mutate_operation(operation.mission_id, persist)
        if persisted is None or not persisted_batch:
            raise HTTPException(
                status_code=409,
                detail=self._problem_detail(
                    "quickscout_operation_removed_during_submission",
                    "The QuickScout mission was removed while its command was being queued.",
                    details={
                        "command_id": receipt.command_id,
                        "tracking_url": receipt.tracking_url,
                    },
                ),
            )
        batch = persisted_batch[0]
        return QuickScoutCommandQueuedResponse(
            mission_id=operation.mission_id,
            latest_command_batch=batch,
            message=message,
        )

    async def launch_mission(
        self,
        deps: Any,
        mission_id: str,
        *,
        revalidation_token: Optional[str] = None,
    ) -> QuickScoutCommandQueuedResponse:
        async with self._mission_command_lock(mission_id):
            return await self._launch_mission_serialized(
                deps,
                mission_id,
                revalidation_token=revalidation_token,
            )

    async def _launch_mission_serialized(
        self,
        deps: Any,
        mission_id: str,
        *,
        revalidation_token: Optional[str] = None,
    ) -> QuickScoutCommandQueuedResponse:
        operation = self.store.get_operation(mission_id)
        if operation is None:
            raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

        if operation.state != SurveyState.READY:
            raise HTTPException(
                status_code=409,
                detail=self._problem_detail(
                    "quickscout_launch_state_invalid",
                    "Only a ready QuickScout mission package can be launched.",
                    details={"state": operation.state.value},
                ),
            )
        recovered = self._recover_pending_command(operation, QuickScoutCommandAction.LAUNCH)
        if recovered is not None:
            return recovered
        self._ensure_command_slot_available(operation, QuickScoutCommandAction.LAUNCH)
        attempt = self._next_command_attempt(operation, QuickScoutCommandAction.LAUNCH)

        if operation.requires_revalidation and not self._consume_launch_revalidation_token(mission_id, revalidation_token):
            raise self._build_launch_revalidation_required_error(operation)

        hw_ids = self._validate_plan_target_ids(operation)
        per_target_payloads = {
            plan.hw_id: {
                "waypoints": [waypoint.model_dump(mode="json") for waypoint in plan.waypoints],
            }
            for plan in operation.plans
        }
        receipt = await submit_tracked_command(
            deps,
            SubmitCommandRequest(
                mission_type=Mission.QUICKSCOUT.value,
                trigger_time=0,
                mission_id=mission_id,
                return_behavior=operation.return_behavior.value,
                target_drone_ids=hw_ids,
                operator_label=self._build_operator_label("launch", mission_id),
                idempotency_key=self._command_idempotency_key(
                    mission_id,
                    QuickScoutCommandAction.LAUNCH,
                    attempt,
                ),
            ),
            per_target_payloads=per_target_payloads,
        )
        return self._persist_queued_batch(
            operation,
            action=QuickScoutCommandAction.LAUNCH,
            attempt=attempt,
            receipt=receipt,
            message=(
                f"QuickScout launch queued for {len(hw_ids)} assigned drone(s). "
                "Mission state will change only after execution evidence arrives."
            ),
        )

    async def pause_and_command(
        self,
        deps: Any,
        mission_id: str,
        pos_ids: Optional[List[int]] = None,
    ) -> QuickScoutCommandQueuedResponse:
        async with self._mission_command_lock(mission_id):
            return await self._pause_and_command_serialized(deps, mission_id, pos_ids)

    async def _pause_and_command_serialized(
        self,
        deps: Any,
        mission_id: str,
        pos_ids: Optional[List[int]] = None,
    ) -> QuickScoutCommandQueuedResponse:
        operation = self.store.get_operation(mission_id)
        if operation is None:
            raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")
        if operation.state != SurveyState.EXECUTING:
            raise HTTPException(
                status_code=409,
                detail=self._problem_detail(
                    "quickscout_pause_state_invalid",
                    "Pause is available only while a QuickScout mission is executing.",
                    details={"state": operation.state.value},
                ),
            )
        recovered = self._recover_pending_command(operation, QuickScoutCommandAction.PAUSE)
        if recovered is not None:
            return recovered
        self._ensure_command_slot_available(operation, QuickScoutCommandAction.PAUSE)
        attempt = self._next_command_attempt(operation, QuickScoutCommandAction.PAUSE)
        hw_ids = self._resolve_control_targets(
            deps,
            operation,
            pos_ids,
            QuickScoutCommandAction.PAUSE,
        )
        receipt = await self._submit_control_command(
            deps,
            mission_type=Mission.HOLD,
            mission_id=mission_id,
            hw_ids=hw_ids,
            action=QuickScoutCommandAction.PAUSE,
            attempt=attempt,
        )
        return self._persist_queued_batch(
            operation,
            action=QuickScoutCommandAction.PAUSE,
            attempt=attempt,
            receipt=receipt,
            message=f"Pause queued for {len(hw_ids)} assigned drone(s); awaiting execution evidence.",
        )

    async def abort_and_command(
        self,
        deps: Any,
        mission_id: str,
        pos_ids: Optional[List[int]] = None,
        return_behavior: str = "return_home",
    ) -> QuickScoutCommandQueuedResponse:
        async with self._mission_command_lock(mission_id):
            return await self._abort_and_command_serialized(
                deps,
                mission_id,
                pos_ids,
                return_behavior,
            )

    async def _abort_and_command_serialized(
        self,
        deps: Any,
        mission_id: str,
        pos_ids: Optional[List[int]] = None,
        return_behavior: str = "return_home",
    ) -> QuickScoutCommandQueuedResponse:
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
        if operation.state not in {SurveyState.EXECUTING, SurveyState.PAUSED}:
            raise HTTPException(
                status_code=409,
                detail=self._problem_detail(
                    "quickscout_abort_state_invalid",
                    "Mission end control is available only while QuickScout is executing or holding.",
                    details={"state": operation.state.value},
                ),
            )
        recovered = self._recover_pending_command(operation, QuickScoutCommandAction.ABORT)
        if recovered is not None:
            if recovered.latest_command_batch.return_behavior != resolved_return_behavior:
                raise HTTPException(
                    status_code=409,
                    detail=self._problem_detail(
                        "quickscout_abort_behavior_conflict",
                        "The queued mission-end command uses a different return behavior.",
                        details={
                            "queued_return_behavior": recovered.latest_command_batch.return_behavior.value,
                            "requested_return_behavior": resolved_return_behavior.value,
                        },
                    ),
                )
            return recovered
        self._ensure_command_slot_available(operation, QuickScoutCommandAction.ABORT)
        attempt = self._next_command_attempt(operation, QuickScoutCommandAction.ABORT)
        hw_ids = self._resolve_control_targets(
            deps,
            operation,
            pos_ids,
            QuickScoutCommandAction.ABORT,
        )
        receipt = await self._submit_control_command(
            deps,
            mission_type=self._resolve_abort_mission_type(resolved_return_behavior),
            mission_id=mission_id,
            hw_ids=hw_ids,
            action=QuickScoutCommandAction.ABORT,
            attempt=attempt,
        )
        return self._persist_queued_batch(
            operation,
            action=QuickScoutCommandAction.ABORT,
            attempt=attempt,
            receipt=receipt,
            return_behavior=resolved_return_behavior,
            message=(
                f"Mission end queued for {len(hw_ids)} assigned drone(s); "
                "return behavior will apply only after successful execution evidence."
            ),
        )

    def report_progress(self, mission_id: str, report: DroneProgressReport) -> QuickScoutProgressReceipt:
        operation = self.store.get_operation(mission_id)
        if operation is None or report.hw_id not in operation.drone_states:
            raise HTTPException(status_code=404, detail="Mission or drone not found")

        applied = self.update_drone_progress(
            mission_id=mission_id,
            hw_id=report.hw_id,
            current_waypoint_index=report.current_waypoint_index,
            total_waypoints=report.total_waypoints,
            distance_covered_m=report.distance_covered_m,
        )
        return QuickScoutProgressReceipt(
            mission_id=mission_id,
            hw_id=report.hw_id,
            applied=applied,
            message=(
                "Progress metrics updated."
                if applied
                else "Stale progress metrics ignored; persisted progress is newer."
            ),
        )

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
