#functions/file_management.py
import os
import shutil
import logging

def setup_logging():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def ensure_directory_exists(directory):
    """Ensure directory exists or create it if not."""
    if not os.path.exists(directory):
        os.makedirs(directory)
        logging.info(f"Created directory: {directory}")

def clear_directory(directory):
    """Clear all files in a directory."""
    for filename in os.listdir(directory):
        file_path = os.path.join(directory, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
                logging.info(f"Deleted file: {file_path}")
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
                logging.info(f"Deleted directory: {file_path}")
        except Exception as e:
            logging.error(f"Failed to delete {file_path}. Reason: {e}")

def copy_files(source_dir, dest_dir):
    """Copy all files from source to destination directory."""
    for filename in os.listdir(source_dir):
        src_file = os.path.join(source_dir, filename)
        dst_file = os.path.join(dest_dir, filename)
        if os.path.isfile(src_file):
            shutil.copy(src_file, dst_file)
            logging.info(f"Copied {src_file} to {dst_file}")
