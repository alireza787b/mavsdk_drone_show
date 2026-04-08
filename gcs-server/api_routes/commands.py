"""Command submission and tracking routes extracted from the GCS FastAPI monolith."""

import time
import traceback
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Path as PathParam, Query

from command_submission import (
    CommandIdempotencyConflictError,
    estimate_max_target_relative_altitude_m as _estimate_max_target_relative_altitude_m,
    submit_tracked_command,
)
from schemas import (
    CommandListResponse,
    CommandOutcome,
    CommandPhase,
    PrecisionMovePolicyResponse,
    CommandStatisticsResponse,
    CommandStatus,
    CommandStatusResponse,
    ExecutionReportRequest,
    ExecutionReportResponse,
    ExecutionStartRequest,
    ExecutionStartResponse,
    SubmitCommandRequest,
    SubmitCommandResponse,
)

def _build_precision_move_policy_payload(params: Any) -> dict[str, Any]:
    return {
        "action": "precision_move",
        "defaults": {
            "speed_m_s": float(getattr(params, "PRECISION_MOVE_DEFAULT_SPEED_MPS", 1.0)),
            "position_tolerance_m": float(
                getattr(params, "PRECISION_MOVE_DEFAULT_POSITION_TOLERANCE_M", 0.15)
            ),
            "yaw_tolerance_deg": float(
                getattr(params, "PRECISION_MOVE_DEFAULT_YAW_TOLERANCE_DEG", 5.0)
            ),
            "settle_time_sec": float(getattr(params, "PRECISION_MOVE_DEFAULT_SETTLE_TIME_SEC", 1.0)),
            "timeout_sec": float(getattr(params, "PRECISION_MOVE_DEFAULT_TIMEOUT_SEC", 30.0)),
        },
        "limits": {
            "max_translation_m": float(getattr(params, "PRECISION_MOVE_MAX_TRANSLATION_M", 100.0)),
            "max_speed_m_s": float(getattr(params, "PRECISION_MOVE_MAX_SPEED_MPS", 5.0)),
            "min_position_tolerance_m": float(
                getattr(params, "PRECISION_MOVE_MIN_POSITION_TOLERANCE_M", 0.05)
            ),
            "max_timeout_sec": float(getattr(params, "PRECISION_MOVE_MAX_TIMEOUT_SEC", 180.0)),
            "min_airborne_altitude_m": float(
                getattr(params, "PRECISION_MOVE_MIN_AIRBORNE_ALTITUDE_M", 0.3)
            ),
            "control_rate_hz": float(getattr(params, "PRECISION_MOVE_CONTROL_RATE_HZ", 10.0)),
        },
        "execution": {
            "supported_frames": ["body", "ned"],
            "supported_yaw_modes": ["hold_current", "relative_delta", "absolute_heading"],
            "hold_mode": "px4_hold",
            "immediate_only": True,
            "requires_airborne": True,
            "requires_local_position": True,
        },
    }

