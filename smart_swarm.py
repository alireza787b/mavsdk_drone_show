# smart_swarm/smart_swarm.py
# Copyright (c) 2025 Alireza Ghaderi
# SPDX-License-Identifier: CC-BY-NC-SA-4.0
#
# This file is part of MAVSDK Drone Show
# https://github.com/alireza787b/mavsdk_drone_show
#
# Licensed under Creative Commons Attribution-NonCommercial-ShareAlike 4.0
# For commercial licensing, contact: p30planets@gmail.com

"""
===========================================================================
 Project: MavSDK Drone Show (smart_swarm)
 Repository: https://github.com/alireza787b/mavsdk_drone_show
 
 Description:
   This project implements a smart swarm control system using MAVSDK, designed
   to operate drones in a coordinated formation. The system distinguishes
   between leader and follower drones based on configuration JSON files. Followers
   receive state updates from the leader, process these with a Kalman filter, and
   compute velocity commands using a PD controller (with low-pass filtering).
   The code is built using Python's asyncio framework for concurrent tasks such as
   state updates, control loops, and dynamic configuration updates.

 Features:
   - Reads drone and swarm configuration from JSON files.
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
      - Load drone configuration from config.json and swarm configuration from swarm.json.
      - Determine if the drone is operating as a Leader or Follower.
      - Set formation offsets and body coordinate mode based on the swarm configuration.
      - For followers, extract leader information and initialize a Kalman filter.
   
   2. MAVSDK Server & Drone Connection:
      - Start the MAVSDK server and ensure it is running.
      - Initialize the drone and perform pre-flight checks (global position and home position).
      - Fetch the drone's home position using a primary (telemetry) and a fallback (HTTP) API.
      - Set the reference position for NED coordinate conversion.
   
   3. Dynamic Configuration Update:
      - A periodic task (update_swarm_config_periodically) re-reads the swarm config at a defined
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
   - Future improvements may include replacing the JSON-based configuration update with a
     direct query to a Ground Control Station (GCS) endpoint.
   - This file serves as the central orchestrator for the swarm behavior and leverages
     several modules (e.g., Kalman filter, PD controller, LED controller) for a modular
     and maintainable code base.
===========================================================================
"""


import os
import sys
import logging
import time
import asyncio
import csv
import subprocess
import socket
import psutil
import argparse
from typing import Optional
from datetime import datetime
from collections import namedtuple
from mavsdk import System
from mavsdk.offboard import PositionNedYaw, VelocityBodyYawspeed, VelocityNedYaw, OffboardError
from mavsdk.action import ActionError
from tenacity import retry, stop_after_attempt, wait_fixed
import navpy
import numpy as np  # Added for numerical computations

from src.drone_config import ConfigLoader
from src.drone_api_routes import DRONE_STATE_ROUTE
from src.led_controller import LEDController
from src.params import Params
import aiohttp 

from smart_swarm_src.kalman_filter import LeaderKalmanFilter
from smart_swarm_src.pd_controller import PDController  # New import
from smart_swarm_src.low_pass_filter import LowPassFilter  # New import
from smart_swarm_src.failover import choose_leader_loss_response
from smart_swarm_src.utils import (
    transform_body_to_nea,
    is_data_fresh,
    fetch_home_position,
    lla_to_ned
)
from src.swarm_runtime_state import write_runtime_swarm_assignment

# Unified logging system
from mds_logging.drone import init_drone_logging
from mds_logging import get_logger, register_component
from mds_logging.cli import add_log_arguments, apply_log_args

# ----------------------------- #
#        Data Structures        #
# ----------------------------- #

DroneConfig = namedtuple(
    "DroneConfig", "hw_id pos_id x y ip mavlink_port"
)

SwarmConfig = namedtuple(
    "SwarmConfig", "hw_id follow offset_x offset_y offset_z frame"
)

# ----------------------------- #
#        Global Variables       #
# ----------------------------- #

