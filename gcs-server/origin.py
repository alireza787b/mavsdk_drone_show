# gcs-server/origin.py

import math
import os
import json
import csv
import logging
from datetime import datetime
from params import Params
from pyproj import Proj, Transformer
from scipy.optimize import minimize

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define the path for storing origin data
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
origin_file_path = os.path.join(BASE_DIR, 'data', 'origin.json')

# Ensure the data directory exists
if not os.path.exists(os.path.dirname(origin_file_path)):
    os.makedirs(os.path.dirname(origin_file_path))

def save_origin(data):
    """
    Save the origin coordinates to a JSON file (v2 schema with altitude support).

    Schema v2:
      - lat: float (required) - Latitude in decimal degrees
      - lon: float (required) - Longitude in decimal degrees
      - alt: float (optional, default 0) - MSL altitude in meters
      - alt_source: str (optional) - 'manual' | 'drone' | 'elevation_api'
      - timestamp: ISO datetime string
      - version: int (schema version)

    :param data: Dictionary containing origin data
    """
    try:
        # Build v2 schema with backwards compatibility
        origin_data = {
            'lat': float(data.get('lat')),
            'lon': float(data.get('lon')),
            'alt': float(data.get('alt', 0)),  # Default to 0 for backwards compat
            'alt_source': data.get('alt_source', 'manual'),
            'timestamp': datetime.now().isoformat(),
            'version': 2
        }

        with open(origin_file_path, 'w') as f:
            json.dump(origin_data, f, indent=2)

        logger.info(f"Origin coordinates saved successfully: lat={origin_data['lat']}, "
                   f"lon={origin_data['lon']}, alt={origin_data['alt']}m")
    except Exception as e:
        logger.error(f"Error saving origin coordinates: {e}")
        raise

def load_origin():
    """
    Load the origin coordinates from a JSON file with backwards compatibility.

    Automatically migrates v1 format (lat/lon only) to v2 (with altitude).

    :return: Dictionary containing origin data in v2 format
    """
    if os.path.exists(origin_file_path):
        try:
            with open(origin_file_path, 'r') as f:
                data = json.load(f)

            # Check version and migrate if needed
            if 'version' not in data or data.get('version') == 1:
                # Migrate from v1 to v2
                logger.info("Migrating origin data from v1 to v2 schema")
                data = {
                    'lat': data.get('lat', ''),
                    'lon': data.get('lon', ''),
                    'alt': 0,  # Old format assumed ground level
                    'alt_source': 'manual',
                    'timestamp': datetime.now().isoformat(),
                    'version': 2
                }
                # Save migrated data
                try:
                    save_origin(data)
                except:
                    pass  # Don't fail if save fails during migration

            logger.info("Origin coordinates loaded successfully.")
            return data

        except Exception as e:
            logger.error(f"Error loading origin coordinates: {e}")
            return {'lat': '', 'lon': '', 'alt': 0, 'version': 2}
    else:
        logger.warning("Origin file does not exist. Returning default values.")
        return {'lat': '', 'lon': '', 'alt': 0, 'version': 2}

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


