"""
Swarm Trajectory Utilities
Common utilities for swarm trajectory processing
"""

import os
from src.params import Params

def get_swarm_trajectory_folders():
    """Get folder paths following existing pattern"""
    # Get the root project directory (parent of current working directory if in gcs-server)
    current_dir = os.getcwd()
    if current_dir.endswith('gcs-server'):
        root_dir = os.path.dirname(current_dir)
    else:
        root_dir = current_dir

    base_folder = 'shapes_sitl' if Params.sim_mode else 'shapes'
    base_path = os.path.join(root_dir, base_folder)

    return {
        'base': base_path,
        'raw': os.path.join(base_path, 'swarm_trajectory', 'raw'),
        'processed': os.path.join(base_path, 'swarm_trajectory', 'processed'),
        'plots': os.path.join(base_path, 'swarm_trajectory', 'plots')
    }