HW_ID = None  # Hardware ID of the drone
DRONE_CONFIG = {}  # Drone configurations from config.json
SWARM_CONFIG = {}  # Swarm configurations from swarm.json
DRONE_STATE = {}  # Own drone's state
LEADER_STATE = {}  # Leader drone's state
OWN_STATE = {}  # Own drone's NED state
IS_LEADER = False  # Flag indicating if this drone is a leader
OFFSETS = {'x': 0.0, 'y': 0.0, 'z': 0.0}  # Offsets from the leader
FRAME = "ned"  # Coordinate frame for offsets: "ned" or "body"
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
LEADER_FAILOVER_IN_PROGRESS = False  # Prevent duplicate failover runs while leader health is degraded

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


def normalize_hw_id(hw_id):
    """Normalize a hardware ID for dict lookups. Returns None for leader/no-follow."""
    try:
        normalized = int(hw_id)
    except (TypeError, ValueError):
        return None

    if normalized <= 0:
        return None
    return str(normalized)


def get_drone_config_for_hw_id(hw_id):
    """Resolve a drone config entry regardless of string/int HW ID input."""
    normalized = normalize_hw_id(hw_id)
    if normalized is None:
        return None
    return DRONE_CONFIG.get(normalized)


def reset_leader_tracking():
    """Drop leader-estimation state when the follow target changes."""
    global LEADER_STATE, LEADER_KALMAN_FILTER, leader_unreachable_count, LEADER_FAILOVER_IN_PROGRESS
    LEADER_STATE.clear()
    LEADER_KALMAN_FILTER = LeaderKalmanFilter()
    leader_unreachable_count = 0
    LEADER_FAILOVER_IN_PROGRESS = False


def assign_leader_target(new_leader_hw_id):
    """Apply a new follow target and reset estimation state."""
    global LEADER_HW_ID, LEADER_IP

    normalized = normalize_hw_id(new_leader_hw_id)
    if normalized is None:
        LEADER_HW_ID = None
        LEADER_IP = None
        reset_leader_tracking()
        return None

    leader_cfg = get_drone_config_for_hw_id(normalized)
    if leader_cfg is None:
        return None

    LEADER_HW_ID = normalized
    LEADER_IP = leader_cfg['ip']
    reset_leader_tracking()
    return leader_cfg


def persist_current_swarm_assignment(logger=None):
    """Persist the latest local assignment so telemetry reflects live swarm changes."""
    assignment = SWARM_CONFIG.get(str(HW_ID))
    if not assignment:
        return

    try:
        write_runtime_swarm_assignment(dict(assignment))
    except Exception as exc:
        active_logger = logger or logging.getLogger(__name__)
        active_logger.debug("Failed to persist runtime swarm assignment: %s", exc)


async def cancel_follower_tasks(logger):
    """Cancel follower-mode tasks without leaking unfinished coroutines."""
    global FOLLOWER_TASKS

    if not FOLLOWER_TASKS:
        return

    for task_name, task in list(FOLLOWER_TASKS.items()):
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            logger.debug("Cancelled follower task: %s", task_name)
        except Exception:
            logger.exception("Follower task %s exited with an error during cancellation", task_name)
    FOLLOWER_TASKS.clear()


def _follower_task_missing(task_name: str) -> bool:
    task = FOLLOWER_TASKS.get(task_name)
    return task is None or task.done()


async def ensure_offboard_active_for_follower(drone: System, logger, reason: str) -> bool:
    """Start follower offboard mode if it is not already active."""
    try:
        await drone.offboard.set_velocity_body(VelocityBodyYawspeed(0.0, 0.0, 0.0, 0.0))
        await drone.offboard.start()
        logger.info("Follower offboard control active (%s).", reason)
        return True
    except OffboardError as exc:
        message = str(exc).lower()
        if "already" in message and "offboard" in message:
            logger.debug("Follower offboard control already active (%s).", reason)
            return True
        logger.error("Failed to start follower offboard control (%s): %s", reason, exc)
        return False
    except Exception as exc:
        logger.error("Unexpected error while starting follower offboard control (%s): %s", reason, exc)
        return False


