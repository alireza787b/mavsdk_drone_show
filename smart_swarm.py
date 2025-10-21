# smart_swarm/smart_swarm.py

"""
===========================================================================
 Project: MavSDK Drone Show (smart_swarm)
 Repository: https://github.com/the-mak-00/mavsdk_drone_show
 
 Description:
   This project implements a smart swarm control system using MAVSDK, designed
   to operate drones in a coordinated formation. The system distinguishes
   between leader and follower drones based on configuration CSV files. Followers
   receive state updates from the leader, process these with a Kalman filter, and
   compute velocity commands using a PD controller (with low-pass filtering).
   The code is built using Python's asyncio framework for concurrent tasks such as
   state updates, control loops, and dynamic configuration updates.

 Features:
   - Reads drone and swarm configuration from CSV files.
   - Dynamically updates swarm configuration (role, formation offsets, etc.) during flight.
   - Integrates a primary (telemetry API) and a fallback (HTTP API) source for fetching
     the drone's GPS global origin.
   - Manages MAVSDK server startup and logs its output asynchronously.
   - Implements a robust offboard control loop with failsafe mechanisms.
   - Uses detailed logging for all operations, including error handling and dynamic
     configuration changes.
   - Modular design: Separate functions for initialization, state updates, control loop,
     failsafe procedures, and periodic configuration re-reads.

 Workflow:
   1. Initialization:
      - Read the hardware ID from a .hwID file.
      - Load drone configuration from config.csv and swarm configuration from swarm.csv.
      - Determine if the drone is operating as a Leader or Follower.
      - Set formation offsets and body coordinate mode based on the swarm configuration.
      - For followers, extract leader information and initialize a Kalman filter.
   
   2. MAVSDK Server & Drone Connection:
      - Start the MAVSDK server and ensure it is running.
      - Initialize the drone and perform pre-flight checks (global position and home position).
      - Fetch the drone's home position using a primary (telemetry) and a fallback (HTTP) API.
      - Set the reference position for NED coordinate conversion.
   
   3. Dynamic Configuration Update:
      - A periodic task (update_swarm_config_periodically) re-reads the swarm CSV at a defined
        interval to detect any configuration changes (role, offsets, etc.).
      - On detecting changes:
          * If switching from follower to leader, the follower tasks are cancelled.
          * If switching from leader to follower, the appropriate follower tasks are started.
          * Formation offsets and coordinate flags are updated accordingly.
   
   4. Control Loop & Failsafe:
      - For followers, a control loop computes desired velocities based on the predicted leader state
        and sends commands via offboard control.
      - If leader data becomes stale or an error occurs, a failsafe procedure is activated.
   
   5. Shutdown:
      - On termination, all periodic tasks and follower tasks are cleanly cancelled.
      - The MAVSDK server is properly shutdown.

 Developer & Contact Information:
   - Author: Alireza Ghaderi
   - GitHub: https://github.com/alireza787b
   - LinkedIn: https://www.linkedin.com/in/alireza787b
   - Email: p30planets@gmail.com

 Notes:
   - The project is part of the "mavsdk_drone_show" repository.
   - Future improvements may include replacing the CSV-based configuration update with a
     direct query to a Ground Control Station (GCS) endpoint.
   - This file serves as the central orchestrator for the swarm behavior and leverages
     several modules (e.g., Kalman filter, PD controller, LED controller) for a modular
     and maintainable code base.
===========================================================================
"""


import os
import sys
import time
import asyncio
import csv
import subprocess
import logging
import logging.handlers
import socket
import psutil
import argparse
from datetime import datetime
from collections import namedtuple
from mavsdk import System
from mavsdk.offboard import PositionNedYaw, VelocityBodyYawspeed, VelocityNedYaw, OffboardError
from mavsdk.action import ActionError
from tenacity import retry, stop_after_attempt, wait_fixed
import navpy
import requests
import numpy as np  # Added for numerical computations

from src.led_controller import LEDController
from src.params import Params
import aiohttp 

from smart_swarm_src.kalman_filter import LeaderKalmanFilter
from smart_swarm_src.pd_controller import PDController  # New import
from smart_swarm_src.low_pass_filter import LowPassFilter  # New import
from smart_swarm_src.utils import (
    transform_body_to_nea,
    is_data_fresh,
    fetch_home_position,
    lla_to_ned
)

from drone_show_src.utils import configure_logging

# ----------------------------- #
#        Data Structures        #
# ----------------------------- #

DroneConfig = namedtuple(
    "DroneConfig", "hw_id pos_id x y ip mavlink_port debug_port gcs_ip"
)

SwarmConfig = namedtuple(
    "SwarmConfig", "hw_id follow offset_n offset_e offset_alt body_coord"
)

# ----------------------------- #
#        Global Variables       #
# ----------------------------- #

HW_ID = None  # Hardware ID of the drone
DRONE_CONFIG = {}  # Drone configurations from config.csv
SWARM_CONFIG = {}  # Swarm configurations from swarm.csv
DRONE_STATE = {}  # Own drone's state
LEADER_STATE = {}  # Leader drone's state
OWN_STATE = {}  # Own drone's NED state
IS_LEADER = False  # Flag indicating if this drone is a leader
OFFSETS = {'n': 0.0, 'e': 0.0, 'alt': 0.0}  # Offsets from the leader
BODY_COORD = False  # Flag indicating if offsets are in body coordinates
LEADER_HW_ID = None  # Hardware ID of the leader drone
LEADER_IP = None  # IP address of the leader drone
LEADER_KALMAN_FILTER = None  # Kalman filter instance for leader state estimation
LEADER_HOME_POS = None  # Home position of the leader drone
OWN_HOME_POS = None  # Home position of own drone
REFERENCE_POS = None  # Reference position (latitude, longitude, altitude)


DRONE_INSTANCE = None  # MAVSDK drone instance
FOLLOWER_TASKS = {}  # Dictionary to hold tasks for follower mode (leader update, state update, control loop)

