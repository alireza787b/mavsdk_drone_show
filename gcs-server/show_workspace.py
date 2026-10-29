"""Read-only Drone Show projections; tracker and fleet presence remain authoritative."""

import time
from pathlib import Path

from fastapi import HTTPException

from show_management import (
    build_metrics_snapshot_payload, build_show_info_payload,
    list_show_plots_payload, validation_from_metrics,
)
from src.enums import Mission


SHOW_MISSIONS = {Mission.DRONE_SHOW_FROM_CSV.value, Mission.CUSTOM_CSV_DRONE_SHOW.value}


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
    from mission_operation import build_mission_operation_snapshot
    return await build_mission_operation_snapshot(deps, mission_types=SHOW_MISSIONS, operation_kind='show')
