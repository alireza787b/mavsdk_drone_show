#gcs-server/utils.py
import os
import shutil
import logging

ALLOWED_EXTENSIONS = {'zip'}

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