async def ensure_follower_runtime(drone: System, logger, reason: str) -> bool:
    """Ensure the follower control runtime is fully active and recover crashed tasks."""
    if not await ensure_offboard_active_for_follower(drone, logger, reason):
        return False

    if _follower_task_missing('leader_update_task'):
        FOLLOWER_TASKS['leader_update_task'] = asyncio.create_task(update_leader_state())
    if _follower_task_missing('own_state_task'):
        FOLLOWER_TASKS['own_state_task'] = asyncio.create_task(update_own_state(drone))
    if _follower_task_missing('control_task'):
        FOLLOWER_TASKS['control_task'] = asyncio.create_task(control_loop(drone))
    return True


async def handle_leader_unavailability(drone: System, logger, reason: str):
    """Run one failover sequence at a time when leader health is lost."""
    global LEADER_FAILOVER_IN_PROGRESS

    if LEADER_FAILOVER_IN_PROGRESS:
        logger.debug("Leader failover already in progress (%s).", reason)
        return

    LEADER_FAILOVER_IN_PROGRESS = True
    try:
        await execute_failsafe(drone, reason=reason)
        await elect_new_leader()
    finally:
        LEADER_FAILOVER_IN_PROGRESS = False


async def transition_to_leader_mode(drone: System, logger, reason: str):
    """Stop follower control and leave the vehicle in an explicit leader-safe HOLD state."""
    global IS_LEADER

    IS_LEADER = True
    assign_leader_target(0)
    persist_current_swarm_assignment(logger)
    await cancel_follower_tasks(logger)

    try:
        await drone.offboard.stop()
        logger.info("Stopped offboard control while switching to leader mode (%s).", reason)
    except OffboardError as exc:
        logger.debug("Offboard was not active during leader transition (%s): %s", reason, exc)
    except Exception as exc:
        logger.warning("Failed to stop offboard during leader transition (%s): %s", reason, exc)

    try:
        await drone.action.hold()
        logger.info("Drone transitioned to leader mode and entered HOLD (%s).", reason)
    except ActionError as exc:
        logger.warning("Failed to command HOLD during leader transition (%s): %s", reason, exc)
    except Exception as exc:
        logger.warning("Unexpected error while entering HOLD during leader transition (%s): %s", reason, exc)


async def transition_to_follower_mode(drone: System, new_leader_hw_id, logger, reason: str):
    """Start follower-mode tasks against a validated leader target."""
    global IS_LEADER

    leader_cfg = assign_leader_target(new_leader_hw_id)
    if leader_cfg is None:
        logger.error("[Periodic Update] Leader config missing for HW_ID=%s", new_leader_hw_id)
        return False

    logger.info("[Periodic Update] Ensuring follower runtime (%s).", reason)
    if not await ensure_follower_runtime(drone, logger, reason):
        IS_LEADER = True
        logger.warning(
            "[Periodic Update] Follower runtime unavailable for leader %s (%s); keeping leader-mode flag so the runtime retries.",
            new_leader_hw_id,
            reason,
        )
        return False

    IS_LEADER = False
    persist_current_swarm_assignment(logger)
    return True

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

