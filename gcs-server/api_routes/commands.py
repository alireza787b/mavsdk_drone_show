"""Command submission and tracking routes extracted from the GCS FastAPI monolith."""

import json
import time
import traceback
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Path as PathParam, Query, Request

from schemas import (
    CommandListResponse,
    CommandOutcome,
    CommandPhase,
    CommandStatisticsResponse,
    CommandStatus,
    CommandStatusResponse,
    ExecutionReportRequest,
    ExecutionReportResponse,
    ExecutionStartRequest,
    ExecutionStartResponse,
    SubmitCommandResponse,
)


def _get_telemetry_record_for_hw_id(
    telemetry_snapshot: Dict[Any, Dict[str, Any]],
    hw_id: Any,
) -> Dict[str, Any]:
    """Return telemetry for a drone regardless of whether storage keys are ints or strings."""
    if hw_id in telemetry_snapshot:
        return telemetry_snapshot.get(hw_id) or {}

    normalized_hw_id = str(hw_id)
    if normalized_hw_id in telemetry_snapshot:
        return telemetry_snapshot.get(normalized_hw_id) or {}

    try:
        numeric_hw_id = int(normalized_hw_id)
    except (TypeError, ValueError):
        numeric_hw_id = None

    if numeric_hw_id is not None and numeric_hw_id in telemetry_snapshot:
        return telemetry_snapshot.get(numeric_hw_id) or {}

    return {}


def _estimate_max_target_relative_altitude_m(
    deps: Any,
    drones: List[Dict[str, Any]],
    target_hw_ids: List[str],
) -> Optional[float]:
    """Best-effort relative altitude hint for LAND / RTL tracker timeout sizing."""
    if not target_hw_ids:
        return None

    import requests

    drone_by_hw_id: Dict[int, Dict[str, Any]] = {}
    for drone in drones:
        try:
            drone_by_hw_id[int(drone.get("hw_id"))] = drone
        except (TypeError, ValueError):
            continue

    with deps.telemetry_lock:
        telemetry_snapshot = {
            key: (dict(value) if isinstance(value, dict) else value)
            for key, value in deps.telemetry_data_all_drones.items()
        }

    request_timeout = max(
        0.2,
        min(
            float(getattr(deps.Params, "GCS_TELEMETRY_REQUEST_TIMEOUT_SEC", 2.0)),
            1.0,
        ),
    )
    max_relative_altitude_m: Optional[float] = None

    for target_hw_id in target_hw_ids:
        telemetry = _get_telemetry_record_for_hw_id(telemetry_snapshot, target_hw_id)
        try:
            current_altitude_m = float(telemetry.get("position_alt"))
        except (TypeError, ValueError):
            continue

        try:
            telemetry_relative_altitude_m = float(telemetry.get("relative_altitude_m"))
        except (TypeError, ValueError):
            telemetry_relative_altitude_m = None

        if telemetry_relative_altitude_m is not None:
            relative_altitude_m = max(0.0, telemetry_relative_altitude_m)
        else:
            drone = drone_by_hw_id.get(int(target_hw_id))
            if not drone:
                continue

            drone_ip = drone.get("ip")
            if not drone_ip:
                continue

            try:
                response = requests.get(
                    f"http://{drone_ip}:{deps.Params.drone_api_port}/get-home-pos",
                    timeout=request_timeout,
                )
                response.raise_for_status()
                payload = response.json()
                home_altitude_m = float(payload.get("alt"))
            except Exception:
                continue

            relative_altitude_m = max(0.0, current_altitude_m - home_altitude_m)

        if max_relative_altitude_m is None or relative_altitude_m > max_relative_altitude_m:
            max_relative_altitude_m = relative_altitude_m

    return max_relative_altitude_m


async def _parse_required_json_object(request: Request) -> dict[str, Any]:
    raw_body = await request.body()
    if not raw_body or not raw_body.strip():
        raise HTTPException(status_code=400, detail="No command data provided")

    try:
        payload = json.loads(raw_body)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Malformed JSON request body") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")

    if not payload:
        raise HTTPException(status_code=400, detail="No command data provided")

    return payload


