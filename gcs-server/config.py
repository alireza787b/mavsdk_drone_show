#gcs-server/config.py
import csv
import os
import logging
import subprocess
import requests
from flask import Flask, jsonify, request
from params import Params

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE_PATH = os.path.join(BASE_DIR, Params.config_csv_name)
SWARM_FILE_PATH = os.path.join(BASE_DIR, Params.swarm_csv_name)

logger = logging.getLogger(__name__)

# Define the expected column order
CONFIG_COLUMNS = ['hw_id', 'pos_id', 'x', 'y', 'ip', 'mavlink_port', 'debug_port', 'gcs_ip']
SWARM_COLUMNS = ['hw_id' , 'follow' , 'offset_n' , 'offset_e' , 'offset_alt' , 'body_coord']


def load_csv(file_path):
    """General function to load data from a CSV file."""
    data = []
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return data

    try:
        with open(file_path, mode='r') as file:
            reader = csv.DictReader(file)
            for row in reader:
                data.append(row)

        if not data:
            logger.warning(f"File is empty: {file_path}")
    except FileNotFoundError:
        logger.error(f"File not found: {file_path}")
    except csv.Error as e:
        logger.error(f"Error reading CSV file {file_path}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error loading file {file_path}: {e}")

    return data

def save_csv(data, file_path, fieldnames=None):
    """General function to save data to a CSV file with a specified column order."""
    if not data:
        logger.warning(f"No data provided to save in {file_path}. Operation aborted.")
        return

    try:
        with open(file_path, mode='w', newline='') as file:
            # Use the provided fieldnames if available, otherwise use the keys from the data
            writer = csv.DictWriter(file, fieldnames=fieldnames or data[0].keys())
            writer.writeheader()
            writer.writerows(data)
        logger.info(f"Data successfully saved to {file_path}")
    except FileNotFoundError:
        logger.error(f"File not found: {file_path}")
    except csv.Error as e:
        logger.error(f"Error writing CSV file {file_path}: {e}")
    except IOError as e:
        logger.error(f"IO error saving file {file_path}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error saving file {file_path}: {e}")

def load_config(file_path=CONFIG_FILE_PATH):
    return load_csv(file_path)

def save_config(config, file_path=CONFIG_FILE_PATH):
    # Pass the expected column order to ensure consistent column placement
    save_csv(config, file_path, fieldnames=CONFIG_COLUMNS)

def load_swarm(file_path=SWARM_FILE_PATH):
    return load_csv(file_path)

def save_swarm(swarm, file_path=SWARM_FILE_PATH):
    save_csv(swarm, file_path,fieldnames=SWARM_COLUMNS)


def get_git_status():
    """Retrieve the Git status of the GCS."""
    try:
        branch = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD']).strip().decode('utf-8')
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD']).strip().decode('utf-8')
        author_name = subprocess.check_output(['git', 'show', '-s', '--format=%an', commit]).strip().decode('utf-8')
        author_email = subprocess.check_output(['git', 'show', '-s', '--format=%ae', commit]).strip().decode('utf-8')
        commit_date = subprocess.check_output(['git', 'show', '-s', '--format=%cd', '--date=iso-strict', commit]).strip().decode('utf-8')
        commit_message = subprocess.check_output(['git', 'show', '-s', '--format=%B', commit]).strip().decode('utf-8')
        remote_url = subprocess.check_output(['git', 'config', '--get', 'remote.origin.url']).strip().decode('utf-8')
        tracking_branch = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}']).strip().decode('utf-8')
        status = subprocess.check_output(['git', 'status', '--porcelain']).strip().decode('utf-8')

        return {
            'branch': branch,
            'commit': commit,
            'author_name': author_name,
            'author_email': author_email,
            'commit_date': commit_date,
            'commit_message': commit_message,
            'remote_url': remote_url,
            'tracking_branch': tracking_branch,
            'status': 'clean' if not status else 'dirty',
            'uncommitted_changes': status.splitlines() if status else []
        }
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to get Git status: {e}")
        return {'error': f"Git command failed: {str(e)}"}

def get_drone_git_status(drone_uri):
    """Retrieve the Git status from a specific drone."""
    try:
        logging.debug(f"Sending request to {drone_uri}/get-git-status")
        response = requests.get(f"{drone_uri}/get-git-status")  # Make sure it's `requests`
        logging.debug(f"Received response with status code {response.status_code}")

        if response.status_code == 200:
            try:
                json_data = response.json()
                logging.debug(f"Response JSON: {json_data}")
                return json_data
            except ValueError as ve:
                logging.error(f"Error decoding JSON: {str(ve)}")
                return {'error': 'Failed to decode JSON from response'}
        else:
            logging.error(f"Failed to retrieve status, status code: {response.status_code}")
            return {'error': f"Failed to retrieve status from {drone_uri}"}
    except Exception as e:
        logging.error(f"Error contacting drone {drone_uri}: {str(e)}")
        return {'error': f"Error contacting drone {drone_uri}: {str(e)}"}