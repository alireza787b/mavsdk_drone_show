# gcs-server/utils.py
import os
import shutil
import subprocess

from mds_logging import get_logger

logger = get_logger("utils")

from git import Repo, GitCommandError

from params import Params

ALLOWED_EXTENSIONS = {'zip'}

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

def allowed_file(filename):
    """
    Check if the file has an allowed extension.
    """
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def clear_show_directories(base_dir):
    """
    Clear the swarm subdirectories (skybrush, processed, plots)
    for the current mode (SITL or real).
    
    If Params.sim_mode=True => shapes_sitl/swarm/*
    Else => shapes/swarm/*
    """
    if Params.sim_mode:
        shape_folder = 'shapes_sitl'
    else:
        shape_folder = 'shapes'

    swarm_dir = os.path.join(base_dir, shape_folder, 'swarm')
    directories = [
        os.path.join(swarm_dir, 'skybrush'),
        os.path.join(swarm_dir, 'processed'),
        os.path.join(swarm_dir, 'plots')
    ]
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory)  # Create if doesn't exist
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                logger.info(f"Deleted {file_path}")
            except Exception as e:
                logger.error(f"Failed to delete {file_path}. Reason: {e}")

    metrics_file = os.path.join(swarm_dir, 'comprehensive_metrics.json')
    if os.path.exists(metrics_file):
        try:
            os.unlink(metrics_file)
            logger.info(f"Deleted {metrics_file}")
        except Exception as e:
            logger.error(f"Failed to delete {metrics_file}. Reason: {e}")


def zip_directory(folder_path, zip_path):
    """Zip the contents of the specified folder."""
    shutil.make_archive(zip_path, 'zip', folder_path)
    return zip_path + '.zip'


def ensure_directory(directory):
    if not os.path.exists(directory):
        os.makedirs(directory)


def _run_git_with_timeout(git_cmd, args, timeout):
    """Run a GitPython command with a thread-safe timeout.

    Uses the git command's built-in kill_after_timeout parameter which is
    safe for use in async/multithreaded contexts (unlike SIGALRM).
    """
    try:
        # GitPython's git.cmd supports kill_after_timeout natively
        return git_cmd(*args, kill_after_timeout=timeout)
    except Exception as e:
        if 'timeout' in str(e).lower() or 'kill_after_timeout' in str(e).lower():
            raise TimeoutError(f"Git operation timed out after {timeout}s") from e
        raise


def _rollback_auto_commit(git, commit_hash):
    """Undo an auto-created commit while keeping working tree changes intact."""
    if not commit_hash:
        return
    try:
        logger.warning(
            "Rolling back local auto-commit %s after git propagation failure; "
            "leaving changes in the working tree only.",
            commit_hash,
        )
        git.reset('--mixed', 'HEAD~1')
    except Exception as rollback_error:
        logger.error(f"Failed to roll back auto-commit {commit_hash}: {rollback_error}")


