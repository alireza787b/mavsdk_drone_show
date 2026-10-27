"""Read-only Drone Show projections; tracker and fleet presence remain authoritative."""

import time
from contextlib import nullcontext
from pathlib import Path

from fastapi import HTTPException

from presence import build_presence_snapshot, resolve_presence_thresholds
from show_management import (
    build_metrics_snapshot_payload, build_show_info_payload,
    list_show_plots_payload, validation_from_metrics,
)
from src.enums import Mission
from src.px4_flight_modes import describe_px4_custom_mode


SHOW_MISSIONS = {Mission.DRONE_SHOW_FROM_CSV.value, Mission.CUSTOM_CSV_DRONE_SHOW.value}
RECOVERY_ACTIONS = {Mission.NONE.value, Mission.HOLD.value, Mission.LAND.value, Mission.RETURN_RTL.value}


def build_workspace_snapshot(deps):
    """Use the import-produced cache, never recalculate trajectories while polling."""
    try:
        package = {**build_show_info_payload(deps.skybrush_dir), "available": True}
    except (HTTPException, FileNotFoundError):
        package = {"available": False, "drone_count": 0}
    except (ValueError, OSError):
        package = {"available": False, "drone_count": 0, "error": "Show package could not be read"}
    files = sorted(Path(deps.processed_dir).glob("Drone *.csv"))
    package["position_ids"] = [p.stem.removeprefix("Drone ") for p in files]
    package["processed_count"] = len(files)
    try:
        metrics = build_metrics_snapshot_payload(
            metrics_available=bool(deps.METRICS_AVAILABLE),
            load_saved_metrics_if_current_func=deps._load_saved_metrics_if_current,
        )
    except HTTPException:
        metrics = {"available": False}
    cached = metrics.get("metrics") if metrics.get("available") else None
    return {
        "package": package, "metrics": metrics,
        "safety": {"safety_analysis": cached.get("safety_metrics", {})} if cached else None,
        "validation": validation_from_metrics(cached) if cached else None,
        "plots": list_show_plots_payload(deps.plots_directory),
        "timestamp": int(time.time() * 1000),
    }


async def build_operation_snapshot(deps):
    now = time.time()
    tracker = deps.get_command_tracker()
    # Creation order is operator intent order. Late callbacks from an old show
    # must never displace a newer show or silently shrink the next launch scope.
    shows = await tracker.get_recent(limit=1, mission_filter=sorted(SHOW_MISSIONS))
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
    return {
        "state": "active" if active else phase, "phase": phase,
        "progress_percent": round(100 * completed / expected) if expected else 0,
        "progress_kind": "aircraft_completion",
        "command_id": (command or {}).get("command_id"),
        "mission_type": (command or {}).get("mission_type"),
        "mission_name": (command or {}).get("mission_name"),
        "operation_kind": "show" if (command or {}).get("mission_type") in SHOW_MISSIONS
            else ("recovery" if command else None),
        "target_drone_ids": [str(item["hw_id"]) for item in configured],
        "operation_target_ids": (show or {}).get("target_drones", []),
        "fleet": fleet, "command": command, "timestamp": int(now * 1000),
    }
