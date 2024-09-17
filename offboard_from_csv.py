import os
import sys
import time
import asyncio
import csv
import subprocess
import signal
import logging

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

# Constants
STEP_TIME = 0.1  # Time step for trajectory execution loop in seconds
GRPC_PORT = 50040  # gRPC port for MAVSDK server
MAVSDK_PORT = 14540  # MAVSDK port for communication
SHOW_DEVIATIONS = False  # Flag to show deviations during flight
INITIAL_CLIMB_DURATION = 5  # Duration in seconds for the initial climb phase
MAX_VERTICAL_CLIMB_RATE = 2.0  # Maximum vertical climb rate in m/s
MIN_SAFE_ALTITUDE = 1.0  # Minimum safe altitude in meters
ENABLE_MIN_ALTITUDE_CHECK = True  # Enable/Disable minimum altitude check
LANDING_CHECK_DURATION = 5  # Duration in seconds for landing checks during the last n seconds of flight
MAX_RETRIES = 3  # Maximum number of retries for critical operations
PRE_FLIGHT_TIMEOUT = 5  # Timeout for pre-flight checks in seconds

# Global variables for telemetry data
global_position_telemetry = {}  # Global position telemetry data
current_landed_state = None  # Current landed state of the drone

# Mode descriptions
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
        LEDController.set_color(255, 0, 0)
    except ActionError as e:
        logger.error(f"Error disarming drone: {e}")
    except Exception as e:
        logger.error(f"Unexpected error disarming drone: {e}")

def start_mavsdk_server():
    """
    Start MAVSDK server instance for the drone.
    """
    try:
        mavsdk_server = subprocess.Popen(
            ["./mavsdk_server", "-p", str(GRPC_PORT), f"udp://:{MAVSDK_PORT}"]
        )
        logger.info(f"MAVSDK server started with gRPC port {GRPC_PORT} and UDP port {MAVSDK_PORT}.")
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

        # Create the drone system
        drone = System(mavsdk_server_address="127.0.0.1", port=GRPC_PORT)
        await drone.connect(system_address=f"udp://:{MAVSDK_PORT}")

        logger.info("Waiting for drone to connect...")
        start_time = time.time()
        async for state in drone.core.connection_state():
            if state.is_connected:
                logger.info("-- Connected to drone!")
                break
            if time.time() - start_time > 10:
                logger.error("Timeout while waiting for drone connection.")
                # Set color to red to indicate error
                LEDController.set_color(255, 0, 0)
                raise TimeoutError("Drone connection timeout.")
            await asyncio.sleep(1)

        # Start telemetry tasks
        telemetry_task = asyncio.create_task(get_global_position_telemetry(drone))
        landed_state_task = asyncio.create_task(get_landed_state_telemetry(drone))

        return drone, telemetry_task, landed_state_task
    except Exception as e:
        logger.error(f"Error in initial setup and connection: {e}")
        # Set color to red to indicate error
        LEDController.set_color(255, 0, 0)
        raise

async def pre_flight_checks(drone):
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
async def arming_and_starting_offboard_mode(drone):
    """
    Arm the drone and start offboard mode.
    """
    try:
        # Set color to green to indicate arming
        LEDController.set_color(0, 255, 0)
        logger.info("-- Arming drone")
        await drone.action.arm()
        logger.info("-- Setting initial setpoint")
        await drone.offboard.set_position_ned(PositionNedYaw(0.0, 0.0, 0.0, 0.0))
        logger.info("-- Starting offboard mode")
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

async def perform_trajectory(drone, waypoints):
    """
    Perform the flight trajectory based on waypoints, with safety checks.
    """
    logger.info("-- Performing trajectory")
    total_duration = waypoints[-1][0]  # Total duration is the time of the last waypoint
    t = 0.0  # Time variable
    last_mode = 0

    # Initialize LEDController
    led_controller = LEDController.get_instance()

    while t <= total_duration:
        try:
            # Find the current waypoint based on time
            current_waypoint = None
            for waypoint in waypoints:
                if t <= waypoint[0]:
                    current_waypoint = waypoint
                    break

            if current_waypoint is None:
                # Reached the end of the trajectory
                break

            # Extract data from current_waypoint
            position = current_waypoint[1:4]  # (px, py, pz)
            velocity = current_waypoint[4:7]  # (vx, vy, vz)
            acceleration = current_waypoint[7:10]  # (ax, ay, az)
            yaw = current_waypoint[10]
            mode_code = current_waypoint[11]
            ledr, ledg, ledb = current_waypoint[12], current_waypoint[13], current_waypoint[14]

            if last_mode != mode_code:
                # Print the mode number and its description
                mode_description = mode_descriptions.get(mode_code, 'Unknown mode')
                logger.info(f"Mode number: {mode_code}, Description: {mode_description}")
                last_mode = mode_code

            # Update LED colors
            LEDController.set_color(ledr, ledg, ledb)

            if t <= INITIAL_CLIMB_DURATION:
                # Initial climb phase: send vertical velocity command only
                vz = velocity[2]  # Vertical velocity (vz)
                # Limit vertical climb rate
                if abs(vz) > MAX_VERTICAL_CLIMB_RATE:
                    vz = MAX_VERTICAL_CLIMB_RATE * (vz / abs(vz))  # Limit to max climb rate
                    logger.warning(f"Vertical climb rate limited to {vz} m/s")
                logger.debug(f"Initial climb phase, sending vertical velocity: {vz}")
                await drone.offboard.set_velocity_body(VelocityBodyYawspeed(0.0, 0.0, vz, 0.0))
            else:
                # After initial climb phase: send position, velocity, and acceleration setpoints
                # Minimum altitude check
                if ENABLE_MIN_ALTITUDE_CHECK:
                    if position[2] > -MIN_SAFE_ALTITUDE:
                        logger.warning(f"Desired altitude {position[2]:.2f}m is below minimum safe altitude. Adjusting to -{MIN_SAFE_ALTITUDE}m.")
                        position = (position[0], position[1], -MIN_SAFE_ALTITUDE)

                await drone.offboard.set_position_velocity_acceleration_ned(
                    PositionNedYaw(*position, yaw),
                    VelocityNedYaw(*velocity, yaw),
                    AccelerationNed(*acceleration)
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

    logger.info("-- Trajectory completed")
    # Set color to blue to indicate mission completion
    LEDController.set_color(0, 0, 255)
    # Turn off LEDs after trajectory is completed
    LEDController.turn_off()

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
            if time.time() - start_time > PRE_FLIGHT_TIMEOUT:
                logger.error("Landing timeout.")
                break
            await asyncio.sleep(1)
    except ActionError as e:
        logger.error(f"Action error during landing: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during landing: {e}")

async def run():
    telemetry_task = None
    landed_state_task = None
    mavsdk_server = None
    try:
        # Start mavsdk_server
        mavsdk_server = start_mavsdk_server()
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
            await pre_flight_checks(drone)
        except Exception as e:
            logger.error(f"Pre-flight checks failed: {e}")
            sys.exit(1)

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
        await perform_trajectory(drone, waypoints)

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

def main():
    try:
        asyncio.run(run())
    except Exception as e:
        logger.error(f"Unhandled exception in main: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