def read_config(filename: str):
    """
    Reads the drone configurations from the config JSON file and populates DRONE_CONFIG.

    Note: x,y positions now come from trajectory CSV files (single source of truth),
    not from config.json.

    Args:
        filename (str): Path to the config JSON file.
    """
    logger = logging.getLogger(__name__)
    global DRONE_CONFIG
    try:
        import json
        with open(filename, 'r') as f:
            data = json.load(f)
        entries = data.get('drones', data) if isinstance(data, dict) else data
        for entry in entries:
            try:
                hw_id = str(int(entry["hw_id"]))
                pos_id = int(entry["pos_id"])

                # Get position from trajectory CSV (single source of truth)
                base_dir = 'shapes_sitl' if Params.sim_mode else 'shapes'
                trajectory_file = os.path.join(
                    os.path.dirname(__file__),  # Project root
                    base_dir,
                    'swarm',
                    'processed',
                    f"Drone {pos_id}.csv"
                )

                x, y = 0.0, 0.0  # Default values
                try:
                    if os.path.exists(trajectory_file):
                        with open(trajectory_file, 'r') as traj_f:
                            traj_reader = csv.DictReader(traj_f)
                            first_waypoint = next(traj_reader, None)
                            if first_waypoint:
                                x = float(first_waypoint.get('px', 0))  # North
                                y = float(first_waypoint.get('py', 0))  # East
                            else:
                                logger.warning(f"Trajectory file empty for pos_id={pos_id}")
                    else:
                        logger.warning(f"Trajectory file not found for pos_id={pos_id}: {trajectory_file}")
                except Exception as e:
                    logger.error(f"Error reading trajectory for pos_id={pos_id}: {e}")

                DRONE_CONFIG[hw_id] = {
                    'hw_id': hw_id,
                    'pos_id': pos_id,
                    'x': x,
                    'y': y,
                    'ip': entry["ip"],
                    'mavlink_port': int(entry["mavlink_port"]),
                }
            except ValueError as ve:
                logger.error(f"Invalid data type in config file entry: {entry}. Error: {ve}")
        logger.info(f"Read {len(DRONE_CONFIG)} drone configurations from '{filename}' with positions from trajectory CSV.")
    except FileNotFoundError:
        logger.exception(f"Config file '{filename}' not found.")
        sys.exit(1)
    except Exception:
        logger.exception(f"Error reading config file '{filename}'.")
        sys.exit(1)

def read_swarm(filename: str):
    """
    Reads the swarm configurations from the swarm JSON file and populates SWARM_CONFIG.

    Args:
        filename (str): Path to the swarm JSON file.
    """
    logger = logging.getLogger(__name__)
    try:
        import json
        with open(filename, 'r') as f:
            data = json.load(f)
        entries = data.get('assignments', data) if isinstance(data, dict) else data
        replace_swarm_config(entries, source_name=f"local file '{filename}'", announce_level=logging.INFO)
    except FileNotFoundError:
        logger.exception(f"Swarm file '{filename}' not found.")
        sys.exit(1)
    except Exception:
        logger.exception(f"Error reading swarm file '{filename}'.")
        sys.exit(1)


def parse_swarm_entries(entries):
    """Parse raw swarm assignment entries into the normalized in-memory map."""
    logger = logging.getLogger(__name__)
    parsed = {}
    for entry in entries:
        try:
            hw_id = str(int(entry["hw_id"]))
            parsed[hw_id] = {
                'hw_id': hw_id,
                'follow': int(entry["follow"]),
                'offset_x': float(entry["offset_x"]),
                'offset_y': float(entry["offset_y"]),
                'offset_z': float(entry["offset_z"]),
                'frame': str(entry.get("frame", "ned")),
            }
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("Invalid swarm entry %s. Error: %s", entry, exc)
    return parsed


def replace_swarm_config(entries, source_name: str, announce_level=logging.DEBUG):
    """Replace the global swarm assignment map from a raw entry list."""
    global SWARM_CONFIG

    SWARM_CONFIG.clear()
    SWARM_CONFIG.update(parse_swarm_entries(entries))
    logging.getLogger(__name__).log(
        announce_level,
        "Loaded %d swarm configurations from %s.",
        len(SWARM_CONFIG),
        source_name,
    )


