import os
import sys
import glob
import logging
import logging.handlers
from datetime import datetime
import time
import csv
from mavsdk.system import System
from src.params import Params

from mavsdk.offboard import PositionNedYaw
import numpy as np
from pyproj import CRS, Transformer
import navpy

def calculate_ned_origin(current_gps, ned_position):
    lat, lon, alt = current_gps
    north, east, down = ned_position

    # Define the CRS (coordinate reference system) using EPSG codes
    wgs84 = CRS.from_epsg(4326)  # WGS 84
    ecef = CRS.from_epsg(4978)   # ECEF (Earth-Centered, Earth-Fixed)

    # Create a transformer to convert between WGS84 and ECEF
    transformer = Transformer.from_crs(wgs84, ecef, always_xy=True)

    # Convert current GPS to ECEF coordinates
    ecef_current = transformer.transform(lon, lat, alt)

    # Calculate the ECEF position of the NED origin
    ecef_origin = np.array(ecef_current) - np.array([north, east, down])

    # Inverse transformation to convert back to geodetic coordinates
    transformer_inv = Transformer.from_crs(ecef, wgs84, always_xy=True)
    lat_origin, lon_origin, alt_origin = transformer_inv.transform(ecef_origin[0], ecef_origin[1], ecef_origin[2])

    return lat_origin, lon_origin, alt_origin


def configure_logging(mission_type="drone_show"):
    """
    Configures simple logging - ONE log file per mission type only.
    No archives, no redundancy, just clean current mission logs.

    Args:
        mission_type (str): Type of mission (drone_show, swarm_trajectory, smart_swarm)
    """
    # Check if the root logger already has handlers configured
    if logging.getLogger().hasHandlers():
        return

    # Create logs directory if it doesn't exist
    logs_directory = os.path.join("logs")
    os.makedirs(logs_directory, exist_ok=True)

    # Configure the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Create detailed formatter with timestamps and step-by-step info
    formatter = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)  # Less verbose on console
    console_handler.setFormatter(formatter)

    # Create ONE log file per mission type (overwrites each run)
    log_filename = f"last_{mission_type}.log"
    log_file = os.path.join(logs_directory, log_filename)

    # Overwrite previous mission log
    file_handler = logging.FileHandler(log_file, mode='w')
    file_handler.setLevel(logging.DEBUG)  # Full detail in file
    file_handler.setFormatter(formatter)

    # Add handlers to the root logger
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # Log the mission start with full details
    logger = logging.getLogger(__name__)
    logger.info(f"=== {mission_type.upper()} MISSION STARTED ===")
    logger.info(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}")
    logger.info(f"Log file: {log_file}")
    logger.info(f"Mission type: {mission_type}")
    logger.info("=" * 60)

# Legacy limit_log_files function removed - no more archives, just simple one-log-per-mission

def read_hw_id() -> int:
    """
    Read the hardware ID from a file with the extension '.hwID'.

    Returns:
        int: Hardware ID if found, else None.
    """
    logger = logging.getLogger(__name__)
    hwid_files = glob.glob(os.path.join('*.hwID'))
    if hwid_files:
        filename = os.path.basename(hwid_files[0])
        hw_id = os.path.splitext(filename)[0]  # Get filename without extension
        logger.info(f"Hardware ID {hw_id} detected.")
        try:
            return int(hw_id)
        except ValueError:
            logger.error(f"Invalid HW ID format in file '{filename}'. Must be an integer.")
            return None
    else:
        logger.error("Hardware ID file not found.")
        return None

def clamp_led_value(value):
    """
    Clamps the LED value to be within 0 to 255.

    Args:
        value: The input value for the LED.

    Returns:
        int: Clamped LED value.
    """
    logger = logging.getLogger(__name__)
    try:
        return int(max(0, min(255, float(value))))
    except ValueError:
        logger.warning(f"Invalid LED value '{value}'. Defaulting to 0.")
        return 0  # Default to 0 if the value cannot be converted


