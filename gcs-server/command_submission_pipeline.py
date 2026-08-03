"""I/O pipeline executed after a tracked command receives its stable ID."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from command_execution_policy import resolve_strict_sync_trigger_time
from schemas import CommandPhase, CommandSubmissionReceipt
from src.enums import CommandErrorCode


class SITLCallbackEndpointMismatchError(RuntimeError):
    """The simulator fleet reports execution to a different GCS endpoint."""


@dataclass(frozen=True)
class TrackedSubmissionWork:
    """Validated local command data owned by one background submission task."""

    deps: Any
    tracker: Any
    command_id: str
    command_data: Dict[str, Any]
    dispatch_payload: Dict[str, Any]
    actual_targets: List[Dict[str, Any]]
    target_hw_ids: List[str]
    resolved_mission: Any
    mission_type_int: int
    launch_preparation_required: bool
    tracking_max_relative_altitude_m: Optional[float]
    tracking_skybrush_dir: str
    tracking_processed_dir: str
    tracking_shapes_dir: str
    per_target_payloads: Optional[Dict[str, Dict[str, Any]]] = None


def _sitl_callback_endpoint_guard_enabled(deps: Any) -> bool:
    """Return whether tracked SITL commands must match the active GCS endpoint."""
    return getattr(getattr(deps, "Params", None), "sim_mode", False) is True


def ensure_sitl_callback_endpoint_matches(deps: Any, target_hw_ids: List[str]) -> None:
    """Fail closed before dispatch when a SITL fleet reports to another GCS.

    The check is deliberately best-effort for legacy images and non-Docker
    deployments. When current container metadata is available, a mismatch is
    a deterministic configuration error and must not create a tracked command
    that can only time out after the drone has acted.
    """
    if not _sitl_callback_endpoint_guard_enabled(deps):
        return

    service = getattr(deps, "sitl_control_service", None)
    if service is None:
        try:
            from src.sitl_control_service import SitlControlService

            service = SitlControlService(
                deps.Params,
                repo_root=str(getattr(deps, "BASE_DIR", "") or "") or None,
            )
        except Exception:
            return

    checker = getattr(service, "callback_endpoint_mismatches", None)
    if not callable(checker):
        return
    try:
        mismatches = checker(set(target_hw_ids))
    except Exception as exc:
        logger = getattr(deps, "log_system_warning", None)
        if callable(logger):
            logger(f"SITL callback endpoint preflight unavailable: {exc}", "command")
        return
    if not mismatches:
        return

    details = []
    for mismatch in mismatches[:4]:
        name = mismatch.get("name") or f"drone-{mismatch.get('hw_id') or '?'}"
        observed = f"{mismatch.get('observed_ip')}:{mismatch.get('observed_port')}"
        expected = f"{mismatch.get('expected_ip')}:{mismatch.get('expected_port')}"
        details.append(f"{name} reports to {observed}; active GCS is {expected}")
    message = (
        "SITL command blocked because execution callbacks are routed to a "
        "different GCS process. Reconcile or recreate the SITL fleet from "
        "this GCS before retrying. "
        + "; ".join(details)
    )
    warning = getattr(deps, "log_system_warning", None)
    if callable(warning):
        warning(message, "command")
    raise SITLCallbackEndpointMismatchError(message)


async def record_command_acknowledgements(
    tracker: Any,
    command_id: str,
    results: dict[str, Any],
) -> None:
    """Record every typed per-target transport classification in the tracker."""
    for drone_id, result in results.get("results", {}).items():
        category = result.get("category", "error")
        if result.get("success"):
            await tracker.record_ack(
                command_id,
                drone_id,
                category="accepted",
                message=result.get("message") or "Drone accepted command",
                error_detail=result.get("error_detail"),
                delivery_state=result.get("delivery_state") or "accepted",
            )
        elif category == "offline":
            await tracker.record_ack(
                command_id,
                drone_id,
                category="offline",
                message=result.get("error", "Drone unreachable"),
                error_code=result.get("error_code") or CommandErrorCode.DRONE_OFFLINE.value,
                error_detail=result.get("error_detail"),
                delivery_state=result.get("delivery_state") or "dispatch_unreachable",
            )
        elif category == "rejected":
            await tracker.record_ack(
                command_id,
                drone_id,
                category="rejected",
                message=result.get("error", "Drone rejected command"),
                error_code=result.get("error_code") or CommandErrorCode.HTTP_ERROR.value,
                error_detail=result.get("error_detail"),
                delivery_state=result.get("delivery_state") or "rejected",
            )
        else:
            await tracker.record_ack(
                command_id,
                drone_id,
                category="error",
                message=result.get("error", "Unexpected error"),
                error_code=result.get("error_code") or CommandErrorCode.INTERNAL_ERROR.value,
                error_detail=result.get("error_detail"),
                delivery_state=result.get("delivery_state") or "transport_error",
            )


async def _prepare_launch(
    deps: Any,
    drones: List[Dict[str, Any]],
    *,
    dispatch_payload: Dict[str, Any],
    callback_capabilities: Dict[str, str],
    per_target_payloads: Optional[Dict[str, Dict[str, Any]]],
) -> Dict[str, Any]:
    get_service = getattr(deps, "get_fleet_rpc_service", None)
    if not callable(get_service):
        raise RuntimeError("FleetRPC service is unavailable; no command was dispatched")
    service = get_service()
    if service is None:
        raise RuntimeError("FleetRPC service is unavailable; no command was dispatched")
    return await service.prepare_launch(
        drones,
        dispatch_payload,
        callback_capabilities=callback_capabilities,
        per_target_payloads=per_target_payloads,
        require_global_position=True,
    )


async def _dispatch_command(
    deps: Any,
    *,
    actual_targets: List[Dict[str, Any]],
    dispatch_payload: Dict[str, Any],
    callback_capabilities: Dict[str, str],
    per_target_payloads: Optional[Dict[str, Dict[str, Any]]],
    launch_preparation_tokens: Optional[Dict[str, str]],
) -> Dict[str, Any]:
    """Dispatch every committed target without cached-presence suppression."""
    get_service = getattr(deps, "get_fleet_rpc_service", None)
    if not callable(get_service):
        raise RuntimeError("FleetRPC service is unavailable after submission; delivery is unknown")
    service = get_service()
    if service is None:
        raise RuntimeError("FleetRPC service is unavailable after submission; delivery is unknown")
    return await service.dispatch(
        actual_targets,
        dispatch_payload,
        callback_capabilities=callback_capabilities,
        per_target_payloads=per_target_payloads,
        launch_preparation_tokens=launch_preparation_tokens,
    )


async def record_launch_preparations(
    tracker: Any,
    command_id: str,
    target_hw_ids: List[str],
    launch_probe: Dict[str, Any],
) -> None:
    """Persist readiness as preparation evidence, never as a delivery ACK."""
    results = launch_probe.get("results") or {}
    for drone_id in target_hw_ids:
        result = results.get(drone_id) or {}
        state = result.get("prepare_state")
        if state not in {"ready", "blocked", "unavailable"}:
            if result.get("ready") is True:
                state = "ready"
            elif result.get("category") == "blocked":
                state = "blocked"
            else:
                state = "unavailable"

        details = result.get("details") if isinstance(result.get("details"), dict) else {}
        observation = details.get("observation") if isinstance(details, dict) else None
        if state == "blocked":
            error_code = result.get("error_code") or CommandErrorCode.PREFLIGHT_FAILED.value
        elif state == "unavailable":
            error_code = result.get("error_code") or CommandErrorCode.DRONE_UNREACHABLE.value
        else:
            error_code = None

        await tracker.record_preparation(
            command_id,
            drone_id,
            state=state,
            message=result.get("summary") or ("Ready for launch" if state == "ready" else None),
            error_code=error_code,
            error_detail=result.get("error_detail"),
            observation=observation,
        )


async def run_tracked_submission(work: TrackedSubmissionWork) -> None:
    """Complete timeout estimation, readiness, and dispatch for one tracker ID."""
    deps = work.deps
    tracker = work.tracker
    await asyncio.to_thread(
        ensure_sitl_callback_endpoint_matches,
        deps,
        work.target_hw_ids,
    )
    callback_capabilities = await tracker.get_callback_capabilities(work.command_id)
    launch_preparation_tokens: Optional[Dict[str, str]] = None
    if work.launch_preparation_required:
        launch_preparation = await _prepare_launch(
            deps,
            work.actual_targets,
            dispatch_payload=work.dispatch_payload,
            callback_capabilities=callback_capabilities,
            per_target_payloads=work.per_target_payloads,
        )
        await record_launch_preparations(
            tracker,
            work.command_id,
            work.target_hw_ids,
            launch_preparation,
        )
        if not launch_preparation["all_prepared"]:
            return
        launch_preparation_tokens = launch_preparation["preparation_tokens"]

    trigger_time = resolve_strict_sync_trigger_time(
        work.resolved_mission,
        requested_trigger_time=int(work.command_data.get("trigger_time", 0)),
        params=deps.Params,
    )
    if trigger_time != work.command_data.get("trigger_time", 0):
        if not await tracker.update_params_before_dispatch(
            work.command_id,
            {"trigger_time": trigger_time},
        ):
            raise RuntimeError("Command trigger could not be committed before dispatch")
        work.command_data["trigger_time"] = trigger_time
        work.dispatch_payload["trigger_time"] = trigger_time

    tracking_timeout_ms = await asyncio.to_thread(
        deps.estimate_command_tracking_timeout_ms,
        work.resolved_mission,
        command_data=work.command_data,
        target_drone_ids=work.target_hw_ids,
        max_relative_altitude_m=work.tracking_max_relative_altitude_m,
        skybrush_dir=work.tracking_skybrush_dir,
        processed_dir=work.tracking_processed_dir,
        shapes_dir=work.tracking_shapes_dir,
    )
    timeout_at_ms = int(time.time() * 1000) + max(1, int(tracking_timeout_ms))
    if not await tracker.update_deadline_before_dispatch(work.command_id, timeout_at_ms):
        return

    if not await tracker.mark_submitted(work.command_id):
        status = await tracker.get_status(work.command_id)
        if status and status.get("phase") == CommandPhase.TERMINAL.value:
            return
        raise RuntimeError("Command preparation did not produce a dispatchable target set")

    results = await _dispatch_command(
        deps,
        actual_targets=work.actual_targets,
        dispatch_payload=work.dispatch_payload,
        callback_capabilities=callback_capabilities,
        per_target_payloads=work.per_target_payloads,
        launch_preparation_tokens=launch_preparation_tokens,
    )
    await record_command_acknowledgements(tracker, work.command_id, results)


async def terminalize_submission_failure(
    work: TrackedSubmissionWork,
    reason: str,
) -> None:
    """Preserve definite pre-dispatch failure vs post-submit uncertainty."""
    compact_reason = " ".join(str(reason).split())[:500]
    if await work.tracker.fail_command_before_dispatch(work.command_id, compact_reason):
        return

    status = await work.tracker.get_status(work.command_id)
    if not status or status.get("phase") == CommandPhase.TERMINAL.value:
        return

    existing = set(((status.get("acks") or {}).get("details") or {}).keys())
    for hw_id in work.target_hw_ids:
        if hw_id in existing:
            continue
        await work.tracker.record_ack(
            work.command_id,
            hw_id,
            category="error",
            message=(
                "GCS submission orchestration stopped after dispatch may have begun; "
                "delivery is unknown"
            ),
            error_code=CommandErrorCode.INTERNAL_ERROR.value,
            error_detail=compact_reason,
            delivery_state="delivery_unknown",
        )


def build_submission_receipt(
    *,
    command_id: str,
    idempotency_key: Optional[str],
    mission_type_int: int,
    mission_name: str,
    target_hw_ids: List[str],
) -> CommandSubmissionReceipt:
    """Return proof of tracked work without claiming any node-side outcome."""
    return CommandSubmissionReceipt(
        accepted_for_tracking=True,
        command_id=command_id,
        idempotency_key=idempotency_key,
        replayed=False,
        mission_type=mission_type_int,
        mission_name=mission_name,
        target_drones=target_hw_ids,
        tracking_url=f"/api/v1/commands/{command_id}",
        message=(
            "Command accepted for tracked preparation. Monitor the tracking URL "
            "for readiness, dispatch, execution, and terminal outcome."
        ),
        timestamp=int(time.time() * 1000),
    )


__all__ = [
    "TrackedSubmissionWork",
    "SITLCallbackEndpointMismatchError",
    "build_submission_receipt",
    "ensure_sitl_callback_endpoint_matches",
    "record_command_acknowledgements",
    "record_launch_preparations",
    "run_tracked_submission",
    "terminalize_submission_failure",
]
