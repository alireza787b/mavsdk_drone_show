# functions/git_manager.py
"""
Git Manager Module
==================
Centralized Git operations for the MAVSDK Drone Show project.

This module provides:
- Local Git status retrieval (GCS machine)
- Remote Git status fetching (from drones via HTTP)
- Git command execution utilities

All Git operations should use these functions to ensure consistent
error handling and logging across the codebase.
"""

import subprocess
import logging
import requests
from typing import Dict, Any, Optional
from src.drone_api_routes import DRONE_GIT_STATUS_ROUTE

logger = logging.getLogger(__name__)

IGNORED_UNCOMMITTED_PATHS = {
    '.mds_sitl_image_build.env',
    '.mds_px4_source_provenance.env',
    '.mds_px4_submodules.txt',
}


def filter_git_status_lines(status_lines: list[str]) -> list[str]:
    """Remove generated runtime metadata that should not mark the repo dirty."""
    filtered_lines: list[str] = []

    for line in status_lines:
        if not line:
            continue

        path = line[3:].strip() if len(line) >= 4 else line.strip()
        if path in IGNORED_UNCOMMITTED_PATHS:
            continue

        filtered_lines.append(line)

    return filtered_lines


def parse_filtered_git_status(status_output: Optional[str]) -> list[str]:
    """Parse porcelain output and drop generated metadata noise."""
    if not status_output:
        return []
    return filter_git_status_lines(status_output.splitlines())


# ============================================================================
# Local Git Operations (for GCS machine)
# ============================================================================

def execute_git_command(command: list, cwd: Optional[str] = None) -> Optional[str]:
    """
    Execute a git command and return the output.

    Args:
        command: Git command as a list (e.g., ['git', 'status'])
        cwd: Optional working directory for the command

    Returns:
        Command output as string, or None on error
    """
    try:
        result = subprocess.check_output(
            command,
            cwd=cwd,
            stderr=subprocess.DEVNULL
        ).strip().decode('utf-8')
        return result
    except subprocess.CalledProcessError as e:
        logger.debug(f"Git command failed: {command} - {e}")
        return None
    except Exception as e:
        logger.error(f"Error executing git command {command}: {e}")
        return None


