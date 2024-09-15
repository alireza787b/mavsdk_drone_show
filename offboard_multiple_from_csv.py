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
from mavsdk.offboard import PositionNedYaw, VelocityBodyYawspeed, VelocityNedYaw, AccelerationNed, OffboardError
from mavsdk.telemetry import LandedState
from mavsdk.action import ActionError
import navpy
from tenacity import retry, stop_after_attempt, wait_fixed
from src.led_controller import LEDController

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Constants
STEP_TIME = 0.05
DEFAULT_Z = 0.83
GRPC_PORT = 50040  # Fixed port since SIM_MODE is False
MAVSDK_PORT = 14540  # MAVSDK port for communication
SHOW_DEVIATIONS = False
INITIAL_CLIMB_DURATION = 5  # Duration in seconds for the initial climb phase
MAX_RETRIES = 3  # Maximum number of retries for critical operations
PRE_FLIGHT_TIMEOUT = 60  # Timeout for pre-flight checks in seconds

Drone = namedtuple('Drone', 'hw_id pos_id x y ip mavlink_port debug_port gcs_ip')

HW_ID = None
global_position_telemetry = {}

def read_hw_id() -> int:
    """
    Read the hardware ID from a file.
    """
    hwid_files = glob.glob('*.hwID')
    if hwid_files:
        filename = hwid_files[0]
        hw_id = os.path.splitext(filename)[0]  # Get filename without extension
        logger.info(f"Hardware ID {hw_id} detected.")
        return int(hw_id)
    else:
        logger.error("Hardware ID file not found.")
        return None

def read_config(filename: str) -> Drone:
    """
    Read the drone configuration from a CSV file.
    """
    try:
        with open(filename, newline='') as csvfile:
            reader = csv.reader(csvfile)
            headers = next(reader, None)  # Read the header row
            for row in reader:
                hw_id, pos_id, x, y, ip, mavlink_port, debug_port, gcs_ip = row
                if int(hw_id) == HW_ID:
                    drone = Drone(hw_id, pos_id, float(x), float(y), ip, mavlink_port, debug_port, gcs_ip)
                    logger.info(f"Drone configuration found: {drone}")
                    return drone
        logger.error(f"No configuration found for HW_ID {HW_ID}.")
        return None
    except FileNotFoundError as e:
        logger.error(f"Config file not found: {e}")
        return None
    except Exception as e:
        logger.error(f"Error reading config file {filename}: {e}")
        return None

