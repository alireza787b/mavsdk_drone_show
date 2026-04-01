"""
Swarm Trajectory Utilities
Common utilities for swarm trajectory processing
"""

from pathlib import Path

from src.params import Params


def get_project_root(base_dir=None):
    """Return the repository root independent of the current working directory."""
    if base_dir is not None:
        return str(Path(base_dir).resolve())

    return str(Path(__file__).resolve().parents[1])


def get_swarm_trajectory_folders(sim_mode=None, base_dir=None):
    """Get swarm trajectory directories for the requested mode."""
    use_sim_mode = Params.sim_mode if sim_mode is None else sim_mode
    shared_dir = getattr(Params, "SWARM_TRAJECTORY_SHARED_DIR", "").strip()

    if use_sim_mode and shared_dir:
        base_path = Path(shared_dir).resolve()
    else:
        root_dir = get_project_root(base_dir=base_dir)
        base_folder = 'shapes_sitl' if use_sim_mode else 'shapes'
        base_path = Path(root_dir) / base_folder / 'swarm_trajectory'

    return {
        'base': str(base_path),
        'raw': str(base_path / 'raw'),
        'processed': str(base_path / 'processed'),
        'plots': str(base_path / 'plots'),
    }
