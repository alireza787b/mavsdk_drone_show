"""Shared read-only mission operation projection from command and presence truth."""
import time
from contextlib import nullcontext
from presence import build_presence_snapshot, resolve_presence_thresholds
from src.enums import Mission
from src.px4_flight_modes import describe_px4_custom_mode

RECOVERY_ACTIONS = {Mission.NONE.value, Mission.HOLD.value, Mission.LAND.value, Mission.RETURN_RTL.value}


async def build_mission_operation_snapshot(deps, *, mission_types, operation_kind):
    now = time.time()
    tracker = deps.get_command_tracker()
    # Creation order is operator intent order. Late callbacks from an old show
    # must never displace a newer show or silently shrink the next launch scope.
    shows = await tracker.get_recent(limit=1, mission_filter=sorted(mission_types))
    show = shows[0] if shows else None
    command = show
    if show:
        recent = await tracker.get_recent(limit=100, mission_filter=sorted(RECOVERY_ACTIONS))
        recovery = next((r for r in recent
                         if r.get("created_at", 0) >= show.get("created_at", 0)
                         and set(r.get("target_drones", [])) & set(show.get("target_drones", []))), None)
        if recovery:
            command = recovery
    configured = deps.load_config() or []
    with getattr(deps, "telemetry_lock", None) or nullcontext():
        telemetry = {str(k): dict(v or {}) for k, v in deps.telemetry_data_all_drones.items()}
        received = {str(k): v for k, v in getattr(deps, "last_telemetry_time", {}).items()}
    fleet = []
    thresholds = resolve_presence_thresholds(deps.Params)
    for item in configured:
        hw = str(item["hw_id"])
        row = telemetry.get(hw, {})
        telemetry_row = {**row, "telemetry_available": row.get("telemetry_available", True)}
        presence = build_presence_snapshot(
            hw_id=hw,
            heartbeat={"received_at_gcs_ms": row.get("heartbeat_last_seen")},
            telemetry=telemetry_row,
            telemetry_success_time=received.get(hw) or row.get("timestamp"),
            configured=True, now=now, thresholds=thresholds,
        )
        mode = row.get("flight_mode_name")
        if not mode:
            raw_mode = row.get("flight_mode")
            mode = describe_px4_custom_mode(raw_mode) if isinstance(raw_mode, int) else raw_mode
        fleet.append({
            "hw_id": hw, "pos_id": str(item.get("pos_id", hw)),
            "name": item.get("callsign") or f"P{item.get('pos_id', hw)} | H{hw}",
            "state": mode or "Unknown", "armed": row.get("is_armed"),
            "landed_state": row.get("landed_state"),
            "ready_to_arm": row.get("is_ready_to_arm") is True,
            "readiness_summary": row.get("readiness_summary") or "Readiness unavailable",
            "warnings": row.get("preflight_warnings") or [],
            "battery_percent": row.get("battery_remaining_percent"),
            "telemetry_age_ms": round(presence["telemetry_age_sec"] * 1000)
                if presence["telemetry_age_sec"] is not None else None,
            "telemetry_fresh": presence["fresh"],
            "trajectory_execution": row.get('trajectory_execution')
                if isinstance(row.get('trajectory_execution'), dict)
                and row['trajectory_execution'].get('command_id') == (show or {}).get('command_id')
                and presence['fresh'] else None,
        })
    phase = "idle"
    if command:
        phase = (command.get("progress") or {}).get("stage") or command.get("phase", "unknown")
        if phase == "in_progress":
            phase = "executing"
        if command.get("phase") == "terminal":
            phase = command.get("outcome") or command.get("status") or "unknown"
    active = bool(command and command.get("phase") != "terminal")
    # No fabricated trajectory percentage: tracker completion is per aircraft.
    completed = (command or {}).get("executions", {}).get("succeeded", 0)
    expected = len((command or {}).get("target_drones", []))
    trajectory = operation_kind == 'trajectory'
    if trajectory:
        formation = deps.swarm_trajectory_service.get_formation_payload()
        from functions.swarm_session_manager import SwarmSessionManager
        current = SwarmSessionManager().get_current_session()
        session = {'session_id': current.session_id if current else None}
    else:
        formation, session = None, None
    return {
        "state": "active" if active else phase, "phase": phase,
        "progress_percent": round(100 * completed / expected) if expected else 0,
        "progress_kind": "aircraft_completion",
        "command_id": (command or {}).get("command_id"),
        "mission_type": (command or {}).get("mission_type"),
        "mission_name": (command or {}).get("mission_name"),
        "operation_kind": operation_kind if (command or {}).get("mission_type") in mission_types
            else ("recovery" if command else None),
        "target_drone_ids": [str(item["hw_id"]) for item in configured],
        "operation_target_ids": (show or {}).get("target_drones", []),
        "fleet": fleet, "command": command, "timestamp": int(now * 1000),
        **({'formation': formation, 'package_session': session} if trajectory else {}),
    }