def read_trajectory_file(filename: str) -> list:
    """
    Read the trajectory waypoints from a CSV file.
    """
    waypoints = []
    try:
        with open(filename, newline="") as csvfile:
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
                ledr = int(float(row.get("ledr", 0)))  # Read LED Red value
                ledg = int(float(row.get("ledg", 0)))  # Read LED Green value
                ledb = int(float(row.get("ledb", 0)))  # Read LED Blue value
                waypoints.append((t, px, py, pz, vx, vy, vz, ax, ay, az, yaw, ledr, ledg, ledb))
        logger.info(f"Trajectory file '{filename}' read successfully with {len(waypoints)} waypoints.")
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
    """
    try:
        # Convert latitude and longitude to the local coordinate system
        lla_ref = [home_position.latitude_deg, home_position.longitude_deg, home_position.absolute_altitude_m]
        lla = [global_position.latitude_deg, global_position.longitude_deg, global_position.absolute_altitude_m]

        ned = navpy.lla2ned(lla[0], lla[1], lla[2],
                            lla_ref[0], lla_ref[1], lla_ref[2])

        # Return the local position
        return PositionNedYaw(ned[0], ned[1], ned[2], 0.0)
    except Exception as e:
        logger.error(f"Error converting global to local coordinates: {e}")
        return PositionNedYaw(0.0, 0.0, 0.0, 0.0)

async def get_global_position_telemetry(drone: System):
    """
    Fetch and store global position telemetry for the drone.
    """
    try:
        async for global_position in drone.telemetry.position():
            global_position_telemetry["drone"] = global_position
    except Exception as e:
        logger.error(f"Error fetching global position telemetry: {e}")

async def perform_trajectory(drone: System, waypoints: list, home_position):
    """
    Perform the flight trajectory based on waypoints.
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

            # Get current waypoint
            current_waypoint = None
            for i in range(last_waypoint_index, len(waypoints)):
                if t <= waypoints[i][0]:
                    current_waypoint = waypoints[i]
                    last_waypoint_index = i
                    break

            if current_waypoint is None:
                logger.error("No waypoint found for current time.")
                break

            if t <= INITIAL_CLIMB_DURATION:
                vz = current_waypoint[6]
                logger.debug(f"Initial climb phase, sending vertical velocity: {vz}")
                await drone.offboard.set_velocity_body(VelocityBodyYawspeed(0.0, 0.0, vz, 0.0))
            else:
                position = current_waypoint[1:4]
                velocity = current_waypoint[4:7]
                acceleration = current_waypoint[7:10]
                yaw = current_waypoint[10]

                # Update LED colors from trajectory
                ledr, ledg, ledb = current_waypoint[11], current_waypoint[12], current_waypoint[13]
                LEDController.set_color(ledr, ledg, ledb)

                await drone.offboard.set_position_velocity_acceleration_ned(
                    PositionNedYaw(*position, yaw),
                    VelocityNedYaw(*velocity, yaw),
                    AccelerationNed(*acceleration)
                )

            await asyncio.sleep(STEP_TIME)
            t += STEP_TIME

            if position is not None and SHOW_DEVIATIONS and int(t / STEP_TIME) % 100 == 0:
                deviation = [
                    position[0] - local_ned_position.north_m,
                    position[1] - local_ned_position.east_m,
                    position[2] - local_ned_position.down_m
                ]
                logger.info(f"Deviations: N:{deviation[0]:.2f} E:{deviation[1]:.2f} D:{deviation[2]:.2f}")

        except OffboardError as e:
            logger.error(f"Offboard error during trajectory: {e}")
            # Set color to red to indicate error
            LEDController.set_color(255, 0, 0)
            break
        except Exception as e:
            logger.error(f"Error during trajectory: {e}")
            # Set color to red to indicate error
            LEDController.set_color(255, 0, 0)
            break

    logger.info("Trajectory completed.")
    # Set color to blue to indicate mission completion
    LEDController.set_color(0, 0, 255)
    # Turn off LEDs after trajectory is completed
    LEDController.turn_off()

@retry(stop=stop_after_attempt(MAX_RETRIES), wait=wait_fixed(5))
async def initial_setup_and_connection():
    """
    Perform the initial setup and connection for the drone.
    """
    try:
        # Initialize LEDController
        led_controller = LEDController.get_instance()
        # Set color to blue to indicate initialization
        LEDController.set_color(0, 0, 255)

        # Determine the MAVSDK server address and port
        grpc_port = GRPC_PORT  # Fixed gRPC port

        # Real drone mode
        mavsdk_server_address = "127.0.0.1"

        # Create the drone system
        drone = System(mavsdk_server_address=mavsdk_server_address, port=grpc_port)
        await drone.connect(system_address=f"udp://:{MAVSDK_PORT}")

        logger.info(f"Connecting to drone via MAVSDK server at {mavsdk_server_address}:{grpc_port} on UDP port {MAVSDK_PORT}.")

        # Wait for connection with a timeout
        start_time = time.time()
        async for state in drone.core.connection_state():
            if state.is_connected:
                logger.info(f"Drone connected via MAVSDK server at {mavsdk_server_address}:{grpc_port}.")
                break
            if time.time() - start_time > 10:
                logger.error("Timeout while waiting for drone connection.")
                # Set color to red to indicate error
                LEDController.set_color(255, 0, 0)
                raise TimeoutError("Drone connection timeout.")
            await asyncio.sleep(1)

        # Start telemetry task
        telemetry_task = asyncio.create_task(get_global_position_telemetry(drone))

        return drone, telemetry_task
    except Exception as e:
        logger.error(f"Error in initial setup and connection: {e}")
        # Set color to red to indicate error
        LEDController.set_color(255, 0, 0)
        raise

