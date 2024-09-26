import os
import sys
import time
import asyncio
import csv
import subprocess
import signal
import glob
import logging
import socket
import psutil
import argparse
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

# ----------------------------- #
#          Logging Setup        #
# ----------------------------- #

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ----------------------------- #
#           Constants           #
# ----------------------------- #

# Fixed gRPC port for MAVSDK server
GRPC_PORT = 50040

# MAVSDK port for communication
MAVSDK_PORT = 14540

# Flag to show deviations during flight
SHOW_DEVIATIONS = False

# Maximum number of retries for critical operations
MAX_RETRIES = 3

# Timeout for pre-flight checks in seconds
PRE_FLIGHT_TIMEOUT = 5

# Timeout for landing detection during landing phase in seconds
LANDING_TIMEOUT = 6

# Descent speed during landing phase in m/s
DESCENT_SPEED = 0.3

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
global_position_telemetry = {}  # Global position telemetry data
current_landed_state = None  # Current landed state of the drone
global_synchronized_start_time = None
# ----------------------------- #
#         Helper Functions      #
# ----------------------------- #

def read_hw_id() -> int:
    """
    Read the hardware ID from a file with the extension '.hwID'.

    Returns:
        int: Hardware ID if found, else None.
    """
    hwid_files = glob.glob("*.hwID")
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

def read_config(filename: str) -> Drone:
    """
    Read the drone configuration from a CSV file.

    Args:
        filename (str): Path to the config CSV file.

    Returns:
        Drone: Namedtuple containing drone configuration if found, else None.
    """
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
    except FileNotFoundError as e:
        logger.error(f"Config file not found: {e}")
        return None
    except Exception as e:
        logger.error(f"Error reading config file {filename}: {e}")
        return None

