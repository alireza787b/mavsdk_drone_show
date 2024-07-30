#gcs-server/utils.py
import os
import shutil
import logging
import subprocess

from flask import current_app

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
    Handles Git operations including add, commit, and an intelligent push that handles possible upstream changes.
    This function uses configured branch names from Params.GIT_BRANCH.
    """
    try:
        # Staging changes
        subprocess.check_call(['git', 'add', '.'], cwd=base_dir)
        subprocess.check_call(['git', 'commit', '-m', commit_message], cwd=base_dir)
        
        # Fetch the latest changes from the repository to prepare for rebase
        subprocess.check_call(['git', 'fetch'], cwd=base_dir)
        
        try:
            # Attempt to rebase onto the fetched branch
            subprocess.check_call(['git', 'rebase', f'origin/{Params.GIT_BRANCH}'], cwd=base_dir)
        except subprocess.CalledProcessError:
            # If rebase fails, log the failure and suggest manual intervention
            logging.error("Rebase failed, attempting to abort.")
            subprocess.check_call(['git', 'rebase', '--abort'], cwd=base_dir)
            return "Rebase failed; manual intervention required."

        # Push the changes if rebase was successful
        subprocess.check_call(['git', 'push', 'origin', Params.GIT_BRANCH], cwd=base_dir)
        return "Changes pushed to repository successfully."
    except subprocess.CalledProcessError as e:
        # Log the specific error and return a friendly message
        logging.error(f"Git operation failed: {e}")
        return f"Failed to push changes to repository: {e.output}"