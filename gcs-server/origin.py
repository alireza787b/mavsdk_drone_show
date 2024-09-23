# gcs-server/origin.py

import os
import json
import logging

# Setup logging
logger = logging.getLogger(__name__)

# Define the path for storing origin data
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
origin_file_path = os.path.join(BASE_DIR, 'data', 'origin.json')

# Ensure the data directory exists
if not os.path.exists(os.path.dirname(origin_file_path)):
    os.makedirs(os.path.dirname(origin_file_path))

def save_origin(data):
    """
    Save the origin coordinates to a JSON file.

    :param data: Dictionary containing 'lat' and 'lon'.
    """
    try:
        with open(origin_file_path, 'w') as f:
            json.dump(data, f)
        logger.info("Origin coordinates saved successfully.")
    except Exception as e:
        logger.error(f"Error saving origin coordinates: {e}")

def load_origin():
    """
    Load the origin coordinates from a JSON file.

    :return: Dictionary containing 'lat' and 'lon'.
    """
    if os.path.exists(origin_file_path):
        try:
            with open(origin_file_path, 'r') as f:
                data = json.load(f)
            logger.info("Origin coordinates loaded successfully.")
            return data
        except Exception as e:
            logger.error(f"Error loading origin coordinates: {e}")
            return {'lat': '', 'lon': ''}
    else:
        logger.warning("Origin file does not exist. Returning default values.")
        return {'lat': '', 'lon': ''}
