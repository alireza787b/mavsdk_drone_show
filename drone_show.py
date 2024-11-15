# drone_show/drone_show.py

import os
import sys
import time
import asyncio
import csv
import subprocess
import glob
import logging
import logging.handlers
import socket
import psutil
import argparse
from datetime import datetime
from collections import namedtuple

from mavsdk import System
from mavsdk.offboard import (
    PositionNedYaw,
    VelocityBodyYawspeed,
    VelocityNedYaw,
    AccelerationNed,
    OffboardError,
)
from mavsdk.telemetry import LandedState
from mavsdk.action import ActionError
import navpy
from tenacity import retry, stop_after_attempt, wait_fixed


from src.led_controller import LEDController
from src.params import Params

from drone_show_src.utils import configure_logging, limit_log_files, read_hw_id, clamp_led_value, global_to_local

# ----------------------------- #
#        Data Structures        #
# ----------------------------- #

Drone = namedtuple(
    "Drone", "hw_id pos_id initial_x initial_y ip mavlink_port debug_port gcs_ip"
)

# ----------------------------- #
#        Global Variables       #
# ----------------------------- #

HW_ID = None  # Hardware ID of the drone
position_id = None  # Position ID of the drone
global_synchronized_start_time = None  # Synchronized start time
initial_position_drift = None  # Initial position drift in NED coordinates

CONFIG_CSV_NAME = os.path.join(Params.config_csv_name)

# ----------------------------- #
#         Helper Functions      #
# ----------------------------- #