def _get_expected_position_from_trajectory(pos_id, sim_mode=False):
    """
    Get the expected position (starting point) from a trajectory CSV file.

    This function reads the first waypoint from the trajectory CSV file
    corresponding to the given position ID. This is the single source of truth
    for expected position, especially critical when hw_id ≠ pos_id.

    Args:
        pos_id (int): Position ID (determines which trajectory file to read)
        sim_mode (bool): Whether in simulation mode (affects path: shapes vs shapes_sitl)

    Returns:
        tuple: (north, east) coordinates from first waypoint, or (None, None) on error

    Example:
        When hw_id=10 performs pos_id=1's show, this function reads
        "Drone 1.csv" first row to get the expected starting position.
    """
    try:
        # Construct trajectory file path based on pos_id
        base_dir = 'shapes_sitl' if sim_mode else 'shapes'
        trajectory_file = os.path.join(
            BASE_DIR,  # Use GCS server base directory
            base_dir,
            'swarm',
            'processed',
            f"Drone {pos_id}.csv"
        )

        # Check if file exists
        if not os.path.exists(trajectory_file):
            logger.error(f"Trajectory file not found: {trajectory_file}")
            return None, None

        # Read first waypoint from CSV
        with open(trajectory_file, 'r') as f:
            reader = csv.DictReader(f)
            first_waypoint = next(reader, None)

            if first_waypoint is None:
                logger.error(f"Trajectory file is empty: {trajectory_file}")
                return None, None

            # Extract px (North) and py (East) from first waypoint
            # These represent the canonical expected position for this pos_id
            expected_north = float(first_waypoint.get('px', 0))
            expected_east = float(first_waypoint.get('py', 0))

            logger.debug(
                f"Expected position for pos_id={pos_id}: "
                f"North={expected_north:.2f}m, East={expected_east:.2f}m "
                f"(from {trajectory_file})"
            )

            return expected_north, expected_east

    except FileNotFoundError:
        logger.error(f"Trajectory file not found for pos_id={pos_id}")
        return None, None
    except KeyError as e:
        logger.error(f"Missing column in trajectory CSV: {e}")
        return None, None
    except ValueError as e:
        logger.error(f"Invalid coordinate value in trajectory CSV: {e}")
        return None, None
    except Exception as e:
        logger.error(f"Unexpected error reading trajectory file for pos_id={pos_id}: {e}")
        return None, None


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
        pos_id = drone.get('pos_id')

        if not hw_id:
            continue

        # CRITICAL FIX: Use pos_id to get expected position from trajectory CSV
        # When hw_id ≠ pos_id, the drone executes pos_id's trajectory, so expected
        # position must come from trajectory file, NOT from config.csv x,y values
        if not pos_id:
            # Fallback: if no pos_id defined, assume pos_id == hw_id
            pos_id = hw_id
            logger.warning(f"No pos_id found for hw_id={hw_id}, assuming pos_id={hw_id}")

        # Detect simulation mode from Params
        sim_mode = getattr(Params, 'sim_mode', False)

        # Get expected position from trajectory CSV (single source of truth)
        initial_north, initial_east = _get_expected_position_from_trajectory(pos_id, sim_mode)

        if initial_north is None or initial_east is None:
            deviations[hw_id] = {
                "error": f"Could not read trajectory file for pos_id={pos_id}"
            }
            logger.error(
                f"hw_id={hw_id}, pos_id={pos_id}: Failed to read expected position from trajectory CSV"
            )
            continue

        logger.debug(
            f"hw_id={hw_id}, pos_id={pos_id}: Expected position from trajectory: "
            f"North={initial_north:.2f}m, East={initial_east:.2f}m"
        )

        # Get current position from telemetry
        drone_telemetry = telemetry_data_all_drones.get(hw_id, {})
        current_lat = drone_telemetry.get('position_lat')
        current_lon = drone_telemetry.get('position_long')

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

def compute_origin_from_drone(current_lat, current_lon, intended_north, intended_east):
    """
    Computes the origin lat/lon based on the drone's current lat/lon and intended N,E positions.
    """
    try:
        logger.info(f"Starting origin computation with current_lat={current_lat}, current_lon={current_lon}, intended_north={intended_north}, intended_east={intended_east}")

        # Define the error function to minimize
        def error_function(origin_coords):
            try:
                origin_lat, origin_lon = origin_coords

                # Define the projection
                proj_string = f"+proj=tmerc +lat_0={origin_lat} +lon_0={origin_lon} +k=1 +units=m +ellps=WGS84"
                transformer = Transformer.from_proj(
                    Proj('epsg:4326'),  # WGS84
                    Proj(proj_string),
                    always_xy=True
                )

                # Compute N,E positions of the drone's current lat/lon relative to this origin
                east, north = transformer.transform(current_lon, current_lat)

                # Compute the difference between computed N,E and intended N,E
                delta_north = north - intended_north
                delta_east = east - intended_east

                error = delta_north ** 2 + delta_east ** 2

                logger.debug(f"Origin ({origin_lat}, {origin_lon}): Delta N={delta_north}, Delta E={delta_east}, Error={error}")

                return error
            except Exception as e:
                logger.error(f"Exception in error_function with origin_coords={origin_coords}: {e}", exc_info=True)
                return 1e10  # Return a large error to penalize invalid origins

        # Initial guess for the origin is the drone's current position
        initial_guess = [current_lat, current_lon]
        logger.debug(f"Initial guess for origin: {initial_guess}")

        # Set bounds for latitude and longitude
        bounds = [(-90, 90), (-180, 180)]

        # Use scipy.optimize to minimize the error function
        result = minimize(
            error_function,
            initial_guess,
            method='L-BFGS-B',
            bounds=bounds
        )

        logger.info(f"Optimization result: {result}")

        if result.success:
            origin_lat, origin_lon = result.x
            logger.info(f"Origin computed successfully: ({origin_lat}, {origin_lon})")
            return origin_lat, origin_lon
        else:
            logger.error(f"Optimization failed: {result.message}")
            raise Exception(f"Optimization failed: {result.message}")

    except Exception as e:
        logger.error(f"Error computing origin from drone: {e}", exc_info=True)
        raise