def get_local_git_report(repo_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Get comprehensive Git status of the local repository.

    Args:
        repo_path: Optional path to the git repository. Uses current dir if not specified.

    Returns:
        Dictionary with git status information including:
        - branch: Current branch name
        - commit: Current commit hash
        - author_name: Commit author name
        - author_email: Commit author email
        - commit_date: Commit date (ISO format)
        - commit_message: Commit message
        - remote_url: Remote origin URL
        - tracking_branch: Upstream tracking branch
        - status: 'clean' or 'dirty'
        - uncommitted_changes: List of uncommitted changes
        Or {'error': message} on failure
    """
    try:
        # Get current branch
        branch = execute_git_command(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=repo_path)
        if not branch:
            return {'error': 'Failed to get current branch'}

        # Get current commit hash
        commit = execute_git_command(['git', 'rev-parse', 'HEAD'], cwd=repo_path)
        if not commit:
            return {'error': 'Failed to get commit hash'}

        # Get commit details
        author_name = execute_git_command(
            ['git', 'show', '-s', '--format=%an', commit], cwd=repo_path
        ) or 'Unknown'

        author_email = execute_git_command(
            ['git', 'show', '-s', '--format=%ae', commit], cwd=repo_path
        ) or 'Unknown'

        commit_date = execute_git_command(
            ['git', 'show', '-s', '--format=%cd', '--date=iso-strict', commit], cwd=repo_path
        ) or ''

        commit_message = execute_git_command(
            ['git', 'show', '-s', '--format=%B', commit], cwd=repo_path
        ) or ''

        # Get remote info
        remote_url = execute_git_command(
            ['git', 'config', '--get', 'remote.origin.url'], cwd=repo_path
        ) or ''

        tracking_branch = execute_git_command(
            ['git', 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}'], cwd=repo_path
        ) or ''

        # Get working tree status
        status_output = execute_git_command(
            ['git', 'status', '--porcelain'], cwd=repo_path
        ) or ''
        filtered_changes = parse_filtered_git_status(status_output)

        return {
            'branch': branch,
            'commit': commit,
            'author_name': author_name,
            'author_email': author_email,
            'commit_date': commit_date,
            'commit_message': commit_message.strip(),
            'remote_url': remote_url,
            'tracking_branch': tracking_branch,
            'status': 'clean' if not filtered_changes else 'dirty',
            'uncommitted_changes': filtered_changes,
        }

    except Exception as e:
        logger.error(f"Failed to get Git status: {e}")
        return {'error': f"Git command failed: {str(e)}"}


def get_local_git_short_status(repo_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Get abbreviated Git status for quick checks.

    Args:
        repo_path: Optional path to the git repository

    Returns:
        Dictionary with minimal git info:
        - branch: Current branch name
        - commit_short: Short commit hash (7 chars)
        - status: 'clean' or 'dirty'
    """
    try:
        branch = execute_git_command(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=repo_path
        )
        commit = execute_git_command(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=repo_path
        )
        status_output = execute_git_command(
            ['git', 'status', '--porcelain'], cwd=repo_path
        )
        filtered_changes = parse_filtered_git_status(status_output)

        return {
            'branch': branch or 'unknown',
            'commit_short': commit or 'unknown',
            'status': 'clean' if not filtered_changes else 'dirty'
        }
    except Exception as e:
        return {'error': str(e)}


# ============================================================================
# Remote Git Operations (for fetching drone git status via HTTP)
# ============================================================================

def get_remote_git_status(
    drone_uri: str,
    timeout: float = 5.0
) -> Dict[str, Any]:
    """
    Fetch Git status from a remote drone via HTTP.

    Args:
        drone_uri: Base URI of the drone (e.g., 'http://192.168.1.101:7070')
        timeout: Request timeout in seconds

    Returns:
        Dictionary with git status from drone, or {'error': message} on failure
    """
    endpoint = f"{drone_uri}{DRONE_GIT_STATUS_ROUTE}"

    try:
        logger.debug(f"Fetching git status from {endpoint}")
        response = requests.get(endpoint, timeout=timeout)

        if response.status_code == 200:
            try:
                data = response.json()
                logger.debug(f"Git status response from {drone_uri}: {data}")
                return data
            except ValueError as e:
                logger.error(f"Failed to decode JSON from {drone_uri}: {e}")
                return {'error': 'Failed to decode JSON from response'}
        else:
            logger.warning(f"Git status request to {drone_uri} returned {response.status_code}")
            return {'error': f"HTTP {response.status_code} from {drone_uri}"}

    except requests.Timeout:
        logger.warning(f"Timeout fetching git status from {drone_uri}")
        return {'error': f"Timeout connecting to {drone_uri}"}
    except requests.ConnectionError as e:
        logger.debug(f"Connection error to {drone_uri}: {e}")
        return {'error': f"Connection error: {drone_uri}"}
    except Exception as e:
        logger.error(f"Error fetching git status from {drone_uri}: {e}")
        return {'error': str(e)}


def compare_git_status(local_status: Dict, remote_status: Dict) -> Dict[str, Any]:
    """
    Compare local and remote git status to check synchronization.

    Args:
        local_status: Git status dict from get_local_git_report()
        remote_status: Git status dict from get_remote_git_status()

    Returns:
        Dictionary with comparison results:
        - synced: bool indicating if commits match
        - local_commit: Local commit hash
        - remote_commit: Remote commit hash
        - local_branch: Local branch name
        - remote_branch: Remote branch name
    """
    local_commit = local_status.get('commit', '')
    remote_commit = remote_status.get('commit', '')
    local_branch = local_status.get('branch', '')
    remote_branch = remote_status.get('branch', '')

    return {
        'synced': local_commit == remote_commit and local_commit != '',
        'local_commit': local_commit[:7] if local_commit else 'unknown',
        'remote_commit': remote_commit[:7] if remote_commit else 'unknown',
        'local_branch': local_branch,
        'remote_branch': remote_branch,
        'branch_match': local_branch == remote_branch
    }