def read_trajectory_file(filename: str, initial_x: float, initial_y: float) -> list:
    """
    Read and adjust the trajectory waypoints from a CSV file.

    Args:
        filename (str): Path to the drone-specific trajectory CSV file.
        initial_x (float): Initial x-coordinate from config.csv.
        initial_y (float): Initial y-coordinate from config.csv.

    Returns:
        list: List of adjusted waypoints.
    """
    waypoints = []
    try:
        with open(filename, newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                try:
                    t = float(row["t"])
                    px = float(row["px"]) - initial_x  # Adjust x-coordinate
                    py = float(row["py"]) - initial_y  # Adjust y-coordinate
                    pz = float(row["pz"])
                    vx = float(row["vx"])
                    vy = float(row["vy"])
                    vz = float(row["vz"])
                    ax = float(row["ax"])
                    ay = float(row["ay"])
                    az = float(row["az"])
                    yaw = float(row["yaw"])
                    ledr = int(float(row.get("ledr", 0)))
                    ledg = int(float(row.get("ledg", 0)))
                    ledb = int(float(row.get("ledb", 0)))
                    mode = row.get("mode", "0")  # Assuming 'mode' is an integer string
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
    except FileNotFoundError as e:
        logger.error(f"Trajectory file not found: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error reading trajectory file {filename}: {e}")
        sys.exit(1)
    return waypoints

def global_to_local(global_position, home_position):
    """
    Convert global coordinates to local NED coordinates.

    Args:
        global_position: Global position telemetry data.
        home_position: Home position telemetry data.

    Returns:
        PositionNedYaw: Converted local NED position.
    """
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
    except Exception as e:
        logger.error(f"Error converting global to local coordinates: {e}")
        return PositionNedYaw(0.0, 0.0, 0.0, 0.0)

# ----------------------------- #
#      Telemetry Coroutines     #
# ----------------------------- #

async def get_global_position_telemetry(drone: System):
    """
    Fetch and store global position telemetry for the drone.

    Args:
        drone (System): MAVSDK drone system instance.
    """
    try:
        async for global_position in drone.telemetry.position():
            global_position_telemetry["drone"] = global_position
    except Exception as e:
        logger.error(f"Error fetching global position telemetry: {e}")

async def get_landed_state_telemetry(drone: System):
    """
    Fetch and store landed state telemetry for the drone.

    Args:
        drone (System): MAVSDK drone system instance.
    """
    global current_landed_state
    try:
        async for landed_state in drone.telemetry.landed_state():
            current_landed_state = landed_state
    except Exception as e:
        logger.error(f"Error fetching landed state telemetry: {e}")

# ----------------------------- #
#        Core Functionalities   #
# ----------------------------- #

async def perform_trajectory(drone: System, waypoints: list, home_position, start_time):
    """
    Perform the flight trajectory based on waypoints, with time synchronization.

    Args:
        drone (System): MAVSDK drone system instance.
        waypoints (list): List of waypoints to execute.
        home_position: Home position telemetry data.
        start_time (float): Synchronized start time (UNIX timestamp).
    """
    logger.info("Performing trajectory with time synchronization.")
    total_waypoints = len(waypoints)
    waypoint_index = 0
    landing_detected = False

    # Initialize LEDController
    led_controller = LEDController.get_instance()

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

                # Update LED colors from trajectory
                led_controller.set_color(ledr, ledg, ledb)

                # Send setpoints to drone
                position_setpoint = PositionNedYaw(px, py, pz, yaw)
                velocity_setpoint = VelocityNedYaw(vx, vy, vz, yaw)
                acceleration_setpoint = AccelerationNed(ax, ay, az)

                await drone.offboard.set_position_velocity_acceleration_ned(
                    position_setpoint, velocity_setpoint, acceleration_setpoint
                )
                logger.debug(f"At time {elapsed_time:.2f}s, executing waypoint at t={t_wp:.2f}s.")

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

            # Landing checks after trajectory completion
            if waypoint_index >= total_waypoints and not landing_detected:
                if current_landed_state == LandedState.ON_GROUND:
                    logger.info("Drone has landed.")
                    landing_detected = True
                    break

        except OffboardError as e:
            logger.error(f"Offboard error during trajectory: {e}")
            led_controller.set_color(255, 0, 0)  # Red
            break
        except Exception as e:
            logger.error(f"Error during trajectory: {e}")
            led_controller.set_color(255, 0, 0)  # Red
            break

    logger.info("Trajectory completed.")
    led_controller.set_color(0, 0, 255)  # Blue

    # Begin landing phase
    logger.info("Beginning landing phase.")
    landing_start_time = time.time()

    while not landing_detected and (time.time() - landing_start_time) < LANDING_TIMEOUT:
        try:
            # Send setpoint with final descent speed
            velocity_setpoint = VelocityNedYaw(0.0, 0.0, DESCENT_SPEED, 0.0)

            await drone.offboard.set_velocity_ned(
                velocity_setpoint
            )
            logger.debug(f"Landing phase: Descending at {DESCENT_SPEED:.2f} m/s")

            # Check for landing detection
            if current_landed_state == LandedState.ON_GROUND:
                landing_detected = True
                logger.info("Landing detected during landing phase.")
                break

            await asyncio.sleep(0.1)
        except OffboardError as e:
            logger.error(f"Offboard error during landing phase: {e}")
            led_controller.set_color(255, 0, 0)  # Red
            break
        except Exception as e:
            logger.error(f"Error during landing phase: {e}")
            led_controller.set_color(255, 0, 0)  # Red
            break

    if landing_detected:
        await stop_offboard_mode(drone)
        await disarm_drone(drone)
    else:
        # If timeout and still no landing detected, activate default land command
        logger.warning("Landing not detected within timeout, initiating default land command.")
        await stop_offboard_mode(drone)
        await perform_landing(drone)

    # Turn off LEDs
    led_controller.set_color(0, 255, 0)  # Green

@retry(stop=stop_after_attempt(MAX_RETRIES), wait=wait_fixed(5))
async def initial_setup_and_connection():
    """
    Perform the initial setup and connection for the drone.

    Returns:
        tuple: (drone System instance, telemetry_task, landed_state_task)
    """
    try:
        # Initialize LEDController
        led_controller = LEDController.get_instance()
        # Set color to blue to indicate initialization
        led_controller.set_color(0, 0, 255)

        # Determine the MAVSDK server address and port
        grpc_port = GRPC_PORT  # Fixed gRPC port

        # MAVSDK server is assumed to be running on localhost
        mavsdk_server_address = "127.0.0.1"

        # Create the drone system
        drone = System(mavsdk_server_address=mavsdk_server_address, port=grpc_port)
        await drone.connect(system_address=f"udp://:{MAVSDK_PORT}")

        logger.info(
            f"Connecting to drone via MAVSDK server at {mavsdk_server_address}:{grpc_port} on UDP port {MAVSDK_PORT}."
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

        # Start telemetry tasks
        telemetry_task = asyncio.create_task(get_global_position_telemetry(drone))
        landed_state_task = asyncio.create_task(get_landed_state_telemetry(drone))

        return drone, telemetry_task, landed_state_task
    except Exception as e:
        logger.error(f"Error in initial setup and connection: {e}")
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
                home_position = global_position_telemetry.get("drone")
                if home_position:
                    logger.info(f"Home Position set to: {home_position}")
                else:
                    logger.error("Home position telemetry data is missing.")
                break
            else:
                if not health.is_global_position_ok:
                    logger.warning("Waiting for global position to be okay.")
                if not health.is_home_position_ok:
                    logger.warning("Waiting for home position to be set.")

            if time.time() - start_time > PRE_FLIGHT_TIMEOUT:
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
    except Exception as e:
        logger.error(f"Error during pre-flight checks: {e}")
        led_controller.set_color(255, 0, 0)  # Red
        raise

@retry(stop=stop_after_attempt(MAX_RETRIES), wait=wait_fixed(2))
async def arming_and_starting_offboard_mode(drone: System):
    """
    Arm the drone and start offboard mode.

    Args:
        drone (System): MAVSDK drone system instance.
    """
    try:
        led_controller = LEDController.get_instance()
        # Set color to green to indicate arming
        led_controller.set_color(0, 255, 0)
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
    except Exception as e:
        logger.error(f"Error during arming and starting offboard mode: {e}")
        await drone.action.disarm()
        led_controller.set_color(255, 0, 0)  # Red
        raise

async def perform_landing(drone: System):
    """
    Perform landing for the drone.

    Args:
        drone (System): MAVSDK drone system instance.
    """
    try:
        logger.info("Initiating landing.")
        await drone.action.land()

        start_time = time.time()
        while True:
            if current_landed_state == LandedState.ON_GROUND:
                logger.info("Drone has landed.")
                break
            if time.time() - start_time > PRE_FLIGHT_TIMEOUT:
                logger.error("Landing timeout.")
                break
            await asyncio.sleep(1)
    except ActionError as e:
        logger.error(f"Action error during landing: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during landing: {e}")

async def stop_offboard_mode(drone: System):
    """
    Stop offboard mode for the drone.

    Args:
        drone (System): MAVSDK drone system instance.
    """
    try:
        logger.info("Stopping offboard mode.")
        await drone.offboard.stop()
    except OffboardError as error:
        logger.error(f"Error stopping offboard mode: {error}")
    except Exception as e:
        logger.error(f"Unexpected error stopping offboard mode: {e}")

async def disarm_drone(drone: System):
    """
    Disarm the drone.

    Args:
        drone (System): MAVSDK drone system instance.
    """
    try:
        logger.info("Disarming drone.")
        await drone.action.disarm()
        # Set LEDs to solid red to indicate disarming
        led_controller = LEDController.get_instance()
        led_controller.set_color(255, 0, 0)
    except ActionError as e:
        logger.error(f"Error disarming drone: {e}")
    except Exception as e:
        logger.error(f"Unexpected error disarming drone: {e}")

# ----------------------------- #
#       MAVSDK Server Control   #
# ----------------------------- #

def check_mavsdk_server_running(port):
    """
    Checks if the MAVSDK server is running on the specified gRPC port.

    Args:
        port (int): The gRPC port to check.

    Returns:
        tuple: (is_running (bool), pid (int or None))
    """
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            for conn in proc.connections(kind='inet'):
                if conn.laddr.port == port:
                    return True, proc.info['pid']
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False, None

def wait_for_port(port, host='localhost', timeout=10.0):
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
        except (ConnectionRefusedError, socket.timeout):
            if time.time() - start_time >= timeout:
                return False
            time.sleep(0.1)

def start_mavsdk_server(udp_port: int):
    """
    Start MAVSDK server instance for the drone.

    Args:
        udp_port (int): UDP port for MAVSDK server communication.

    Returns:
        subprocess.Popen: MAVSDK server subprocess if started successfully, else None.
    """
    try:
        # Check if MAVSDK server is already running
        is_running, pid = check_mavsdk_server_running(GRPC_PORT)
        if is_running:
            logger.info(f"MAVSDK server already running on port {GRPC_PORT}. Terminating...")
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

        # Start the MAVSDK server
        mavsdk_server = subprocess.Popen(
            ["./mavsdk_server", "-p", str(GRPC_PORT), f"udp://:{udp_port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        logger.info(
            f"MAVSDK server started with gRPC port {GRPC_PORT} and UDP port {udp_port}."
        )

        # Wait until the server is listening on the gRPC port
        if not wait_for_port(GRPC_PORT, timeout=10):
            logger.error(f"MAVSDK server did not start listening on port {GRPC_PORT} within timeout.")
            mavsdk_server.terminate()
            return None

        logger.info("MAVSDK server is now listening on gRPC port.")
        return mavsdk_server
    except FileNotFoundError:
        logger.error("mavsdk_server executable not found. Ensure it is present in the current directory.")
        return None
    except Exception as e:
        logger.error(f"Error starting MAVSDK server: {e}")
        return None

def stop_mavsdk_server(mavsdk_server):
    """
    Stop the MAVSDK server instance.

    Args:
        mavsdk_server (subprocess.Popen): MAVSDK server subprocess.
    """
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
    except Exception as e:
        logger.error(f"Error stopping MAVSDK server: {e}")

# ----------------------------- #
#         Main Drone Runner     #
# ----------------------------- #

async def run_drone(synchronized_start_time):
    """
    Run the drone with the provided configurations.

    Args:
        synchronized_start_time (float): Synchronized start time (UNIX timestamp).
    """
    telemetry_task = None
    landed_state_task = None
    mavsdk_server = None
    try:
        global HW_ID

        # Step 1: Read Hardware ID
        HW_ID = read_hw_id()
        if HW_ID is None:
            logger.error("Failed to read HW ID. Exiting program.")
            sys.exit(1)

        # Step 2: Read Drone Configuration
        drone_config = read_config("config.csv")
        if drone_config is None:
            logger.error("Drone configuration not found. Exiting program.")
            sys.exit(1)

        # Step 3: Start MAVSDK Server
        udp_port = MAVSDK_PORT
        position_id = drone_config.pos_id
        mavsdk_server = start_mavsdk_server(udp_port)
        if mavsdk_server is None:
            logger.error("Failed to start MAVSDK server. Exiting program.")
            sys.exit(1)

        # Wait briefly for the MAVSDK server to initialize
        await asyncio.sleep(2)

        # Step 4: Initial Setup and Connection
        drone, telemetry_task, landed_state_task = await initial_setup_and_connection()

        # Step 5: Perform Pre-flight Checks
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

        # Step 6: Arm and Start Offboard Mode
        await arming_and_starting_offboard_mode(drone)

        # Step 7: Read and Adjust Trajectory Waypoints (for position_id of the drone)
        trajectory_filename = f"shapes/swarm/processed/Drone {position_id}.csv"
        waypoints = read_trajectory_file(
            trajectory_filename, drone_config.initial_x, drone_config.initial_y
        )

        # Step 8: Execute Trajectory
        await perform_trajectory(drone, waypoints, home_position, synchronized_start_time)

        logger.info("Drone mission completed successfully.")
        sys.exit(0)

    except Exception as e:
        logger.error(f"Error running drone: {e}")
        sys.exit(1)
    finally:
        # Clean up telemetry tasks
        if telemetry_task:
            telemetry_task.cancel()
            try:
                await telemetry_task
            except asyncio.CancelledError:
                pass
        if landed_state_task:
            landed_state_task.cancel()
            try:
                await landed_state_task
            except asyncio.CancelledError:
                pass
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
    parser = argparse.ArgumentParser(description='Drone Show Script')
    parser.add_argument('--start_time', type=float, help='Synchronized start UNIX time')
    args = parser.parse_args()

    # Get the synchronized start time
    if args.start_time:
        synchronized_start_time = args.start_time
    else:
        synchronized_start_time = time.time()
        
    global_synchronized_start_time = synchronized_start_time

    try:
        asyncio.run(run_drone(synchronized_start_time))
    except Exception as e:
        logger.error(f"Unhandled exception in main: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
