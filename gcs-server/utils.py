#gcs-server/utils.py
import os
import shutil
import logging
import subprocess

from flask import current_app
from git import Repo, GitCommandError


from params import Params

ALLOWED_EXTENSIONS = {'zip'}

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

def allowed_file(filename):
    """
    Check if the file has an allowed extension.
    """
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def clear_show_directories(BASE_DIR):
    """
    Clear specific directories used for drone show data.
    """
    directories = [
        os.path.join(BASE_DIR, 'shapes', 'swarm', 'skybrush'),
        os.path.join(BASE_DIR, 'shapes', 'swarm', 'processed'),
        os.path.join(BASE_DIR, 'shapes', 'swarm', 'plots')
    ]
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory)  # Create the directory if it doesn't exist
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                logging.info(f"Deleted {file_path}")
            except Exception as e:
                logging.error(f"Failed to delete {file_path}. Reason: {e}")


def zip_directory(folder_path, zip_path):
    """Zip the contents of the specified folder."""
    shutil.make_archive(zip_path, 'zip', folder_path)
    return zip_path + '.zip'


def ensure_directory(directory):
    if not os.path.exists(directory):
        os.makedirs(directory)


# Utility function for Git operations
def git_operations(base_dir, commit_message):
    """
    Handles Git operations using GitPython for better control and error handling.
    """
    try:
        repo = Repo(base_dir)
        git = repo.git

        # Check for uncommitted changes
        if repo.is_dirty(untracked_files=True):
            logging.info("Staging changes...")
            repo.git.add('--all')

            logging.info("Committing changes...")
            repo.index.commit(commit_message)
        else:
            message = "No changes to commit."
            logging.info(message)

        # Pull latest changes with rebase
        logging.info("Rebasing local changes on top of remote changes...")
        git.pull('--rebase', 'origin', Params.GIT_BRANCH)

        # Push changes to remote
        logging.info("Pushing changes to remote repository...")
        git.push('origin', Params.GIT_BRANCH)

        success_message = "Changes pushed to repository successfully."
        logging.info(success_message)
        return {'success': True, 'message': success_message}

    except GitCommandError as e:
        error_message = f"Git command error: {str(e)}"
        logging.error(error_message)
        return {'success': False, 'message': error_message}
    except Exception as e:
        error_message = f"Exception during git operations: {str(e)}"
        logging.error(error_message, exc_info=True)
        return {'success': False, 'message': error_message}