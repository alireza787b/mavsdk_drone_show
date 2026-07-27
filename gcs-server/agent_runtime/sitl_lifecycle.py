"""Pure completion checks for guarded SITL lifecycle operations."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


_REMOVE_OPERATION_TYPES = frozenset({"remove_instance", "remove_instances"})
_READY_OPERATION_TYPES = frozenset(
    {
        "create_instance",
        "reconcile_fleet",
        "restart_instance",
        "restart_instances",
    }
)
_RUNNING_INSTANCE_STATES = frozenset({"running", "up"})
_BAD_HEALTH_STATES = frozenset({"dead", "failed", "unhealthy"})


def sitl_lifecycle_evidence_roles(operation: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the registry evidence roles required by one typed operation."""

    operation_type = _text(operation.get("operation_type")).casefold()
    target_count = _integer(_mapping(operation.get("metadata")).get("target_count"))
    if operation_type in _REMOVE_OPERATION_TYPES:
        return ("instances",)
    if operation_type == "reconcile_fleet" and target_count == 0:
        return ("instances",)
    return ("instances", "heartbeats", "telemetry")


def evaluate_sitl_lifecycle_completion(
    *,
    operation: Mapping[str, Any],
    instances_payload: Any,
    heartbeats_payload: Any = None,
    telemetry_payload: Any = None,
) -> dict[str, Any]:
    """Evaluate typed Docker, MAVLink presence, and preflight evidence.

    This function deliberately consumes machine contracts rather than operator
    prose. Language interpretation belongs to the planning layer; lifecycle
    completion must remain deterministic and auditable.
    """

    operation_type = _text(operation.get("operation_type")).casefold()
    affected_instances = _string_list(operation.get("affected_instances"))
    instance_rows = _instance_rows(instances_payload)
    instances_by_name = {
        name: row
        for row in instance_rows
        if (name := _instance_name(row))
    }

    if operation_type in _REMOVE_OPERATION_TYPES:
        return _evaluate_removal(
            operation_type=operation_type,
            affected_instances=affected_instances,
            instances_by_name=instances_by_name,
        )

    if operation_type not in _READY_OPERATION_TYPES:
        return _result(
            status="unsupported",
            verified=False,
            label="SITL completion evidence is unavailable",
            summary=f"No lifecycle completion evaluator is registered for operation type {operation_type or 'unknown'}.",
            operation_type=operation_type,
            affected_instances=affected_instances,
            blockers=("unsupported_operation_type",),
        )

    target_count = _integer(_mapping(operation.get("metadata")).get("target_count"))
    if operation_type == "reconcile_fleet" and target_count == 0:
        total_instances = _integer(_mapping(instances_payload).get("total_instances"))
        verified = total_instances == 0
        return _result(
            status="verified" if verified else "pending",
            verified=verified,
            label="SITL fleet is empty" if verified else "Waiting for SITL containers to be removed",
            summary=(
                "SITL reconcile completed and no managed instances remain."
                if verified
                else "The reconcile operation completed, but managed SITL instances are still present."
            ),
            operation_type=operation_type,
            affected_instances=affected_instances,
            blockers=() if verified else ("instances_still_present",),
        )

    if not affected_instances:
        return _result(
            status="unavailable",
            verified=False,
            label="Waiting for affected SITL instance identity",
            summary="The operation response did not identify the SITL instances whose readiness must be verified.",
            operation_type=operation_type,
            affected_instances=affected_instances,
            blockers=("affected_instances_missing",),
        )

    docker = _mapping(_mapping(instances_payload).get("docker"))
    docker_reachable = _boolean(_first_present(docker, "daemon_reachable", "available"))
    heartbeat_rows = _rows_by_vehicle_id(heartbeats_payload, collection_keys=("heartbeats", "data", "items"))
    telemetry_rows = _rows_by_vehicle_id(
        telemetry_payload,
        collection_keys=("telemetry", "data", "drones", "items"),
    )

    rows: list[dict[str, Any]] = []
    for instance_name in affected_instances:
        instance = instances_by_name.get(instance_name, {})
        vehicle_id = _instance_vehicle_id(instance, fallback_name=instance_name)
        heartbeat = heartbeat_rows.get(vehicle_id, {}) if vehicle_id else {}
        telemetry = telemetry_rows.get(vehicle_id, {}) if vehicle_id else {}
        state = _instance_state(instance)
        health = _text(_first_present(instance, "health_status", "health")).casefold()
        container_running = state in _RUNNING_INSTANCE_STATES and health not in _BAD_HEALTH_STATES
        mavlink_live = _heartbeat_live(heartbeat) and _telemetry_present(
            telemetry,
            heartbeat=heartbeat,
        )
        preflight_ready = _boolean(
            _first_present(telemetry, "is_ready_to_arm", "ready_to_arm", "preflight_ready", "ready")
        )
        rows.append(
            {
                "instance_name": instance_name,
                "vehicle_id": vehicle_id or None,
                "container_present": bool(instance),
                "container_state": state or "unknown",
                "health_status": health or None,
                "container_running": container_running,
                "mavlink_live": mavlink_live,
                "preflight_ready": preflight_ready,
                "armed": _boolean(_first_present(telemetry, "is_armed", "armed")),
                "mode": _text(_first_present(telemetry, "flight_mode_name", "mode_name", "mode")) or None,
                "gps_fix_type": _first_present(telemetry, "gps_fix_type", "fix_type", "gps_fix"),
                "satellites_visible": _first_present(
                    telemetry,
                    "satellites_visible",
                    "gps_satellites_visible",
                    "satellites",
                ),
                "battery_voltage": _first_present(telemetry, "battery_voltage", "voltage", "battery_v"),
            }
        )

    expected = len(rows)
    containers_ready = sum(1 for row in rows if row["container_running"])
    mavlink_ready = sum(1 for row in rows if row["mavlink_live"])
    preflight_ready = sum(1 for row in rows if row["preflight_ready"] is True)
    blockers: list[str] = []
    if docker_reachable is not True:
        blockers.append("docker_unreachable" if docker_reachable is False else "docker_state_unknown")
    if containers_ready < expected:
        blockers.append("containers_not_running")
    if mavlink_ready < expected:
        blockers.append("mavlink_not_live")
    if preflight_ready < expected:
        blockers.append("preflight_not_ready")
    if operation_type == "reconcile_fleet" and target_count is not None:
        total_instances = _integer(_mapping(instances_payload).get("total_instances"))
        if total_instances != target_count:
            blockers.append("fleet_count_not_converged")

    verified = not blockers
    if verified:
        label = _count_label(expected, "SITL vehicle ready", "SITL vehicles ready")
        summary = (
            f"{expected}/{expected} affected SITL vehicle(s) have a running container, "
            "fresh MAVLink presence, and preflight-ready telemetry."
        )
    elif docker_reachable is not True or containers_ready < expected:
        label = f"Containers running {containers_ready}/{expected}"
        summary = "The lifecycle operation completed; waiting for affected Docker containers to run."
    elif mavlink_ready < expected:
        label = f"MAVLink live {mavlink_ready}/{expected}"
        summary = "Affected containers are running; waiting for fresh vehicle presence and telemetry."
    else:
        label = f"Preflight ready {preflight_ready}/{expected}"
        summary = "MAVLink is live; waiting for all affected vehicles to report preflight ready."

    return _result(
        status="verified" if verified else "pending",
        verified=verified,
        label=label,
        summary=summary,
        operation_type=operation_type,
        affected_instances=affected_instances,
        blockers=tuple(blockers),
        instances=rows,
        docker_reachable=docker_reachable,
    )


