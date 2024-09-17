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


async def run():
    try:
        # Define a dictionary to map mode codes to their descriptions
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

        grpc_port = GRPC_PORT
        drone = System(mavsdk_server_address="127.0.0.1", port=grpc_port)
        await drone.connect(system_address=f"udp://:{MAVSDK_PORT}")

        logger.info("Waiting for drone to connect...")
        async for state in drone.core.connection_state():
            if state.is_connected:
                logger.info("-- Connected to drone!")
                break

        logger.info("Waiting for drone to have a global position estimate...")
        async for health in drone.telemetry.health():
            if health.is_global_position_ok and health.is_home_position_ok:
                logger.info("-- Global position estimate OK")
                break

        logger.info("-- Arming drone")
        await drone.action.arm()

        logger.info("-- Setting initial setpoint")
        await drone.offboard.set_position_ned(PositionNedYaw(0.0, 0.0, 0.0, 0.0))

        logger.info("-- Starting offboard mode")
        try:
            await drone.offboard.start()
        except OffboardError as error:
            logger.error(f"Starting offboard mode failed with error code: {error._result.result}")
            logger.info("-- Disarming drone")
            await drone.action.disarm()
            return

        # Start telemetry tasks
        telemetry_task = asyncio.create_task(get_global_position_telemetry(drone))
        landed_state_task = asyncio.create_task(get_landed_state_telemetry(drone))

        waypoints = []

        # Read data from the CSV file
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

        # Ensure offboard mode is stopped
        await stop_offboard_mode(drone)

        # Initiate landing
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

        # Disarm the drone
        await disarm_drone(drone)

        # Turn off LEDs after landing
        LEDController.turn_off()

    except Exception as e:
        logger.error(f"Error running drone: {e}")
        await disarm_drone(drone)
    finally:
        # Cancel telemetry tasks
        if 'telemetry_task' in locals():
            telemetry_task.cancel()
            await asyncio.sleep(0)
        if 'landed_state_task' in locals():
            landed_state_task.cancel()
            await asyncio.sleep(0)


async def main():
    try:
        udp_port = MAVSDK_PORT

        # Start mavsdk_server
        grpc_port = GRPC_PORT
        mavsdk_server = subprocess.Popen(
            ["./mavsdk_server", "-p", str(grpc_port), f"udp://:{udp_port}"]
        )

        # Wait a bit for the MAVSDK server to start
        await asyncio.sleep(2)

        await run()

    except Exception as e:
        logger.error(f"Unhandled exception in main: {e}")
    finally:
        # Kill mavsdk_server
        if mavsdk_server:
            os.kill(mavsdk_server.pid, signal.SIGTERM)
        logger.info("All tasks completed. Exiting program.")


if __name__ == "__main__":
    asyncio.run(main())