def _normalize_target_drone_ids(raw_target_drones: Any) -> Optional[set[str]]:
    if raw_target_drones is None:
        return None

    if isinstance(raw_target_drones, (str, bytes)) or not isinstance(raw_target_drones, (list, tuple, set)):
        raise HTTPException(status_code=400, detail="target_drones must be an array of drone identifiers")

    if not raw_target_drones:
        return None

    normalized_target_ids = {
        str(target_id).strip()
        for target_id in raw_target_drones
        if target_id not in (None, "")
    }
    return normalized_target_ids or None


def _build_results_summary(results: dict[str, Any]) -> dict[str, int]:
    return {
        "accepted": results.get("success", 0),
        "offline": results.get("offline", 0),
        "rejected": results.get("rejected", 0),
        "errors": results.get("errors", 0),
    }


def _derive_submission_status(results: dict[str, Any]) -> str:
    has_success = results.get("success", 0) > 0
    rejected = results.get("rejected", 0)
    errors = results.get("errors", 0)
    offline = results.get("offline", 0)

    if has_success and rejected == 0 and errors == 0 and offline == 0:
        return "submitted"
    if has_success:
        return "partial"
    if offline > 0 and rejected == 0 and errors == 0:
        return "offline"
    return "failed"


async def _record_command_acknowledgements(tracker: Any, command_id: str, results: dict[str, Any]) -> None:
    for drone_id, result in results.get("results", {}).items():
        category = result.get("category", "error")
        if result.get("success"):
            await tracker.record_ack(
                command_id,
                drone_id,
                category="accepted",
                message="HTTP 200 received",
            )
        elif category == "offline":
            await tracker.record_ack(
                command_id,
                drone_id,
                category="offline",
                message=result.get("error", "Drone unreachable"),
                error_code="E304",
            )
        elif category == "rejected":
            await tracker.record_ack(
                command_id,
                drone_id,
                category="rejected",
                message=result.get("error", "Drone rejected command"),
                error_code="E303",
            )
        else:
            await tracker.record_ack(
                command_id,
                drone_id,
                category="error",
                message=result.get("error", "Unexpected error"),
                error_code="E500",
            )


