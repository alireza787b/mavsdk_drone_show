import argparse
import asyncio
import csv
import glob
import os
import subprocess
import logging
import psutil  # You may need to install this package
from mavsdk import System

# Helper function to check if MAVSDK server is running
def check_mavsdk_server_running(port):
    """Check if MAVSDK server is running on a given port."""
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            for conn in proc.connections(kind='inet'):
                if conn.laddr.port == port:
                    return True, proc.info['pid']
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False, None

def start_mavsdk_server(grpc_port, udp_port):
    """Start the MAVSDK server if it is not already running."""
    is_running, pid = check_mavsdk_server_running(grpc_port)
    if is_running:
        logging.info(f"MAVSDK server already running on port {grpc_port}. Terminating...")
        psutil.Process(pid).terminate()
        psutil.Process(pid).wait()
    
    logging.info(f"Starting mavsdk_server on gRPC port: {grpc_port}, UDP port: {udp_port}")
    return subprocess.Popen(["./mavsdk_server", "-p", str(grpc_port), f"udp://:{udp_port}"])

def read_hw_id():
    """Read the hardware ID from the file system."""
    hwid_files = glob.glob('*.hwID')
    if hwid_files:
        filename = hwid_files[0]
        hw_id = os.path.splitext(filename)[0]
        logging.info(f"Hardware ID {hw_id} detected.")
        return int(hw_id)
    else:
        logging.warning("Hardware ID file not found.")
        return None

def read_config(filename='config.csv'):
    """Read drone configuration from the specified CSV file."""
    logging.info("Reading drone configuration...")
    with open(filename, newline='') as csvfile:
        reader = csv.reader(csvfile)
        next(reader, None)  # Skip the header
        for row in reader:
            hw_id, pos_id, x, y, ip, mavlink_port, debug_port, gcs_ip = row
            if int(hw_id) == HW_ID:
                logging.info(f"Matching hardware ID found: {hw_id}")
                return {
                    'hw_id': hw_id,
                    'udp_port': mavlink_port,
                    'grpc_port': debug_port
                }
    logging.warning("No matching hardware ID found in the configuration file.")
    return None

# Configuration
SIM_MODE = False  # or True based on your setting
GRPC_PORT_BASE = 50041
HW_ID = read_hw_id()

async def perform_action(action, altitude):
    """Perform a specified drone action."""
    logging.info("Starting to perform action...")
    droneConfig = read_config()
    if not droneConfig:
        logging.error("Drone configuration not found, aborting.")
        return

    grpc_port = GRPC_PORT_BASE + HW_ID if SIM_MODE else GRPC_PORT_BASE - 1
    udp_port = int(droneConfig['udp_port']) if SIM_MODE else 14540

    mavsdk_server = start_mavsdk_server(grpc_port, udp_port)
    drone = System(mavsdk_server_address="localhost", port=grpc_port)
    
    try:
        logging.info("Attempting to connect to drone...")
        await drone.connect(system_address=f"udp://:{udp_port}")
        connection_state = await drone.core.connection_state().first_value()
        if connection_state.is_connected:
            logging.info(f"Drone connected on UDP Port: {udp_port} and gRPC Port: {grpc_port}")
        else:
            raise ConnectionError("Failed to connect to drone.")
        
        if action == "takeoff":
            await drone.action.set_takeoff_altitude(float(altitude))
            await drone.action.arm()
            await drone.action.takeoff()
            logging.info("Takeoff successful.")
        elif action == "land":
            await drone.action.hold()
            await asyncio.sleep(1)
            await drone.action.land()
            logging.info("Landing successful.")
        elif action == "hold":
            await drone.action.hold()
            logging.info("Hold position successful.")
        elif action == "test":
            await drone.action.arm()
            await asyncio.sleep(3)
            await drone.action.disarm()
            logging.info("Test action successful.")
        else:
            logging.error("Invalid action specified.")
    except Exception as e:
        logging.error(f"Failed to perform action {action}: {e}")
    finally:
        stop_mavsdk_server(mavsdk_server)

def stop_mavsdk_server(mavsdk_server):
    """Stop the MAVSDK server."""
    logging.info("Stopping MAVSDK server")
    mavsdk_server.terminate()
    mavsdk_server.wait()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    parser = argparse.ArgumentParser(description="Perform actions with drones.")
    parser.add_argument('--action', type=str, required=True, help='Action to perform: takeoff, land, hold, test')
    parser.add_argument('--altitude', type=float, default=10, help='Altitude for takeoff')

    args = parser.parse_args()
    asyncio.run(perform_action(args.action, args.altitude))
