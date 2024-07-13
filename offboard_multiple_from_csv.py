import os
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
import functions.global_to_local
from tenacity import retry, stop_after_attempt, wait_fixed

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
STEP_TIME = 0.05
DEFAULT_Z = 0.83
GRPC_PORT_BASE = 50041
SHOW_DEVIATIONS = False
INITIAL_CLIMB_DURATION = 3  # Duration in seconds for the initial climb phase

Drone = namedtuple('Drone', 'hw_id pos_id x y ip mavlink_port debug_port gcs_ip')
SIM_MODE = False
SEPARATE_CSV = True
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
        logger.warning("Hardware ID file not found.")
        return None

def read_config(filename: str) -> list:
    """
    Read the drone configuration from a CSV file.
    """
    drones_config = []
    try:
        with open(filename, newline='') as csvfile:
            reader = csv.reader(csvfile)
            next(reader, None)  # Skip the header
            for row in reader:
                print("Unpacking config:", row)
                hw_id, pos_id, x, y, ip, mavlink_port, debug_port, gcs_ip = row
                if not SIM_MODE and int(hw_id) == HW_ID:
                    drone = Drone(hw_id, pos_id, float(x), float(y), ip, mavlink_port, debug_port, gcs_ip)
                    drones_config.append(drone)
                    break
                if SIM_MODE:
                    drone = Drone(hw_id, pos_id, float(x), float(y), ip, mavlink_port, debug_port, gcs_ip)
                    drones_config.append(drone)
    except FileNotFoundError as e:
        logger.error(f"Config file not found: {e}")
    except Exception as e:
        logger.error(f"Error reading config file {filename}: {e}")
    return drones_config

