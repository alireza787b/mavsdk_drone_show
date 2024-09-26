import os
import sys
import time
import asyncio
import csv
import subprocess
import signal
import logging
import socket
import psutil
import argparse

from mavsdk import System
from mavsdk.offboard import (
    PositionNedYaw,
    VelocityNedYaw,
    AccelerationNed,
    VelocityBodyYawspeed,
    OffboardError
)
from mavsdk.telemetry import LandedState
from mavsdk.action import ActionError
from tenacity import retry, stop_after_attempt, wait_fixed, RetryError
from src.led_controller import LEDController  # Import the LEDController

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ----------------------------- #
#           Constants           #
# ----------------------------- #

GRPC_PORT = 50040  # gRPC port for MAVSDK server
MAVSDK_PORT = 14540  # MAVSDK port for communication
SHOW_DEVIATIONS = False  # Flag to show deviations during flight
MAX_VERTICAL_CLIMB_RATE = 2.0  # Maximum vertical climb rate in m/s
MIN_SAFE_ALTITUDE = 1.0  # Minimum safe altitude in meters
ENABLE_MIN_ALTITUDE_CHECK = True  # Enable/Disable minimum altitude check
MAX_RETRIES = 3  # Maximum number of retries for critical operations
PRE_FLIGHT_TIMEOUT = 5  # Timeout for pre-flight checks in seconds
LANDING_TIMEOUT = 6  # Timeout for landing detection during landing phase in seconds

# ----------------------------- #
#        Global Variables       #
# ----------------------------- #

global_position_telemetry = {}  # Global position telemetry data
current_landed_state = None  # Current landed state of the drone
gloal_synchronized_start_time = None
# ----------------------------- #
#        Mode Descriptions      #
# ----------------------------- #

mode_descriptions = {
    0: "On the ground",
    10: "Initial climbing state",
    20: "Initial holding after climb",
    30: "Moving to start point",
    40: "Holding at start point",
    50: "Moving to maneuvering start point",
    60: "Holding at maneuver start point",
    70: "Maneuvering (trajectory)",
    80: "Holding at the end of the trajectory coordinate",
    90: "Returning to home coordinate",
    100: "Landing"
}

# ----------------------------- #
#        Helper Functions       #
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
#     Telemetry Coroutines      #
# ----------------------------- #

async def get_global_position_telemetry(drone):
    """
    Fetch and store global position telemetry for the drone.
    """
    try:
        async for global_position in drone.telemetry.position():
            global_position_telemetry["drone"] = global_position
    except Exception as e:
        logger.error(f"Error fetching global position telemetry: {e}")

async def get_landed_state_telemetry(drone):
    """
    Fetch and store landed state telemetry for the drone.
    """
    global current_landed_state
    try:
        async for landed_state in drone.telemetry.landed_state():
            current_landed_state = landed_state
    except Exception as e:
        logger.error(f"Error fetching landed state telemetry: {e}")

# ----------------------------- #
#         Core Functions        #
# ----------------------------- #

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