def create_command_router(deps: Any) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/commands", response_model=SubmitCommandResponse, tags=["Commands"])
    @router.post("/submit_command", response_model=SubmitCommandResponse, tags=["Commands"])
    async def submit_command(request: Request):
        """
        Submit command to drones with tracking.

        Returns a command_id that can be used to track the command's progress via
        GET /command/{command_id} endpoint.
        """
        try:
            command_data = await _parse_required_json_object(request)

            if "missionType" not in command_data:
                raise HTTPException(status_code=400, detail="missionType is required")

            mission_type = command_data.get("missionType")
            trigger_time = command_data.get("triggerTime", "0")
            operator_label = command_data.get("operatorLabel")
            log_suffix = f", operatorLabel={operator_label}" if operator_label else ""
            deps.log_system_event(
                f"Command received: missionType={mission_type}, triggerTime={trigger_time}{log_suffix}",
                "INFO",
                "command",
            )

            target_drones = command_data.pop("target_drones", None)
            normalized_target_ids = _normalize_target_drone_ids(target_drones)

            if command_data.get("auto_global_origin", False):
                try:
                    origin = deps.load_origin()
                    if (
                        origin
                        and origin.get("lat") not in ("", None)
                        and origin.get("lon") not in ("", None)
                    ):
                        command_data["origin"] = {
                            "lat": float(origin["lat"]),
                            "lon": float(origin["lon"]),
                            "alt": float(origin.get("alt", 0)),
                            "timestamp": origin.get("timestamp", ""),
                            "source": origin.get("alt_source", "gcs"),
                        }
                except Exception as exc:
                    deps.log_system_error(f"Failed to load origin for command: {exc}", "command")

            drones = deps.load_config()
            if not drones:
                raise HTTPException(status_code=500, detail="No drones found in configuration")

            if normalized_target_ids:
                actual_targets = [
                    drone
                    for drone in drones
                    if str(drone.get("hw_id")) in normalized_target_ids
                    or str(drone.get("pos_id")) in normalized_target_ids
                ]
                if not actual_targets:
                    raise HTTPException(
                        status_code=400,
                        detail="No configured drones matched target_drones",
                    )
            else:
                actual_targets = drones

            target_hw_ids = [str(drone["hw_id"]) for drone in actual_targets]
            resolved_mission = deps.resolve_mission_type(mission_type)

            if resolved_mission == deps.Mission.SWARM_TRAJECTORY and normalized_target_ids:
                try:
                    status_payload = deps.swarm_trajectory_service.get_processing_status_payload()["status"]
                    structure = {
                        "swarm_config": {
                            int(drone_id): {"follow": follow_id}
                            for drone_id, follow_id in (status_payload.get("follow_map") or {}).items()
                        },
                    }
                    scope_issues = deps.swarm_trajectory_service.validate_target_scope_for_swarm_trajectory(
                        structure=structure,
                        processed_drones=status_payload.get("processed_drones") or [],
                        target_drone_ids=[int(drone_id) for drone_id in target_hw_ids],
                    )
                except Exception as exc:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Swarm Trajectory target scope could not be verified: {exc}",
                    ) from exc

                if scope_issues:
                    formatted_issues = []
                    for issue in scope_issues:
                        drone_id = issue.get("drone_id")
                        leader_id = issue.get("leader_id")
                        issue_code = issue.get("issue")
                        if issue_code == "missing_processed_trajectory":
                            formatted_issues.append(
                                f"Drone {drone_id} has no processed trajectory in the active package"
                            )
                        elif issue_code == "leader_not_in_active_mission_set":
                            formatted_issues.append(
                                f"Drone {drone_id} requires leader {leader_id} in the same target set"
                            )
                        elif issue_code == "missing_swarm_assignment":
                            formatted_issues.append(
                                f"Drone {drone_id} is not present in the current swarm configuration"
                            )
                        elif issue_code == "circular_leader_chain":
                            formatted_issues.append(
                                f"Drone {drone_id} has an invalid circular leader chain"
                            )

                    raise HTTPException(
                        status_code=400,
                        detail="Unsafe Swarm Trajectory target set. " + "; ".join(formatted_issues[:4]),
                    )

            if deps.mission_requires_launch_armability_probe(resolved_mission):
                launch_probe = deps.probe_live_armability_for_drones(
                    actual_targets,
                    require_global_position=True,
                )
                if not launch_probe["all_ready"]:
                    formatted = []
                    for drone_id in launch_probe["blocked_ids"][:4]:
                        summary = launch_probe["results"][drone_id]["summary"]
                        formatted.append(f"Drone {drone_id}: {summary}")
                    for drone_id in launch_probe["unavailable_ids"][:4]:
                        summary = launch_probe["results"][drone_id]["summary"]
                        formatted.append(f"Drone {drone_id}: {summary}")

                    raise HTTPException(
                        status_code=400,
                        detail="Live launch readiness probe failed. " + "; ".join(formatted),
                    )

            tracker = deps.get_command_tracker()
            mission_type_int = resolved_mission.value if resolved_mission else 0
            tracking_skybrush_dir = deps.skybrush_dir
            tracking_processed_dir = deps.processed_dir
            tracking_shapes_dir = deps.shapes_dir

            if resolved_mission == deps.Mission.SWARM_TRAJECTORY:
                trajectory_folders = deps.get_swarm_trajectory_folders()
                tracking_processed_dir = trajectory_folders.get("processed", deps.processed_dir)

            tracking_max_relative_altitude_m = None
            if resolved_mission in {deps.Mission.LAND, deps.Mission.RETURN_RTL}:
                tracking_max_relative_altitude_m = _estimate_max_target_relative_altitude_m(
                    deps,
                    drones,
                    target_hw_ids,
                )

            tracking_timeout_ms = deps.estimate_command_tracking_timeout_ms(
                resolved_mission,
                command_data=command_data,
                target_drone_ids=target_hw_ids,
                max_relative_altitude_m=tracking_max_relative_altitude_m,
                skybrush_dir=tracking_skybrush_dir,
                processed_dir=tracking_processed_dir,
                shapes_dir=tracking_shapes_dir,
            )

            command_id = await tracker.create_command(
                mission_type=mission_type_int,
                target_drones=target_hw_ids,
                params={
                    "triggerTime": trigger_time,
                    **{k: v for k, v in command_data.items() if k not in ["missionType", "triggerTime"]},
                },
                timeout_ms=tracking_timeout_ms,
            )

            command_data["command_id"] = command_id

            if normalized_target_ids:
                results = deps.send_commands_to_selected(drones, command_data, target_hw_ids)
            else:
                results = deps.send_commands_to_all(drones, command_data)

            await tracker.mark_submitted(command_id)
            await _record_command_acknowledgements(tracker, command_id, results)

            tracked_status = await tracker.get_status(command_id)
            results_summary = _build_results_summary(results)

            try:
                mission_name = deps.Mission(mission_type_int).name
            except ValueError:
                mission_name = f"MISSION_{mission_type}"

            return SubmitCommandResponse(
                success=results.get("success", 0) > 0,
                command_id=command_id,
                status=_derive_submission_status(results),
                mission_type=mission_type_int,
                mission_name=mission_name,
                target_drones=target_hw_ids,
                submitted_count=results.get("success", 0),
                message=results.get("result_summary", f"Command {mission_name} sent"),
                timestamp=int(time.time() * 1000),
                results_summary=results_summary,
                ack_summary=tracked_status.get("acks") if tracked_status else None,
                tracking_status=CommandStatus(tracked_status["status"]) if tracked_status else None,
                tracking_phase=CommandPhase(tracked_status["phase"]) if tracked_status else None,
                tracking_outcome=(
                    CommandOutcome(tracked_status["outcome"])
                    if tracked_status and tracked_status.get("outcome")
                    else None
                ),
                tracking_timeout_ms=tracking_timeout_ms,
            )
        except HTTPException:
            raise
        except Exception as exc:
            deps.log_system_error(f"submit_command failed: {exc}\n{traceback.format_exc()}", "command")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/api/v1/commands/recent", response_model=CommandListResponse, tags=["Commands"])
    @router.get("/commands/recent", response_model=CommandListResponse, tags=["Commands"])
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
    @router.get("/commands/active", response_model=CommandListResponse, tags=["Commands"])
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
    @router.get("/commands/statistics", response_model=CommandStatisticsResponse, tags=["Commands"])
    async def get_command_statistics():
        """Get command execution statistics."""
        tracker = deps.get_command_tracker()
        stats = await tracker.get_statistics()

        return CommandStatisticsResponse(
            **stats,
            timestamp=int(time.time() * 1000),
        )

    @router.get("/api/v1/commands/{command_id}", response_model=CommandStatusResponse, tags=["Commands"])
    @router.get("/command/{command_id}", response_model=CommandStatusResponse, tags=["Commands"])
    async def get_command_status(command_id: str = PathParam(..., description="Command UUID")):
        """Get detailed status of a specific command."""
        tracker = deps.get_command_tracker()
        status = await tracker.get_status(command_id)

        if not status:
            raise HTTPException(status_code=404, detail=f"Command {command_id} not found")

        return status

    @router.post("/api/v1/commands/{command_id}/cancel", tags=["Commands"])
    @router.post("/command/{command_id}/cancel", tags=["Commands"])
    async def cancel_command(
        command_id: str = PathParam(..., description="Command UUID"),
        reason: str = Query("User cancelled", description="Cancellation reason"),
    ):
        """
        Cancel endpoint is intentionally fail-closed until it is wired to drone dispatch.

        Live mission/action cancellation must go through `/submit_command` with
        `missionType=0` so the cancel command is actually delivered to the drones
        instead of only mutating tracker state in memory.
        """
        del reason
        raise HTTPException(
            status_code=409,
            detail=(
                f"Command cancel endpoint /api/v1/commands/{command_id}/cancel is disabled because it does not dispatch to drones. "
                "Use POST /api/v1/commands (legacy /submit_command) with missionType=0 to cancel live mission execution safely."
            ),
        )

    @router.post("/api/v1/command-reports/execution-result", response_model=ExecutionReportResponse, tags=["Commands"])
    @router.post("/command/execution-result", response_model=ExecutionReportResponse, tags=["Commands"])
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
    @router.post("/command/execution-start", response_model=ExecutionStartResponse, tags=["Commands"])
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
