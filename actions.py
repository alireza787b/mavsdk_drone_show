import argparse
import asyncio
import csv
from mavsdk import System
import glob
import os
import subprocess
import logging
import psutil  # You may need to install this package

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

# Function to make sure mavsdk_server is executable
def ensure_mavsdk_server_executable(path):
    if not os.access(path, os.X_OK):
        os.chmod(path, 0o755)
        logging.info(f"Set executable permissions for {path}")

# Modified start_mavsdk_server function
def start_mavsdk_server(grpc_port, udp_port):
    mavsdk_server_path = "./mavsdk_server"
    ensure_mavsdk_server_executable(mavsdk_server_path)
    
    is_running, pid = check_mavsdk_server_running(grpc_port)
    if is_running:
        logging.info(f"MAVSDK server already running on port {grpc_port}. Terminating...")
        psutil.Process(pid).terminate()
        psutil.Process(pid).wait()  # Wait for the process to actually terminate
    
    logging.info(f"Starting mavsdk_server on gRPC port: {grpc_port}, UDP port: {udp_port}")
    try:
        mavsdk_server = subprocess.Popen([mavsdk_server_path, "-p", str(grpc_port), f"udp://:{udp_port}"])
        return mavsdk_server
    except OSError as e:
        logging.error(f"Failed to start mavsdk_server: {e}")
        raise

def read_hw_id():
    hwid_files = glob.glob('*.hwID')
    if hwid_files:
        filename = hwid_files[0]
        hw_id = os.path.splitext(filename)[0]  # Get filename without extension
        logging.info(f"Hardware ID {hw_id} detected.")
        return int(hw_id)
    else:
        logging.info("Hardware ID file not found.")
        return None

def read_config(filename='config.csv'):
    logging.info("Reading drone configuration...")
    with open(filename, newline='') as csvfile:
        reader = csv.reader(csvfile)
        next(reader, None)  # Skip the header
        for row in reader:
            hw_id, pos_id, x, y, ip, mavlink_port, debug_port, gcs_ip = row
            if int(hw_id) == HW_ID:
                logging.info(f"Matching hardware ID found: {hw_id}")
                droneConfig = {
                    'hw_id': hw_id,
                    'udp_port': mavlink_port,
                    'grpc_port': debug_port
                }
                logging.info(f"Drone configuration: {droneConfig}")
                return droneConfig
    logging.info("No matching hardware ID found in the configuration file.")
    return None

SIM_MODE = False  # or True based on your setting
GRPC_PORT_BASE = 50041
HW_ID = read_hw_id()

def stop_mavsdk_server(mavsdk_server):
    logging.info("Stopping mavsdk_server")
    mavsdk_server.terminate()

async def perform_action_with_retries(action, altitude, retries=3, retry_interval=5):
    for attempt in range(retries):
        success = await perform_action(action, altitude)
        if success:
            return True
        logging.info(f"Attempt {attempt + 1} failed, retrying after {retry_interval} seconds...")
        await asyncio.sleep(retry_interval)
    return False

async def perform_action(action, altitude):
    logging.info("Starting to perform action...")
    droneConfig = read_config()
    if droneConfig is None:
        logging.error("Failed to read drone configuration.")
        return False

    grpc_port = GRPC_PORT_BASE + HW_ID if SIM_MODE else GRPC_PORT_BASE - 1
    udp_port = 14540 if not SIM_MODE else int(droneConfig['udp_port'])

    logging.info(f"gRPC Port: {grpc_port}, UDP Port: {udp_port}")
    
    # Start mavsdk_server
    try:
        mavsdk_server = start_mavsdk_server(grpc_port, udp_port)
    except Exception as e:
        logging.error(f"Failed to start MAVSDK server: {e}")
        return False
    
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
        return False

    # Perform the action
    try:
        if action == "takeoff":
            await drone.action.set_takeoff_altitude(float(altitude))
            await drone.action.arm()
            await drone.action.takeoff()
            logging.info("Takeoff successful.")
        elif action == "land":
            await drone.action.hold()  # Switch to Hold mode
            await asyncio.sleep(1)  # Wait for a short period
            await drone.action.land()  # Then execute land command
            logging.info("Landing successful.")
        elif action == "hold":
            await drone.action.hold()  # Switch to Hold mode
            logging.info("Hold position successful.")
        elif action == "test":
            await drone.action.arm()
            await asyncio.sleep(3)
            await drone.action.disarm()
            logging.info("Test action successful.")
        else:
            logging.error("Invalid action specified.")
            return False
    except Exception as e:
        logging.error(f"Action {action} failed: {e}")
        return False
    finally:
        if state.is_connected:
            # Terminate MAVSDK server if still running
            is_running, pid = check_mavsdk_server_running(grpc_port)
            if is_running:
                logging.info(f"Terminating MAVSDK server running on port {grpc_port}...")
                psutil.Process(pid).terminate()
                psutil.Process(pid).wait()  # Ensure the server is properly terminated

    return True

if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Perform actions with drones.")
    parser.add_argument('--action', type=str, required=True, help='Action to perform: takeoff, land, hold, test')
    parser.add_argument('--altitude', type=float, default=10, help='Altitude for takeoff')
    parser.add_argument('--retries', type=int, default=3, help='Number of retries if the action fails')
    parser.add_argument('--retry_interval', type=int, default=5, help='Time interval between retries in seconds')

    args = parser.parse_args()

    # Run the main event loop
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(perform_action_with_retries(args.action, args.altitude, args.retries, args.retry_interval))
    except Exception as e:
        logging.error(f"An error occurred: {e}")
    finally:
        loop.close()  # Ensure the loop is closed properly
        logging.info("Operation completed, event loop closed.")
