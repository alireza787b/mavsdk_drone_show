"""
Swarm trajectory service helpers shared by the FastAPI surface.
"""

from __future__ import annotations

import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

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


class SwarmTrajectoryError(Exception):
    """Typed exception for API-friendly swarm trajectory failures."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


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
    return process_swarm_trajectories(force_clear=force_clear, auto_reload=auto_reload)


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

    try:
        structure = _load_swarm_structure()
        top_leaders = structure["top_leaders"]
        processed_leaders = [drone_id for drone_id in processed_drones if drone_id in top_leaders]
        processed_followers = [drone_id for drone_id in processed_drones if drone_id not in top_leaders]
        processed_drone_set = set(processed_drones)
        raw_leader_set = set(raw_leaders)
        clusters = []

        for leader_id in top_leaders:
            follower_ids = structure["hierarchies"].get(leader_id, [])
            processed_follower_ids = [drone_id for drone_id in follower_ids if drone_id in processed_drone_set]
            missing_follower_ids = [drone_id for drone_id in follower_ids if drone_id not in processed_drone_set]
            leader_plot_path = plots_dir / f"drone_{leader_id}_trajectory.jpg"
            cluster_plot_path = plots_dir / f"cluster_leader_{leader_id}.jpg"

            clusters.append({
                "leader_id": leader_id,
                "follower_ids": follower_ids,
                "follower_count": len(follower_ids),
                "leader_uploaded": leader_id in raw_leader_set,
                "leader_processed": leader_id in processed_drone_set,
                "processed_follower_ids": processed_follower_ids,
                "missing_follower_ids": missing_follower_ids,
                "leader_plot_available": leader_plot_path.exists(),
                "cluster_plot_available": cluster_plot_path.exists(),
                "ready": (
                    leader_id in raw_leader_set
                    and leader_id in processed_drone_set
                    and not missing_follower_ids
                ),
            })
    except Exception as e:
        logger.warning("Could not analyze swarm structure for status: %s", e)
        processed_leaders = processed_drones
        processed_followers = []
        clusters = []

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
            "leader_count": len(processed_leaders),
            "follower_count": len(processed_followers),
            "has_results": processed_count > 0,
            "plots_available": plot_count > 0,
            "clusters": clusters,
        },
        "folders": folders,
    }


def clear_processed_payload() -> Dict:
    return clear_processed_data()


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