def read_config(filename: str) -> Drone:
    """
    Read the drone configuration from a CSV file.

    Args:
        filename (str): Path to the config CSV file.

    Returns:
        Drone: Namedtuple containing drone configuration if found, else None.
    """
    logger = logging.getLogger(__name__)
    try:
        with open(filename, newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                try:
                    hw_id = int(row["hw_id"])
                    if hw_id == HW_ID:
                        pos_id = int(row["pos_id"])
                        initial_x = float(row["x"])
                        initial_y = float(row["y"])
                        ip = row["ip"]
                        mavlink_port = int(row["mavlink_port"])
                        debug_port = int(row["debug_port"])
                        gcs_ip = row["gcs_ip"]
                        drone = Drone(
                            hw_id, pos_id, initial_x, initial_y, ip, mavlink_port, debug_port, gcs_ip
                        )
                        logger.info(f"Drone configuration found: {drone}")
                        return drone
                except ValueError as ve:
                    logger.error(f"Invalid data type in config file row: {row}. Error: {ve}")
            logger.error(f"No configuration found for HW_ID {HW_ID}.")
            return None
    except FileNotFoundError:
        logger.exception("Config file not found.")
        return None
    except Exception:
        logger.exception(f"Error reading config file {filename}")
        return None

def read_trajectory_file(filename: str, initial_x: float = 0.0, initial_y: float = 0.0) -> list:
    """
    Read and adjust the trajectory waypoints from a CSV file.

    Args:
        filename (str): Path to the drone-specific trajectory CSV file.
        initial_x (float): Initial x-coordinate from config.csv.
        initial_y (float): Initial y-coordinate from config.csv.

    Returns:
        list: List of adjusted waypoints.
    """
    logger = logging.getLogger(__name__)
    waypoints = []
    try:
        with open(filename, newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                try:
                    t = float(row["t"])
                    px = float(row["px"]) - initial_x
                    py = float(row["py"]) - initial_y
                    pz = float(row["pz"])
                    vx = float(row["vx"])
                    vy = float(row["vy"])
                    vz = float(row["vz"])
                    ax = float(row["ax"])
                    ay = float(row["ay"])
                    az = float(row["az"])
                    yaw = float(row["yaw"])
                    ledr = clamp_led_value(row.get("ledr", 0))
                    ledg = clamp_led_value(row.get("ledg", 0))
                    ledb = clamp_led_value(row.get("ledb", 0))
                    mode = row.get("mode", "0")
                    waypoints.append(
                        (
                            t,
                            px,
                            py,
                            pz,
                            vx,
                            vy,
                            vz,
                            ax,
                            ay,
                            az,
                            yaw,
                            mode,
                            ledr,
                            ledg,
                            ledb,
                        )
                    )
                except ValueError as ve:
                    logger.error(f"Invalid data type in trajectory file row: {row}. Error: {ve}")
        if waypoints:
            logger.info(
                f"Trajectory file '{filename}' read successfully with {len(waypoints)} waypoints."
            )
        else:
            logger.error(f"No waypoints found in trajectory file '{filename}'.")
            sys.exit(1)
    except FileNotFoundError:
        logger.exception(f"Trajectory file '{filename}' not found.")
        sys.exit(1)
    except Exception:
        logger.exception(f"Error reading trajectory file {filename}")
        sys.exit(1)
    return waypoints

# ----------------------------- #
#        Core Functionalities   #
# ----------------------------- #

async def perform_trajectory(drone: System, waypoints: list, home_position, start_time):
    """
    Executes the trajectory by sending setpoints to the drone.

    Args:
        drone (System): MAVSDK drone system instance.
        waypoints (list): List of trajectory waypoints.
        home_position: Home position telemetry data.
        start_time (float): Synchronized start time.
    """
    logger = logging.getLogger(__name__)
    logger.info("Performing trajectory with time synchronization.")
    total_waypoints = len(waypoints)
    waypoint_index = 0
    landing_detected = False

    # Initialize LEDController
    led_controller = LEDController.get_instance()

    # Determine if trajectory ends high or at ground level
    final_altitude = waypoints[-1][3]  # pz of the last waypoint
    if final_altitude > Params.GROUND_ALTITUDE_THRESHOLD:
        trajectory_ends_high = True
        logger.info("Trajectory ends high in the sky. Will perform PX4 native landing.")
    else:
        trajectory_ends_high = False
        logger.info("Trajectory guides back to ground level. Will perform controlled landing.")

    # Main trajectory execution loop
    while waypoint_index < total_waypoints:
        try:
            current_time = time.time()
            elapsed_time = current_time - start_time

            # Get current waypoint
            waypoint = waypoints[waypoint_index]
            t_wp = waypoint[0]

            if elapsed_time >= t_wp:
                # Extract waypoint data
                (
                    _,
                    px,
                    py,
                    pz,
                    vx,
                    vy,
                    vz,
                    ax,
                    ay,
                    az,
                    yaw,
                    mode,
                    ledr,
                    ledg,
                    ledb,
                ) = waypoint

                # Log waypoint details
                logger.debug(
                    f"Waypoint {waypoint_index}: t={t_wp}, px={px}, py={py}, pz={pz}, "
                    f"vx={vx}, vy={vy}, vz={vz}, ax={ax}, ay={ay}, az={az}, "
                    f"yaw={yaw}, mode={mode}, ledr={ledr}, ledg={ledg}, ledb={ledb}"
                )

                # Update LED colors from trajectory
                led_controller.set_color(ledr, ledg, ledb)

                # Adjust waypoints for initial position drift if enabled
                if Params.ENABLE_INITIAL_POSITION_CORRECTION and initial_position_drift is not None:
                    logger.debug("Applying Drift Correction")
                    px += initial_position_drift.north_m
                    py += initial_position_drift.east_m

                # Send setpoints based on configuration
                position_setpoint = PositionNedYaw(px, py, pz, yaw)

                if Params.FEEDFORWARD_VELOCITY_ENABLED and Params.FEEDFORWARD_ACCELERATION_ENABLED:
                    velocity_setpoint = VelocityNedYaw(vx, vy, vz, yaw)
                    acceleration_setpoint = AccelerationNed(ax, ay, az)
                    await drone.offboard.set_position_velocity_acceleration_ned(
                        position_setpoint, velocity_setpoint, acceleration_setpoint
                    )
                    logger.debug("Position, velocity, and acceleration mode: Sending full setpoints")
                elif Params.FEEDFORWARD_VELOCITY_ENABLED:
                    velocity_setpoint = VelocityNedYaw(vx, vy, vz, yaw)
                    await drone.offboard.set_position_velocity_ned(position_setpoint, velocity_setpoint)
                    logger.debug("Position and velocity mode: Sending position and velocity setpoints")
                else:
                    await drone.offboard.set_position_ned(position_setpoint)
                    logger.debug("Position-only mode: Sending position setpoints")

                # Calculate time to end and mission progress
                time_to_end = waypoints[-1][0] - t_wp
                mission_progress = waypoint_index / total_waypoints

                logger.debug(
                    f"At time {elapsed_time:.2f}s, executing waypoint at t={t_wp:.2f}s. "
                    f"Time to end: {time_to_end:.2f}s, Mission progress: {mission_progress:.2%}"
                )

                # Check if we should initiate controlled landing
                if not trajectory_ends_high and mission_progress >= Params.MISSION_PROGRESS_THRESHOLD:
                    if (time_to_end <= Params.CONTROLLED_LANDING_TIME) or (-1 * pz < Params.CONTROLLED_LANDING_ALTITUDE):
                        logger.info("Initiating controlled landing phase.")
                        await controlled_landing(drone)
                        landing_detected = True
                        break  # Exit the trajectory execution loop

                waypoint_index += 1
            else:
                # Sleep until the time for the next waypoint
                sleep_duration = t_wp - elapsed_time
                if sleep_duration > 0:
                    await asyncio.sleep(sleep_duration)
                else:
                    # If sleep_duration is negative, we are behind schedule
                    logger.warning(f"Behind schedule by {-sleep_duration:.2f}s, skipping waypoint at t={t_wp:.2f}s.")
                    waypoint_index += 1

        except OffboardError as e:
            logger.error(f"Offboard error during trajectory: {e}")
            led_controller.set_color(255, 0, 0)  # Red
            break
        except Exception:
            logger.exception("Error during trajectory")
            led_controller.set_color(255, 0, 0)  # Red
            break

    # After trajectory completion
    if not landing_detected:
        if trajectory_ends_high:
            logger.info("Trajectory completed. Initiating PX4 native landing.")
            await stop_offboard_mode(drone)
            await perform_landing(drone)
            await wait_for_landing(drone)
        else:
            logger.warning("Controlled landing not initiated as expected. Initiating controlled landing now.")
            await controlled_landing(drone)

    logger.info("Drone mission completed.")
    led_controller.set_color(0, 255, 0)  # Green

async def controlled_landing(drone: System):
    """
    Perform controlled landing by sending descent commands and monitoring landing state.

    Args:
        drone (System): MAVSDK drone system instance.
    """
    logger = logging.getLogger(__name__)
    logger.info("Starting controlled landing.")
    led_controller = LEDController.get_instance()
    landing_detected = False
    landing_start_time = time.time()

    # Stop sending position setpoints
    logger.info("Stopping position setpoints and switching to velocity descent.")
    try:
        await drone.offboard.set_position_velocity_ned(
            PositionNedYaw(0.0, 0.0, 0.0, 0.0),
            VelocityNedYaw(0.0, 0.0, Params.CONTROLLED_DESCENT_SPEED, 0.0)
        )
    except OffboardError as e:
        logger.error(f"Offboard error during controlled landing setup: {e}")
        led_controller.set_color(255, 0, 0)  # Red
        return

    while not landing_detected:
        try:
            # Send descent command
            velocity_setpoint = VelocityNedYaw(0.0, 0.0, Params.CONTROLLED_DESCENT_SPEED, 0.0)
            await drone.offboard.set_velocity_ned(velocity_setpoint)
            logger.debug(f"Controlled landing: Descending at {Params.CONTROLLED_DESCENT_SPEED:.2f} m/s")

            # Check for landing detection
            async for landed_state in drone.telemetry.landed_state():
                if landed_state == LandedState.ON_GROUND:
                    landing_detected = True
                    logger.info("Landing detected during controlled landing.")
                    break
                break  # Only check the latest state

            # Check for timeout
            if (time.time() - landing_start_time) > Params.LANDING_TIMEOUT:
                logger.warning("Controlled landing timeout. Initiating PX4 native landing.")
                await stop_offboard_mode(drone)
                await perform_landing(drone)
                break

            await asyncio.sleep(0.1)
        except OffboardError as e:
            logger.error(f"Offboard error during controlled landing: {e}")
            led_controller.set_color(255, 0, 0)  # Red
            break
        except Exception:
            logger.exception("Error during controlled landing")
            led_controller.set_color(255, 0, 0)  # Red
            break

    if landing_detected:
        await stop_offboard_mode(drone)
        await disarm_drone(drone)
    else:
        # If timeout and still no landing detected, activate default land command
        logger.warning("Landing not detected, initiating PX4 native landing.")
        await stop_offboard_mode(drone)
        await perform_landing(drone)

    # Turn off LEDs
    led_controller.set_color(0, 255, 0)  # Green

async def wait_for_landing(drone: System):
    """
    Wait for the drone to land after initiating landing.

    Args:
        drone (System): MAVSDK drone system instance.
    """
    logger = logging.getLogger(__name__)
    start_time = time.time()
    while True:
        async for landed_state in drone.telemetry.landed_state():
            if landed_state == LandedState.ON_GROUND:
                logger.info("Drone has landed.")
                return
            break
        if time.time() - start_time > Params.LANDING_TIMEOUT:
            logger.error("Landing timeout.")
            break
        await asyncio.sleep(1)

@retry(stop=stop_after_attempt(Params.PREFLIGHT_MAX_RETRIES), wait=wait_fixed(5))
async def initial_setup_and_connection():
    """
    Perform the initial setup and connection for the drone.

    Returns:
        drone (System): MAVSDK drone system instance.
    """
    logger = logging.getLogger(__name__)
    try:
        # Initialize LEDController
        led_controller = LEDController.get_instance()
        # Set color to blue to indicate initialization
        led_controller.set_color(0, 0, 255)

        # Determine the MAVSDK server address and port
        grpc_port = Params.DEFAULT_GRPC_PORT  # Fixed gRPC port

        # MAVSDK server is assumed to be running on localhost
        mavsdk_server_address = "127.0.0.1"

        # Create the drone system
        drone = System(mavsdk_server_address=mavsdk_server_address, port=grpc_port)
        await drone.connect(system_address=f"udp://:{Params.mavsdk_port}")

        logger.info(
            f"Connecting to drone via MAVSDK server at {mavsdk_server_address}:{grpc_port} on UDP port {Params.mavsdk_port}."
        )

        # Wait for connection with a timeout
        start_time = time.time()
        async for state in drone.core.connection_state():
            if state.is_connected:
                logger.info(
                    f"Drone connected via MAVSDK server at {mavsdk_server_address}:{grpc_port}."
                )
                break
            if time.time() - start_time > 10:
                logger.error("Timeout while waiting for drone connection.")
                led_controller.set_color(255, 0, 0)  # Red
                raise TimeoutError("Drone connection timeout.")
            await asyncio.sleep(1)

        return drone
    except Exception:
        logger.exception("Error in initial setup and connection")
        led_controller.set_color(255, 0, 0)  # Red
        raise

async def pre_flight_checks(drone: System):
    """
    Perform pre-flight checks to ensure the drone is ready for flight.

    Args:
        drone (System): MAVSDK drone system instance.

    Returns:
        GlobalPosition: Home position telemetry data.
    """
    logger = logging.getLogger(__name__)
    logger.info("Starting pre-flight checks.")
    home_position = None
    led_controller = LEDController.get_instance()

    # Set color to yellow to indicate waiting for GPS lock
    led_controller.set_color(255, 255, 0)
    start_time = time.time()
    try:
        async for health in drone.telemetry.health():
            if health.is_global_position_ok and health.is_home_position_ok:
                logger.info("Global position estimate and home position check passed.")
                # Get home position
                async for position in drone.telemetry.position():
                    home_position = position
                    logger.info(f"Home Position set to: {home_position}")
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

        return home_position
    except Exception:
        logger.exception("Error during pre-flight checks")
        led_controller.set_color(255, 0, 0)  # Red
        raise

@retry(stop=stop_after_attempt(Params.PREFLIGHT_MAX_RETRIES), wait=wait_fixed(2))
async def arming_and_starting_offboard_mode(drone: System, home_position):
    """
    Arm the drone and start offboard mode.

    Args:
        drone (System): MAVSDK drone system instance.
        home_position: Home position telemetry data.
    """
    logger = logging.getLogger(__name__)
    try:
        led_controller = LEDController.get_instance()
        # Set color to green to indicate arming
        led_controller.set_color(0, 255, 0)

        # Get current global position
        current_global_position = None
        start_time = time.time()
        while current_global_position is None:
            async for position in drone.telemetry.position():
                current_global_position = position
                break
            if time.time() - start_time > Params.PRE_FLIGHT_TIMEOUT:
                logger.error("Timeout waiting for current global position.")
                raise TimeoutError("Timeout waiting for current global position.")
            await asyncio.sleep(0.1)

        # Compute initial position drift in NED coordinates
        initial_position_drift_ned = global_to_local(current_global_position, home_position)
        logger.info(f"Initial position drift in NED: {initial_position_drift_ned}")

        # Store the drift
        global initial_position_drift
        initial_position_drift = initial_position_drift_ned

        # Proceed to arm and start offboard mode
        logger.info("Arming drone.")
        await drone.action.arm()
        logger.info("Setting initial setpoint for offboard mode.")
        await drone.offboard.set_velocity_body(VelocityBodyYawspeed(0.0, 0.0, 0.0, 0.0))
        logger.info("Starting offboard mode.")
        await drone.offboard.start()
        # Set LEDs to solid white to indicate ready to fly
        led_controller.set_color(255, 255, 255)
    except OffboardError as error:
        logger.error(f"Offboard error: {error}")
        await drone.action.disarm()
        led_controller.set_color(255, 0, 0)  # Red
        raise
    except Exception:
        logger.exception("Error during arming and starting offboard mode")
        await drone.action.disarm()
        led_controller.set_color(255, 0, 0)  # Red
        raise

async def perform_landing(drone: System):
    """
    Perform landing for the drone.

    Args:
        drone (System): MAVSDK drone system instance.
    """
    logger = logging.getLogger(__name__)
    try:
        logger.info("Initiating landing.")
        await drone.action.land()

        start_time = time.time()
        while True:
            async for landed_state in drone.telemetry.landed_state():
                if landed_state == LandedState.ON_GROUND:
                    logger.info("Drone has landed.")
                    return
                break
            if time.time() - start_time > Params.LANDING_TIMEOUT:
                logger.error("Landing timeout.")
                break
            await asyncio.sleep(1)
    except ActionError as e:
        logger.error(f"Action error during landing: {e}")
    except Exception:
        logger.exception("Unexpected error during landing")

async def stop_offboard_mode(drone: System):
    """
    Stop offboard mode for the drone.

    Args:
        drone (System): MAVSDK drone system instance.
    """
    logger = logging.getLogger(__name__)
    try:
        logger.info("Stopping offboard mode.")
        await drone.offboard.stop()
    except OffboardError as error:
        logger.error(f"Error stopping offboard mode: {error}")
    except Exception:
        logger.exception("Unexpected error stopping offboard mode")

async def disarm_drone(drone: System):
    """
    Disarm the drone.

    Args:
        drone (System): MAVSDK drone system instance.
    """
    logger = logging.getLogger(__name__)
    try:
        logger.info("Disarming drone.")
        await drone.action.disarm()
        # Set LEDs to solid red to indicate disarming
        led_controller = LEDController.get_instance()
        led_controller.set_color(255, 0, 0)
    except ActionError as e:
        logger.error(f"Error disarming drone: {e}")
    except Exception:
        logger.exception("Unexpected error disarming drone")

# ----------------------------- #
#       MAVSDK Server Control   #
# ----------------------------- #

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
            for conn in proc.connections(kind='inet'):
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
#         Main Drone Runner     #
# ----------------------------- #

async def run_drone(synchronized_start_time, custom_csv=None):
    """
    Run the drone with the provided configurations.

    Args:
        synchronized_start_time (float): Synchronized start time (UNIX timestamp).
        custom_csv (str): Name of the custom trajectory CSV file.
    """
    logger = logging.getLogger(__name__)
    mavsdk_server = None
    try:
        global HW_ID

        # Step 1: Start MAVSDK Server
        udp_port = Params.mavsdk_port
        mavsdk_server = start_mavsdk_server(udp_port)
        if mavsdk_server is None:
            logger.error("Failed to start MAVSDK server. Exiting program.")
            sys.exit(1)

        # Wait briefly for the MAVSDK server to initialize
        await asyncio.sleep(2)

        # Step 2: Initial Setup and Connection
        drone = await initial_setup_and_connection()

        # Step 3: Perform Pre-flight Checks
        home_position = await pre_flight_checks(drone)

        # Wait until synchronized start time
        current_time = time.time()
        if synchronized_start_time > current_time:
            sleep_duration = synchronized_start_time - current_time
            logger.info(f"Waiting {sleep_duration:.2f}s until synchronized start time.")
            await asyncio.sleep(sleep_duration)
        elif synchronized_start_time < current_time:
            # We started after the synchronized start time, log a warning
            logger.warning(f"Synchronized start time was {current_time - synchronized_start_time:.2f}s ago.")
        else:
            logger.info("Synchronized start time is now.")

        # Step 4: Arm and Start Offboard Mode
        await arming_and_starting_offboard_mode(drone, home_position)

        # Step 5: Read and Adjust Trajectory Waypoints
        if custom_csv:
            # Custom CSV mode
            
            if Params.sim_mode:
                trajectory_filename = os.path.join('shapes_sitl', custom_csv)
            else:
                trajectory_filename = os.path.join('shapes', custom_csv)
            
            waypoints = read_trajectory_file(trajectory_filename)
        else:
            # Drone show mode
            # Read Hardware ID
            HW_ID = read_hw_id()
            if HW_ID is None:
                logger.error("Failed to read HW ID. Exiting program.")
                sys.exit(1)

            # Read Drone Configuration
            drone_config = read_config(CONFIG_CSV_NAME)
            if drone_config is None:
                logger.error("Drone configuration not found. Exiting program.")
                sys.exit(1)

            position_id = drone_config.pos_id
            if Params.sim_mode:
                trajectory_filename = os.path.join('shapes_sitl', 'swarm', 'processed', f"Drone {position_id}.csv")
            else:
                trajectory_filename = os.path.join('shapes', 'swarm', 'processed', f"Drone {position_id}.csv")
                
            waypoints = read_trajectory_file(
                trajectory_filename, drone_config.initial_x, drone_config.initial_y
            )

        # Step 6: Execute Trajectory
        await perform_trajectory(drone, waypoints, home_position, synchronized_start_time)

        logger.info("Drone mission completed successfully.")
        sys.exit(0)

    except Exception:
        logger.exception("Error running drone")
        sys.exit(1)
    finally:
        # Stop MAVSDK server
        if mavsdk_server:
            stop_mavsdk_server(mavsdk_server)

# ----------------------------- #
#             Main              #
# ----------------------------- #

def main():
    """
    Main function to run the drone.
    """
    # Configure logging
    configure_logging()
    logger = logging.getLogger(__name__)

    parser = argparse.ArgumentParser(description='Drone Show Script')
    parser.add_argument('--start_time', type=float, help='Synchronized start UNIX time')
    parser.add_argument('--custom_csv', type=str, help='Name of the custom trajectory CSV file eg. active.csv')
    args = parser.parse_args()

    # Get the synchronized start time
    if args.start_time:
        synchronized_start_time = args.start_time
    else:
        synchronized_start_time = time.time()

    global global_synchronized_start_time
    global_synchronized_start_time = synchronized_start_time

    try:
        asyncio.run(run_drone(synchronized_start_time, custom_csv=args.custom_csv))
    except Exception:
        logger.exception("Unhandled exception in main")
        sys.exit(1)

if __name__ == "__main__":
    main()