def get_expected_position_from_trajectory(pos_id, sim_mode=False):
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
    logger = logging.getLogger(__name__)

    try:
        # Construct trajectory file path based on pos_id
        base_dir = 'shapes_sitl' if sim_mode else 'shapes'
        trajectory_file = os.path.join(
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
        logger.error(f"Trajectory file not found for pos_id={pos_id}: {trajectory_file}")
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


def global_to_local(global_position, home_position):
    """
    Convert global coordinates to local NED coordinates.

    Args:
        global_position: Global position telemetry data.
        home_position: Home position telemetry data.

    Returns:
        PositionNedYaw: Converted local NED position.
    """
    logger = logging.getLogger(__name__)
    try:
        # Reference LLA from home position (assuming home_position is a tuple)
        lat_ref, lon_ref, alt_ref = home_position  # Now we handle it as a tuple

        # Current LLA from global position
        lat, lon, alt = global_position.latitude_deg , global_position.longitude_deg, global_position.absolute_altitude_m   # Again, handle as tuple

        ned = navpy.lla2ned(
            lat,
            lon,
            alt,
            lat_ref,
            lon_ref,
            alt_ref,
            latlon_unit="deg",
            alt_unit="m",
            model="wgs84",
        )

        # Return the local position with yaw set to 0.0
        return PositionNedYaw(ned[0], ned[1], ned[2], 0.0)
    except Exception:
        logger.exception("Error converting global to local coordinates")
        return PositionNedYaw(0.0, 0.0, 0.0, 0.0)


async def pre_flight_checks(drone: System):
    """
    Perform pre-flight checks to ensure the drone is ready for flight.

    Args:
        drone (System): MAVSDK drone system instance.

    Returns:
        tuple: GPS coordinates of the NED origin (latitude, longitude, altitude).
    """
    logger = logging.getLogger(__name__)
    logger.info("Starting pre-flight checks.")
    home_position = None
    led_controller = LEDController.get_instance()

    # Set LED color to yellow to indicate pre-flight checks
    led_controller.set_color(255, 255, 0)
    logger.info("LED set to yellow: Pre-flight checks in progress.")

    start_time = time.time()

    try:
        # Check if global position check is required
        if Params.REQUIRE_GLOBAL_POSITION:
            async for health in drone.telemetry.health():
                if health.is_global_position_ok and health.is_home_position_ok:
                    logger.info("Global position estimate and home position check passed.")
                    # Get home position
                    async for position in drone.telemetry.position():
                        home_position = position
                        logger.info(f"Home Position set to: Latitude={home_position.latitude_deg}, "
                                    f"Longitude={home_position.longitude_deg}, Altitude={home_position.absolute_altitude_m}m")
                        break

                    if home_position is None:
                        logger.error("Home position telemetry data is missing.")
                    break
                else:
                    if not health.is_global_position_ok:
                        logger.warning("Waiting for global position to be okay.")
                    if not health.is_home_position_ok:
                        logger.warning("Waiting for home position to be set.")

                if time.time() - start_time > Params.PRE_FLIGHT_TIMEOUT:
                    logger.error("Pre-flight checks timed out.")
                    led_controller.set_color(255, 0, 0)  # Red
                    raise TimeoutError("Pre-flight checks timed out.")
                await asyncio.sleep(1)

            if home_position:
                logger.info("Pre-flight checks successful.")
                led_controller.set_color(0, 255, 0)  # Green
            else:
                logger.error("Pre-flight checks failed.")
                led_controller.set_color(255, 0, 0)  # Red
                raise Exception("Pre-flight checks failed.")

            # Now calculate the NED origin based on the home position and the NED position
            current_gps = (home_position.latitude_deg, home_position.longitude_deg, home_position.absolute_altitude_m)
            async for ned_position in drone.telemetry.position_velocity_ned():
                ned_origin = calculate_ned_origin(current_gps, (ned_position.position.north_m, ned_position.position.east_m, ned_position.position.down_m))
                logger.info(f"NED Origin calculated: Latitude={ned_origin[0]}, Longitude={ned_origin[1]}, Altitude={ned_origin[2]}m")
                return ned_origin

        else:
            # If global position check is not required, log and continue
            logger.info("Skipping global position check as per configuration.")
            led_controller.set_color(0, 255, 0)  # Green
            return None

    except Exception:
        logger.exception("Error during pre-flight checks.")
        led_controller.set_color(255, 0, 0)  # Red
        raise