async def pre_flight_checks(drone: System):
    """
    Perform pre-flight checks to ensure the drone is ready for flight.
    """
    logger.info("Starting pre-flight checks.")
    home_position = None

    # Set color to yellow to indicate waiting for GPS lock
    LEDController.set_color(255, 255, 0)
    start_time = time.time()
    async for health in drone.telemetry.health():
        if health.is_global_position_ok and health.is_home_position_ok:
            logger.info("Global position estimate and home position check passed.")
            home_position = global_position_telemetry.get("drone")
            logger.info(f"Home Position set to: {home_position}")
            break
        else:
            if not health.is_global_position_ok:
                logger.warning("Waiting for global position to be okay.")
            if not health.is_home_position_ok:
                logger.warning("Waiting for home position to be set.")

        if time.time() - start_time > PRE_FLIGHT_TIMEOUT:
            logger.error("Pre-flight checks timed out.")
            # Set color to red to indicate error
            LEDController.set_color(255, 0, 0)
            raise TimeoutError("Pre-flight checks timed out.")
        await asyncio.sleep(1)

    if home_position is not None:
        logger.info("Pre-flight checks successful.")
        # Set LEDs to solid green to indicate success
        LEDController.set_color(0, 255, 0)
    else:
        logger.error("Pre-flight checks failed.")
        # Set color to red to indicate error
        LEDController.set_color(255, 0, 0)
        raise Exception("Pre-flight checks failed.")

    return home_position

@retry(stop=stop_after_attempt(MAX_RETRIES), wait=wait_fixed(2))
async def arming_and_starting_offboard_mode(drone: System):
    """
    Arm the drone and start offboard mode.
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
        # Set color to red to indicate error
        LEDController.set_color(255, 0, 0)
        raise
    except Exception as e:
        logger.error(f"Error during arming and starting offboard mode: {e}")
        await drone.action.disarm()
        # Set color to red to indicate error
        LEDController.set_color(255, 0, 0)
        raise

async def perform_landing(drone: System):
    """
    Perform landing for the drone.
    """
    try:
        logger.info("Initiating landing.")
        await drone.action.land()

        async for state in drone.telemetry.landed_state():
            if state == LandedState.ON_GROUND:
                logger.info("Drone has landed.")
                break
            await asyncio.sleep(1)
    except ActionError as e:
        logger.error(f"Action error during landing: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during landing: {e}")

async def stop_offboard_mode(drone: System):
    """
        Stop offboard mode for the drone.
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

def start_mavsdk_server(udp_port: int):
    """
    Start MAVSDK server instance for the drone.
    """
    try:
        mavsdk_server = subprocess.Popen(["./mavsdk_server", "-p", str(GRPC_PORT), f"udp://:{udp_port}"])
        logger.info(f"MAVSDK server started with gRPC port {GRPC_PORT} and UDP port {udp_port}.")
        return mavsdk_server
    except Exception as e:
        logger.error(f"Error starting MAVSDK server: {e}")
        return None

def stop_mavsdk_server(mavsdk_server):
    """
    Stop the MAVSDK server instance.
    """
    try:
        os.kill(mavsdk_server.pid, signal.SIGTERM)
        logger.info("MAVSDK server stopped.")
    except Exception as e:
        logger.error(f"Error stopping MAVSDK server: {e}")

async def run_drone():
    """
    Run the drone with the provided configurations.
    """
    telemetry_task = None
    mavsdk_server = None
    try:
        global HW_ID

        HW_ID = read_hw_id()
        if HW_ID is None:
            logger.error("Failed to read HW ID. Exiting program.")
            sys.exit(1)

        drone_config = read_config('config.csv')
        if drone_config is None:
            logger.error("Drone configuration not found. Exiting program.")
            sys.exit(1)

        udp_port = int(drone_config.mavlink_port)
        mavsdk_server = start_mavsdk_server(udp_port)
        if mavsdk_server is None:
            logger.error("Failed to start MAVSDK server. Exiting program.")
            sys.exit(1)

        # Wait a bit for the MAVSDK server to start
        await asyncio.sleep(2)

        drone, telemetry_task = await initial_setup_and_connection()

        home_position = await pre_flight_checks(drone)
        await arming_and_starting_offboard_mode(drone)

        filename = f"shapes/swarm/processed/Drone {HW_ID}.csv"
        waypoints = read_trajectory_file(filename)
        await perform_trajectory(drone, waypoints, home_position)

        await stop_offboard_mode(drone)
        await perform_landing(drone)
        await disarm_drone(drone)

        logger.info("Drone mission completed successfully.")
        sys.exit(0)

    except Exception as e:
        logger.error(f"Error running drone: {e}")
        sys.exit(1)
    finally:
        if telemetry_task:
            telemetry_task.cancel()
            await asyncio.sleep(0)  # Allow cancellation to propagate
        if mavsdk_server:
            stop_mavsdk_server(mavsdk_server)

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
