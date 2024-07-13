import argparse
import asyncio
import csv
from mavsdk import System
import glob
import os
import subprocess
import logging
import psutil

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Function to check if MAVSDK server is running
def check_mavsdk_server_running(port):
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            for conn in proc.connections(kind='inet'):
                if conn.laddr.port == port:
                    return True, proc.info['pid']
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False, None

# Modified start_mavsdk_server function
def start_mavsdk_server(grpc_port, udp_port):
    is_running, pid = check_mavsdk_server_running(grpc_port)
    if is_running:
        logger.info(f"MAVSDK server already running on port {grpc_port}. Terminating...")
        psutil.Process(pid).terminate()
        psutil.Process(pid).wait()  # Wait for the process to actually terminate
    
    logger.info(f"Starting mavsdk_server on gRPC port: {grpc_port}, UDP port: {udp_port}")
    mavsdk_server = subprocess.Popen(["./mavsdk_server", "-p", str(grpc_port), f"udp://:{udp_port}"])
    return mavsdk_server

def read_hw_id():
    hwid_files = glob.glob('*.hwID')
    if hwid_files:
        filename = hwid_files[0]
        hw_id = os.path.splitext(filename)[0]  # Get filename without extension
        logger.info(f"Hardware ID {hw_id} detected.")
        return int(hw_id)
    else:
        logger.warning("Hardware ID file not found.")
        return None

def read_config(filename='config.csv'):
    logger.info("Reading drone configuration...")
    dronesConfig = []
    try:
        with open(filename, newline='') as csvfile:
            reader = csv.reader(csvfile)
            next(reader, None)  # Skip the header
            for row in reader:
                hw_id, pos_id, x, y, ip, mavlink_port, debug_port, gcs_ip = row
                if int(hw_id) == HW_ID:
                    logger.info(f"Matching hardware ID found: {hw_id}")
                    droneConfig = {
                        'hw_id': hw_id,
                        'udp_port': mavlink_port,
                        'grpc_port': debug_port
                    }
                    logger.info(f"Drone configuration: {droneConfig}")
                    return droneConfig
    except FileNotFoundError as e:
        logger.error(f"Config file not found: {e}")
    except Exception as e:
        logger.error(f"Error reading config file {filename}: {e}")
    logger.warning("No matching hardware ID found in the configuration file.")
    return None
            
SIM_MODE = False  # or True based on your setting
GRPC_PORT_BASE = 50041
HW_ID = read_hw_id()

def stop_mavsdk_server(mavsdk_server):
    logger.info("Stopping mavsdk_server")
    mavsdk_server.terminate()

async def perform_action(action, altitude=None):
    logging.info("Starting to perform action...")
    droneConfig = read_config()
    if not droneConfig:
        logging.error("Drone configuration not found. Exiting...")
        return
    
    grpc_port = GRPC_PORT_BASE + HW_ID if SIM_MODE else GRPC_PORT_BASE - 1
    udp_port = 14540 if not SIM_MODE else int(droneConfig['udp_port'])

    logger.info(f"gRPC Port: {grpc_port}, UDP Port: {udp_port}")

    mavsdk_server = start_mavsdk_server(grpc_port, udp_port)
    
    drone = System(mavsdk_server_address="localhost", port=grpc_port)
    logging.info("Attempting to connect to drone...")
    await drone.connect(system_address=f"udp://:{udp_port}")

    logging.info("Checking connection state...")
    async for state in drone.core.connection_state():
        if state.is_connected:
            logging.info(f"Drone connected on UDP Port: {udp_port} and gRPC Port: {grpc_port}")
            break
    else:
        logging.error("Could not establish a connection with the drone.")
        stop_mavsdk_server(mavsdk_server)
        return

    try:
        if action == "takeoff":
            await takeoff(drone, altitude)
        elif action == "land":
            await land(drone)
        elif action == "hold":
            await hold(drone)
        elif action == "test":
            await test(drone)
        elif action == "reboot":
            await reboot(drone)
        else:
            logging.error("Invalid action specified.")
    except Exception as e:
        logging.error(f"Error performing action {action}: {e}")
    finally:
        is_running, pid = check_mavsdk_server_running(grpc_port)
        if is_running:
            logger.info(f"Terminating MAVSDK server running on port {grpc_port}...")
            psutil.Process(pid).terminate()
            psutil.Process(pid).wait()
        logging.info("Action completed.")

async def takeoff(drone, altitude):
    try:
        await drone.action.set_takeoff_altitude(float(altitude))
        await drone.action.arm()
        await drone.action.takeoff()
        logger.info("Takeoff successful.")
    except Exception as e:
        logger.error(f"Takeoff failed: {e}")

async def land(drone):
    try:
        await drone.action.hold()  # Switch to Hold mode
        await asyncio.sleep(1)  # Wait for a short period
        await drone.action.land()  # Then execute land command
        logger.info("Landing successful.")
    except Exception as e:
        logger.error(f"Landing failed: {e}")

async def hold(drone):
    try:
        await drone.action.hold()  # Switch to Hold mode
        logger.info("Hold position successful.")
    except Exception as e:
        logger.error(f"Hold failed: {e}")

async def test(drone):
    try:
        await drone.action.arm()
        await asyncio.sleep(3)
        await drone.action.disarm()
        logger.info("Test action successful.")
    except Exception as e:
        logger.error(f"Test failed: {e}")

async def reboot(drone):
    try:
        await drone.action.reboot()
        logger.info("Reboot successful.")
    except Exception as e:
        logger.error(f"Reboot failed: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Perform actions with drones.")
    parser.add_argument('--action', type=str, required=True, help='Action to perform: takeoff, land, hold, test, reboot')
    parser.add_argument('--altitude', type=float, default=10, help='Altitude for takeoff')

    args = parser.parse_args()

    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(perform_action(args.action, args.altitude))
    except Exception as e:
        logger.error(f"An error occurred: {e}")
    finally:
        loop.close()  # Ensure the loop is closed properly
        logger.info("Operation completed, event loop closed.")
