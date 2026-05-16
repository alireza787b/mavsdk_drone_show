"""
Swarm trajectory service helpers shared by the FastAPI surface.
"""

from __future__ import annotations

import logging
import math
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from config import load_swarm
from functions.swarm_analyzer import analyze_swarm_structure, fetch_swarm_data, find_ultimate_leader
from functions.swarm_kml_generator import generate_cluster_kml, generate_kml_for_drone
from functions.swarm_session_manager import SwarmSessionManager
from functions.swarm_trajectory_processor import (
    clear_processed_data,
    get_processing_recommendation,
    process_swarm_trajectories,
)
from functions.swarm_trajectory_utils import get_project_root, get_swarm_trajectory_folders
from src.params import Params
from utils import git_operations

logger = logging.getLogger(__name__)

_PROCESSING_JOB_TERMINAL_STATES = {"succeeded", "failed", "canceled"}
_PROCESSING_JOB_LOCK = threading.Lock()
_PROCESSING_JOB_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="swarm-trajectory")
_PROCESSING_JOBS: Dict[str, Dict[str, Any]] = {}


class SwarmTrajectoryError(Exception):
    """Typed exception for API-friendly swarm trajectory failures."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _processing_failure_status_code(result: Dict) -> int:
    error = str(result.get("error") or "").lower()
    stage = str(result.get("processing_stage") or "").lower()

    if stage in {"initialization", "execution"}:
        return 500

    if "failed to clear data" in error:
        return 500

    return 400


def _load_swarm_structure() -> Dict:
    swarm_data = load_swarm()
    return analyze_swarm_structure(swarm_data)


def _collect_drone_ids(directory: str) -> List[int]:
    drone_ids = []
    directory_path = Path(directory)

    if not directory_path.exists():
        return drone_ids

    for file_path in sorted(directory_path.glob("Drone *.csv")):
        suffix = file_path.stem.replace("Drone ", "", 1)
        try:
            drone_ids.append(int(suffix))
        except ValueError:
            logger.warning("Ignoring unexpected trajectory filename: %s", file_path.name)

    return sorted(drone_ids)


def _remove_file(path: Path, removed_files: List[str], label: str) -> bool:
    if not path.exists():
        return False

    path.unlink()
    removed_files.append(label)
    return True


def _clear_current_session() -> None:
    SwarmSessionManager().clear_session()


def _clear_session_file(session_file: Path, cleared_items: List[str]) -> None:
    if session_file.exists():
        session_file.unlink()
        cleared_items.append(str(session_file.relative_to(Path(get_project_root()))))


def _build_follow_map(structure: Dict) -> Dict[int, int]:
    follow_map: Dict[int, int] = {}
    swarm_config = structure.get("swarm_config", {})

    for drone_id, config in swarm_config.items():
        try:
            numeric_id = int(drone_id)
            follow_map[numeric_id] = int(config.get("follow", 0) or 0)
        except (TypeError, ValueError):
            logger.warning("Ignoring invalid swarm follow assignment for drone %s", drone_id)

    return follow_map


def _build_empty_package_stats() -> Dict:
    return {
        "available": False,
        "drone_count": 0,
        "drone_ids": [],
        "route_entry_time_s": None,
        "mission_clock_s": None,
        "route_motion_time_s": None,
        "max_altitude_msl_m": None,
        "min_altitude_msl_m": None,
        "altitude_window_m": None,
    }


def _round_metric(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 2)


def _is_finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _first_elevation_result(provider_payload: Dict[str, Any]) -> Dict[str, Any]:
    results = provider_payload.get("results")
    if isinstance(results, list) and results:
        first = results[0]
        if isinstance(first, dict):
            return first
    return {}


def _normalize_elevation_payload(provider_payload: Any) -> Dict[str, Any]:
    """Normalize backend elevation providers into the Swarm authoring contract."""
    if _is_finite_number(provider_payload):
        return {
            "elevation_m": float(provider_payload),
            "status": "ok",
            "source": "backend",
            "provider": "backend",
            "confidence": "reported",
            "message": None,
            "sample_time": None,
        }

    if not isinstance(provider_payload, dict):
        return {
            "elevation_m": None,
            "status": "unavailable",
            "source": "unavailable",
            "provider": "unavailable",
            "confidence": "none",
            "message": "Elevation value was not returned.",
            "sample_time": None,
        }

    result_payload = _first_elevation_result(provider_payload)
    elevation = provider_payload.get("elevation")
    if elevation is None:
        elevation = provider_payload.get("elevation_m")
    if elevation is None:
        elevation = result_payload.get("elevation")
    if elevation is None:
        elevation = result_payload.get("elevation_m")

    source = (
        provider_payload.get("source")
        or result_payload.get("source")
        or provider_payload.get("dataset")
        or result_payload.get("dataset")
        or ("opentopodata" if result_payload else "backend")
    )
    provider = provider_payload.get("provider") or source
    confidence = provider_payload.get("confidence") or result_payload.get("confidence")
    sample_time = (
        provider_payload.get("sample_time")
        or provider_payload.get("timestamp")
        or result_payload.get("sample_time")
        or result_payload.get("timestamp")
    )

    if _is_finite_number(elevation):
        return {
            "elevation_m": float(elevation),
            "status": "ok",
            "source": str(source),
            "provider": str(provider),
            "confidence": str(confidence or "reported"),
            "message": provider_payload.get("message") or result_payload.get("message"),
            "sample_time": sample_time,
        }

    return {
        "elevation_m": None,
        "status": "unavailable",
        "source": str(source or "unavailable"),
        "provider": str(provider or source or "unavailable"),
        "confidence": str(confidence or "none"),
        "message": str(
            provider_payload.get("error")
            or result_payload.get("error")
            or provider_payload.get("message")
            or "Elevation value was not returned."
        ),
        "sample_time": sample_time,
    }


def _first_existing_column(columns: List[str], candidates: List[str]) -> Optional[str]:
    lowered = {str(column).lower(): column for column in columns}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None


def _swarm_issue(
    code: str,
    message: str,
    severity: str,
    *,
    drone_id: Optional[int] = None,
    leader_id: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = {
        "code": code,
        "message": message,
        "severity": severity,
    }
    if drone_id is not None:
        payload["drone_id"] = int(drone_id)
    if leader_id is not None:
        payload["leader_id"] = int(leader_id)
    if details:
        payload["details"] = details
    return payload


def _resolve_top_leader(drone_id: int, follow_map: Dict[int, int]) -> Tuple[Optional[int], Optional[str]]:
    current_id = int(drone_id)
    visited = set()
    while True:
        if current_id in visited:
            return None, "circular_leader_chain"
        visited.add(current_id)
        leader_id = follow_map.get(current_id)
        if leader_id is None:
            return None, "missing_swarm_assignment"
        if int(leader_id) == 0:
            return current_id, None
        current_id = int(leader_id)


def _serialize_processing_job(job_id: str) -> Dict[str, Any]:
    with _PROCESSING_JOB_LOCK:
        job = _PROCESSING_JOBS.get(job_id)
        if not job:
            raise SwarmTrajectoryError("Swarm trajectory processing job not found", status_code=404)
        return {
            "job_id": job_id,
            "status": job["status"],
            "phase": job["phase"],
            "progress_percent": job["progress_percent"],
            "message": job.get("message"),
            "result": job.get("result"),
            "error_code": job.get("error_code"),
            "error_message": job.get("error_message"),
            "cancel_requested": bool(job.get("cancel_requested")),
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
            "started_at": job.get("started_at"),
            "completed_at": job.get("completed_at"),
        }


def _update_processing_job(job_id: str, **updates: Any) -> None:
    if not job_id:
        return
    with _PROCESSING_JOB_LOCK:
        job = _PROCESSING_JOBS.get(job_id)
        if not job:
            return
        now = time.time()
        job.update(updates)
        job["updated_at"] = now
        if updates.get("status") == "running" and not job.get("started_at"):
            job["started_at"] = now
        if updates.get("status") in _PROCESSING_JOB_TERMINAL_STATES:
            job["completed_at"] = now


def _read_processed_preview_points(csv_path: Path, max_points: int) -> Tuple[List[Dict[str, Any]], int, bool, List[str]]:
    warnings: List[str] = []
    try:
        trajectory = pd.read_csv(csv_path)
    except Exception as exc:
        return [], 0, False, [f"Unable to read processed CSV: {exc}"]

    if trajectory.empty:
        return [], 0, False, ["Processed CSV is empty."]

    columns = list(trajectory.columns)
    time_col = _first_existing_column(columns, ["t", "time_s", "TimeFromStart_s", "time"])
    lat_col = _first_existing_column(columns, ["lat", "latitude", "Latitude"])
    lng_col = _first_existing_column(columns, ["lon", "lng", "longitude", "Longitude"])
    alt_col = _first_existing_column(columns, ["alt", "alt_msl", "Altitude_MSL_m", "z", "pz"])
    yaw_col = _first_existing_column(columns, ["yaw", "heading_deg", "Heading_deg", "Heading"])
    global_coordinates_available = lat_col is not None and lng_col is not None

    if not global_coordinates_available:
        warnings.append("Global latitude/longitude columns are unavailable; preview path cannot be shown on the map.")

    row_count = int(len(trajectory))
    stride = max(1, math.ceil(row_count / max(1, max_points)))
    preview_rows = trajectory.iloc[::stride].head(max_points)
    points: List[Dict[str, Any]] = []

    for sequence, (_, row) in enumerate(preview_rows.iterrows()):
        point: Dict[str, Any] = {"sequence": sequence}
        if time_col and _is_finite_number(row.get(time_col)):
            point["time_s"] = _round_metric(float(row.get(time_col)))
        if global_coordinates_available and _is_finite_number(row.get(lat_col)) and _is_finite_number(row.get(lng_col)):
            point["lat"] = float(row.get(lat_col))
            point["lng"] = float(row.get(lng_col))
        if alt_col and _is_finite_number(row.get(alt_col)):
            point["alt_msl"] = _round_metric(float(row.get(alt_col)))
        if yaw_col and _is_finite_number(row.get(yaw_col)):
            point["yaw_deg"] = _round_metric(float(row.get(yaw_col)))
        points.append(point)

    return points, row_count, global_coordinates_available, warnings


def _collect_processed_package_drone_stats(processed_dir: Path, drone_ids: List[int]) -> Dict[int, Dict]:
    stats_by_drone: Dict[int, Dict] = {}

    for drone_id in sorted(set(drone_ids)):
        file_path = processed_dir / f"Drone {drone_id}.csv"
        if not file_path.exists():
            continue

        try:
            trajectory = pd.read_csv(file_path, usecols=lambda column: column in {"t", "alt"})
        except Exception as exc:
            logger.warning("Ignoring unreadable processed trajectory %s: %s", file_path.name, exc)
            continue

        if trajectory.empty or "t" not in trajectory.columns:
            continue

        time_series = pd.to_numeric(trajectory["t"], errors="coerce").dropna()
        altitude_series = pd.to_numeric(trajectory["alt"], errors="coerce").dropna() if "alt" in trajectory.columns else pd.Series(dtype=float)

        if time_series.empty:
            continue

        route_entry_time = float(time_series.min())
        mission_clock = float(time_series.max())
        max_altitude = float(altitude_series.max()) if not altitude_series.empty else None
        min_altitude = float(altitude_series.min()) if not altitude_series.empty else None

        stats_by_drone[drone_id] = {
            "drone_id": drone_id,
            "route_entry_time_s": _round_metric(route_entry_time),
            "mission_clock_s": _round_metric(mission_clock),
            "route_motion_time_s": _round_metric(max(mission_clock - route_entry_time, 0.0)),
            "max_altitude_msl_m": _round_metric(max_altitude),
            "min_altitude_msl_m": _round_metric(min_altitude),
            "altitude_window_m": (
                _round_metric(max_altitude - min_altitude)
                if max_altitude is not None and min_altitude is not None
                else None
            ),
        }

    return stats_by_drone


def _aggregate_package_stats_from_drone_stats(drone_stats: Dict[int, Dict]) -> Dict:
    if not drone_stats:
        return _build_empty_package_stats()

    mission_clocks = [stat["mission_clock_s"] for stat in drone_stats.values() if stat.get("mission_clock_s") is not None]
    route_entries = [stat["route_entry_time_s"] for stat in drone_stats.values() if stat.get("route_entry_time_s") is not None]
    max_altitudes = [stat["max_altitude_msl_m"] for stat in drone_stats.values() if stat.get("max_altitude_msl_m") is not None]
    min_altitudes = [stat["min_altitude_msl_m"] for stat in drone_stats.values() if stat.get("min_altitude_msl_m") is not None]

    mission_clock = max(mission_clocks) if mission_clocks else None
    route_entry_time = min(route_entries) if route_entries else None
    route_motion_time = (
        max(mission_clock - route_entry_time, 0.0)
        if mission_clock is not None and route_entry_time is not None
        else None
    )
    max_altitude = max(max_altitudes) if max_altitudes else None
    min_altitude = min(min_altitudes) if min_altitudes else None

    return {
        "available": True,
        "drone_count": len(drone_stats),
        "drone_ids": sorted(drone_stats.keys()),
        "route_entry_time_s": _round_metric(route_entry_time),
        "mission_clock_s": _round_metric(mission_clock),
        "route_motion_time_s": _round_metric(route_motion_time),
        "max_altitude_msl_m": _round_metric(max_altitude),
        "min_altitude_msl_m": _round_metric(min_altitude),
        "altitude_window_m": (
            _round_metric(max_altitude - min_altitude)
            if max_altitude is not None and min_altitude is not None
            else None
        ),
    }


def validate_target_scope_for_swarm_trajectory(
    *,
    structure: Dict,
    processed_drones: List[int],
    target_drone_ids: List[int],
) -> List[Dict]:
    """
    Validate that a targeted Swarm Trajectory launch is internally safe.

    Each selected drone must:
    - belong to the current swarm configuration
    - have a processed output in the active package
    - include every required leader in its follow chain within the same target set
    """
    follow_map = _build_follow_map(structure)
    processed_set = set(processed_drones)
    active_set = {int(drone_id) for drone_id in target_drone_ids}
    issues: List[Dict] = []

    for drone_id in sorted(active_set):
        if drone_id not in follow_map:
            issues.append({
                "drone_id": drone_id,
                "issue": "missing_swarm_assignment",
            })
            continue

        if drone_id not in processed_set:
            issues.append({
                "drone_id": drone_id,
                "issue": "missing_processed_trajectory",
            })

        current_id = drone_id
        visited = {drone_id}

        while True:
            leader_id = follow_map.get(current_id)
            if leader_id is None:
                issues.append({
                    "drone_id": drone_id,
                    "issue": "missing_swarm_assignment",
                    "current_id": current_id,
                })
                break

            if leader_id == 0:
                break

            if leader_id in visited:
                issues.append({
                    "drone_id": drone_id,
                    "leader_id": leader_id,
                    "issue": "circular_leader_chain",
                })
                break

            if leader_id not in active_set:
                issues.append({
                    "drone_id": drone_id,
                    "leader_id": leader_id,
                    "issue": "leader_not_in_active_mission_set",
                })
                break

            visited.add(leader_id)
            current_id = leader_id

    return issues


def _build_cluster_status(
    structure: Dict,
    raw_leaders: List[int],
    processed_drones: List[int],
    plots_dir: Path,
    package_drone_stats: Dict[int, Dict],
) -> Tuple[List[Dict], Dict]:
    raw_leader_set = set(raw_leaders)
    processed_drone_set = set(processed_drones)
    top_leaders = structure["top_leaders"]
    clusters: List[Dict] = []
    summary = {
        "cluster_count": len(top_leaders),
        "ready_cluster_count": 0,
        "needs_processing_cluster_count": 0,
        "missing_upload_cluster_count": 0,
        "partial_output_cluster_count": 0,
        "processed_cluster_count": 0,
        "all_clusters_ready": False,
        "overall_state": "empty" if not top_leaders else "missing_uploads",
    }

    for leader_id in top_leaders:
        follower_ids = structure["hierarchies"].get(leader_id, [])
        leader_uploaded = leader_id in raw_leader_set
        leader_processed = leader_id in processed_drone_set
        processed_follower_ids = [drone_id for drone_id in follower_ids if drone_id in processed_drone_set]
        missing_follower_ids = [drone_id for drone_id in follower_ids if drone_id not in processed_drone_set]
        cluster_processed_drone_ids = ([leader_id] if leader_processed else []) + processed_follower_ids
        leader_plot_path = plots_dir / f"drone_{leader_id}_trajectory.jpg"
        cluster_plot_path = plots_dir / f"cluster_leader_{leader_id}.jpg"
        issues: List[str] = []
        advisories: List[str] = []

        if not leader_uploaded:
            state = "missing_upload"
            issues.append("Leader trajectory CSV has not been uploaded.")
            summary["missing_upload_cluster_count"] += 1
        elif not leader_processed:
            state = "needs_processing"
            issues.append("Leader CSV is uploaded, but processed outputs have not been generated yet.")
            summary["needs_processing_cluster_count"] += 1
        elif missing_follower_ids:
            state = "partial_outputs"
            issues.append(
                "One or more follower trajectories are missing from processed outputs."
            )
            summary["partial_output_cluster_count"] += 1
        else:
            state = "ready"
            summary["ready_cluster_count"] += 1

        if leader_processed:
            summary["processed_cluster_count"] += 1

        if leader_processed and not leader_plot_path.exists():
            advisories.append("Leader trajectory plot is missing.")
        if leader_processed and not cluster_plot_path.exists():
            advisories.append("Cluster formation plot is missing.")

        ready = state == "ready"
        clusters.append({
            "leader_id": leader_id,
            "follower_ids": follower_ids,
            "follower_count": len(follower_ids),
            "expected_drone_count": 1 + len(follower_ids),
            "processed_drone_count": int(leader_processed) + len(processed_follower_ids),
            "leader_uploaded": leader_uploaded,
            "leader_processed": leader_processed,
            "processed_follower_ids": processed_follower_ids,
            "missing_follower_ids": missing_follower_ids,
            "leader_plot_available": leader_plot_path.exists(),
            "cluster_plot_available": cluster_plot_path.exists(),
            "package_stats": _aggregate_package_stats_from_drone_stats({
                drone_id: package_drone_stats[drone_id]
                for drone_id in cluster_processed_drone_ids
                if drone_id in package_drone_stats
            }),
            "ready": ready,
            "state": state,
            "issues": issues,
            "advisories": advisories,
        })

    if summary["cluster_count"] == 0:
        summary["overall_state"] = "empty"
    elif summary["ready_cluster_count"] == summary["cluster_count"]:
        summary["overall_state"] = "ready"
        summary["all_clusters_ready"] = True
    elif summary["processed_cluster_count"] > 0 or summary["needs_processing_cluster_count"] > 0:
        summary["overall_state"] = "partial"
    else:
        summary["overall_state"] = "missing_uploads"

    return clusters, summary


def get_swarm_leaders_payload() -> Dict:
    structure = _load_swarm_structure()
    folders = get_swarm_trajectory_folders()
    uploaded_leaders = []

    for leader_id in structure["top_leaders"]:
        csv_path = Path(folders["raw"]) / f"Drone {leader_id}.csv"
        if csv_path.exists():
            uploaded_leaders.append(leader_id)

    return {
        "success": True,
        "leaders": structure["top_leaders"],
        "hierarchies": {key: len(value) for key, value in structure["hierarchies"].items()},
        "follower_details": structure["hierarchies"],
        "uploaded_leaders": uploaded_leaders,
        "simulation_mode": Params.sim_mode,
    }


def save_uploaded_trajectory(leader_id: int, filename: str, content: bytes) -> Dict:
    if not filename or not filename.endswith(".csv"):
        raise SwarmTrajectoryError("File must be CSV format", status_code=400)

    structure = _load_swarm_structure()
    valid_leaders = set(structure["top_leaders"])
    if leader_id not in valid_leaders:
        valid_leader_list = ", ".join(str(current_leader) for current_leader in sorted(valid_leaders)) or "none"
        raise SwarmTrajectoryError(
            f"Drone {leader_id} is not a current top-level leader. Valid leaders: {valid_leader_list}",
            status_code=400,
        )

    folders = get_swarm_trajectory_folders()
    raw_dir = Path(folders["raw"])
    raw_dir.mkdir(parents=True, exist_ok=True)
    filepath = raw_dir / f"Drone {leader_id}.csv"
    filepath.write_bytes(content)

    return {
        "success": True,
        "message": f"Drone {leader_id} trajectory uploaded successfully",
        "filepath": str(filepath),
    }


def process_trajectories_payload(force_clear: bool = False, auto_reload: bool = True) -> Dict:
    result = process_swarm_trajectories(force_clear=force_clear, auto_reload=auto_reload)
    if result.get("success"):
        return result

    raise SwarmTrajectoryError(
        str(result.get("error") or result.get("message") or "Swarm trajectory processing failed"),
        status_code=_processing_failure_status_code(result),
    )


def get_processing_recommendation_payload() -> Dict:
    recommendation = get_processing_recommendation()
    return {
        "success": True,
        "recommendation": recommendation,
    }


def get_processing_status_payload() -> Dict:
    folders = get_swarm_trajectory_folders()
    raw_dir = Path(folders["raw"])
    processed_dir = Path(folders["processed"])
    plots_dir = Path(folders["plots"])

    raw_count = len(list(raw_dir.glob("*.csv"))) if raw_dir.exists() else 0
    processed_count = len(list(processed_dir.glob("*.csv"))) if processed_dir.exists() else 0
    plot_count = len(list(plots_dir.glob("*.jpg"))) if plots_dir.exists() else 0
    raw_leaders = _collect_drone_ids(folders["raw"])
    processed_drones = _collect_drone_ids(folders["processed"])
    package_drone_stats = _collect_processed_package_drone_stats(processed_dir, processed_drones)
    package_stats = _aggregate_package_stats_from_drone_stats(package_drone_stats)

    session_manager = SwarmSessionManager()
    current_session = session_manager.get_current_session()
    processing_recommendation = session_manager.get_processing_recommendation()
    session_changes = processing_recommendation.get("changes", {})

    try:
        structure = _load_swarm_structure()
        top_leaders = structure["top_leaders"]
        follow_map = _build_follow_map(structure)
        processed_leaders = [drone_id for drone_id in processed_drones if drone_id in top_leaders]
        processed_followers = [drone_id for drone_id in processed_drones if drone_id not in top_leaders]
        clusters, cluster_summary = _build_cluster_status(
            structure=structure,
            raw_leaders=raw_leaders,
            processed_drones=processed_drones,
            plots_dir=plots_dir,
            package_drone_stats=package_drone_stats,
        )
        orphan_uploaded_leaders = [drone_id for drone_id in raw_leaders if drone_id not in top_leaders]
        missing_uploaded_leaders = [leader_id for leader_id in top_leaders if leader_id not in raw_leaders]
    except Exception as e:
        logger.warning("Could not analyze swarm structure for status: %s", e)
        processed_leaders = processed_drones
        processed_followers = []
        clusters = []
        top_leaders = []
        follow_map = {}
        orphan_uploaded_leaders = raw_leaders
        missing_uploaded_leaders = []
        package_drone_stats = {}
        package_stats = _build_empty_package_stats()
        cluster_summary = {
            "cluster_count": 0,
            "ready_cluster_count": 0,
            "needs_processing_cluster_count": 0,
            "missing_upload_cluster_count": 0,
            "partial_output_cluster_count": 0,
            "processed_cluster_count": 0,
            "all_clusters_ready": False,
            "overall_state": "unknown",
        }

    return {
        "success": True,
        "status": {
            "raw_trajectories": raw_count,
            "processed_trajectories": processed_count,
            "generated_plots": plot_count,
            "raw_leaders": raw_leaders,
            "processed_drones": processed_drones,
            "processed_leaders": processed_leaders,
            "processed_followers": processed_followers,
            "follow_map": follow_map,
            "leader_count": len(processed_leaders),
            "follower_count": len(processed_followers),
            "package_stats": package_stats,
            "package_drone_stats": package_drone_stats,
            "has_results": processed_count > 0,
            "plots_available": plot_count > 0,
            "expected_top_leaders": top_leaders,
            "uploaded_leaders": raw_leaders,
            "missing_uploaded_leaders": missing_uploaded_leaders,
            "orphan_uploaded_leaders": orphan_uploaded_leaders,
            "clusters": clusters,
            "cluster_summary": cluster_summary,
            "session": {
                "exists": current_session is not None,
                "session_id": current_session.session_id if current_session else None,
                "timestamp": current_session.timestamp if current_session else None,
                "processed_leaders": current_session.processed_leaders if current_session else [],
                "total_drones": current_session.total_drones if current_session else 0,
            },
            "session_changes": session_changes,
            "processing_recommendation": processing_recommendation,
        },
        "folders": folders,
    }


def get_validation_payload() -> Dict:
    status_payload = get_processing_status_payload()
    status = status_payload["status"]
    blockers: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    advisories: List[Dict[str, Any]] = []

    processed_drone_ids = sorted(int(drone_id) for drone_id in status.get("processed_drones", []))
    follow_map = {
        int(drone_id): int(leader_id)
        for drone_id, leader_id in (status.get("follow_map") or {}).items()
    }
    expected_drone_ids = sorted(follow_map.keys())
    missing_drone_ids = sorted(set(expected_drone_ids) - set(processed_drone_ids))
    cluster_summary = status.get("cluster_summary") or {}
    workspace_state = cluster_summary.get("overall_state") or "unknown"

    if workspace_state == "unknown":
        blockers.append(_swarm_issue(
            "swarm_trajectory_swarm_structure_unavailable",
            "Swarm structure could not be analyzed. Check the swarm configuration before preview, commit, or transfer.",
            "blocker",
        ))
    elif status.get("has_results") and int(cluster_summary.get("cluster_count") or 0) == 0:
        blockers.append(_swarm_issue(
            "swarm_trajectory_no_swarm_clusters",
            "Processed outputs exist, but the current swarm configuration has no valid leader clusters.",
            "blocker",
        ))

    if not status.get("has_results"):
        blockers.append(_swarm_issue(
            "swarm_trajectory_no_processed_outputs",
            "No processed Swarm Trajectory package is available. Process leader uploads before preview, commit, or transfer.",
            "blocker",
        ))

    for cluster in status.get("clusters") or []:
        leader_id = cluster.get("leader_id")
        if not cluster.get("ready"):
            state = cluster.get("state") or "unknown"
            severity = "blocker" if state in {"missing_upload", "needs_processing", "partial_outputs"} else "warning"
            target = blockers if severity == "blocker" else warnings
            target.append(_swarm_issue(
                f"swarm_trajectory_cluster_{state}",
                f"Cluster {leader_id} is not ready: {state.replace('_', ' ')}.",
                severity,
                leader_id=leader_id,
                details={
                    "missing_follower_ids": cluster.get("missing_follower_ids") or [],
                    "processed_follower_ids": cluster.get("processed_follower_ids") or [],
                    "processed_drone_count": cluster.get("processed_drone_count"),
                    "expected_drone_count": cluster.get("expected_drone_count"),
                },
            ))

        for issue in cluster.get("issues") or []:
            blockers.append(_swarm_issue(
                "swarm_trajectory_cluster_issue",
                str(issue),
                "blocker",
                leader_id=leader_id,
            ))

        for advisory in cluster.get("advisories") or []:
            advisories.append(_swarm_issue(
                "swarm_trajectory_cluster_advisory",
                str(advisory),
                "advisory",
                leader_id=leader_id,
            ))

    session_changes = status.get("session_changes") or {}
    if session_changes.get("requires_full_reprocess"):
        blockers.append(_swarm_issue(
            "swarm_trajectory_reprocess_required",
            "The saved processing session is stale. Reprocess the package before commit or transfer.",
            "blocker",
            details=session_changes,
        ))
    elif session_changes.get("has_previous_session") and not session_changes.get("safe_to_incremental", True):
        warnings.append(_swarm_issue(
            "swarm_trajectory_session_review_required",
            "Processing session changes require operator review before committing outputs.",
            "warning",
            details=session_changes,
        ))

    if missing_drone_ids:
        blockers.append(_swarm_issue(
            "swarm_trajectory_missing_processed_drones",
            f"Processed outputs are missing for drones: {missing_drone_ids}.",
            "blocker",
            details={"missing_drone_ids": missing_drone_ids},
        ))

    package_stats = status.get("package_stats") or {}
    if status.get("has_results") and not package_stats.get("available"):
        warnings.append(_swarm_issue(
            "swarm_trajectory_package_stats_unavailable",
            "Processed package timing/altitude statistics are unavailable.",
            "warning",
        ))

    if status.get("has_results") and not status.get("plots_available"):
        warnings.append(_swarm_issue(
            "swarm_trajectory_plots_unavailable",
            "Processed path plots are unavailable; use the map preview and regenerate plots when needed.",
            "warning",
        ))

    orphan_uploaded_leaders = status.get("orphan_uploaded_leaders") or []
    if orphan_uploaded_leaders:
        warnings.append(_swarm_issue(
            "swarm_trajectory_orphan_uploads",
            "One or more uploaded leader CSV files are not part of the current swarm configuration.",
            "warning",
            details={"orphan_uploaded_leaders": orphan_uploaded_leaders},
        ))

    for drone_id, stats in (status.get("package_drone_stats") or {}).items():
        if stats.get("max_altitude_msl_m") is None or stats.get("min_altitude_msl_m") is None:
            warnings.append(_swarm_issue(
                "swarm_trajectory_altitude_stats_unavailable",
                f"Altitude statistics are unavailable for drone {drone_id}.",
                "warning",
                drone_id=int(drone_id),
            ))

    return {
        "success": True,
        "ready": len(blockers) == 0,
        "state": workspace_state,
        "blockers": blockers,
        "warnings": warnings,
        "advisories": advisories,
        "processed_drone_ids": processed_drone_ids,
        "expected_drone_ids": expected_drone_ids,
        "missing_drone_ids": missing_drone_ids,
        "cluster_summary": cluster_summary,
        "package_stats": package_stats,
    }


def get_preview_payload(max_points_per_drone: int = 500) -> Dict:
    status_payload = get_processing_status_payload()
    status = status_payload["status"]
    validation = get_validation_payload()
    processed_dir = Path(status_payload["folders"]["processed"])
    processed_drone_ids = sorted(int(drone_id) for drone_id in status.get("processed_drones", []))
    follow_map = {
        int(drone_id): int(leader_id)
        for drone_id, leader_id in (status.get("follow_map") or {}).items()
    }
    package_drone_stats = status.get("package_drone_stats") or {}
    drones: List[Dict[str, Any]] = []

    for drone_id in processed_drone_ids:
        csv_path = processed_dir / f"Drone {drone_id}.csv"
        points, row_count, global_available, preview_warnings = _read_processed_preview_points(
            csv_path,
            max_points=max_points_per_drone,
        )
        direct_leader_id = follow_map.get(drone_id)
        top_leader_id, leader_error = _resolve_top_leader(drone_id, follow_map)
        role = "leader" if direct_leader_id == 0 else "follower" if direct_leader_id is not None else "unknown"
        if leader_error:
            preview_warnings.append(f"Leader relationship issue: {leader_error}.")

        drones.append({
            "drone_id": drone_id,
            "role": role,
            "top_leader_id": top_leader_id,
            "direct_leader_id": direct_leader_id if direct_leader_id not in (None, 0) else None,
            "point_count": row_count,
            "preview_point_count": len(points),
            "global_coordinates_available": global_available,
            "points": points,
            "warnings": preview_warnings,
            "package_stats": package_drone_stats.get(str(drone_id)) or package_drone_stats.get(drone_id),
        })

    clusters = []
    processed_set = set(processed_drone_ids)
    for cluster in status.get("clusters") or []:
        leader_id = int(cluster.get("leader_id"))
        expected_ids = [leader_id] + [int(value) for value in cluster.get("follower_ids", [])]
        clusters.append({
            "leader_id": leader_id,
            "drone_ids": [drone_id for drone_id in expected_ids if drone_id in processed_set],
            "expected_drone_ids": expected_ids,
            "ready": bool(cluster.get("ready")),
            "state": cluster.get("state") or "unknown",
            "issues": cluster.get("issues") or [],
            "advisories": cluster.get("advisories") or [],
        })

    return {
        "success": True,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "drones": drones,
        "clusters": clusters,
        "summary": {
            "processed_drone_count": len(processed_drone_ids),
            "cluster_summary": status.get("cluster_summary") or {},
            "package_stats": status.get("package_stats") or _build_empty_package_stats(),
            "has_results": bool(status.get("has_results")),
            "global_preview_drone_count": sum(1 for drone in drones if drone["global_coordinates_available"]),
        },
        "blockers": validation["blockers"],
        "warnings": validation["warnings"],
        "advisories": validation["advisories"],
    }


def get_elevation_batch_payload(
    points: List[Dict[str, Any]],
    elevation_provider: Optional[Callable[[float, float], Optional[Dict[str, Any]]]],
) -> Dict:
    results: List[Dict[str, Any]] = []

    for point in points:
        lat = float(point["lat"])
        lng = float(point["lng"])
        result = {
            "id": point.get("id"),
            "lat": lat,
            "lng": lng,
            "elevation_m": None,
            "status": "unavailable",
            "source": "unavailable",
            "provider": "unavailable",
            "confidence": "none",
            "message": "Elevation provider is unavailable.",
            "sample_time": None,
        }

        if elevation_provider is not None:
            try:
                elevation_data = elevation_provider(lat, lng)
                normalized = _normalize_elevation_payload(elevation_data)
                if normalized["status"] == "ok":
                    result.update({
                        "elevation_m": normalized["elevation_m"],
                        "status": "ok",
                        "source": normalized["source"],
                        "provider": normalized["provider"],
                        "confidence": normalized["confidence"],
                        "message": normalized["message"],
                        "sample_time": normalized["sample_time"],
                    })
                else:
                    result.update({
                        "source": normalized["source"],
                        "provider": normalized["provider"],
                        "confidence": normalized["confidence"],
                        "message": normalized["message"],
                        "sample_time": normalized["sample_time"],
                    })
            except Exception as exc:
                result["message"] = f"Elevation lookup failed: {exc}"

        results.append(result)

    resolved = sum(1 for item in results if item["status"] == "ok")
    return {
        "success": True,
        "results": results,
        "summary": {
            "requested": len(points),
            "resolved": resolved,
            "unavailable": len(points) - resolved,
            "status": "ok" if resolved == len(points) else "partial" if resolved else "unavailable",
        },
    }


def create_processing_job_payload(force_clear: bool = False, auto_reload: bool = True) -> Dict:
    job_id = str(uuid.uuid4())
    now = time.time()
    with _PROCESSING_JOB_LOCK:
        _PROCESSING_JOBS[job_id] = {
            "status": "queued",
            "phase": "queued",
            "progress_percent": 0,
            "message": "Queued Swarm Trajectory processing job.",
            "cancel_requested": False,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "completed_at": None,
            "result": None,
        }

    def _run_job() -> None:
        with _PROCESSING_JOB_LOCK:
            job = _PROCESSING_JOBS.get(job_id)
            if not job:
                return
            if job.get("cancel_requested"):
                job.update({
                    "status": "canceled",
                    "phase": "canceled",
                    "progress_percent": 0,
                    "message": "Processing canceled before start.",
                    "updated_at": time.time(),
                    "completed_at": time.time(),
                })
                return

        _update_processing_job(
            job_id,
            status="running",
            phase="processing",
            progress_percent=20,
            message="Processing leader/follower trajectories.",
        )
        try:
            result = process_trajectories_payload(force_clear=force_clear, auto_reload=auto_reload)
            _update_processing_job(
                job_id,
                status="succeeded",
                phase="complete",
                progress_percent=100,
                message=result.get("message") or "Swarm Trajectory processing complete.",
                result=result,
            )
        except SwarmTrajectoryError as exc:
            _update_processing_job(
                job_id,
                status="failed",
                phase="failed",
                progress_percent=100,
                error_code="swarm_trajectory_processing_failed",
                error_message=exc.message,
                message=exc.message,
            )
        except Exception as exc:
            logger.error("Swarm Trajectory processing job failed: %s", exc, exc_info=True)
            _update_processing_job(
                job_id,
                status="failed",
                phase="failed",
                progress_percent=100,
                error_code="swarm_trajectory_internal_error",
                error_message=str(exc),
                message="Swarm Trajectory processing failed.",
            )

    future = _PROCESSING_JOB_EXECUTOR.submit(_run_job)
    with _PROCESSING_JOB_LOCK:
        _PROCESSING_JOBS[job_id]["future"] = future
    return _serialize_processing_job(job_id)


def get_processing_job_payload(job_id: str) -> Dict:
    return _serialize_processing_job(job_id)


def cancel_processing_job_payload(job_id: str) -> Dict:
    terminal = False
    with _PROCESSING_JOB_LOCK:
        job = _PROCESSING_JOBS.get(job_id)
        if not job:
            raise SwarmTrajectoryError("Swarm trajectory processing job not found", status_code=404)
        if job["status"] in _PROCESSING_JOB_TERMINAL_STATES:
            terminal = True
            future = None
        else:
            job["cancel_requested"] = True
            future = job.get("future")

    if terminal:
        return _serialize_processing_job(job_id)

    if future and future.cancel():
        _update_processing_job(
            job_id,
            status="canceled",
            phase="canceled",
            message="Processing canceled before execution.",
        )
    else:
        _update_processing_job(
            job_id,
            message="Cancellation requested. The active processor cannot be interrupted safely; wait for terminal status.",
        )

    return _serialize_processing_job(job_id)


def clear_processed_payload() -> Dict:
    result = clear_processed_data()
    if result.get("success"):
        return result

    raise SwarmTrajectoryError(
        str(result.get("error") or result.get("message") or "Failed to clear processed swarm trajectory data"),
        status_code=500,
    )


def clear_all_payload() -> Dict:
    project_root = Path(get_project_root())
    cleared_items: List[str] = []

    for sim_mode in (False, True):
        folders = get_swarm_trajectory_folders(sim_mode=sim_mode)
        base_dir = Path(folders["base"])
        session_file = base_dir / ".trajectory_session.json"

        for key in ("raw", "processed", "plots"):
            directory = Path(folders[key])
            if not directory.exists():
                continue

            files = [path for path in directory.iterdir() if path.is_file()]
            if not files:
                continue

            for file_path in files:
                file_path.unlink()
                cleared_items.append(str(file_path.relative_to(project_root)))

        _clear_session_file(session_file, cleared_items)

        swarm_traj_dir = base_dir / "swarm_trajectory"
        if not swarm_traj_dir.exists():
            continue

        for file_path in swarm_traj_dir.rglob("*"):
            if not file_path.is_file():
                continue

            lower_name = file_path.name.lower()
            if file_path.suffix.lower() in {".csv", ".jpg", ".png", ".kml"} or "trajectory" in lower_name or "cluster" in lower_name:
                file_path.unlink()
                cleared_items.append(str(file_path.relative_to(project_root)))

    if not cleared_items:
        return {
            "success": True,
            "message": "No swarm trajectory files were present to clear",
            "cleared_directories": [],
        }

    return {
        "success": True,
        "message": f"All trajectory files cleared successfully from {len(cleared_items)} locations",
        "cleared_directories": cleared_items,
    }


def remove_leader_trajectory_payload(leader_id: int) -> Dict:
    folders = get_swarm_trajectory_folders()
    structure = _load_swarm_structure()
    cluster_drones = [leader_id] + structure["hierarchies"].get(leader_id, [])
    removed_files: List[str] = []

    raw_dir = Path(folders["raw"])
    processed_dir = Path(folders["processed"])
    plots_dir = Path(folders["plots"])

    _remove_file(raw_dir / f"Drone {leader_id}.csv", removed_files, f"raw/Drone {leader_id}.csv")

    for drone_id in cluster_drones:
        _remove_file(
            processed_dir / f"Drone {drone_id}.csv",
            removed_files,
            f"processed/Drone {drone_id}.csv",
        )
        _remove_file(
            plots_dir / f"drone_{drone_id}_trajectory.jpg",
            removed_files,
            f"plots/drone_{drone_id}_trajectory.jpg",
        )

    _remove_file(
        plots_dir / f"cluster_leader_{leader_id}.jpg",
        removed_files,
        f"plots/cluster_leader_{leader_id}.jpg",
    )
    _remove_file(
        plots_dir / "combined_swarm.jpg",
        removed_files,
        "plots/combined_swarm.jpg",
    )

    if not removed_files:
        raise SwarmTrajectoryError(f"No trajectory files found for Drone {leader_id}", status_code=404)

    _clear_current_session()

    message = f"Removed trajectory for Drone {leader_id}"
    related_count = len(removed_files) - 1
    if related_count > 0:
        message += f" and {related_count} related file(s)"

    return {
        "success": True,
        "message": message,
        "removed_files": removed_files,
        "files_removed": len(removed_files),
    }


def clear_leader_trajectory_payload(leader_id: int) -> Dict:
    result = remove_leader_trajectory_payload(leader_id)
    return {
        "success": True,
        "message": f"Drone {leader_id} and associated trajectories cleared successfully",
        "removed_files": result["removed_files"],
    }


def get_processed_trajectory_download(drone_id: int) -> Tuple[str, str]:
    folders = get_swarm_trajectory_folders()
    file_path = Path(folders["processed"]) / f"Drone {drone_id}.csv"

    if not file_path.exists():
        raise SwarmTrajectoryError(f"Trajectory for drone {drone_id} not found", status_code=404)

    return str(file_path), f"Drone {drone_id}_trajectory.csv"


def get_drone_kml_download(drone_id: int) -> Tuple[bytes, str]:
    folders = get_swarm_trajectory_folders()
    csv_path = Path(folders["processed"]) / f"Drone {drone_id}.csv"

    if not csv_path.exists():
        raise SwarmTrajectoryError(
            f"Processed trajectory for Drone {drone_id} not found. Make sure trajectory processing has been completed.",
            status_code=404,
        )

    trajectory_df = pd.read_csv(csv_path)
    required_columns = {"t", "lat", "lon", "alt"}
    if not required_columns.issubset(set(trajectory_df.columns)):
        raise SwarmTrajectoryError(f"Invalid trajectory data for Drone {drone_id}", status_code=400)

    with tempfile.TemporaryDirectory() as temp_dir:
        kml_path = generate_kml_for_drone(drone_id, trajectory_df, temp_dir)
        content = Path(kml_path).read_bytes()

    return content, f"Drone {drone_id}_trajectory.kml"


def get_cluster_kml_download(leader_id: int) -> Tuple[bytes, str]:
    folders = get_swarm_trajectory_folders()
    structure = _load_swarm_structure()

    if leader_id not in structure["top_leaders"]:
        raise SwarmTrajectoryError(f"Drone {leader_id} is not a cluster leader", status_code=400)

    cluster_drones = [leader_id] + structure["hierarchies"].get(leader_id, [])
    missing_drones = []
    for drone_id in cluster_drones:
        csv_path = Path(folders["processed"]) / f"Drone {drone_id}.csv"
        if not csv_path.exists():
            missing_drones.append(drone_id)

    if missing_drones:
        raise SwarmTrajectoryError(
            f"Missing processed trajectories for drones: {missing_drones}",
            status_code=404,
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        kml_path = generate_cluster_kml(leader_id, cluster_drones, folders["processed"], temp_dir)
        content = Path(kml_path).read_bytes()

    return content, f"Cluster_Leader_{leader_id}.kml"


def clear_individual_drone_payload(drone_id: int) -> Dict:
    swarm_data = fetch_swarm_data()
    swarm_df = pd.DataFrame(swarm_data)
    if not swarm_df.empty:
        swarm_df["hw_id"] = pd.to_numeric(swarm_df["hw_id"], errors="coerce")
        swarm_df["follow"] = pd.to_numeric(swarm_df["follow"], errors="coerce")
        swarm_df = swarm_df.dropna(subset=["hw_id", "follow"])

        top_leaders = set(swarm_df[swarm_df["follow"] == 0]["hw_id"].astype(int).tolist())
        if drone_id in top_leaders:
            raise SwarmTrajectoryError(
                f"Drone {drone_id} is a leader. Use the cluster clear action instead.",
                status_code=400,
            )
    else:
        swarm_df = pd.DataFrame(columns=["hw_id", "follow"])

    folders = get_swarm_trajectory_folders()
    processed_dir = Path(folders["processed"])
    plots_dir = Path(folders["plots"])
    removed_files: List[str] = []

    _remove_file(
        processed_dir / f"Drone {drone_id}.csv",
        removed_files,
        f"processed/Drone {drone_id}.csv",
    )
    _remove_file(
        plots_dir / f"drone_{drone_id}_trajectory.jpg",
        removed_files,
        f"plots/drone_{drone_id}_trajectory.jpg",
    )

    if not swarm_df.empty:
        try:
            leader_id = int(find_ultimate_leader(drone_id, swarm_df))
        except Exception:
            leader_id = None
    else:
        leader_id = None

    if leader_id is not None:
        _remove_file(
            plots_dir / f"cluster_leader_{leader_id}.jpg",
            removed_files,
            f"plots/cluster_leader_{leader_id}.jpg",
        )

    _remove_file(
        plots_dir / "combined_swarm.jpg",
        removed_files,
        "plots/combined_swarm.jpg",
    )

    if not removed_files:
        raise SwarmTrajectoryError(f"No trajectory files found for Drone {drone_id}", status_code=404)

    _clear_current_session()

    return {
        "success": True,
        "message": f"Drone {drone_id} trajectory files removed successfully",
        "removed_files": removed_files,
    }


def commit_trajectory_changes_payload(commit_message: str | None = None) -> Dict:
    message = commit_message or f"Swarm trajectory update - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    git_result = git_operations(get_project_root(), message)

    if git_result.get("success"):
        return {
            "success": True,
            "message": "Trajectory changes committed and pushed successfully",
            "git_info": git_result,
        }

    return {
        "success": False,
        "error": git_result.get("message", "Git operations failed"),
        "git_info": git_result,
    }