def _evaluate_removal(
    *,
    operation_type: str,
    affected_instances: list[str],
    instances_by_name: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if not affected_instances:
        return _result(
            status="unavailable",
            verified=False,
            label="Waiting for affected SITL instance identity",
            summary="The remove operation did not identify which SITL instances must be absent.",
            operation_type=operation_type,
            affected_instances=affected_instances,
            blockers=("affected_instances_missing",),
        )
    remaining = [name for name in affected_instances if name in instances_by_name]
    verified = not remaining
    return _result(
        status="verified" if verified else "pending",
        verified=verified,
        label=(
            _count_label(len(affected_instances), "SITL instance removed", "SITL instances removed")
            if verified
            else f"Waiting to remove {len(remaining)} SITL instance(s)"
        ),
        summary=(
            f"{len(affected_instances)}/{len(affected_instances)} requested SITL instance(s) are absent from the managed inventory."
            if verified
            else "The remove operation completed, but requested instances are still present in the managed inventory."
        ),
        operation_type=operation_type,
        affected_instances=affected_instances,
        blockers=() if verified else ("instances_still_present",),
        remaining_instances=remaining,
    )


def _result(
    *,
    status: str,
    verified: bool,
    label: str,
    summary: str,
    operation_type: str,
    affected_instances: Sequence[str],
    blockers: Sequence[str],
    **extra: Any,
) -> dict[str, Any]:
    return {
        "kind": "sitl_lifecycle",
        "status": status,
        "verified": verified,
        "label": label,
        "summary": summary,
        "operation_type": operation_type,
        "affected_instances": list(affected_instances),
        "blockers": list(blockers),
        **extra,
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return list(dict.fromkeys(_text(item) for item in value if _text(item)))


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number


def _boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "yes", "1", "on", "ready", "live", "online", "connected"}:
            return True
        if normalized in {"false", "no", "0", "off", "not_ready", "offline", "disconnected"}:
            return False
    return None


def _first_present(value: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in value and value.get(key) is not None:
            return value.get(key)
    return None


def _instance_rows(value: Any) -> list[Mapping[str, Any]]:
    raw = _mapping(value).get("instances")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _instance_name(row: Mapping[str, Any]) -> str:
    return _text(_first_present(row, "name", "container_name", "instance_name"))


def _instance_state(row: Mapping[str, Any]) -> str:
    value = _text(_first_present(row, "state", "status", "container_status")).casefold()
    return value.split()[0] if value else ""


def _instance_vehicle_id(row: Mapping[str, Any], *, fallback_name: str) -> str:
    explicit = _text(_first_present(row, "hw_id", "pos_id_hint"))
    if explicit:
        return explicit
    match = re.fullmatch(r"drone-(\d+)", fallback_name.casefold())
    return match.group(1) if match else ""


def _rows_by_vehicle_id(value: Any, *, collection_keys: Sequence[str]) -> dict[str, Mapping[str, Any]]:
    raw: Any = value
    if isinstance(value, Mapping):
        raw = None
        for key in collection_keys:
            if key in value:
                raw = value.get(key)
                break
        if raw is None and all(isinstance(item, Mapping) for item in value.values()):
            raw = value
    rows: dict[str, Mapping[str, Any]] = {}
    if isinstance(raw, Mapping):
        for fallback, row in raw.items():
            if isinstance(row, Mapping):
                vehicle_id = _row_vehicle_id(row, fallback=fallback)
                if vehicle_id:
                    rows[vehicle_id] = row
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        for row in raw:
            if isinstance(row, Mapping):
                vehicle_id = _row_vehicle_id(row)
                if vehicle_id:
                    rows[vehicle_id] = row
    return rows


def _row_vehicle_id(row: Mapping[str, Any], *, fallback: Any = "") -> str:
    return _text(_first_present(row, "hw_id", "drone_id", "id", "pos_id")) or _text(fallback)


def _heartbeat_live(row: Mapping[str, Any]) -> bool:
    presence = _mapping(row.get("presence"))
    fresh = _boolean(presence.get("fresh"))
    if fresh is not None:
        return fresh
    online = _boolean(_first_present(row, "online", "connected", "is_online", "is_live"))
    if online is not None:
        return online
    state = _text(_first_present(row, "presence_state", "state", "status")).casefold()
    return state in {"connected", "live", "online", "ready"}


def _telemetry_present(
    row: Mapping[str, Any],
    *,
    heartbeat: Mapping[str, Any],
) -> bool:
    if not row:
        return False
    available = _boolean(_first_present(row, "telemetry_available", "available", "online"))
    if available is False:
        return False
    presence = _mapping(heartbeat.get("presence"))
    telemetry_recent = _boolean(presence.get("telemetry_recent"))
    return telemetry_recent is True


def _count_label(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"
