# gcs-server/git_status.py
"""
Git Status Data Store
=====================
Shared data structures for drone git status polling.

The actual polling is done by BackgroundServices._poll_git_status() in app_fastapi.py.
This module provides:
- Thread-safe shared data store (git_status_data_all_drones)
- check_git_sync_status() for comparing drone commits against GCS
"""

import sys
import threading
import time
from typing import Dict, Any

# Thread-safe data structures (written by app_fastapi.py BackgroundServices, read by endpoints)
git_status_data_all_drones: Dict[str, Dict[str, Any]] = {}
data_lock_git_status = threading.Lock()


def tracking_count(report: dict, field: str) -> int:
    """Read a Git ahead/behind count, using -1 for a malformed observation."""
    value = report.get(field, 0)  # Older companions omit zero counters.
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        try:
            return int(value)
        except ValueError:
            pass
    return -1


def commits_match(left_commit: str, right_commit: str) -> bool:
    """Treat matching short/full SHAs as equivalent when one is a prefix."""
    left = str(left_commit or "").strip().lower()
    right = str(right_commit or "").strip().lower()
    if not left or not right or left == "unknown" or right == "unknown":
        return False
    if left == right:
        return True
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    return len(shorter) >= 7 and longer.startswith(shorter)


def check_git_sync_status():
    """
    Check if all drones are on the same git commit and branch,
    and also compare each drone's commit against the GCS commit (source of truth).

    Returns dict with sync status information.
    """
    from config import get_gcs_git_report

    branches = {}
    commits = {}
    drones_out_of_sync_with_gcs = []

    # Get GCS commit as source of truth
    gcs_commit = None
    try:
        gcs_report = get_gcs_git_report()
        gcs_commit = gcs_report.get('commit', None)
    except Exception:
        pass

    with data_lock_git_status:
        for drone_id, git_data in git_status_data_all_drones.items():
            if git_data:  # Only check drones with valid git data
                branch = git_data.get('branch', 'unknown')
                commit = git_data.get('commit', 'unknown')

                if branch not in branches:
                    branches[branch] = []
                branches[branch].append(drone_id)

                if commit not in commits:
                    commits[commit] = []
                commits[commit].append(drone_id)

                # Compare against GCS commit
                if gcs_commit and commit != 'unknown' and not commits_match(commit, gcs_commit):
                    drones_out_of_sync_with_gcs.append(drone_id)

    # Determine sync status
    branch_count = len(branches)
    commit_count = len(commits)

    is_branch_synced = branch_count <= 1
    is_commit_synced = commit_count <= 1
    is_synced_with_gcs = len(drones_out_of_sync_with_gcs) == 0

    sync_status = {
        'is_fully_synced': is_branch_synced and is_commit_synced and is_synced_with_gcs,
        'is_branch_synced': is_branch_synced,
        'is_commit_synced': is_commit_synced,
        'is_synced_with_gcs': is_synced_with_gcs,
        'gcs_commit': gcs_commit[:8] if gcs_commit else None,
        'drones_out_of_sync_with_gcs': drones_out_of_sync_with_gcs,
        'branch_distribution': branches,
        'commit_distribution': commits,
        'total_active_drones': sum(len(drone_list) for drone_list in branches.values())
    }

    return sync_status


# Standalone test mode
if __name__ == "__main__":
    from config import load_config
    from mds_logging.server import init_server_logging

    init_server_logging()

    drones = load_config()
    if not drones:
        print("No drones found in configuration!")
        sys.exit(1)

    print(f"Checking git sync status for {len(drones)} configured drones...")
    sync_status = check_git_sync_status()
    print(f"Fully synced: {sync_status['is_fully_synced']}")
    print(f"Branch distribution: {sync_status['branch_distribution']}")
    print(f"Commit distribution: {sync_status['commit_distribution']}")
    if sync_status['drones_out_of_sync_with_gcs']:
        print(f"Drones out of sync with GCS: {sync_status['drones_out_of_sync_with_gcs']}")
