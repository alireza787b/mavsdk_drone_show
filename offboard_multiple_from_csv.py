import os
import sys
import time
import asyncio
import csv
import subprocess
import signal
import glob
import logging
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

STEP_TIME = 0.05  # Time step for trajectory execution loop in seconds
GRPC_PORT = 50040  # Fixed gRPC port for MAVSDK server
MAVSDK_PORT = 14540  # MAVSDK port for communication
SHOW_DEVIATIONS = False  # Flag to show deviations during flight
INITIAL_CLIMB_DURATION = 5  # Duration in seconds for the initial climb phase
MAX_VERTICAL_CLIMB_RATE = 2.0  # Maximum vertical climb rate in m/s
MAX_RETRIES = 3  # Maximum number of retries for critical operations
PRE_FLIGHT_TIMEOUT = 5  # Timeout for pre-flight checks in seconds
MIN_SAFE_ALTITUDE = 1.0  # Minimum safe altitude in meters
ENABLE_MIN_ALTITUDE_CHECK = True  # Enable/Disable minimum altitude check
LANDING_CHECK_DURATION = 5  # Duration in seconds for landing checks during the last n seconds of flight

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
position_id = None # Position ID of the drone
global_position_telemetry = {}  # Global position telemetry data
current_landed_state = None  # Current landed state of the drone

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

async def perform_trajectory(drone: System, waypoints: list, home_position):
    """
    Perform the flight trajectory based on waypoints, with safety checks.

    Args:
        drone (System): MAVSDK drone system instance.
        waypoints (list): List of waypoints to execute.
        home_position: Home position telemetry data.
    """
    logger.info("Performing trajectory.")
    total_duration = waypoints[-1][0]
    t = 0.0
    last_waypoint_index = 0

    # Initialize LEDController
    led_controller = LEDController.get_instance()

    while t <= total_duration:
        try:
            actual_position = global_position_telemetry.get("drone")
            if actual_position and home_position:
                local_ned_position = global_to_local(actual_position, home_position)
            else:
                local_ned_position = PositionNedYaw(0.0, 0.0, 0.0, 0.0)

            # Get current waypoint based on time 't'
            current_waypoint = None
            for i in range(last_waypoint_index, len(waypoints)):
                if t <= waypoints[i][0]:
                    current_waypoint = waypoints[i]
                    last_waypoint_index = i
                    break

            if current_waypoint is None:
                logger.error("No waypoint found for current time.")
                break

            # Extract waypoint data
            (
                t_wp,
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
            ) = current_waypoint

            # Update LED colors from trajectory
            LEDController.set_color(ledr, ledg, ledb)

            if t <= INITIAL_CLIMB_DURATION:
                # Initial climb phase: send vertical velocity command only
                vz_cmd = vz  # Vertical velocity (vz)
                # Limit vertical climb rate
                if abs(vz_cmd) > MAX_VERTICAL_CLIMB_RATE:
                    vz_cmd = MAX_VERTICAL_CLIMB_RATE * (vz_cmd / abs(vz_cmd))  # Limit to max climb rate
                    logger.warning(f"Vertical climb rate limited to {vz_cmd} m/s")
                logger.debug(f"Initial climb phase, sending vertical velocity: {vz_cmd}")
                await drone.offboard.set_velocity_body(VelocityBodyYawspeed(0.0, 0.0, vz_cmd, 0.0))
            else:
                # After initial climb phase: send position, velocity, and acceleration setpoints
                # Minimum altitude check
                if ENABLE_MIN_ALTITUDE_CHECK:
                    if pz > -MIN_SAFE_ALTITUDE:
                        logger.warning(
                            f"Desired altitude {pz:.2f}m is below minimum safe altitude. Adjusting to -{MIN_SAFE_ALTITUDE}m."
                        )
                        pz = -MIN_SAFE_ALTITUDE

                # Create setpoints
                position_setpoint = PositionNedYaw(px, py, pz, yaw)
                velocity_setpoint = VelocityNedYaw(vx, vy, vz, yaw)
                acceleration_setpoint = AccelerationNed(ax, ay, az)

                # Send setpoints to drone
                await drone.offboard.set_position_velocity_acceleration_ned(
                    position_setpoint, velocity_setpoint, acceleration_setpoint
                )

                # Landing checks during the last LANDING_CHECK_DURATION seconds
                if total_duration - t <= LANDING_CHECK_DURATION:
                    if current_landed_state == LandedState.ON_GROUND:
                        logger.info("Drone has detected landing during trajectory.")
                        await stop_offboard_mode(drone)
                        await disarm_drone(drone)
                        break

            await asyncio.sleep(STEP_TIME)
            t += STEP_TIME

            # Show deviations if enabled
            if SHOW_DEVIATIONS and position_setpoint is not None and int(t / STEP_TIME) % 100 == 0:
                deviation = [
                    px - local_ned_position.north_m,
                    py - local_ned_position.east_m,
                    pz - local_ned_position.down_m,
                ]
                logger.info(
                    f"Deviations: N:{deviation[0]:.2f} E:{deviation[1]:.2f} D:{deviation[2]:.2f}"
                )

        except OffboardError as e:
            logger.error(f"Offboard error during trajectory: {e}")
            LEDController.set_color(255, 0, 0)  # Red
            break
        except Exception as e:
            logger.error(f"Error during trajectory: {e}")
            LEDController.set_color(255, 0, 0)  # Red
            break

    logger.info("Trajectory completed.")
    LEDController.set_color(0, 0, 255)  # Blue
    LEDController.turn_off()

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
        LEDController.set_color(0, 0, 255)

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
                LEDController.set_color(255, 0, 0)  # Red
                raise TimeoutError("Drone connection timeout.")
            await asyncio.sleep(1)

        # Start telemetry tasks
        telemetry_task = asyncio.create_task(get_global_position_telemetry(drone))
        landed_state_task = asyncio.create_task(get_landed_state_telemetry(drone))

        return drone, telemetry_task, landed_state_task
    except Exception as e:
        logger.error(f"Error in initial setup and connection: {e}")
        LEDController.set_color(255, 0, 0)  # Red
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

    # Set color to yellow to indicate waiting for GPS lock
    LEDController.set_color(255, 255, 0)
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
                LEDController.set_color(255, 0, 0)  # Red
                raise TimeoutError("Pre-flight checks timed out.")
            await asyncio.sleep(1)

        if home_position:
            logger.info("Pre-flight checks successful.")
            LEDController.set_color(0, 255, 0)  # Green
        else:
            logger.error("Pre-flight checks failed.")
            LEDController.set_color(255, 0, 0)  # Red
            raise Exception("Pre-flight checks failed.")

        return home_position
    except Exception as e:
        logger.error(f"Error during pre-flight checks: {e}")
        LEDController.set_color(255, 0, 0)  # Red
        raise