def create_command_router(deps: Any) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/api/v1/commands/policy/precision-move",
        response_model=PrecisionMovePolicyResponse,
        tags=["Commands"],
    )
    async def get_precision_move_policy():
        """Get the current runtime policy envelope for Precision Move."""
        return PrecisionMovePolicyResponse.model_validate(_build_precision_move_policy_payload(deps.Params))

    @router.post("/api/v1/commands", response_model=SubmitCommandResponse, tags=["Commands"])
    async def submit_command(command: SubmitCommandRequest):
        """
        Submit command to drones with tracking.

        Returns a command_id that can be used to track the command's progress via
        GET /api/v1/commands/{command_id} endpoint.
        """
        try:
            return await submit_tracked_command(deps, command)
        except CommandIdempotencyConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:
            deps.log_system_error(f"submit_command failed: {exc}\n{traceback.format_exc()}", "command")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/api/v1/commands/recent", response_model=CommandListResponse, tags=["Commands"])
    async def get_recent_commands(
        limit: int = Query(50, ge=1, le=200, description="Maximum commands to return"),
        status: Optional[str] = Query(None, description="Filter by status (e.g., 'completed', 'failed')"),
        mission_type: Optional[int] = Query(None, description="Filter by mission type"),
    ):
        """Get recent commands with optional filtering."""
        tracker = deps.get_command_tracker()

        status_filter = None
        if status:
            try:
                status_filter = [CommandStatus(status)]
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"Invalid status: {status}") from exc

        mission_filter = [mission_type] if mission_type is not None else None

        commands = await tracker.get_recent(
            limit=limit,
            status_filter=status_filter,
            mission_filter=mission_filter,
        )

        return CommandListResponse(
            commands=commands,
            total=len(commands),
            timestamp=int(time.time() * 1000),
        )

    @router.get("/api/v1/commands/active", response_model=CommandListResponse, tags=["Commands"])
    async def get_active_commands():
        """Get all currently active (non-terminal) commands."""
        tracker = deps.get_command_tracker()
        commands = await tracker.get_active_commands()

        return CommandListResponse(
            commands=commands,
            total=len(commands),
            timestamp=int(time.time() * 1000),
        )

    @router.get("/api/v1/commands/statistics", response_model=CommandStatisticsResponse, tags=["Commands"])
    async def get_command_statistics():
        """Get command execution statistics."""
        tracker = deps.get_command_tracker()
        stats = await tracker.get_statistics()

        return CommandStatisticsResponse(
            **stats,
            timestamp=int(time.time() * 1000),
        )

    @router.get("/api/v1/commands/{command_id}", response_model=CommandStatusResponse, tags=["Commands"])
    async def get_command_status(command_id: str = PathParam(..., description="Command UUID")):
        """Get detailed status of a specific command."""
        tracker = deps.get_command_tracker()
        status = await tracker.get_status(command_id)

        if not status:
            raise HTTPException(status_code=404, detail=f"Command {command_id} not found")

        return status

    @router.post("/api/v1/command-reports/execution-result", response_model=ExecutionReportResponse, tags=["Commands"])
    async def report_execution_result(report: ExecutionReportRequest):
        """Endpoint for drones to report command execution results."""
        tracker = deps.get_command_tracker()

        success = await tracker.record_execution(
            command_id=report.command_id,
            hw_id=report.hw_id,
            success=report.success,
            error_message=report.error_message,
            exit_code=report.exit_code,
            script_output=report.script_output,
            duration_ms=report.duration_ms,
        )

        if not success:
            deps.log_system_warning(
                f"Execution report for unknown command {report.command_id} from {report.hw_id}",
                "command",
            )

        status = await tracker.get_status(report.command_id)
        command_status = CommandStatus(status["status"]) if status else CommandStatus.FAILED

        return ExecutionReportResponse(
            received=success,
            command_id=report.command_id,
            command_status=command_status,
            message="Execution result recorded" if success else "Command not found in tracker",
            timestamp=int(time.time() * 1000),
        )

    @router.post("/api/v1/command-reports/execution-start", response_model=ExecutionStartResponse, tags=["Commands"])
    async def report_execution_start(report: ExecutionStartRequest):
        """Endpoint for drones to report that command execution has actually started."""
        tracker = deps.get_command_tracker()

        success = await tracker.record_execution_start(
            command_id=report.command_id,
            hw_id=report.hw_id,
        )

        if not success:
            deps.log_system_warning(
                f"Execution-start report for unknown command {report.command_id} from {report.hw_id}",
                "command",
            )

        status = await tracker.get_status(report.command_id)
        command_status = CommandStatus(status["status"]) if status else CommandStatus.FAILED
        command_phase = CommandPhase(status["phase"]) if status else CommandPhase.TERMINAL

        return ExecutionStartResponse(
            received=success,
            command_id=report.command_id,
            command_status=command_status,
            command_phase=command_phase,
            message="Execution start recorded" if success else "Command not found in tracker",
            timestamp=int(time.time() * 1000),
        )

    return router
