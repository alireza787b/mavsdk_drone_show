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

import os
import subprocess
import logging
import requests
from typing import Dict, Any, Optional
from src.drone_api_routes import DRONE_GIT_STATUS_ROUTE
from src.settings.runtime import preload_local_env

logger = logging.getLogger(__name__)

IGNORED_UNCOMMITTED_PATHS = {
    '.mds_sitl_image_build.env',
    '.mds_px4_source_provenance.env',
    '.mds_px4_submodules.txt',
}


def normalize_branch_name(raw_branch: Optional[str]) -> str:
    """Strip remote prefixes and detached-name noise from a git branch reference."""
    if not raw_branch:
        return ''

    branch = raw_branch.strip()
    for prefix in ('refs/remotes/', 'refs/heads/', 'remotes/'):
        if branch.startswith(prefix):
            branch = branch[len(prefix):]
    if branch.startswith('origin/'):
        branch = branch[len('origin/'):]
    if branch.endswith('^0'):
        branch = branch[:-2]
    return branch


def resolve_current_git_branch(
    command_executor,
    *,
    cwd: Optional[str] = None,
) -> Optional[str]:
    """
    Resolve the current branch even when Git is running from a detached HEAD worktree.

    Prefers the direct branch name when available, then falls back to upstream,
    remote refs that contain HEAD, and finally a name-rev hint.
    """
    branch = command_executor(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=cwd)
    if branch and branch != 'HEAD':
        return normalize_branch_name(branch)

    tracking_branch = command_executor(
        ['git', 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}'],
        cwd=cwd,
    )
    if tracking_branch:
        normalized = normalize_branch_name(tracking_branch)
        if normalized and normalized != 'HEAD':
            return normalized

    remote_refs_output = command_executor(
        ['git', 'for-each-ref', '--format=%(refname:short)', '--contains', 'HEAD', 'refs/remotes'],
        cwd=cwd,
    ) or ''
    remote_refs = [
        normalize_branch_name(line)
        for line in remote_refs_output.splitlines()
        if line.strip() and not line.strip().endswith('/HEAD')
    ]
    if remote_refs:
        preferred_order = ('main', 'master', 'main-candidate')
        preferred = next(
            (branch for branch in preferred_order if branch in remote_refs),
            remote_refs[0],
        )
        return preferred

    name_rev = command_executor(['git', 'name-rev', '--name-only', 'HEAD'], cwd=cwd)
    normalized_name_rev = normalize_branch_name(name_rev)
    if normalized_name_rev and normalized_name_rev not in {'HEAD', 'undefined'}:
        return normalized_name_rev

    return None


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


def get_tracking_branch_sync_counts(
    command_executor,
    *,
    tracking_branch: Optional[str],
    cwd: Optional[str] = None,
) -> tuple[int, int]:
    """
    Return `(commits_ahead, commits_behind)` for the current HEAD vs a tracking branch.

    Repositories running on custom branches or detached worktrees may not have an
    upstream configured. In those cases this returns `(0, 0)` instead of treating
    the missing upstream as an error.
    """
    if not tracking_branch:
        return 0, 0

    ahead_behind = command_executor(
        ['git', 'rev-list', '--left-right', '--count', f'{tracking_branch}...HEAD'],
        cwd=cwd,
    )
    if not ahead_behind:
        return 0, 0

    parts = ahead_behind.split()
    if len(parts) != 2:
        return 0, 0

    try:
        commits_behind = int(parts[0])
        commits_ahead = int(parts[1])
    except (TypeError, ValueError):
        return 0, 0

    return commits_ahead, commits_behind


def describe_repo_access_mode(
    repo_url: Optional[str],
    *,
    token_file: Optional[str] = None,
    ssh_key_file: Optional[str] = None,
) -> str:
    """Classify the current repo/auth posture without leaking credential paths."""
    normalized = str(repo_url or '').strip()
    if normalized.startswith('git@github.com:'):
        return 'ssh_key'
    if normalized.startswith('https://github.com/') and token_file:
        return 'https_token_file'
    if normalized.startswith('https://github.com/'):
        return 'https_public_or_read_only'
    return 'custom_or_unknown'


def build_read_only_git_auth_health(
    *,
    repo_access_mode: str,
    token_file: Optional[str],
    token_file_readable: bool,
    ssh_key_file: Optional[str],
    ssh_key_file_readable: bool,
) -> dict[str, Any]:
    """Summarize whether the node's current repo/auth posture is usable for read-only sync."""
    issues: list[str] = []

    if repo_access_mode == 'https_token_file' and not token_file_readable:
        issues.append(
            'HTTPS token-file mode is selected but the configured token file is missing or unreadable.'
        )
    if repo_access_mode == 'ssh_key' and not ssh_key_file_readable:
        issues.append(
            'SSH-key mode is selected but the configured SSH key file is missing or unreadable.'
        )
    if repo_access_mode == 'custom_or_unknown':
        issues.append(
            'Repo/auth posture is custom or unknown; verify node read access explicitly.'
        )

    if issues:
        status = 'error' if any('missing or unreadable' in issue for issue in issues) else 'warning'
    else:
        status = 'healthy'

    if status == 'healthy':
        if repo_access_mode == 'https_token_file':
            summary = 'HTTPS token-file access is configured and readable for node sync.'
        elif repo_access_mode == 'ssh_key':
            summary = 'SSH-key access is configured and readable for node sync.'
        elif repo_access_mode == 'https_public_or_read_only':
            summary = 'HTTPS public/read-only access is active; this is valid for node sync.'
        else:
            summary = 'Node git auth posture does not report any immediate issues.'
    elif status == 'warning':
        summary = 'Node git auth posture is usable but needs operator attention.'
    else:
        summary = 'Node git auth posture is broken for the currently selected access mode.'

    return {
        'status': status,
        'summary': summary,
        'issues': issues,
    }


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
        preload_local_env(logger)

        # Get current branch
        branch = resolve_current_git_branch(execute_git_command, cwd=repo_path)
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

        commits_ahead, commits_behind = get_tracking_branch_sync_counts(
            execute_git_command,
            tracking_branch=tracking_branch,
            cwd=repo_path,
        )

        # Get working tree status
        status_output = execute_git_command(
            ['git', 'status', '--porcelain'], cwd=repo_path
        ) or ''
        filtered_changes = parse_filtered_git_status(status_output)

        git_auth_token_file = str(os.environ.get('MDS_GIT_AUTH_TOKEN_FILE') or '').strip()
        git_ssh_key_file = str(os.environ.get('MDS_GIT_SSH_KEY_FILE') or '').strip()
        repo_access_mode = describe_repo_access_mode(
            remote_url,
            token_file=git_auth_token_file,
            ssh_key_file=git_ssh_key_file,
        )
        git_auth_health = build_read_only_git_auth_health(
            repo_access_mode=repo_access_mode,
            token_file=git_auth_token_file,
            token_file_readable=bool(git_auth_token_file and os.path.isfile(git_auth_token_file)),
            ssh_key_file=git_ssh_key_file,
            ssh_key_file_readable=bool(git_ssh_key_file and os.path.isfile(git_ssh_key_file)),
        )

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
            'commits_ahead': commits_ahead,
            'commits_behind': commits_behind,
            'repo_access_mode': repo_access_mode,
            'git_auth_health_status': git_auth_health['status'],
            'git_auth_health_summary': git_auth_health['summary'],
            'git_auth_health_issues': git_auth_health['issues'],
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
        branch = resolve_current_git_branch(execute_git_command, cwd=repo_path)
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
