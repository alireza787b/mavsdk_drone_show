# smart_swarm/smart_swarm.py

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

from smart_swarm_src.kalman_filter import LeaderKalmanFilter
from smart_swarm_src.pd_controller import PDController  # New import
from smart_swarm_src.low_pass_filter import LowPassFilter  # New import
from smart_swarm_src.utils import (
    transform_body_to_nea,
    is_data_fresh,
    fetch_home_position,
    lla_to_ned
)

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

# ----------------------------- #
#         Helper Functions      #
# ----------------------------- #

def configure_logging():
    """
    Configures logging for the script, ensuring logs are written to a per-session file
    and displayed on the console. It also limits the number of log files.
    """
    # Create logs directory if it doesn't exist
    logs_directory = os.path.join("..", "logs", "smart_swarm_logs")
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
    log_filename = f"smart_swarm_{session_time}.log"
    log_file = os.path.join(logs_directory, log_filename)
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # Add handlers to the root logger
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # Limit the number of log files TODO!
    #limit_log_files(logs_directory, MAX_LOG_FILES)

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

# ----------------------------- #
#    Leader State Update Task   #
# ----------------------------- #

async def update_leader_state():
    """
    Periodically fetches the leader's state and updates the Kalman filter.
    """
    logger = logging.getLogger(__name__)
    global LEADER_STATE, LEADER_KALMAN_FILTER
    update_interval = 1 / Params.LEADER_UPDATE_FREQUENCY
    last_update_time = None

    while True:
        try:
            # Fetch leader's state
            state_url = f"http://{LEADER_IP}:{Params.drones_flask_port}/{Params.get_drone_state_URI}"
            response = requests.get(state_url, timeout=1)
            if response.status_code == 200:
                data = response.json()
                leader_update_time = data.get('update_time', None)
                if leader_update_time and leader_update_time != last_update_time:
                    last_update_time = leader_update_time
                    # Convert lat, lon, alt to NED
                    leader_n, leader_e, leader_d = lla_to_ned(
                        data['position_lat'], data['position_long'], data['position_alt'],
                        REFERENCE_POS['latitude'], REFERENCE_POS['longitude'], REFERENCE_POS['altitude']
                    )
                    # Update LEADER_STATE
                    LEADER_STATE['pos_n'] = leader_n
                    LEADER_STATE['pos_e'] = leader_e
                    LEADER_STATE['pos_d'] = leader_d
                    LEADER_STATE['vel_n'] = data['velocity_north']
                    LEADER_STATE['vel_e'] = data['velocity_east']
                    LEADER_STATE['vel_d'] = data['velocity_down']
                    LEADER_STATE['yaw'] = data['yaw']
                    LEADER_STATE['update_time'] = leader_update_time

                    # Prepare measurement for Kalman filter
                    measurement = {
                        'pos_n': leader_n,
                        'pos_e': leader_e,
                        'pos_d': leader_d,
                        'vel_n': data['velocity_north'],
                        'vel_e': data['velocity_east'],
                        'vel_d': data['velocity_down'],
                    }
                    measurement_time = leader_update_time  # Already in seconds
                    # Update Kalman filter
                    LEADER_KALMAN_FILTER.update(measurement, measurement_time)
                    logger.debug(f"Leader measurement at time {measurement_time:.3f}s: {measurement}")
                    logger.debug(f"Kalman filter updated. Current state: {LEADER_KALMAN_FILTER.get_state()}")
                    logger.debug("Leader state updated and Kalman filter updated.")
                else:
                    logger.error("Leader data does not contain 'update_time'.")
            else:
                logger.error(f"Failed to fetch leader state: HTTP {response.status_code}")
        except requests.RequestException as e:
            logger.error(f"Exception while fetching leader state: {e}")
        except Exception:
            logger.exception("Unexpected error in updating leader state")
        await asyncio.sleep(update_interval)

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
    stale_duration_threshold = 1.0  # seconds

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
                desired_d = -1*(leader_d - OFFSETS['alt'])  #  Seems this -1 is needed. double check later why. maybe we are doing offset reverse
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
    Main function to run the smart swarm mode.
    """
    logger = logging.getLogger(__name__)
    global HW_ID, DRONE_CONFIG, SWARM_CONFIG, IS_LEADER, OFFSETS, BODY_COORD, LEADER_HW_ID, LEADER_IP, LEADER_KALMAN_FILTER
    global LEADER_HOME_POS, OWN_HOME_POS, REFERENCE_POS

    # Read HW_ID
    HW_ID = read_hw_id()
    if HW_ID is None:
        logger.error("Hardware ID not found.")
        sys.exit(1)

    # Read configurations
    config_filename = os.path.join('config_sitl.csv' if Params.sim_mode else 'config.csv')
    swarm_filename = os.path.join('swarm_sitl.csv' if Params.sim_mode else 'swarm.csv')
    read_config_csv(config_filename)
    read_swarm_csv(swarm_filename)

    # Get own configuration
    hw_id_str = str(HW_ID)
    drone_config = DRONE_CONFIG.get(hw_id_str)
    if drone_config is None:
        logger.error(f"Configuration for HW_ID {HW_ID} not found.")
        sys.exit(1)

    # Get swarm configuration
    swarm_config = SWARM_CONFIG.get(hw_id_str)
    if swarm_config is None:
        logger.error(f"Swarm configuration for HW_ID {HW_ID} not found.")
        sys.exit(1)

    # Determine role
    IS_LEADER = swarm_config['follow'] == '0'
    OFFSETS['n'] = swarm_config['offset_n']
    OFFSETS['e'] = swarm_config['offset_e']
    OFFSETS['alt'] = swarm_config['offset_alt']
    BODY_COORD = swarm_config['body_coord']
    logger.info(f"Drone HW_ID {HW_ID} - Leader: {IS_LEADER}, Offsets: {OFFSETS}, Body Coord: {BODY_COORD}")

    # If follower, get leader info
    if not IS_LEADER:
        LEADER_HW_ID = swarm_config['follow']
        leader_config = DRONE_CONFIG.get(LEADER_HW_ID)
        if leader_config is None:
            logger.error(f"Leader configuration for HW_ID {LEADER_HW_ID} not found.")
            sys.exit(1)
        LEADER_IP = leader_config['ip']
        # Initialize Kalman filter
        LEADER_KALMAN_FILTER = LeaderKalmanFilter()
        
    else:
        logger.info("It is a leader drone so no need to command. exiting...")
        sys.exit(1)

    # Start MAVSDK server
    mavsdk_server = start_mavsdk_server(Params.mavsdk_port)
    if mavsdk_server is None:
        logger.error("Failed to start MAVSDK server.")
        sys.exit(1)

    # Wait briefly for the MAVSDK server to initialize
    await asyncio.sleep(2)

    # Initialize drone
    try:
        drone = await initialize_drone()
    except Exception:
        logger.error("Failed to initialize drone.")
        sys.exit(1)

    # Fetch own home position
    own_ip = '127.0.0.1'
    own_home_pos = fetch_home_position(
        own_ip, Params.drones_flask_port, Params.get_drone_home_URI
    )
    if own_home_pos is None:
        logger.error("Failed to fetch own home position.")
        sys.exit(1)
    OWN_HOME_POS = own_home_pos
    logger.info(f"Own home position: {OWN_HOME_POS}")

    # For reference position, we can use own home position
    REFERENCE_POS = {
        'latitude': OWN_HOME_POS['latitude'],
        'longitude': OWN_HOME_POS['longitude'],
        'altitude': OWN_HOME_POS['altitude'],
    }

    # If follower, fetch leader's home position
    if not IS_LEADER:
        leader_home_pos = fetch_home_position(
            LEADER_IP, Params.drones_flask_port, Params.get_drone_home_URI
        )
        if leader_home_pos is None:
            logger.error("Failed to fetch leader's home position.")
            sys.exit(1)
        LEADER_HOME_POS = leader_home_pos
        logger.info(f"Leader's home position: {LEADER_HOME_POS}")

    # Start leader state update task
    if not IS_LEADER:
        leader_update_task = asyncio.create_task(update_leader_state())
        # Start own state update task
        own_state_task = asyncio.create_task(update_own_state(drone))
        # Start control loop
        control_task = asyncio.create_task(control_loop(drone))
    else:
        logger.info("This drone is a leader. Waiting for termination.")
        await asyncio.Event().wait()  # Keep the leader running indefinitely

    try:
        # Keep the script running
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received. Shutting down.")
    finally:
        # Clean up tasks
        if not IS_LEADER:
            leader_update_task.cancel()
            try:
                await leader_update_task
            except asyncio.CancelledError:
                pass
            own_state_task.cancel()
            try:
                await own_state_task
            except asyncio.CancelledError:
                pass
            control_task.cancel()
            try:
                await control_task
            except asyncio.CancelledError:
                pass

        # Disarm drone and stop offboard mode
        try:
            # await drone.offboard.stop()
            # await drone.action.disarm()
            pass
        except Exception:
            logger.exception("Error during drone shutdown.")

        # Stop MAVSDK server
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
    configure_logging()

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
