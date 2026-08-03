"""Shared tracked command submission helpers for GCS routes and internal services."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from command_tracker import CommandIdempotencyConflictError
from command_execution_policy import (
    CommandSubmissionAuthority,
    CommandSubmissionPolicyError,
    enforce_command_submission_policy,
    mission_is_recovery,
)
from command_submission_coordinator import (
    CommandSubmissionCapacityError,
    CommandSubmissionUnavailableError,
    SubmissionReservation,
)
from command_submission_pipeline import (
    TrackedSubmissionWork,
    build_submission_receipt,
    ensure_sitl_callback_endpoint_matches,
    record_command_acknowledgements,
    run_tracked_submission,
    terminalize_submission_failure,
)
from schemas import (
    CommandSubmissionReceipt,
    SubmitCommandRequest,
)
from target_command_payloads import per_target_payload_digests, validate_per_target_payloads
_ensure_sitl_callback_endpoint_matches = ensure_sitl_callback_endpoint_matches


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

    with deps.telemetry_lock:
        telemetry_snapshot = {
            key: (dict(value) if isinstance(value, dict) else value)
            for key, value in deps.telemetry_data_all_drones.items()
        }

    max_relative_altitude_m: Optional[float] = None

    for target_hw_id in target_hw_ids:
        telemetry = _get_telemetry_record_for_hw_id(telemetry_snapshot, target_hw_id)
        try:
            telemetry_relative_altitude_m = float(telemetry.get("relative_altitude_m"))
        except (TypeError, ValueError):
            telemetry_relative_altitude_m = None

        # Timeout sizing is advisory and must never block or delay a LAND/RTL
        # request with per-node network calls. If relative altitude is absent,
        # the tracker policy uses its conservative fallback budget.
        if telemetry_relative_altitude_m is None:
            continue
        relative_altitude_m = max(0.0, telemetry_relative_altitude_m)

        if max_relative_altitude_m is None or relative_altitude_m > max_relative_altitude_m:
            max_relative_altitude_m = relative_altitude_m

    return max_relative_altitude_m


def build_replay_receipt(
    command_status: Dict[str, Any],
) -> CommandSubmissionReceipt:
    """Recover the stable tracking identity without duplicating tracker state."""
    target_drones = list(command_status.get("target_drones") or [])
    command_id = str(command_status["command_id"])
    return CommandSubmissionReceipt(
        accepted_for_tracking=True,
        command_id=command_status["command_id"],
        idempotency_key=command_status.get("idempotency_key"),
        replayed=True,
        mission_type=int(command_status["mission_type"]),
        mission_name=command_status["mission_name"],
        target_drones=target_drones,
        tracking_url=f"/api/v1/commands/{command_id}",
        message=(
            "Recovered the existing tracked command. Monitor the tracking URL "
            "for its current lifecycle state."
        ),
        timestamp=int(time.time() * 1000),
    )


def build_submit_request_fingerprint(
    command: SubmitCommandRequest,
    *,
    per_target_payloads: Mapping[str, Mapping[str, Any]] | None = None,
) -> str:
    payload = command.model_dump(exclude_none=True)
    payload.pop("idempotency_key", None)
    if isinstance(payload.get("target_drone_ids"), list):
        payload["target_drone_ids"] = sorted(
            str(value).strip()
            for value in payload["target_drone_ids"]
            if value not in (None, "")
        )
    if per_target_payloads is not None:
        payload["per_target_payloads"] = per_target_payloads
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def submit_tracked_command(
    deps: Any,
    command: SubmitCommandRequest,
    *,
    authority: CommandSubmissionAuthority = CommandSubmissionAuthority.OPERATOR_COMMAND,
    per_target_payloads: Mapping[str, Mapping[str, Any]] | None = None,
) -> CommandSubmissionReceipt:
    """Submit a tracked command using the canonical GCS lifecycle."""
    mission_type = command.mission_type
    resolved_mission = deps.resolve_mission_type(mission_type)
    if resolved_mission is None or resolved_mission == deps.Mission.UNKNOWN:
        raise HTTPException(
            status_code=400,
            detail="mission_type must identify an executable mission; no command was created",
        )
    try:
        enforce_command_submission_policy(
            resolved_mission,
            command,
            params=deps.Params,
            authority=authority,
        )
    except CommandSubmissionPolicyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    normalized_per_target_payloads = validate_per_target_payloads(
        resolved_mission,
        list(command.target_drone_ids or []),
        per_target_payloads,
    )
    tracker = deps.get_command_tracker()
    command_data = command.model_dump(exclude_none=True)
    dispatch_payload = command.to_drone_payload()
    request_fingerprint = build_submit_request_fingerprint(
        command,
        per_target_payloads=normalized_per_target_payloads,
    )
    idempotency_key = command.idempotency_key
    provisional_timeout_ms = max(
        1_000,
        int(
            getattr(
                deps.Params,
                "GCS_COMMAND_PREPARATION_PROVISIONAL_TIMEOUT_MS",
                300_000,
            )
        ),
    )

    if idempotency_key:
        existing_command = await tracker.lookup_command_by_idempotency_key(
            idempotency_key,
            request_fingerprint=request_fingerprint,
        )
        if existing_command is not None:
            return build_replay_receipt(existing_command)

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
        raise HTTPException(
            status_code=409,
            detail="Fleet configuration has no drones. No command was dispatched.",
        )

    drones_by_hw_id: Dict[str, Dict[str, Any]] = {}
    invalid_hw_ids: List[str] = []
    duplicate_hw_ids: List[str] = []
    for drone in drones:
        hw_id = str(drone.get("hw_id", "")).strip()
        if not hw_id:
            invalid_hw_ids.append("missing")
            continue
        if hw_id in drones_by_hw_id:
            duplicate_hw_ids.append(hw_id)
            continue
        drones_by_hw_id[hw_id] = drone

    if invalid_hw_ids or duplicate_hw_ids or len(drones_by_hw_id) != len(drones):
        duplicate_summary = ", ".join(sorted(set(duplicate_hw_ids))) or "none"
        raise HTTPException(
            status_code=409,
            detail=(
                "Fleet configuration has invalid or duplicate hardware identities; "
                f"duplicate hardware IDs: {duplicate_summary}. No command was dispatched."
            ),
        )

    if normalized_target_ids:
        unmatched_target_ids = sorted(normalized_target_ids - set(drones_by_hw_id))
        if unmatched_target_ids:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Unknown target hardware ID(s): "
                    + ", ".join(unmatched_target_ids)
                    + ". No command was dispatched."
                ),
            )
        # Resolve strictly by hardware identity. Position/trajectory slots are
        # intentionally not accepted as command addresses because role swaps
        # can make an unqualified number ambiguous.
        actual_targets = [
            drone for drone in drones
            if str(drone.get("hw_id", "")).strip() in normalized_target_ids
        ]
    else:
        actual_targets = drones

    target_hw_ids = [str(drone["hw_id"]) for drone in actual_targets]
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

    mission_type_int = resolved_mission.value
    launch_preparation_required = deps.mission_requires_launch_armability_probe(resolved_mission)
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

    get_coordinator = getattr(deps, "get_command_submission_coordinator", None)
    if not callable(get_coordinator):
        raise HTTPException(
            status_code=503,
            detail="Tracked command submission service is unavailable; no command was created",
        )
    coordinator = get_coordinator()
    recovery = mission_is_recovery(resolved_mission)
    try:
        reservation: SubmissionReservation = await coordinator.reserve(recovery=recovery)
    except (CommandSubmissionCapacityError, CommandSubmissionUnavailableError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    command_id: Optional[str] = None
    launched = False
    try:
        creation_result = await tracker.create_or_replay_command(
            mission_type=mission_type_int,
            target_drones=target_hw_ids,
            params={
                "trigger_time": trigger_time,
                **(
                    {"per_target_payload_sha256": per_target_payload_digests(normalized_per_target_payloads)}
                    if normalized_per_target_payloads
                    else {}
                ),
                **{
                    k: v
                    for k, v in command_data.items()
                    if k not in [
                        "idempotency_key",
                        "mission_type",
                        "trigger_time",
                        "target_drone_ids",
                        "target_scope",
                    ]
                },
            },
            timeout_ms=provisional_timeout_ms,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            preparation_required=launch_preparation_required,
            start_preparing=True,
        )
        command_id = creation_result.command_id

        if creation_result.replayed:
            await coordinator.release(reservation)
            tracked_status = await tracker.get_status(command_id)
            if tracked_status is None:
                raise HTTPException(
                    status_code=500,
                    detail="Replay-safe command lookup lost tracker state",
                )
            return build_replay_receipt(tracked_status)

        dispatch_payload["command_id"] = command_id
        work = TrackedSubmissionWork(
            deps=deps,
            tracker=tracker,
            command_id=command_id,
            command_data=command_data,
            dispatch_payload=dispatch_payload,
            actual_targets=actual_targets,
            target_hw_ids=target_hw_ids,
            resolved_mission=resolved_mission,
            mission_type_int=mission_type_int,
            launch_preparation_required=launch_preparation_required,
            tracking_max_relative_altitude_m=tracking_max_relative_altitude_m,
            tracking_skybrush_dir=tracking_skybrush_dir,
            tracking_processed_dir=tracking_processed_dir,
            tracking_shapes_dir=tracking_shapes_dir,
            per_target_payloads=normalized_per_target_payloads,
        )
        tracked_status = await tracker.get_status(command_id)
        if tracked_status is None:
            raise RuntimeError("New command tracker state disappeared before response")
        try:
            mission_name = deps.Mission(mission_type_int).name
        except ValueError:
            mission_name = f"MISSION_{mission_type}"
        submission_receipt = build_submission_receipt(
            command_id=command_id,
            idempotency_key=idempotency_key,
            mission_type_int=mission_type_int,
            mission_name=mission_name,
            target_hw_ids=target_hw_ids,
        )
        await coordinator.launch(
            reservation,
            command_id=command_id,
            operation_factory=lambda: run_tracked_submission(work),
            on_failure=lambda reason: terminalize_submission_failure(work, reason),
            log_error=lambda message: deps.log_system_error(message, "command"),
        )
        launched = True
        return submission_receipt
    except Exception:
        if not launched:
            await coordinator.release(reservation)
            if command_id is not None:
                await tracker.fail_command_before_dispatch(
                    command_id,
                    "GCS could not start the owned command preparation task",
                )
        raise


__all__ = [
    "CommandIdempotencyConflictError",
    "build_submit_request_fingerprint",
    "build_replay_receipt",
    "estimate_max_target_relative_altitude_m",
    "record_command_acknowledgements",
    "submit_tracked_command",
]