def git_operations(base_dir, commit_message, timeout=30):
    """
    Handles Git operations using GitPython for better control and error handling.
    This version automatically resolves conflicts and maintains an uninterrupted workflow.

    Thread-safe: uses GitPython's kill_after_timeout instead of SIGALRM.
    Should be called via run_in_executor() from async endpoints to avoid blocking
    the event loop.

    Args:
        base_dir: Repository base directory
        commit_message: Commit message
        timeout: Timeout in seconds for network operations (fetch/pull/push). Default 30s.

    Returns:
        dict with 'success', 'message', and optionally 'commit_hash'
    """
    from git import Repo, GitCommandError

    try:
        repo = Repo(base_dir)
        git = repo.git
        git.update_environment(
            GIT_TERMINAL_PROMPT='0',
            GIT_ASKPASS='echo',
            SSH_ASKPASS='echo',
            GCM_INTERACTIVE='never',
        )

        # Fetch latest changes (with timeout)
        logger.info("Fetching latest changes from remote...")
        try:
            git.fetch('origin', kill_after_timeout=timeout)
        except (TimeoutError, GitCommandError) as e:
            if 'timeout' in str(e).lower() or 'kill_after_timeout' in str(e).lower():
                logger.warning(f"Git fetch timed out after {timeout}s, continuing with commit/push...")
            else:
                logger.warning(f"Git fetch failed: {e}, continuing with commit/push...")

        # Stage + commit if dirty
        commit_hash = None
        if repo.is_dirty(untracked_files=True):
            logger.info("Staging changes...")
            repo.git.add('--all')

            logger.info("Committing changes...")
            commit_obj = repo.index.commit(commit_message)
            commit_hash = commit_obj.hexsha[:8]

            # ====================================================================
            # CRITICAL VERIFICATION: Check what was actually committed
            # ====================================================================
            try:
                committed_files = list(commit_obj.stats.files.keys())
                file_count = len(committed_files)

                logger.info(f"Git commit successful: {file_count} file(s) committed [{commit_hash}]")

                # Log first 10 files for verification
                for filepath in committed_files[:10]:
                    logger.info(f"  + {filepath}")
                if file_count > 10:
                    logger.info(f"  ... and {file_count - 10} more file(s)")

                # Check for critical drone show files
                processed_committed = [f for f in committed_files if 'swarm/processed/' in f and f.endswith('.csv')]
                skybrush_committed = [f for f in committed_files if 'swarm/skybrush/' in f and f.endswith('.csv')]

                if processed_committed:
                    logger.info(f"Committed {len(processed_committed)} processed drone file(s)")
                if skybrush_committed:
                    logger.info(f"Committed {len(skybrush_committed)} raw drone file(s)")

            except Exception as verify_error:
                logger.warning(f"Could not verify committed files: {verify_error}")

        if not Params.GIT_AUTO_PUSH:
            if commit_hash:
                success_message = "Changes committed locally. Auto-push is disabled on this GCS."
            else:
                success_message = "No new git commit was needed. Auto-push is disabled on this GCS."
            logger.info(success_message)
            return {
                'success': True,
                'message': success_message,
                'commit_hash': commit_hash,
                'auto_push_enabled': False,
                'pushed': False,
            }

        # Pull latest changes with rebase (with timeout)
        logger.info("Rebasing local changes on top of remote changes...")
        try:
            git.pull('--rebase', 'origin', Params.GIT_BRANCH, kill_after_timeout=timeout)
        except (TimeoutError, GitCommandError) as e:
            if 'timeout' in str(e).lower() or 'kill_after_timeout' in str(e).lower():
                _rollback_auto_commit(git, commit_hash)
                return {'success': False, 'message': f'Git pull timed out after {timeout}s',
                        'commit_hash': commit_hash}
            elif 'merge conflict' in str(e).lower() or 'rebase' in str(e).lower():
                logger.error("Merge conflict detected. Attempting to resolve automatically...")
                try:
                    git.rebase('--abort')
                except Exception:
                    pass
                git.reset('--hard', 'HEAD')
                git.pull('--rebase', 'origin', Params.GIT_BRANCH, kill_after_timeout=timeout)
            else:
                raise

        # Push changes (with timeout)
        logger.info("Pushing changes to remote repository...")
        try:
            git.push('origin', Params.GIT_BRANCH, kill_after_timeout=timeout)
        except (TimeoutError, GitCommandError) as e:
            if 'timeout' in str(e).lower() or 'kill_after_timeout' in str(e).lower():
                _rollback_auto_commit(git, commit_hash)
                return {'success': False, 'message': f'Git push timed out after {timeout}s',
                        'commit_hash': commit_hash}
            raise

        success_message = "Changes pushed to repository successfully."
        logger.info(success_message)
        return {
            'success': True,
            'message': success_message,
            'commit_hash': commit_hash,
            'auto_push_enabled': True,
            'pushed': True,
        }

    except GitCommandError as e:
        error_str = str(e)
        # Provide specific error messages
        lowered_error = error_str.lower()
        if (
            'could not read username' in lowered_error
            or 'terminal prompts disabled' in lowered_error
            or 'authentication failed' in lowered_error
        ):
            error_message = (
                "Git push failed: authenticated write access is required for auto-push. "
                "Configure SSH/PAT credentials or disable GIT_AUTO_PUSH on this GCS."
            )
        elif 'Permission denied' in error_str or 'publickey' in error_str:
            error_message = "Git push failed: no SSH key or permission denied. Ensure GCS has a deploy key with write access."
        elif 'Could not resolve host' in error_str or 'unable to access' in error_str:
            error_message = "Git push failed: network error. Check internet connectivity."
        elif 'rejected' in error_str and 'non-fast-forward' in error_str:
            error_message = "Git push failed: remote has diverged. Pull and resolve conflicts first."
        else:
            error_message = f"Git command error: {error_str}"

        # Check if remote is HTTPS (no push without auth)
        try:
            remote_url = repo.git.config('--get', 'remote.origin.url')
            if remote_url.startswith('https://'):
                error_message += " (GCS remote is HTTPS - push requires SSH. See docs/guides/gcs-setup.md)"
        except Exception:
            pass

        _rollback_auto_commit(git, commit_hash)
        logger.error(error_message)
        return {'success': False, 'message': error_message}
    except Exception as e:
        error_message = f"Exception during git operations: {str(e)}"
        logger.error(error_message, exc_info=True)
        return {'success': False, 'message': error_message}