def read_trajectory_file(filename: str, trajectory_offset: tuple, altitude_offset: float) -> list:
    """
    Read the trajectory waypoints from a CSV file.
    """
    waypoints = []
    try:
        with open(filename, newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                t = float(row["t"])
                px = float(row["px"]) + trajectory_offset[0]
                py = float(row["py"]) + trajectory_offset[1]
                pz = float(row["pz"]) + trajectory_offset[2] - altitude_offset
                vx = float(row["vx"])
                vy = float(row["vy"])
                vz = float(row["vz"])
                ax = float(row["ax"])
                ay = float(row["ay"])
                az = float(row["az"])
                yaw = float(row["yaw"])
                mode_code = int(row["mode"])
                waypoints.append((t, px, py, pz, vx, vy, vz, ax, ay, az, yaw, mode_code))
    except FileNotFoundError as e:
        logger.error(f"Trajectory file not found: {e}")
    except Exception as e:
        logger.error(f"Error reading trajectory file {filename}: {e}")
    return waypoints

async def get_global_position_telemetry(drone_id: int, drone: System):
    """
    Fetch and store global position telemetry for a drone.
    """
    try:
        async for global_position in drone.telemetry.position():
            global_position_telemetry[drone_id] = global_position
    except Exception as e:
        logger.error(f"Error fetching global position telemetry for drone {drone_id}: {e}")

async def perform_trajectory(drone_id: int, drone: System, waypoints: list, home_position, home_position_NED, global_position_telemetry: dict, mode_descriptions: dict):
    """
    Perform the trajectory for the given drone based on waypoints and telemetry data.
    """
    logger.info(f"Performing trajectory for drone {drone_id}")
    total_duration = waypoints[-1][0]
    t = 0
    last_mode = 0
    last_waypoint_index = 0

    while t <= total_duration:
        try:
            actual_position = global_position_telemetry[drone_id]
            logger.debug(f"Actual position: {actual_position}, Home position: {home_position}")
            local_ned_position = functions.global_to_local.global_to_local(actual_position, home_position)
            local_ned_position = functions.global_to_local.global_to_local(actual_position, home_position)
            
            current_waypoint = None
            for i in range(last_waypoint_index, len(waypoints)):
                if t <= waypoints[i][0]:
                    current_waypoint = waypoints[i]
                    last_waypoint_index = i
                    break

            if t <= INITIAL_CLIMB_DURATION:
                # Initial climb phase: send velocity setpoints to only take off and climb
                vz = current_waypoint[6]
                logger.debug(f"Drone {drone_id+1}: Initial climb phase, sending vertical velocity: {vz}")
                await drone.offboard.set_velocity_body(VelocityBodyYawspeed(0.0, 0.0, vz, 0.0))
            else:
                position = tuple(a - b for a, b in zip(current_waypoint[1:4], home_position_NED)) if SEPARATE_CSV else current_waypoint[1:4]
                velocity = current_waypoint[4:7]
                acceleration = current_waypoint[7:10]
                yaw = current_waypoint[10]
                mode_code = current_waypoint[-1]
                if last_mode != mode_code:
                    logger.info(f"Drone {drone_id+1}: Mode number: {mode_code}, Description: {mode_descriptions[mode_code]}")
                    last_mode = mode_code

                await drone.offboard.set_position_velocity_acceleration_ned(
                    PositionNedYaw(*position, yaw),
                    VelocityNedYaw(*velocity, yaw),
                    AccelerationNed(*acceleration)
                )

            await asyncio.sleep(STEP_TIME)
            t += STEP_TIME
            
            if int(t / STEP_TIME) % 100 == 0:
                deviation = [(a - b) for a, b in zip(position, [local_ned_position.north_m, local_ned_position.east_m, local_ned_position.down_m])]
                if SHOW_DEVIATIONS:
                    logger.info(f"Drone {drone_id+1} Deviations: {round(deviation[0], 1)} {round(deviation[1], 1)} {round(deviation[2], 1)}")

        except OffboardError as e:
            logger.error(f"Offboard error during trajectory for drone {drone_id}: {e}")
            break
        except Exception as e:
            logger.error(f"Error during trajectory for drone {drone_id}: {e}")
            break

    logger.info(f"Shape completed for drone {drone_id+1}")

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
async def initial_setup_and_connection(drone_id: int, udp_port: int):
    """
    Perform the initial setup and connection for the drone.
    """
    try:
        drones_config = read_config('config.csv')
        grpc_port = GRPC_PORT_BASE + drone_id if SIM_MODE else GRPC_PORT_BASE - 1
        home_position = None


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

        drone = System(mavsdk_server_address="127.0.0.1", port=grpc_port)
        await drone.connect(system_address=f"udp://:{udp_port}")
        logger.info(f"Drone connecting with UDP: {udp_port}")

        asyncio.ensure_future(get_global_position_telemetry(drone_id, drone))
        
        async for state in drone.core.connection_state():
            if state.is_connected:
                logger.info(f"Drone {drone_id+1} connected on Port: {udp_port} and grpc Port: {grpc_port}")
                break

        return drone, mode_descriptions, home_position
    except Exception as e:
        logger.error(f"Error in initial setup and connection for drone {drone_id}: {e}")
        raise

async def pre_flight_checks(drone_id: int, drone: System):
    """
    Perform pre-flight checks to ensure the drone is ready for flight.
    """
    logger.info(f"Starting pre-flight checks for Drone {drone_id+1}...")
    
    home_position = None
    
    async for health in drone.telemetry.health():
        if health.is_global_position_ok and health.is_home_position_ok:
            logger.info(f"Global position estimate and home position check passed for Drone {drone_id+1}.")
            home_position = global_position_telemetry[drone_id]
            logger.info(f"Home Position of Drone {drone_id+1} set to: {home_position}")
            break
        else:
            if not health.is_global_position_ok:
                logger.warning(f"Waiting for global position to be okay for Drone {drone_id+1}.")
            if not health.is_home_position_ok:
                logger.warning(f"Waiting for home position to be set for Drone {drone_id+1}.")

    if home_position is not None:
        logger.info(f"Pre-flight checks successful for Drone {drone_id+1}.")
    else:
        logger.error(f"Pre-flight checks failed for Drone {drone_id+1}. Please resolve the issues and try again.")
    
    return home_position

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
async def arming_and_starting_offboard_mode(drone_id: int, drone: System):
    """
    Arm the drone and start offboard mode.
    """
    try:
        logger.info(f"Arming drone {drone_id+1}")
        await drone.action.arm()
        logger.info(f"Setting initial setpoint for drone {drone_id+1}")
        #await drone.offboard.set_position_ned(PositionNedYaw(0.0, 0.0, 0.0, 0.0))
        await drone.offboard.set_velocity_body(VelocityBodyYawspeed(0.0, 0.0, 0.0, 0.0))
        logger.info(f"Starting offboard mode for drone {drone_id+1}")
        await drone.offboard.start()
    except OffboardError as error:
        logger.error(f"Error starting offboard mode for drone {drone_id+1}: {error}")
        await drone.action.disarm()
        raise
    except Exception as e:
        logger.error(f"Error arming and starting offboard mode for drone {drone_id+1}: {e}")
        await drone.action.disarm()
        raise

async def perform_landing(drone_id: int, drone: System):
    """
    Perform landing for the drone.
    """
    try:
        logger.info(f"Landing drone {drone_id+1}")
        await drone.action.land()

        async for state in drone.telemetry.landed_state():
            if state == LandedState.ON_GROUND:
                break
    except ActionError as e:
        logger.error(f"Error landing drone {drone_id+1}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during landing for drone {drone_id+1}: {e}")

async def stop_offboard_mode(drone_id: int, drone: System):
    """
    Stop offboard mode for the drone.
    """
    try:
        logger.info(f"Stopping offboard mode for drone {drone_id+1}")
        await drone.offboard.stop()
    except OffboardError as error:
        logger.error(f"Error stopping offboard mode for drone {drone_id+1}: {error}")
    except Exception as e:
        logger.error(f"Unexpected error stopping offboard mode for drone {drone_id+1}: {e}")

async def disarm_drone(drone_id: int, drone: System):
    """
    Disarm the drone.
    """
    try:
        logger.info(f"Disarming drone {drone_id+1}")
        await drone.action.disarm()
    except ActionError as e:
        logger.error(f"Error disarming drone {drone_id+1}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error disarming drone {drone_id+1}: {e}")

async def create_drone_configurations(num_drones: int, time_offset: int):
    """
    Create configurations for all drones.
    """
    altitude_steps = 0
    altitude_offsets = [altitude_steps * i for i in range(num_drones)]

    home_positions = [(drone.x, drone.y, DEFAULT_Z) for drone in dronesConfig]
    trajectory_offset = [(0, 0, 0) for i in range(num_drones)]

    udp_ports = [14540] if not SIM_MODE else [drone.mavlink_port for drone in dronesConfig]

    return home_positions, trajectory_offset, udp_ports, altitude_offsets

def start_mavsdk_servers(num_drones: int, udp_ports: list) -> list:
    """
    Start MAVSDK server instances for each drone.
    """
    mavsdk_servers = []
    for i in range(num_drones):
        port = GRPC_PORT_BASE + i if SIM_MODE else 50040
        try:
            mavsdk_server = subprocess.Popen(["./mavsdk_server", "-p", str(port), f"udp://:{udp_ports[i]}"])
            mavsdk_servers.append(mavsdk_server)
        except Exception as e:
            logger.error(f"Error starting MAVSDK server for drone {i+1}: {e}")
    return mavsdk_servers

async def run_all_drones(num_drones: int, home_positions: list, trajectory_offset: list, udp_ports: list, time_offset: int, altitude_offsets: list):
    """
    Run all drones with their respective configurations.
    """
    tasks = []
    for i in range(num_drones):
        drone_id = i if SIM_MODE else HW_ID
        tasks.append(asyncio.create_task(run_drone(drone_id, home_positions[i], trajectory_offset[i], udp_ports[i], i * time_offset, altitude_offsets[i])))
    await asyncio.gather(*tasks)

def stop_all_mavsdk_servers(mavsdk_servers: list):
    """
    Stop all MAVSDK server instances.
    """
    for mavsdk_server in mavsdk_servers:
        try:
            os.kill(mavsdk_server.pid, signal.SIGTERM)
        except Exception as e:
            logger.error(f"Error stopping MAVSDK server: {e}")

async def run_drone(drone_id: int, home_position_NED: tuple, trajectory_offset: tuple, udp_port: int, time_offset: int, altitude_offset: float):
    """
    Run a single drone with the provided configurations.
    """
    try:
        if not SIM_MODE:
            drone_id = 0

        drone, mode_descriptions, home_position = await initial_setup_and_connection(drone_id, udp_port)
        
        await asyncio.sleep(time_offset)
        home_position = await pre_flight_checks(drone_id, drone)
        await arming_and_starting_offboard_mode(drone_id, drone)

        filename = f"shapes/swarm/processed/Drone {HW_ID}.csv" if SEPARATE_CSV and not SIM_MODE else f"shapes/swarm/processed/Drone {drone_id + 1}.csv" if SEPARATE_CSV else "shapes/active.csv"
        waypoints = read_trajectory_file(filename, trajectory_offset, altitude_offset)
        await perform_trajectory(drone_id, drone, waypoints, home_position, home_position_NED, global_position_telemetry, mode_descriptions)
        await perform_landing(drone_id, drone)
        await stop_offboard_mode(drone_id, drone)
        await disarm_drone(drone_id, drone)
    except Exception as e:
        logger.error(f"Error running drone {drone_id}: {e}")

async def main():
    """
    Main function to run all drones.
    """
    global HW_ID, dronesConfig
    HW_ID = read_hw_id()
    if HW_ID is None:
        logger.error("Failed to read HW ID. Exiting program.")
        return

    # Ensure dronesConfig is properly populated
    dronesConfig = read_config('config.csv')
    if not dronesConfig:
        logger.error("No drone configurations available. Exiting program.")
        return

    num_drones = len(dronesConfig)
    time_offset = 0

    home_positions, trajectory_offset, udp_ports, altitude_offsets = await create_drone_configurations(num_drones, time_offset)
    mavsdk_servers = start_mavsdk_servers(num_drones, udp_ports)
    await run_all_drones(num_drones, home_positions, trajectory_offset, udp_ports, time_offset, altitude_offsets)
    stop_all_mavsdk_servers(mavsdk_servers)
    logger.info("All tasks completed. Exiting program.")

if __name__ == "__main__":
    asyncio.run(main())
