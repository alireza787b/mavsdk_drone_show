# gcs-server/origin.py

import math
import os
import json
import logging
from params import Params
from pyproj import Proj, Transformer


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


def _latlon_to_ne(lat, lon, origin_lat, origin_lon):
    """Converts lat/lon to north-east coordinates relative to the origin."""
    try:
        # Define a local projection centered at the origin
        proj_string = f"+proj=tmerc +lat_0={origin_lat} +lon_0={origin_lon} +k=1 +units=m +ellps=WGS84"
        transformer = Transformer.from_proj(
            Proj('epsg:4326'),  # WGS84 coordinate system
            Proj(proj_string),
            always_xy=True
        )
        east, north = transformer.transform(lon, lat)
        return north, east
    except Exception as e:
        logger.error(f"Error in coordinate transformation: {e}", exc_info=True)
        raise

def calculate_position_deviations(telemetry_data_all_drones, drones_config, origin_lat, origin_lon):
    """
    Calculates the position deviations for all drones.
    
    :param telemetry_data_all_drones: Dictionary containing telemetry data for all drones.
    :param drones_config: List of drone configurations.
    :param origin_lat: Latitude of the origin point.
    :param origin_lon: Longitude of the origin point.
    :return: Dictionary with deviations for each drone.
    """
    deviations = {}
    acceptable_range = Params.acceptable_deviation  # in meters

    for drone in drones_config:
        hw_id = drone.get('hw_id')
        if not hw_id:
            continue

        # Get initial positions from config
        try:
            initial_east = float(drone.get('x', 0))  # 'x' is East
            initial_north = float(drone.get('y', 0))  # 'y' is North
        except (TypeError, ValueError):
            deviations[hw_id] = {
                "error": "Invalid initial position in configuration"
            }
            continue

        # Get current position from telemetry
        drone_telemetry = telemetry_data_all_drones.get(hw_id, {})
        current_lat = drone_telemetry.get('Position_Lat')
        current_lon = drone_telemetry.get('Position_Long')

        if current_lat is None or current_lon is None:
            deviations[hw_id] = {
                "error": "Current position not available"
            }
            continue

        try:
            current_lat = float(current_lat)
            current_lon = float(current_lon)
        except (TypeError, ValueError):
            deviations[hw_id] = {
                "error": "Invalid current position data"
            }
            continue

        # Convert current lat/lon to NE coordinates relative to the origin
        try:
            current_north, current_east = _latlon_to_ne(current_lat, current_lon, origin_lat, origin_lon)
        except Exception as e:
            deviations[hw_id] = {
                "error": f"Coordinate transformation error: {str(e)}"
            }
            continue

        # Calculate deviations
        deviation_north = current_north - initial_north
        deviation_east = current_east - initial_east
        total_deviation = math.sqrt(deviation_north**2 + deviation_east**2)

        # Check if within acceptable range
        within_range = total_deviation <= acceptable_range

        # Prepare deviation data
        deviations[hw_id] = {
            "deviation_north": deviation_north,
            "deviation_east": deviation_east,
            "total_deviation": total_deviation,
            "within_acceptable_range": within_range
        }

    return deviations