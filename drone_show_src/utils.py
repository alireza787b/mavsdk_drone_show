# drone_show_src/utils.py

import os
import sys
import glob
import logging
import logging.handlers
import navpy
from datetime import datetime
from src.params import Params


from mavsdk.offboard import PositionNedYaw

import numpy as np

def calculate_ned_origin(current_gps, ned_position):
    """
    Calculate the GPS coordinates of the NED origin based on the current position
    and local NED position.

    Args:
        current_gps (tuple): Current GPS position (latitude, longitude, altitude) in degrees and meters.
        ned_position (tuple): Current NED position (North, East, Down) in meters.

    Returns:
        tuple: Origin latitude, longitude, and altitude (in meters).
    """
    lat, lon, alt = current_gps
    north, east, down = ned_position

    # Convert current GPS to ECEF coordinates (Earth Centered, Earth Fixed)
    ecef_current = navpy.geodetic2ecef(lat, lon, alt)
    
    # Calculate the ECEF position of the NED origin
    ecef_origin = ecef_current - np.array([north, east, down])

    # Convert back to geodetic coordinates (latitude, longitude, altitude)
    lat_origin, lon_origin, alt_origin = navpy.ecef2geodetic(ecef_origin)

    return lat_origin, lon_origin, alt_origin



def configure_logging():
    """
    Configures logging for the script, ensuring logs are written to a per-session file
    and displayed on the console. It also limits the number of log files to MAX_LOG_FILES.
    """
    # Check if the root logger already has handlers configured
    if logging.getLogger().hasHandlers():
        return

    # Create logs directory if it doesn't exist
    logs_directory = os.path.join("..", "logs", "offboard_mission_logs")
    os.makedirs(logs_directory, exist_ok=True)

    # Configure the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Create formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)  # Adjust as needed
    console_handler.setFormatter(formatter)

    # Create file handler with per-session log file
    session_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = f"offboard_mission_{session_time}.log"
    log_file = os.path.join(logs_directory, log_filename)
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # Add handlers to the root logger
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # Limit the number of log files
    limit_log_files(logs_directory, Params.MAX_LOG_FILES)

def limit_log_files(logs_directory, max_files):
    """
    Limits the number of log files in the specified directory to the max_files.
    Deletes the oldest files when the limit is exceeded.

    Args:
        logs_directory (str): Path to the logs directory.
        max_files (int): Maximum number of log files to keep.
    """
    logger = logging.getLogger(__name__)
    try:
        log_files = [os.path.join(logs_directory, f) for f in os.listdir(logs_directory) if os.path.isfile(os.path.join(logs_directory, f))]
        if len(log_files) > max_files:
            # Sort files by creation time
            log_files.sort(key=os.path.getctime)
            files_to_delete = log_files[:len(log_files) - max_files]
            for file_path in files_to_delete:
                os.remove(file_path)
                logger.info(f"Deleted old log file: {file_path}")
    except Exception:
        logger.exception("Error limiting log files")

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
        # Reference LLA from home position
        lla_ref = [
            home_position.latitude_deg,
            home_position.longitude_deg,
            home_position.absolute_altitude_m,
        ]
        # Current LLA from global position
        lla = [
            global_position.latitude_deg,
            global_position.longitude_deg,
            global_position.absolute_altitude_m,
        ]

        ned = navpy.lla2ned(
            lla[0],
            lla[1],
            lla[2],
            lla_ref[0],
            lla_ref[1],
            lla_ref[2],
            latlon_unit="deg",
            alt_unit="m",
            model="wgs84",
        )

        # Return the local position with yaw set to 0.0
        return PositionNedYaw(ned[0], ned[1], ned[2], 0.0)
    except Exception:
        logger.exception("Error converting global to local coordinates")
        return PositionNedYaw(0.0, 0.0, 0.0, 0.0)