@retry(stop=stop_after_attempt(MAX_RETRIES), wait=wait_fixed(2))
async def arming_and_starting_offboard_mode(drone: System):
    """
    Arm the drone and start offboard mode.

    Args:
        drone (System): MAVSDK drone system instance.
    """
    try:
        # Set color to green to indicate arming
        LEDController.set_color(0, 255, 0)
        logger.info("Arming drone.")
        await drone.action.arm()
        logger.info("Setting initial setpoint for offboard mode.")
        await drone.offboard.set_velocity_body(VelocityBodyYawspeed(0.0, 0.0, 0.0, 0.0))
        logger.info("Starting offboard mode.")
        await drone.offboard.start()
        # Set LEDs to solid white to indicate ready to fly
        LEDController.set_color(255, 255, 255)
    except OffboardError as error:
        logger.error(f"Offboard error: {error}")
        await drone.action.disarm()
        LEDController.set_color(255, 0, 0)  # Red
        raise
    except Exception as e:
        logger.error(f"Error during arming and starting offboard mode: {e}")
        await drone.action.disarm()
        LEDController.set_color(255, 0, 0)  # Red
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
        LEDController.set_color(255, 0, 0)
    except ActionError as e:
        logger.error(f"Error disarming drone: {e}")
    except Exception as e:
        logger.error(f"Unexpected error disarming drone: {e}")

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
    try:
        mavsdk_server = subprocess.Popen(
            ["./mavsdk_server", "-p", str(GRPC_PORT), f"udp://:{udp_port}"]
        )
        logger.info(
            f"MAVSDK server started with gRPC port {GRPC_PORT} and UDP port {udp_port}."
        )
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
            os.kill(mavsdk_server.pid, signal.SIGTERM)
            logger.info("MAVSDK server stopped.")
    except Exception as e:
        logger.error(f"Error stopping MAVSDK server: {e}")

# ----------------------------- #
#         Main Drone Runner     #
# ----------------------------- #

async def run_drone():
    """
    Run the drone with the provided configurations.
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
        udp_port = drone_config.mavlink_port
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

        # Step 6: Arm and Start Offboard Mode
        await arming_and_starting_offboard_mode(drone)

        # Step 7: Read and Adjust Trajectory Waypoints (for position_id of the drone)
        trajectory_filename = f"shapes/swarm/processed/Drone {position_id}.csv"
        waypoints = read_trajectory_file(
            trajectory_filename, drone_config.initial_x, drone_config.initial_y
        )

        # Step 8: Execute Trajectory
        await perform_trajectory(drone, waypoints, home_position)

        # Step 9: Stop Offboard Mode
        await stop_offboard_mode(drone)

        # Step 10: Initiate Landing
        await perform_landing(drone)

        # Step 11: Disarm the Drone
        await disarm_drone(drone)

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
    try:
        asyncio.run(run_drone())
    except Exception as e:
        logger.error(f"Unhandled exception in main: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