leader_unreachable_count = 0  # Initialize the counter for failed leader fetch attempts
max_unreachable_attempts = Params.MAX_LEADER_UNREACHABLE_ATTEMPTS  # Set the max retries before leader election

# for leader-election cooldown
last_election_time = 0.0


# ----------------------------- #
#         Helper Functions      #
# ----------------------------- #


def parse_float(field_value, default=0.0):
    """
    Safely convert a field value to float. If it's missing or invalid, log a warning and return default.
    """
    logger = logging.getLogger(__name__)
    try:
        return float(field_value)
    except (TypeError, ValueError):
        logger.warning(f"parse_float: Invalid or missing value '{field_value}', using default={default}")
        return default

# Legacy configure_logging function - now using shared one from drone_show_src.utils
# def configure_logging():
#     """
#     Configures logging for the script, ensuring logs are written to a per-session file
#     and displayed on the console. It also limits the number of log files.
#     """
#     # Create logs directory if it doesn't exist
#     logs_directory = os.path.join("..", "logs", "smart_swarm_logs")
#     os.makedirs(logs_directory, exist_ok=True)
#
#     # Configure the root logger
#     root_logger = logging.getLogger()
#     root_logger.setLevel(logging.DEBUG)
#
#     # Create formatter
#     formatter = logging.Formatter(
#         fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
#         datefmt="%Y-%m-%d %H:%M:%S"
#     )
#
#     # Create console handler
#     console_handler = logging.StreamHandler(sys.stdout)
#     console_handler.setLevel(logging.DEBUG)  # Adjust as needed
#     console_handler.setFormatter(formatter)
#
#     # Create file handler with per-session log file
#     session_time = datetime.now().strftime("%Y%m%d_%H%M%S")
#     log_filename = f"smart_swarm_{session_time}.log"
#     log_file = os.path.join(logs_directory, log_filename)
#     file_handler = logging.FileHandler(log_file)
#     file_handler.setLevel(logging.DEBUG)
#     file_handler.setFormatter(formatter)
#
#     # Add handlers to the root logger
#     root_logger.addHandler(console_handler)
#     root_logger.addHandler(file_handler)
#
#     # Limit the number of log files TODO!
#     #limit_log_files(logs_directory, MAX_LOG_FILES)

def read_hw_id() -> int:
    """
    Read the hardware ID from a file with the extension '.hwID'.

    Returns:
        int: Hardware ID if found, else None.
    """
    logger = logging.getLogger(__name__)
    # Adjust the path to look for the hwID file in the same directory as the script
    hwid_files = [f for f in os.listdir('.') if f.endswith('.hwID')]
    if hwid_files:
        filename = hwid_files[0]
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

