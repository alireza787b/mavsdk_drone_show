"""Shared tracked command submission helpers for GCS routes and internal services."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List, Optional

import requests
from fastapi import HTTPException

from command_tracker import CommandIdempotencyConflictError
from schemas import (
    CommandOutcome,
    CommandPhase,
    CommandStatus,
    SubmitCommandRequest,
    SubmitCommandResponse,
)
from src.drone_api_routes import DRONE_NAVIGATION_HOME_ROUTE


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


def estimate_max_target_relative_altitude_m(
    deps: Any,
    drones: List[Dict[str, Any]],
    target_hw_ids: List[str],
) -> Optional[float]:
    """Best-effort relative altitude hint for LAND / RTL tracker timeout sizing."""
    if not target_hw_ids:
        return None

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
                    f"http://{drone_ip}:{deps.Params.drone_api_port}{DRONE_NAVIGATION_HOME_ROUTE}",
                    timeout=request_timeout,
                )
                response.raise_for_status()
                payload = response.json()
                home_altitude_m = float(payload.get("altitude", payload.get("alt")))
            except Exception:
                continue

            relative_altitude_m = max(0.0, current_altitude_m - home_altitude_m)

        if max_relative_altitude_m is None or relative_altitude_m > max_relative_altitude_m:
            max_relative_altitude_m = relative_altitude_m

    return max_relative_altitude_m


def build_results_summary(results: dict[str, Any]) -> dict[str, int]:
    return {
        "accepted": results.get("success", 0),
        "offline": results.get("offline", 0),
        "rejected": results.get("rejected", 0),
        "errors": results.get("errors", 0),
    }


def derive_submission_status(results: dict[str, Any]) -> str:
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


def _build_results_summary_from_status(command_status: Dict[str, Any]) -> dict[str, int]:
    ack_summary = command_status.get("acks") or {}
    return {
        "accepted": int(ack_summary.get("accepted", 0) or 0),
        "offline": int(ack_summary.get("offline", 0) or 0),
        "rejected": int(ack_summary.get("rejected", 0) or 0),
        "errors": int(ack_summary.get("errors", 0) or 0),
    }


def _derive_submission_status_from_status(command_status: Dict[str, Any]) -> str:
    results = _build_results_summary_from_status(command_status)
    if sum(results.values()) == 0 and command_status.get("phase") != "terminal":
        return "submitted"
    return derive_submission_status(results)


def build_submit_replay_response(command_status: Dict[str, Any]) -> SubmitCommandResponse:
    results_summary = _build_results_summary_from_status(command_status)
    phase = command_status.get("phase")
    target_drones = list(command_status.get("target_drones") or [])
    progress_message = (command_status.get("progress") or {}).get("message")
    accepted_count = results_summary["accepted"]
    in_flight = phase != "terminal"
    timeout_at = command_status.get("timeout_at")
    created_at = command_status.get("created_at")
    tracking_timeout_ms = None
    if isinstance(timeout_at, int) and isinstance(created_at, int) and timeout_at > created_at:
        tracking_timeout_ms = timeout_at - created_at

    return SubmitCommandResponse(
        success=accepted_count > 0 or in_flight,
        command_id=command_status["command_id"],
        idempotency_key=command_status.get("idempotency_key"),
        replayed=True,
        status=_derive_submission_status_from_status(command_status),
        mission_type=int(command_status["mission_type"]),
        mission_name=command_status["mission_name"],
        target_drones=target_drones,
        submitted_count=accepted_count if accepted_count > 0 or not in_flight else len(target_drones),
        message=(
            f"Replayed existing command submission. {progress_message}"
            if progress_message
            else "Replayed existing command submission."
        ),
        timestamp=int(time.time() * 1000),
        results_summary=results_summary,
        ack_summary=command_status.get("acks"),
        tracking_status=CommandStatus(command_status["status"]),
        tracking_phase=CommandPhase(command_status["phase"]),
        tracking_outcome=(
            CommandOutcome(command_status["outcome"])
            if command_status.get("outcome")
            else None
        ),
        tracking_timeout_ms=tracking_timeout_ms,
    )


def build_submit_request_fingerprint(command: SubmitCommandRequest) -> str:
    payload = command.model_dump(exclude_none=True)
    payload.pop("idempotency_key", None)
    if isinstance(payload.get("target_drone_ids"), list):
        payload["target_drone_ids"] = sorted(
            str(value).strip()
            for value in payload["target_drone_ids"]
            if value not in (None, "")
        )
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def record_command_acknowledgements(tracker: Any, command_id: str, results: dict[str, Any]) -> None:
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


async def submit_tracked_command(deps: Any, command: SubmitCommandRequest) -> SubmitCommandResponse:
    """Submit a tracked command using the canonical GCS lifecycle."""
    tracker = deps.get_command_tracker()
    command_data = command.model_dump(exclude_none=True)
    dispatch_payload = command.to_drone_payload()
    request_fingerprint = build_submit_request_fingerprint(command)
    idempotency_key = command.idempotency_key

    if idempotency_key:
        existing_command = await tracker.lookup_command_by_idempotency_key(
            idempotency_key,
            request_fingerprint=request_fingerprint,
        )
        if existing_command is not None:
            return build_submit_replay_response(existing_command)

    mission_type = command.mission_type
    trigger_time = command.trigger_time
    operator_label = command.operator_label
    log_suffix = f", operator_label={operator_label}" if operator_label else ""
    deps.log_system_event(
        f"Command received: mission_type={mission_type}, trigger_time={trigger_time}{log_suffix}",
        "INFO",
        "command",
    )

    normalized_target_ids = set(command.target_drone_ids or [])

    if command.auto_global_origin:
        try:
            origin = deps.load_origin()
            if (
                origin
                and origin.get("lat") not in ("", None)
                and origin.get("lon") not in ("", None)
            ):
                origin_payload = {
                    "lat": float(origin["lat"]),
                    "lon": float(origin["lon"]),
                    "alt": float(origin.get("alt", 0)),
                    "timestamp": origin.get("timestamp", ""),
                    "source": origin.get("alt_source", "gcs"),
                }
                command_data["origin"] = origin_payload
                dispatch_payload["origin"] = origin_payload
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
                detail="No configured drones matched target_drone_ids",
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

    mission_type_int = resolved_mission.value if resolved_mission else 0
    tracking_skybrush_dir = deps.skybrush_dir
    tracking_processed_dir = deps.processed_dir
    tracking_shapes_dir = deps.shapes_dir

    if resolved_mission == deps.Mission.SWARM_TRAJECTORY:
        trajectory_folders = deps.get_swarm_trajectory_folders()
        tracking_processed_dir = trajectory_folders.get("processed", deps.processed_dir)

    tracking_max_relative_altitude_m = None
    if resolved_mission in {deps.Mission.LAND, deps.Mission.RETURN_RTL}:
        tracking_max_relative_altitude_m = estimate_max_target_relative_altitude_m(
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

    creation_result = await tracker.create_or_replay_command(
        mission_type=mission_type_int,
        target_drones=target_hw_ids,
        params={
            "trigger_time": trigger_time,
            **{
                k: v
                for k, v in command_data.items()
                if k not in ["idempotency_key", "mission_type", "trigger_time", "target_drone_ids"]
            },
        },
        timeout_ms=tracking_timeout_ms,
        idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint,
    )
    command_id = creation_result.command_id

    if creation_result.replayed:
        tracked_status = await tracker.get_status(command_id)
        if tracked_status is None:
            raise HTTPException(status_code=500, detail="Replay-safe command lookup lost tracker state")
        return build_submit_replay_response(tracked_status)

    dispatch_payload["command_id"] = command_id

    if normalized_target_ids:
        results = deps.send_commands_to_selected(drones, dispatch_payload, target_hw_ids)
    else:
        results = deps.send_commands_to_all(drones, dispatch_payload)

    await tracker.mark_submitted(command_id)
    await record_command_acknowledgements(tracker, command_id, results)

    tracked_status = await tracker.get_status(command_id)
    results_summary = build_results_summary(results)

    try:
        mission_name = deps.Mission(mission_type_int).name
    except ValueError:
        mission_name = f"MISSION_{mission_type}"

    return SubmitCommandResponse(
        success=results.get("success", 0) > 0,
        command_id=command_id,
        idempotency_key=idempotency_key,
        replayed=False,
        status=derive_submission_status(results),
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


__all__ = [
    "CommandIdempotencyConflictError",
    "build_submit_request_fingerprint",
    "build_submit_replay_response",
    "build_results_summary",
    "derive_submission_status",
    "estimate_max_target_relative_altitude_m",
    "record_command_acknowledgements",
    "submit_tracked_command",
]