async def pre_flight_checks(drone):
    """
    Perform pre-flight checks to ensure the drone is ready for flight.

    Returns:
        home_position: The home position telemetry data.
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
async def arming_and_starting_offboard_mode(drone):
    """
    Arm the drone and start offboard mode.
    """
    try:
        led_controller = LEDController.get_instance()
        # Set color to green to indicate arming
        led_controller.set_color(0, 255, 0)
        logger.info("-- Arming drone")
        await drone.action.arm()
        logger.info("-- Setting initial setpoint")
        await drone.offboard.set_position_ned(PositionNedYaw(0.0, 0.0, 0.0, 0.0))
        logger.info("-- Starting offboard mode")
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

async def perform_trajectory(drone, waypoints, home_position, start_time):
    """
    Perform the flight trajectory based on waypoints, with time synchronization.

    Args:
        drone (System): MAVSDK drone system instance.
        waypoints (list): List of waypoints to execute.
        home_position: Home position telemetry data.
        start_time (float): Synchronized start time (UNIX timestamp).
    """
    logger.info("-- Performing trajectory with time synchronization")
    total_waypoints = len(waypoints)
    waypoint_index = 0
    last_mode = None
    led_controller = LEDController.get_instance()

    while waypoint_index < total_waypoints:
        try:
            current_time = time.time()
            elapsed_time = current_time - start_time

            waypoint = waypoints[waypoint_index]
            t_wp = waypoint[0]

            if elapsed_time >= t_wp:
                # Extract data from waypoint
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
                    mode_code,
                    ledr,
                    ledg,
                    ledb
                ) = waypoint

                if last_mode != mode_code:
                    # Print the mode number and its description
                    mode_description = mode_descriptions.get(mode_code, 'Unknown mode')
                    logger.info(f"Mode number: {mode_code}, Description: {mode_description}")
                    last_mode = mode_code

                # Update LED colors
                led_controller.set_color(ledr, ledg, ledb)

                # Minimum altitude check
                if ENABLE_MIN_ALTITUDE_CHECK:
                    if pz > -MIN_SAFE_ALTITUDE:
                        logger.warning(f"Desired altitude {pz:.2f}m is below minimum safe altitude. Adjusting to -{MIN_SAFE_ALTITUDE}m.")
                        pz = -MIN_SAFE_ALTITUDE

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

            # Check for landing during trajectory
            if current_landed_state == LandedState.ON_GROUND:
                logger.info("Drone has detected landing during trajectory.")
                await stop_offboard_mode(drone)
                await disarm_drone(drone)
                break

        except OffboardError as e:
            logger.error(f"Offboard error during trajectory: {e}")
            led_controller.set_color(255, 0, 0)  # Red
            break
        except Exception as e:
            logger.error(f"Error during trajectory: {e}")
            led_controller.set_color(255, 0, 0)  # Red
            break

    logger.info("-- Trajectory completed")
    led_controller.set_color(0, 0, 255)  # Blue
    # Turn off LEDs after trajectory is completed
    led_controller.turn_off()

async def perform_landing(drone):
    """
    Perform landing for the drone.
    """
    try:
        logger.info("-- Initiating landing")
        await drone.action.land()

        start_time = time.time()
        while True:
            if current_landed_state == LandedState.ON_GROUND:
                logger.info("Drone has landed.")
                break
            if time.time() - start_time > LANDING_TIMEOUT:
                logger.error("Landing timeout.")
                break
            await asyncio.sleep(1)
    except ActionError as e:
        logger.error(f"Action error during landing: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during landing: {e}")

async def stop_offboard_mode(drone):
    """
    Stop offboard mode for the drone.
    """
    try:
        logger.info("-- Stopping offboard mode")
        await drone.offboard.stop()
    except OffboardError as error:
        logger.error(f"Error stopping offboard mode: {error}")
    except Exception as e:
        logger.error(f"Unexpected error stopping offboard mode: {e}")

async def disarm_drone(drone):
    """
    Disarm the drone.
    """
    try:
        logger.info("-- Disarming drone")
        await drone.action.disarm()
        # Set LEDs to solid red to indicate disarming
        led_controller = LEDController.get_instance()
        led_controller.set_color(255, 0, 0)
    except ActionError as e:
        logger.error(f"Error disarming drone: {e}")
    except Exception as e:
        logger.error(f"Unexpected error disarming drone: {e}")

# ----------------------------- #
#          Main Runner          #
# ----------------------------- #

async def run(synchronized_start_time):
    """
    Run the drone mission with time synchronization.

    Args:
        synchronized_start_time (float): Synchronized start time (UNIX timestamp).
    """
    telemetry_task = None
    landed_state_task = None
    mavsdk_server = None
    try:
        # Start mavsdk_server
        udp_port = MAVSDK_PORT
        mavsdk_server = start_mavsdk_server(udp_port)
        if mavsdk_server is None:
            logger.error("Failed to start MAVSDK server. Exiting program.")
            sys.exit(1)

        # Wait a bit for the MAVSDK server to start
        await asyncio.sleep(2)

        # Initial setup and connection
        try:
            drone, telemetry_task, landed_state_task = await initial_setup_and_connection()
        except RetryError:
            logger.error("Initial setup and connection failed after maximum retries. Exiting program.")
            sys.exit(1)

        # Pre-flight checks
        try:
            home_position = await pre_flight_checks(drone)
        except Exception as e:
            logger.error(f"Pre-flight checks failed: {e}")
            sys.exit(1)

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

        # Arming and starting offboard mode
        try:
            await arming_and_starting_offboard_mode(drone)
        except RetryError:
            logger.error("Arming and starting offboard mode failed after maximum retries. Exiting program.")
            sys.exit(1)

        # Read trajectory from CSV file
        waypoints = []
        with open("shapes/active.csv", newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                t = float(row["t"])
                px = float(row["px"])
                py = float(row["py"])
                pz = float(row["pz"])
                vx = float(row["vx"])
                vy = float(row["vy"])
                vz = float(row["vz"])
                ax = float(row["ax"])
                ay = float(row["ay"])
                az = float(row["az"])
                yaw = float(row["yaw"])
                mode_code = int(row["mode"])
                ledr = int(float(row.get("ledr", 0)))  # Read LED Red value
                ledg = int(float(row.get("ledg", 0)))  # Read LED Green value
                ledb = int(float(row.get("ledb", 0)))  # Read LED Blue value

                waypoints.append((t, px, py, pz, vx, vy, vz, ax, ay, az, yaw, mode_code, ledr, ledg, ledb))

        # Perform trajectory
        await perform_trajectory(drone, waypoints, home_position, synchronized_start_time)

        # Ensure offboard mode is stopped
        await stop_offboard_mode(drone)

        # Initiate landing
        await perform_landing(drone)

        # Disarm the drone
        await disarm_drone(drone)

        logger.info("Drone mission completed successfully.")
    except Exception as e:
        logger.error(f"Error running drone: {e}")
        await disarm_drone(drone)
        sys.exit(1)
    finally:
        # Cancel telemetry tasks
        if telemetry_task:
            telemetry_task.cancel()
            await asyncio.sleep(0)
        if landed_state_task:
            landed_state_task.cancel()
            await asyncio.sleep(0)
        # Stop MAVSDK server
        if mavsdk_server:
            stop_mavsdk_server(mavsdk_server)
        logger.info("All tasks completed. Exiting program.")

# ----------------------------- #
#             Main              #
# ----------------------------- #

def main():
    """
    Main function to run the drone mission.
    """
    parser = argparse.ArgumentParser(description='Drone Show Script')
    parser.add_argument('--start_time', type=float, help='Synchronized start UNIX time')
    args = parser.parse_args()

    # Get the synchronized start time
    if args.start_time:
        synchronized_start_time = args.start_time
    else:
        synchronized_start_time = time.time()
    gloal_synchronized_start_time = synchronized_start_time
    try:
        asyncio.run(run(synchronized_start_time))
    except Exception as e:
        logger.error(f"Unhandled exception in main: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