async def refresh_swarm_config_from_gcs(logger, source_label: str, session: Optional[aiohttp.ClientSession] = None):
    """
    Refresh swarm assignments from GCS.

    Returns True when the GCS snapshot was fetched and applied, False when the
    local swarm file remains in effect.
    """
    state_url = f"http://{Params.GCS_IP}:{Params.gcs_api_port}/api/v1/config/swarm"
    owns_session = session is None
    active_session = session

    try:
        if active_session is None:
            timeout = aiohttp.ClientTimeout(total=Params.SMART_SWARM_GCS_CONFIG_TIMEOUT_SEC)
            active_session = aiohttp.ClientSession(timeout=timeout)

        async with active_session.get(state_url) as resp:
            resp.raise_for_status()
            api_data = await resp.json()

        if isinstance(api_data, dict) and isinstance(api_data.get("assignments"), list):
            api_data = api_data["assignments"]

        replace_swarm_config(
            api_data,
            source_name=f"GCS API ({source_label})",
            announce_level=logging.INFO if source_label == "startup" else logging.DEBUG,
        )
        return True
    except Exception as exc:
        logger.warning(
            "[%s] Failed to refresh swarm configuration from GCS; continuing with local swarm file. Error: %s",
            source_label,
            exc,
        )
        return False
    finally:
        if owns_session and active_session is not None:
            await active_session.close()

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

    NOTE: Requires Params.GCS_IP and Params.gcs_api_port to be set.
    """
    global SWARM_CONFIG, IS_LEADER, OFFSETS, FRAME
    global LEADER_HW_ID, LEADER_IP, LEADER_KALMAN_FILTER, FOLLOWER_TASKS
    global HW_ID

    logger = logging.getLogger(__name__)

    str_hw_id = str(HW_ID)
    if not DRONE_CONFIG.get(str_hw_id):
        logger.error(f"[Periodic Update] Cannot resolve drone config for HW_ID={HW_ID}")
        return

    # Shared session for connection reuse
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                logger.debug("[Periodic Update] Checking swarm configuration")
                refreshed = await refresh_swarm_config_from_gcs(
                    logger,
                    source_label="periodic update",
                    session=session,
                )
                if not refreshed:
                    await asyncio.sleep(Params.CONFIG_UPDATE_INTERVAL)
                    continue

                # Grab this drone's new config
                new_cfg = SWARM_CONFIG.get(str(HW_ID))
                if new_cfg is None:
                    logger.error(f"[Periodic Update] No swarm entry for HW_ID={HW_ID}")
                else:
                    persist_current_swarm_assignment(logger)
                    # Determine new role/offsets/frame
                    new_offsets     = {
                        'x':   new_cfg['offset_x'],
                        'y':   new_cfg['offset_y'],
                        'z':   new_cfg['offset_z']
                    }
                    new_frame       = new_cfg['frame']
                    new_leader      = new_cfg['follow']
                    new_is_leader   = (new_leader == 0)

                    # ROLE CHANGE?
                    if new_is_leader != IS_LEADER:
                        logger.info(
                            "[Periodic Update] Role change: %s → %s",
                            "Leader" if IS_LEADER else "Follower",
                            "Leader" if new_is_leader else "Follower"
                        )

                        if new_is_leader:
                            await transition_to_leader_mode(drone, logger, "config update")
                        else:
                            await transition_to_follower_mode(drone, new_leader, logger, "config update")

                    # Handle leader change if drone is a follower
                    if not new_is_leader:
                        new_leader_hw_id = normalize_hw_id(new_leader)
                        if new_leader_hw_id != LEADER_HW_ID:
                            logger.info(f"[Periodic Update] Leader change detected. Following new leader {new_leader}.")
                            leader_cfg = assign_leader_target(new_leader)
                            if not leader_cfg:
                                logger.error("[Periodic Update] Leader config missing for HW_ID=%s", LEADER_HW_ID)
                            else:
                                logger.info(f"[Periodic Update] Following new leader at {LEADER_IP}")

                    # OFFSET CHANGE?
                    if new_offsets != OFFSETS:
                        logger.info(
                            "[Periodic Update] Offsets changed: %s → %s",
                            OFFSETS, new_offsets
                        )
                        OFFSETS.update(new_offsets)

                    # FRAME CHANGE?
                    if new_frame != FRAME:
                        logger.info(
                            "[Periodic Update] Frame changed: %s → %s",
                            FRAME, new_frame
                        )
                        FRAME = new_frame

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

    TODO(next transport phase):
    Keep the validated HTTP polling path as the fallback transport, but move
    leader-state delivery behind a transport abstraction so a future
    WebSocket/subscription path can be added without changing failover,
    stale-data detection, or control-loop behavior.
    """
    logger = logging.getLogger(__name__)
    global LEADER_STATE, LEADER_KALMAN_FILTER, LEADER_IP
    global leader_unreachable_count, max_unreachable_attempts

    update_interval = 1.0 / Params.LEADER_UPDATE_FREQUENCY
    last_update_time = None

    timeout = aiohttp.ClientTimeout(total=Params.SMART_SWARM_LEADER_STATE_TIMEOUT_SEC)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        while True:
            try:
                state_url = f"http://{LEADER_IP}:{Params.drone_api_port}{DRONE_STATE_ROUTE}"
                async with session.get(state_url) as response:
                    if response.status != 200:
                        raise aiohttp.ClientResponseError(
                            response.request_info,
                            response.history,
                            status=response.status,
                            message=f"Leader state fetch failed with HTTP {response.status}",
                            headers=response.headers,
                        )
                    data = await response.json()

                leader_update_time = data.get('update_time', None)
                if leader_update_time and leader_update_time != last_update_time:
                    leader_unreachable_count = 0
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
                        'yaw': data.get('yaw', 0.0),
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
                    leader_unreachable_count += 1
                    logger.debug(
                        "Leader response missing a fresh 'update_time' (%s/%s).",
                        leader_unreachable_count,
                        max_unreachable_attempts,
                    )
                    if leader_unreachable_count >= max_unreachable_attempts and DRONE_INSTANCE is not None:
                        logger.warning(
                            "Leader telemetry stopped advancing for %s checks. Starting failover.",
                            leader_unreachable_count,
                        )
                        await handle_leader_unavailability(DRONE_INSTANCE, logger, "stale leader update_time")
            except Exception as e:
                leader_unreachable_count += 1
                logger.debug("Leader state fetch failed (%s/%s): %s", leader_unreachable_count, max_unreachable_attempts, e)
                if leader_unreachable_count >= max_unreachable_attempts and DRONE_INSTANCE is not None:
                    logger.warning(
                        f"Leader unreachable for {leader_unreachable_count} attempts. Starting failover."
                    )
                    await handle_leader_unavailability(DRONE_INSTANCE, logger, "leader fetch failures")

            await asyncio.sleep(update_interval)

        