def read_config_csv(filename: str):
    """
    Reads the drone configurations from the config CSV file and populates DRONE_CONFIG.

    Args:
        filename (str): Path to the config CSV file.
    """
    logger = logging.getLogger(__name__)
    global DRONE_CONFIG
    try:
        with open(filename, newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                try:
                    hw_id = str(int(row["hw_id"]))
                    DRONE_CONFIG[hw_id] = {
                        'hw_id': hw_id,
                        'pos_id': int(row["pos_id"]),
                        'x': float(row["x"]),
                        'y': float(row["y"]),
                        'ip': row["ip"],
                        'mavlink_port': int(row["mavlink_port"]),
                        'debug_port': int(row["debug_port"]),
                        'gcs_ip': row["gcs_ip"],
                    }
                except ValueError as ve:
                    logger.error(f"Invalid data type in config file row: {row}. Error: {ve}")
        logger.info(f"Read {len(DRONE_CONFIG)} drone configurations from '{filename}'.")
    except FileNotFoundError:
        logger.exception(f"Config file '{filename}' not found.")
        sys.exit(1)
    except Exception:
        logger.exception(f"Error reading config file '{filename}'.")
        sys.exit(1)

def read_swarm_csv(filename: str):
    """
    Reads the swarm configurations from the swarm CSV file and populates SWARM_CONFIG.

    Args:
        filename (str): Path to the swarm CSV file.
    """
    logger = logging.getLogger(__name__)
    global SWARM_CONFIG
    try:
        with open(filename, newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                try:
                    hw_id = str(int(row["hw_id"]))
                    SWARM_CONFIG[hw_id] = {
                        'hw_id': hw_id,
                        'follow': row["follow"],
                        'offset_n': float(row["offset_n"]),
                        'offset_e': float(row["offset_e"]),
                        'offset_alt': float(row["offset_alt"]),
                        'body_coord': row["body_coord"] == '1',
                    }
                except ValueError as ve:
                    logger.error(f"Invalid data type in swarm file row: {row}. Error: {ve}")
        logger.info(f"Read {len(SWARM_CONFIG)} swarm configurations from '{filename}'.")
    except FileNotFoundError:
        logger.exception(f"Swarm file '{filename}' not found.")
        sys.exit(1)
    except Exception:
        logger.exception(f"Error reading swarm file '{filename}'.")
        sys.exit(1)

def get_mavsdk_server_path():
    """
    Constructs the absolute path to the mavsdk_server executable.

    Returns:
        str: Path to mavsdk_server.
    """
    home_dir = os.path.expanduser("~")
    mavsdk_drone_show_dir = os.path.join(home_dir, "mavsdk_drone_show")
    mavsdk_server_path = os.path.join(mavsdk_drone_show_dir, "mavsdk_server")
    return mavsdk_server_path

# ----------------------------- #
#       MAVSDK Server Control   #
# ----------------------------- #

def start_mavsdk_server(udp_port: int):
    """
    Start MAVSDK server instance for the drone.

    Args:
        udp_port (int): UDP port for MAVSDK server communication.

    Returns:
        subprocess.Popen: MAVSDK server subprocess if started successfully, else None.
    """
    logger = logging.getLogger(__name__)
    try:
        # Check if MAVSDK server is already running
        is_running, pid = check_mavsdk_server_running(Params.DEFAULT_GRPC_PORT)
        if is_running:
            logger.info(f"MAVSDK server already running on port {Params.DEFAULT_GRPC_PORT}. Terminating...")
            try:
                psutil.Process(pid).terminate()
                psutil.Process(pid).wait(timeout=5)
                logger.info(f"Terminated existing MAVSDK server with PID: {pid}")
            except psutil.NoSuchProcess:
                logger.warning(f"No process found with PID: {pid} to terminate.")
            except psutil.TimeoutExpired:
                logger.warning(f"Process with PID: {pid} did not terminate gracefully. Killing it.")
                psutil.Process(pid).kill()
                psutil.Process(pid).wait()
                logger.info(f"Killed MAVSDK server with PID: {pid}")

        # Construct the absolute path to mavsdk_server
        mavsdk_server_path = get_mavsdk_server_path()

        logger.debug(f"Constructed MAVSDK server path: {mavsdk_server_path}")

        if not os.path.isfile(mavsdk_server_path):
            logger.error(f"mavsdk_server executable not found at '{mavsdk_server_path}'.")
            sys.exit(1)  # Exit the program as the server is essential

        if not os.access(mavsdk_server_path, os.X_OK):
            logger.info(f"Setting executable permissions for '{mavsdk_server_path}'.")
            os.chmod(mavsdk_server_path, 0o755)

        # Start the MAVSDK server
        mavsdk_server = subprocess.Popen(
            [mavsdk_server_path, "-p", str(Params.DEFAULT_GRPC_PORT), f"udp://:{udp_port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        logger.info(
            f"MAVSDK server started with gRPC port {Params.DEFAULT_GRPC_PORT} and UDP port {udp_port}."
        )

        # Optionally, you can start logging the MAVSDK server output asynchronously
        asyncio.create_task(log_mavsdk_output(mavsdk_server))

        # Wait until the server is listening on the gRPC port
        if not wait_for_port(Params.DEFAULT_GRPC_PORT, timeout=Params.PRE_FLIGHT_TIMEOUT):
            logger.error(f"MAVSDK server did not start listening on port {Params.DEFAULT_GRPC_PORT} within timeout.")
            mavsdk_server.terminate()
            return None

        logger.info("MAVSDK server is now listening on gRPC port.")
        return mavsdk_server

    except FileNotFoundError:
        logger.error("mavsdk_server executable not found. Ensure it is present in the specified directory.")
        return None
    except Exception:
        logger.exception("Error starting MAVSDK server")
        return None

def check_mavsdk_server_running(port):
    """
    Checks if the MAVSDK server is running on the specified gRPC port.

    Args:
        port (int): The gRPC port to check.

    Returns:
        tuple: (is_running (bool), pid (int or None))
    """
    logger = logging.getLogger(__name__)
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            for conn in proc.net_connections(kind='inet'):
                if conn.laddr.port == port:
                    return True, proc.info['pid']
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False, None

def wait_for_port(port, host='localhost', timeout=Params.PRE_FLIGHT_TIMEOUT):
    """
    Wait until a port starts accepting TCP connections.

    Args:
        port (int): The port to check.
        host (str): The hostname to check.
        timeout (float): The maximum time to wait in seconds.

    Returns:
        bool: True if the port is open, False if the timeout was reached.
    """
    start_time = time.time()
    while True:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            if time.time() - start_time >= timeout:
                return False
            time.sleep(0.1)

async def log_mavsdk_output(mavsdk_server):
    """
    Asynchronously logs the stdout and stderr of the MAVSDK server.

    Args:
        mavsdk_server (subprocess.Popen): The subprocess running the MAVSDK server.
    """
    logger = logging.getLogger(__name__)
    try:
        while True:
            line = await asyncio.get_event_loop().run_in_executor(None, mavsdk_server.stdout.readline)
            if not line:
                break
            logger.debug(f"MAVSDK Server: {line.decode().strip()}")
    except Exception:
        logger.exception("Error while reading MAVSDK server stdout")

    try:
        while True:
            line = await asyncio.get_event_loop().run_in_executor(None, mavsdk_server.stderr.readline)
            if not line:
                break
            logger.error(f"MAVSDK Server Error: {line.decode().strip()}")
    except Exception:
        logger.exception("Error while reading MAVSDK server stderr")

def stop_mavsdk_server(mavsdk_server):
    """
    Stop the MAVSDK server instance.

    Args:
        mavsdk_server (subprocess.Popen): MAVSDK server subprocess.
    """
    logger = logging.getLogger(__name__)
    try:
        if mavsdk_server.poll() is None:
            logger.info("Stopping MAVSDK server...")
            mavsdk_server.terminate()
            try:
                mavsdk_server.wait(timeout=5)
                logger.info("MAVSDK server terminated gracefully.")
            except subprocess.TimeoutExpired:
                logger.warning("MAVSDK server did not terminate gracefully. Killing it.")
                mavsdk_server.kill()
                mavsdk_server.wait()
                logger.info("MAVSDK server killed forcefully.")
        else:
            logger.debug("MAVSDK server has already terminated.")
    except Exception:
        logger.exception("Error stopping MAVSDK server")


async def update_swarm_config_periodically(drone):
    """
    Periodically fetches the swarm configuration from the GCS API endpoint and updates
    global parameters such as role, formation offsets, and leader information.

    If a role change is detected (e.g., switching from follower to leader or vice versa),
    it starts or cancels follower-specific tasks accordingly.

    NOTE: Requires DRONE_CONFIG[HW_ID]['gcs_ip'] and Params.flask_telem_socket_port to be set.
    """
    global SWARM_CONFIG, IS_LEADER, OFFSETS, BODY_COORD
    global LEADER_HW_ID, LEADER_IP, LEADER_KALMAN_FILTER, FOLLOWER_TASKS
    global HW_ID

    logger = logging.getLogger(__name__)

    # Resolve the GCS endpoint for this drone
    str_HW_ID = str(HW_ID)
    drone_cfg = DRONE_CONFIG.get(str_HW_ID)
    if not drone_cfg or 'gcs_ip' not in drone_cfg:
        logger.error(f"[Periodic Update] Cannot resolve GCS IP for HW_ID={HW_ID}")
        return

    gcs_ip = drone_cfg['gcs_ip']
    state_url = f"http://{gcs_ip}:{Params.flask_telem_socket_port}/get-swarm-data"

    # Shared session for connection reuse
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                logger.info("[Periodic Update] Checking swarm configuration")
                # Fetch JSON list of swarm entries
                async with session.get(state_url) as resp:
                    resp.raise_for_status()
                    api_data = await resp.json()

                # Rebuild our in-memory SWARM_CONFIG
                SWARM_CONFIG.clear()
                for entry in api_data:
                    hw_str = str(entry['hw_id'])

                    # Safely parse each offset
                    offset_n_val   = parse_float(entry.get('offset_n', None), default=0.0)
                    offset_e_val   = parse_float(entry.get('offset_e', None), default=0.0)
                    offset_alt_val = parse_float(entry.get('offset_alt', None), default=0.0)

                    SWARM_CONFIG[hw_str] = {
                        'follow':     entry.get('follow', '0'),
                        'offset_n':   offset_n_val,
                        'offset_e':   offset_e_val,
                        'offset_alt': offset_alt_val,
                        'body_coord': entry.get('body_coord', '0') == '1',
                    }

                # Grab this drone's new config
                new_cfg = SWARM_CONFIG.get(str(HW_ID))
                if new_cfg is None:
                    logger.error(f"[Periodic Update] No swarm entry for HW_ID={HW_ID}")
                else:
                    # Determine new role/offsets/body_coord
                    new_offsets     = {
                        'n':   new_cfg['offset_n'],
                        'e':   new_cfg['offset_e'],
                        'alt': new_cfg['offset_alt']
                    }
                    new_body_coord  = new_cfg['body_coord']
                    new_leader      = new_cfg['follow']
                    new_is_leader   = (new_leader == '0')

                    # ROLE CHANGE?
                    if new_is_leader != IS_LEADER:
                        logger.info(
                            "[Periodic Update] Role change: %s → %s",
                            "Leader" if IS_LEADER else "Follower",
                            "Leader" if new_is_leader else "Follower"
                        )
                        IS_LEADER = new_is_leader

                        if IS_LEADER:
                            # Cancel any running follower tasks
                            if FOLLOWER_TASKS:
                                logger.info("[Periodic Update] Cancelling follower tasks.")
                                for task in FOLLOWER_TASKS.values():
                                    if not task.done():
                                        task.cancel()
                                FOLLOWER_TASKS.clear()
                        else:
                            # Start follower tasks under new leader
                            if not FOLLOWER_TASKS:
                                LEADER_HW_ID = new_cfg['follow']
                                leader_cfg = DRONE_CONFIG.get(LEADER_HW_ID)
                                if not leader_cfg:
                                    logger.error(
                                        "[Periodic Update] Leader config missing for HW_ID=%s",
                                        LEADER_HW_ID
                                    )
                                else:
                                    LEADER_IP             = leader_cfg['ip']
                                    LEADER_KALMAN_FILTER  = LeaderKalmanFilter()
                                    logger.info("[Periodic Update] Launching follower tasks.")
                                    FOLLOWER_TASKS['leader_update_task'] = asyncio.create_task(update_leader_state())
                                    FOLLOWER_TASKS['own_state_task']    = asyncio.create_task(update_own_state(drone))
                                    FOLLOWER_TASKS['control_task']      = asyncio.create_task(control_loop(drone))

                    # Handle leader change if drone is a follower
                    if not new_is_leader:
                        if new_leader != LEADER_HW_ID:
                            logger.info(f"[Periodic Update] Leader change detected. Following new leader {new_leader}.")
                            LEADER_HW_ID = new_leader
                            leader_cfg = DRONE_CONFIG.get(LEADER_HW_ID)
                            if not leader_cfg:
                                logger.error("[Periodic Update] Leader config missing for HW_ID=%s", LEADER_HW_ID)
                            else:
                                LEADER_IP = leader_cfg['ip']
                                logger.info(f"[Periodic Update] Following new leader at {LEADER_IP}")
                                # You can add any logic to update tasks or behavior based on new leader here.

                    # OFFSET CHANGE?
                    if new_offsets != OFFSETS:
                        logger.info(
                            "[Periodic Update] Offsets changed: %s → %s",
                            OFFSETS, new_offsets
                        )
                        OFFSETS.update(new_offsets)

                    # BODY_COORD CHANGE?
                    if new_body_coord != BODY_COORD:
                        logger.info(
                            "[Periodic Update] Body coord flag: %s → %s",
                            BODY_COORD, new_body_coord
                        )
                        BODY_COORD = new_body_coord

            except Exception as e:
                logger.exception(f"[Periodic Update] Error fetching/updating swarm config: {e}")

            # Wait before next poll
            await asyncio.sleep(Params.CONFIG_UPDATE_INTERVAL)



# ----------------------------- #
#    Leader State Update Task   #
# ----------------------------- #

async def update_leader_state():
    """
    Periodically fetches the leader's state and updates the Kalman filter.
    """
    logger = logging.getLogger(__name__)
    global LEADER_STATE, LEADER_KALMAN_FILTER, LEADER_IP
    global leader_unreachable_count, max_unreachable_attempts

    update_interval = 1.0 / Params.LEADER_UPDATE_FREQUENCY
    last_update_time = None

    while True:
        try:
            state_url = f"http://{LEADER_IP}:{Params.drones_flask_port}/{Params.get_drone_state_URI}"
            response = requests.get(state_url, timeout=1)
            if response.status_code == 200:
                # reset on success
                leader_unreachable_count = 0

                data = response.json()
                leader_update_time = data.get('update_time', None)
                if leader_update_time and leader_update_time != last_update_time:
                    last_update_time = leader_update_time

                    # Convert lat/lon/alt to NED
                    leader_n, leader_e, leader_d = lla_to_ned(
                        data['position_lat'], data['position_long'], data['position_alt'],
                        REFERENCE_POS['latitude'], REFERENCE_POS['longitude'], REFERENCE_POS['altitude']
                    )

                    # Update raw LEADER_STATE
                    LEADER_STATE.update({
                        'pos_n': leader_n,
                        'pos_e': leader_e,
                        'pos_d': leader_d,
                        'vel_n': data['velocity_north'],
                        'vel_e': data['velocity_east'],
                        'vel_d': data['velocity_down'],
                        'yaw':   data.get('yaw', 0.0),
                        'update_time': leader_update_time
                    })

                    # Kalman filter update
                    measurement = {
                        'pos_n': leader_n,
                        'pos_e': leader_e,
                        'pos_d': leader_d,
                        'vel_n': data['velocity_north'],
                        'vel_e': data['velocity_east'],
                        'vel_d': data['velocity_down'],
                    }
                    LEADER_KALMAN_FILTER.update(measurement, leader_update_time)

                    logger.debug(f"Leader @ {leader_update_time:.3f}s: {measurement}")
                    logger.debug(f"Kalman state: {LEADER_KALMAN_FILTER.get_state()}")
                else:
                    logger.error("Leader response missing or unchanged 'update_time'.")
            else:
                logger.error(f"Failed to fetch leader state: HTTP {response.status_code}")
                leader_unreachable_count += 1
                if leader_unreachable_count >= max_unreachable_attempts:
                    logger.warning(
                        f"Leader unreachable for {leader_unreachable_count} attempts. Electing new leader."
                    )
                    await elect_new_leader()

        except Exception as e:
            leader_unreachable_count += 1
            if leader_unreachable_count >= max_unreachable_attempts:
                logger.warning(
                    f"Leader unreachable for {leader_unreachable_count} attempts. Electing new leader."
                )
                await elect_new_leader()

        await asyncio.sleep(update_interval)

        
async def elect_new_leader():
    """
    Elect a new leader when the current leader is unreachable.
    - Enforces a cooldown.
    - Picks the very next HW_ID (wrapping) in numeric order.
    - If that ID == self, self-promote: set role=0, cancel followers, stop offboard & HOLD.
    - Otherwise, notify GCS; if accepted, commit new leader IP & reset counters/filters.

    TODO: Later detect/prevent cycles of intermediate leaders.
    """
    global last_election_time
    global SWARM_CONFIG, LEADER_HW_ID, LEADER_IP
    global leader_unreachable_count, LEADER_KALMAN_FILTER
    global IS_LEADER, FOLLOWER_TASKS, DRONE_INSTANCE

    now = time.time()
    # Cooldown guard
    if now - last_election_time < Params.LEADER_ELECTION_COOLDOWN:
        logging.getLogger(__name__).debug(
            f"Election skipped; only {now-last_election_time:.1f}s since last "
            f"(<{Params.LEADER_ELECTION_COOLDOWN}s cooldown)."
        )
        return
    last_election_time = now

    logger = logging.getLogger(__name__)
    old_leader = LEADER_HW_ID
    old_follow  = SWARM_CONFIG[str(HW_ID)]['follow']

    # Build sorted list of all drone IDs
    all_ids = sorted(int(k) for k in SWARM_CONFIG.keys())
    # Find index of current leader (or -1 if unknown)
    current_idx = all_ids.index(int(old_leader)) if old_leader and int(old_leader) in all_ids else -1

    # Compute the next candidate (wrap-around)
    next_idx = (current_idx + 1) % len(all_ids)
    candidate = all_ids[next_idx]
    logger.info(f"Election candidate based on offset: {candidate}")

    # Self-promotion if candidate == self
    if candidate == HW_ID:
        logger.info("Candidate is self → self-promoting to leader and entering HOLD mode.")
        # Update manifest
        SWARM_CONFIG[str(HW_ID)]['follow'] = '0'
        # Notify GCS (best-effort)
        try:
            await notify_gcs_of_leader_change('0')
        except Exception:
            logger.warning("GCS notify failed for self-promotion.")
        # Flip role
        IS_LEADER = True
        LEADER_HW_ID = None
        LEADER_IP     = None
        leader_unreachable_count = 0
        # Cancel follower tasks
        for task in FOLLOWER_TASKS.values():
            if not task.done():
                task.cancel()
        FOLLOWER_TASKS.clear()
        # Stop offboard and HOLD
        try:
            await DRONE_INSTANCE.offboard.stop()
            await DRONE_INSTANCE.action.hold()
            logger.info("Offboard stopped; drone set to HOLD.")
        except Exception as e:
            logger.error(f"Error during HOLD mode: {e}")
        return

    # Otherwise, propose this candidate as new leader
    new_leader = str(candidate)
    logger.info(f"Proposed new leader: {new_leader}")

    # Stage locally
    SWARM_CONFIG[str(HW_ID)]['follow'] = new_leader

    # Notify GCS
    accepted = await notify_gcs_of_leader_change(new_leader)
    if accepted:
        # Commit: switch IP, reset Kalman filter & counter
        LEADER_HW_ID = new_leader
        LEADER_IP     = DRONE_CONFIG[new_leader]['ip']
        leader_unreachable_count = 0
        LEADER_KALMAN_FILTER     = LeaderKalmanFilter()
        logger.info(f"Leader election committed: now following {new_leader} @ {LEADER_IP}")
    else:
        # Revert on rejection
        SWARM_CONFIG[str(HW_ID)]['follow'] = old_follow
        logger.warning(f"Leader election aborted; staying with {old_leader}")



    
    
async def notify_gcs_of_leader_change(new_leader_hw_id: str) -> bool:
    """
    Notify the GCS of our updated leader by sending only our own swarm entry.
    Returns True if the GCS accepted the change, False otherwise.
    """
    logger = logging.getLogger(__name__)

    gcs_ip = DRONE_CONFIG[str(HW_ID)]['gcs_ip']
    notify_url = f"http://{gcs_ip}:{Params.flask_telem_socket_port}/request-new-leader"

    current = SWARM_CONFIG.get(str(HW_ID))
    if not current:
        logger.error(f"No SWARM_CONFIG entry for HW_ID={HW_ID}")
        return False

    payload = {
        'hw_id':       str(HW_ID),
        'follow':      new_leader_hw_id,
        'offset_n':    current['offset_n'],
        'offset_e':    current['offset_e'],
        'offset_alt':  current['offset_alt'],
        'body_coord':  '1' if current['body_coord'] else '0'
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(notify_url, json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()
                if data.get('status') == 'success':
                    logger.info(f"GCS accepted leader change for HW_ID={HW_ID}")
                    return True
                else:
                    logger.warning(f"GCS rejected leader change: {data}")
                    return False
    except Exception as e:
        logger.error(f"Error notifying GCS of leader change for HW_ID={HW_ID}: {e}")
        return False

        logger.error(f"Error notifying GCS of leader change for HW_ID {HW_ID}: {e}")




# ----------------------------- #
#    Own State Update Task      #
# ----------------------------- #

async def update_own_state(drone: System):
    """
    Periodically updates the own drone's state.
    """
    logger = logging.getLogger(__name__)
    global OWN_STATE
    try:
        async for position_velocity in drone.telemetry.position_velocity_ned():
            position = position_velocity.position
            velocity = position_velocity.velocity
            OWN_STATE['pos_n'] = position.north_m
            OWN_STATE['pos_e'] = position.east_m
            OWN_STATE['pos_d'] = position.down_m
            OWN_STATE['vel_n'] = velocity.north_m_s
            OWN_STATE['vel_e'] = velocity.east_m_s
            OWN_STATE['vel_d'] = velocity.down_m_s
            OWN_STATE['timestamp'] = time.time()
    except Exception:
        logger.exception("Error in updating own state")

# ----------------------------- #
#          Control Loop         #
# ----------------------------- #

async def control_loop(drone: System):
    """
    Control loop that sends offboard setpoints to the drone based on the leader state.

    Args:
        drone (System): MAVSDK drone system instance.
    """
    logger = logging.getLogger(__name__)
    global LEADER_KALMAN_FILTER
    loop_interval = 1 / Params.CONTROL_LOOP_FREQUENCY
    led_controller = LEDController.get_instance()
    led_controller.set_color(0, 255, 0)  # Green to indicate control loop started

    stale_start_time = None
    stale_duration_threshold = Params.MAX_STALE_DURATION  # seconds

    # Initialize PD controller and low-pass filter
    kp = Params.PD_KP  # Proportional gain
    kd = Params.PD_KD  # Derivative gain
    max_velocity = Params.MAX_VELOCITY  # Maximum allowed velocity (m/s)
    alpha = Params.LOW_PASS_FILTER_ALPHA  # Smoothing factor for low-pass filter

    pd_controller = PDController(kp, kd, max_velocity)
    velocity_filter = LowPassFilter(alpha)

    previous_time = None

    try:
        while True:
            current_time = time.time()
            dt = current_time - previous_time if previous_time else loop_interval
            previous_time = current_time

            # Check data freshness
            if 'update_time' in LEADER_STATE and is_data_fresh(LEADER_STATE['update_time'], Params.DATA_FRESHNESS_THRESHOLD):
                stale_start_time = None
                # Predict leader state
                predicted_state = LEADER_KALMAN_FILTER.predict(current_time)
                # Extract predicted positions and velocities
                leader_n = predicted_state[0]
                leader_e = predicted_state[1]
                leader_d = predicted_state[2]
                leader_vel_n = predicted_state[3]
                leader_vel_e = predicted_state[4]
                leader_vel_d = predicted_state[5]
                leader_yaw = LEADER_STATE.get('yaw', 0.0)
                logger.debug(f"Predicted leader state at time {current_time:.3f}s: pos_n={leader_n:.2f}m, pos_e={leader_e:.2f}m, pos_d={leader_d:.2f}m, vel_n={leader_vel_n:.2f}m/s, vel_e={leader_vel_e:.2f}m/s, vel_d={leader_vel_d:.2f}m/s, yaw={leader_yaw:.2f}°")
                # Calculate offsets
                if BODY_COORD:
                    # Note: Although offsets are labeled as N and E, in body coordinate mode, they are Forward and Right
                    offset_n, offset_e = transform_body_to_nea(OFFSETS['n'], OFFSETS['e'], leader_yaw)
                    logger.debug(f"Offsets in body coordinates: Forward={OFFSETS['n']:.2f}m, Right={OFFSETS['e']:.2f}m, Transformed to NED: offset_n={offset_n:.2f}m, offset_e={offset_e:.2f}m")
                else:
                    offset_n, offset_e = OFFSETS['n'], OFFSETS['e']
                    logger.debug(f"Offsets in NED coordinates: offset_n={offset_n:.2f}m, offset_e={offset_e:.2f}m")
                
                logger.debug(f"Altitude offset: offset_alt={OFFSETS['alt']:.2f}m")
                
                # Desired positions
                desired_n = leader_n + offset_n
                desired_e = leader_e + offset_e
                desired_d = -1*(leader_d + OFFSETS['alt'])  
                logger.debug(f"Desired positions: desired_n={desired_n:.2f}m, desired_e={desired_e:.2f}m, desired_d={desired_d:.2f}m, yaw={leader_yaw:.2f}°")

                # Get own position
                current_n = OWN_STATE.get('pos_n', 0.0)
                current_e = OWN_STATE.get('pos_e', 0.0)
                current_d = OWN_STATE.get('pos_d', 0.0)

                # Compute position error
                position_error = np.array([
                    desired_n - current_n,
                    desired_e - current_e,
                    desired_d - current_d
                ])

                # Compute velocity command using PD controller
                velocity_command = pd_controller.compute(position_error, dt)

                # Filter the velocity command
                filtered_velocity = velocity_filter.filter(velocity_command)

                # Send velocity command
                await drone.offboard.set_velocity_ned(VelocityNedYaw(
                    filtered_velocity[0],
                    filtered_velocity[1],
                    filtered_velocity[2],
                    leader_yaw
                ))
                logger.debug(f"Velocity command sent: {filtered_velocity}, yaw: {leader_yaw}")

            else:
                if stale_start_time is None:
                    stale_start_time = current_time
                elif (current_time - stale_start_time) >= stale_duration_threshold:
                    logger.warning(f"Leader data has been stale for over {stale_duration_threshold} seconds, executing failsafe.")
                    await execute_failsafe(drone)
            await asyncio.sleep(loop_interval)
    except asyncio.CancelledError:
        logger.info("Control loop cancelled.")
    except OffboardError as e:
        logger.error(f"Offboard error in control loop: {e}")
        await execute_failsafe(drone)
    except Exception:
        logger.exception("Unexpected error in control loop")
        await execute_failsafe(drone)

# ----------------------------- #
#         Failsafe Function     #
# ----------------------------- #

async def execute_failsafe(drone: System):
    """
    Executes a failsafe procedure, such as holding position or landing.

    Args:
        drone (System): MAVSDK drone system instance.
    """
    logger = logging.getLogger(__name__)
    led_controller = LEDController.get_instance()
    led_controller.set_color(255, 0, 0)  # Red to indicate failsafe
    try:
        # Hold position
        await drone.offboard.set_velocity_ned(VelocityNedYaw(0.0, 0.0, 0.0, 0.0))
        logger.info("Failsafe: Holding position.")
    except OffboardError as e:
        logger.error(f"Failsafe offboard error: {e}")
        # Attempt to re-start offboard mode
        try:
            await drone.offboard.stop()
            await drone.offboard.start()
        except Exception:
            logger.exception("Failed to restart offboard mode during failsafe.")
    except Exception:
        logger.exception("Unexpected error during failsafe procedure.")

# ----------------------------- #
#       Drone Initialization    #
# ----------------------------- #

@retry(stop=stop_after_attempt(Params.PREFLIGHT_MAX_RETRIES), wait=wait_fixed(2))
async def initialize_drone():
    """
    Initializes the drone connection, performs pre-flight checks, and starts offboard mode.

    Returns:
        drone (System): MAVSDK drone system instance.
    """
    logger = logging.getLogger(__name__)
    try:
        # Initialize LEDController
        led_controller = LEDController.get_instance()
        led_controller.set_color(0, 0, 255)  # Blue to indicate initialization


        # MAVSDK server is assumed to be running on localhost
        mavsdk_server_address = "127.0.0.1"

        # Create the drone system
        drone = System(mavsdk_server_address=mavsdk_server_address, port=Params.DEFAULT_GRPC_PORT)
        await drone.connect(system_address=f"udp://:{Params.mavsdk_port}")

        logger.info(
            f"Connecting to drone via MAVSDK server at {mavsdk_server_address}:{Params.DEFAULT_GRPC_PORT} on UDP port {Params.mavsdk_port}."
        )

        # Wait for connection with a timeout
        start_time = time.time()
        async for state in drone.core.connection_state():
            if state.is_connected:
                logger.info(
                    f"Drone connected via MAVSDK server at {mavsdk_server_address}:{Params.DEFAULT_GRPC_PORT}."
                )
                break
            if time.time() - start_time > Params.PRE_FLIGHT_TIMEOUT:
                logger.error("Timeout while waiting for drone connection.")
                led_controller.set_color(255, 0, 0)  # Red
                raise TimeoutError("Drone connection timeout.")
            await asyncio.sleep(1)

        # Perform pre-flight checks (only check for global and home position)
        logger.info("Performing pre-flight checks.")
        start_time = time.time()
        async for health in drone.telemetry.health():
            if health.is_global_position_ok and health.is_home_position_ok:
                logger.info("Global position estimate and home position check passed.")
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

        # Arm the drone and start offboard mode
        # TODO: Maybe do some checks later on here
        # logger.info("Arming drone.")
        # await drone.action.arm() # if not already arm (meaning we start on the ground)
        logger.info("Starting offboard mode.")
        # Send an initial setpoint before starting offboard mode
        await drone.offboard.set_velocity_body(VelocityBodyYawspeed(0.0, 0.0, 0.0, 0.0))
        await drone.offboard.start()
        led_controller.set_color(0, 255, 0)  # Green to indicate ready

        return drone
    except Exception:
        logger.exception("Error during drone initialization")
        raise

# ----------------------------- #
#         Main Runner           #
# ----------------------------- #

async def run_smart_swarm():
    """
    Main function to run the smart swarm mode with dynamic configuration updates.
    """
    logger = logging.getLogger(__name__)
    global HW_ID, DRONE_CONFIG, SWARM_CONFIG, IS_LEADER, OFFSETS, BODY_COORD, LEADER_HW_ID, LEADER_IP, LEADER_KALMAN_FILTER
    global LEADER_HOME_POS, OWN_HOME_POS, REFERENCE_POS

    # --------------------------- #
    #      Initialization         #
    # --------------------------- #

    # Read hardware ID from .hwID file
    HW_ID = read_hw_id()
    if HW_ID is None:
        logger.error("Hardware ID not found.")
        sys.exit(1)

    # Read configuration CSV files (choose simulation vs. real mode)
    config_filename = os.path.join('config_sitl.csv' if Params.sim_mode else 'config.csv')
    swarm_filename = os.path.join('swarm_sitl.csv' if Params.sim_mode else 'swarm.csv')
    read_config_csv(config_filename)
    read_swarm_csv(swarm_filename)

    # Get own drone configuration
    hw_id_str = str(HW_ID)
    drone_config = DRONE_CONFIG.get(hw_id_str)
    if drone_config is None:
        logger.error(f"Configuration for HW_ID {HW_ID} not found.")
        sys.exit(1)

    # Get swarm configuration for own drone
    swarm_config = SWARM_CONFIG.get(hw_id_str)
    if swarm_config is None:
        logger.error(f"Swarm configuration for HW_ID {HW_ID} not found.")
        sys.exit(1)

    # Determine drone role and set formation parameters
    IS_LEADER = swarm_config['follow'] == '0'
    OFFSETS['n'] = swarm_config['offset_n']
    OFFSETS['e'] = swarm_config['offset_e']
    OFFSETS['alt'] = swarm_config['offset_alt']
    BODY_COORD = swarm_config['body_coord']
    logger.info(f"Drone HW_ID {HW_ID} - Initial Role: {'Leader' if IS_LEADER else 'Follower'}, Offsets: {OFFSETS}, Body Coord: {BODY_COORD}")

    # For followers, set leader info and initialize Kalman filter; for leaders, simply log the role.
    if not IS_LEADER:
        LEADER_HW_ID = swarm_config['follow']
        leader_config = DRONE_CONFIG.get(LEADER_HW_ID)
        if leader_config is None:
            logger.error(f"Leader configuration for HW_ID {LEADER_HW_ID} not found.")
            sys.exit(1)
        LEADER_IP = leader_config['ip']
        LEADER_KALMAN_FILTER = LeaderKalmanFilter()
    else:
        logger.info("Operating in Leader mode.")

    # --------------------------- #
    #     Start MAVSDK Server     #
    # --------------------------- #

    mavsdk_server = start_mavsdk_server(Params.mavsdk_port)
    if mavsdk_server is None:
        logger.error("Failed to start MAVSDK server.")
        sys.exit(1)

    await asyncio.sleep(2)  # Allow server to initialize

    # --------------------------- #
    #      Drone Initialization   #
    # --------------------------- #

    try:
        drone = await initialize_drone()
        global DRONE_INSTANCE
        DRONE_INSTANCE = drone
    except Exception:
        logger.error("Failed to initialize drone.")
        sys.exit(1)

    # --------------------------- #
    #  Fetch Own Home Position    #
    # --------------------------- #
    # (Existing logic remains unchanged)
    telemetry_origin = None
    fallback_origin = None

    try:
        origin = await drone.telemetry.get_gps_global_origin()
        telemetry_origin = {
            'latitude': origin.latitude_deg,
            'longitude': origin.longitude_deg,
            'altitude': origin.altitude_m
        }
        logger.info(f"Retrieved GPS global origin from telemetry: {telemetry_origin}")
    except Exception as e:
        logger.warning(f"Telemetry GPS origin request failed: {e}")

    own_ip = '127.0.0.1'
    fallback_origin = fetch_home_position(own_ip, Params.drones_flask_port, Params.get_drone_gps_origin_URI)
    if fallback_origin is not None:
        logger.info(f"Retrieved GPS global origin from fallback API: {fallback_origin}")
    else:
        logger.warning("Fallback API did not return a valid GPS global origin.")

    if telemetry_origin is not None:
        OWN_HOME_POS = telemetry_origin
        logger.info(f"Using telemetry GPS origin as primary: {OWN_HOME_POS}")
    elif fallback_origin is not None:
        OWN_HOME_POS = fallback_origin
        logger.info(f"Using fallback API GPS origin: {OWN_HOME_POS}")
    else:
        logger.error("Both telemetry and fallback API failed to provide a valid GPS origin. Exiting.")
        sys.exit(1)

    REFERENCE_POS = {
        'latitude': OWN_HOME_POS['latitude'],
        'longitude': OWN_HOME_POS['longitude'],
        'altitude': OWN_HOME_POS['altitude'],
    }
    logger.info(f"Reference position set to: {REFERENCE_POS}")

    if not IS_LEADER:
        leader_home_pos = fetch_home_position(LEADER_IP, Params.drones_flask_port, Params.get_drone_home_URI)
        if leader_home_pos is None:
            logger.error("Failed to fetch leader's home position.")
            sys.exit(1)
        LEADER_HOME_POS = leader_home_pos
        logger.info(f"Leader's home position: {LEADER_HOME_POS}")

    # --------------------------- #
    #      Start Async Tasks      #
    # --------------------------- #

    # For followers, start the corresponding tasks and store them in FOLLOWER_TASKS
    if not IS_LEADER:
        FOLLOWER_TASKS['leader_update_task'] = asyncio.create_task(update_leader_state())
        FOLLOWER_TASKS['own_state_task'] = asyncio.create_task(update_own_state(drone))
        FOLLOWER_TASKS['control_task'] = asyncio.create_task(control_loop(drone))
    else:
        logger.info("No follower tasks started as drone is in Leader mode.")

    # Launch the periodic swarm configuration update task (applies to both roles)
    swarm_update_task = asyncio.create_task(update_swarm_config_periodically(drone))
    logger.info(f"[Main] Scheduled swarm_update_task: {swarm_update_task!r}")

    # --------------------------- #
    #         Main Loop         #
    # --------------------------- #

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received. Shutting down.")
    finally:
        # Cancel periodic update task
        swarm_update_task.cancel()
        try:
            await swarm_update_task
        except asyncio.CancelledError:
            pass

        # Cancel follower tasks if any exist
        for task in FOLLOWER_TASKS.values():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Attempt safe shutdown of drone (e.g., stop offboard mode)
        try:
            # await drone.offboard.stop()
            # await drone.action.disarm()
            pass
        except Exception:
            logger.exception("Error during drone shutdown.")

        if mavsdk_server:
            stop_mavsdk_server(mavsdk_server)


# ----------------------------- #
#             Main              #
# ----------------------------- #

def main():
    """
    Main function to run the smart swarm mode.
    """
    # Configure logging
    configure_logging("smart_swarm")

    # Parse command-line arguments if needed
    parser = argparse.ArgumentParser(description='Smart Swarm Mode')
    args = parser.parse_args()

    try:
        asyncio.run(run_smart_swarm())
    except Exception:
        logging.exception("Unhandled exception in main")
        sys.exit(1)

if __name__ == "__main__":
    main()