async def elect_new_leader():
    """
    Elect a new leader when the current leader is unreachable.
    The exact failover policy is controlled by Params.SMART_SWARM_LEADER_LOSS_STRATEGY.
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
    strategy = getattr(Params, "SMART_SWARM_LEADER_LOSS_STRATEGY", "upstream_or_hold")
    failover = choose_leader_loss_response(
        self_hw_id=HW_ID,
        current_leader_hw_id=old_leader,
        swarm_config=SWARM_CONFIG,
        strategy=strategy,
    )
    logger.warning(
        "Leader-loss failover resolved using strategy '%s': %s",
        failover["strategy"],
        failover["reason"],
    )

    if failover["action"] == "self_hold":
        SWARM_CONFIG[str(HW_ID)]['follow'] = 0
        persist_current_swarm_assignment(logger)
        try:
            await notify_gcs_of_leader_change(0)
        except Exception:
            logger.warning("GCS notify failed for self-promotion during failover.")
        await transition_to_leader_mode(DRONE_INSTANCE, logger, "leader loss failover")
        return

    new_leader = failover["leader_hw_id"]
    if new_leader is None:
        logger.warning("Failover did not resolve a leader candidate; entering HOLD mode.")
        SWARM_CONFIG[str(HW_ID)]['follow'] = 0
        persist_current_swarm_assignment(logger)
        await transition_to_leader_mode(DRONE_INSTANCE, logger, "leader loss failover")
        return

    logger.info("Attempting failover to Drone %s.", new_leader)
    SWARM_CONFIG[str(HW_ID)]['follow'] = int(new_leader)
    persist_current_swarm_assignment(logger)

    accepted = await notify_gcs_of_leader_change(new_leader)
    if accepted and assign_leader_target(new_leader) is not None:
        logger.info("Leader failover committed: now following %s @ %s", new_leader, LEADER_IP)
        return

    logger.warning(
        "Leader failover to %s could not be committed; reverting to self-hold for safety.",
        new_leader,
    )
    SWARM_CONFIG[str(HW_ID)]['follow'] = 0
    persist_current_swarm_assignment(logger)
    try:
        await notify_gcs_of_leader_change(0)
    except Exception:
        logger.warning("GCS notify failed while reverting to self-hold after failover rejection.")
    await transition_to_leader_mode(DRONE_INSTANCE, logger, "failover commit rejected")



    
    
async def notify_gcs_of_leader_change(new_leader_hw_id) -> bool:
    """
    Notify the GCS of our updated leader by sending only our own swarm entry.
    Returns True if the GCS accepted the change, False otherwise.
    """
    logger = logging.getLogger(__name__)

    gcs_ip = Params.GCS_IP
    notify_url = f"http://{gcs_ip}:{Params.gcs_api_port}/api/v1/config/swarm/assignments/{int(HW_ID)}"

    payload = {
        'follow':      int(new_leader_hw_id),
    }

    try:
        timeout = aiohttp.ClientTimeout(total=Params.SMART_SWARM_GCS_NOTIFY_TIMEOUT_SEC)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.patch(notify_url, json=payload) as resp:
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
    state_gate_status = None

    try:
        while True:
            current_time = time.time()
            dt = current_time - previous_time if previous_time else loop_interval
            previous_time = current_time

            own_state_ready = 'timestamp' in OWN_STATE
            leader_state_ready = 'update_time' in LEADER_STATE

            if not own_state_ready:
                if state_gate_status != 'own':
                    logger.info("Follower waiting for own-state lock before sending setpoints.")
                    state_gate_status = 'own'
                await asyncio.sleep(loop_interval)
                continue

            if not leader_state_ready:
                if state_gate_status != 'leader':
                    logger.info("Follower waiting for leader-state lock before sending setpoints.")
                    state_gate_status = 'leader'
                await asyncio.sleep(loop_interval)
                continue

            if state_gate_status is not None:
                logger.info("Follower state lock acquired; resuming formation control.")
                state_gate_status = None

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
                if FRAME == "body":
                    offset_x_ned, offset_y_ned = transform_body_to_nea(OFFSETS['x'], OFFSETS['y'], leader_yaw)
                    logger.debug(f"Offsets in body frame: Forward={OFFSETS['x']:.2f}m, Right={OFFSETS['y']:.2f}m, Transformed to NED: offset_x={offset_x_ned:.2f}m, offset_y={offset_y_ned:.2f}m")
                else:
                    offset_x_ned, offset_y_ned = OFFSETS['x'], OFFSETS['y']
                    logger.debug(f"Offsets in NED frame: offset_x={offset_x_ned:.2f}m, offset_y={offset_y_ned:.2f}m")

                logger.debug(f"Altitude offset: offset_z={OFFSETS['z']:.2f}m")
                
                # Desired positions
                desired_n = leader_n + offset_x_ned
                desired_e = leader_e + offset_y_ned
                desired_d = -1*(leader_d + OFFSETS['z'])  
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
                velocity_feedforward = np.array([
                    leader_vel_n,
                    leader_vel_e,
                    leader_vel_d,
                ]) * Params.SMART_SWARM_LEADER_VELOCITY_FEEDFORWARD
                velocity_command = pd_controller.compute(
                    position_error,
                    dt,
                    velocity_feedforward=velocity_feedforward,
                )

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
                    logger.warning(
                        "Leader data has been stale for over %s seconds. Starting failover.",
                        stale_duration_threshold,
                    )
                    await handle_leader_unavailability(drone, logger, "control-loop stale leader data")
                    stale_start_time = current_time
            await asyncio.sleep(loop_interval)
    except asyncio.CancelledError:
        logger.info("Control loop cancelled.")
    except OffboardError as e:
        logger.error(f"Offboard error in control loop: {e}")
        await execute_failsafe(drone, reason="offboard error in control loop")
    except Exception:
        logger.exception("Unexpected error in control loop")
        await execute_failsafe(drone, reason="unexpected control-loop error")

# ----------------------------- #
#         Failsafe Function     #
# ----------------------------- #

async def execute_failsafe(drone: System, reason: str = ""):
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
        logger.info("Failsafe: Holding position%s.", f" ({reason})" if reason else "")
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
async def initialize_drone(start_offboard: bool = False):
    """
    Initializes the drone connection and performs pre-flight checks.

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

        if start_offboard:
            logger.info("Starting offboard mode during initialization.")
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
    global HW_ID, DRONE_CONFIG, SWARM_CONFIG, IS_LEADER, OFFSETS, FRAME, LEADER_HW_ID, LEADER_IP, LEADER_KALMAN_FILTER
    global LEADER_HOME_POS, OWN_HOME_POS, REFERENCE_POS

    # --------------------------- #
    #      Initialization         #
    # --------------------------- #

    # Read hardware ID from .hwID file
    HW_ID = ConfigLoader.get_hw_id()
    if HW_ID is None:
        logger.error("Hardware ID not found.")
        sys.exit(1)

    # Read configuration JSON files
    config_filename = Params.config_file_name
    swarm_filename = Params.swarm_file_name
    read_config(config_filename)
    read_swarm(swarm_filename)
    await refresh_swarm_config_from_gcs(logger, source_label="startup")

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
    IS_LEADER = swarm_config['follow'] == 0
    persist_current_swarm_assignment(logger)
    OFFSETS['x'] = swarm_config['offset_x']
    OFFSETS['y'] = swarm_config['offset_y']
    OFFSETS['z'] = swarm_config['offset_z']
    FRAME = swarm_config['frame']
    logger.info(f"Drone HW_ID {HW_ID} - Initial Role: {'Leader' if IS_LEADER else 'Follower'}, Offsets: {OFFSETS}, Frame: {FRAME}")

    # For followers, set leader info and initialize Kalman filter; for leaders, simply log the role.
    if not IS_LEADER:
        LEADER_HW_ID = normalize_hw_id(swarm_config['follow'])
        leader_config = get_drone_config_for_hw_id(LEADER_HW_ID)
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
        drone = await initialize_drone(start_offboard=False)
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
    fallback_origin = fetch_home_position(own_ip, Params.drone_api_port, Params.get_drone_gps_origin_URI)
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
        leader_home_pos = fetch_home_position(LEADER_IP, Params.drone_api_port, Params.get_drone_home_URI)
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
        if not await ensure_follower_runtime(drone, logger, "startup"):
            logger.error("Failed to start follower runtime.")
            sys.exit(1)
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
        await cancel_follower_tasks(logger)

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
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='Smart Swarm Mode')
    add_log_arguments(parser)
    args = parser.parse_args()

    # Initialize unified logging
    apply_log_args(args)
    register_component("smart_swarm", "drone", "Smart swarm following mode")
    init_drone_logging()
    _logger = get_logger("smart_swarm")

    try:
        asyncio.run(run_smart_swarm())
    except Exception:
        _logger.exception("Unhandled exception in main")
        sys.exit(1)

if __name__ == "__main__":
    main()
