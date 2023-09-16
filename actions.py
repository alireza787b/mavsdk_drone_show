import argparse
import asyncio
import csv
from mavsdk import System
import glob
import os
import subprocess


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

# Modified start_mavsdk_server function
def start_mavsdk_server(grpc_port, udp_port):
    is_running, pid = check_mavsdk_server_running(grpc_port)
    if is_running:
        print(f"MAVSDK server already running on port {grpc_port}. Terminating...")
        psutil.Process(pid).terminate()
        psutil.Process(pid).wait()  # Wait for the process to actually terminate
    
    print(f"Starting mavsdk_server on gRPC port: {grpc_port}, UDP port: {udp_port}")
    mavsdk_server = subprocess.Popen(["./mavsdk_server", "-p", str(grpc_port), f"udp://:{udp_port}"])
    return mavsdk_server


def read_hw_id():
    hwid_files = glob.glob('*.hwID')
    if hwid_files:
        filename = hwid_files[0]
        hw_id = os.path.splitext(filename)[0]  # Get filename without extension
        print(f"Hardware ID {hw_id} detected.")
        return int(hw_id)
    else:
        print("Hardware ID file not found.")
        return None

def read_config(filename='config.csv'):
    print("Reading drone configuration...")
    dronesConfig = []
    with open(filename, newline='') as csvfile:
        reader = csv.reader(csvfile)
        next(reader, None)  # Skip the header
        for row in reader:
            hw_id, pos_id, x, y, ip, mavlink_port, debug_port, gcs_ip = row
            if int(hw_id) == HW_ID:
                print(f"Matching hardware ID found: {hw_id}")
                droneConfig = {
                    'hw_id': hw_id,
                    'udp_port': mavlink_port,
                    'grpc_port': debug_port
                }
                print(f"Drone configuration: {droneConfig}")
                return droneConfig
    print("No matching hardware ID found in the configuration file.")
            
SIM_MODE = False  # or True based on your setting
GRPC_PORT_BASE = 50041
HW_ID = read_hw_id()


def stop_mavsdk_server(mavsdk_server):
    print("Stopping mavsdk_server")
    mavsdk_server.terminate()


async def perform_action(action, altitude):
    print("Starting to perform action...")
    droneConfig = read_config()
    print(f"SIM_MODE: {SIM_MODE}, GRPC_PORT_BASE: {GRPC_PORT_BASE}, HW_ID: {HW_ID}")

    if (SIM_MODE == True):
        grpc_port = GRPC_PORT_BASE + HW_ID
    else:
        grpc_port = GRPC_PORT_BASE - 1

    print(f"gRPC Port: {grpc_port}")

    if (SIM_MODE == False):
        udp_port = 14540  # Default API connection on the same hardware
    else:
        udp_port = int(droneConfig['udp_port'])

    print(f"UDP Port: {udp_port}")
    
    # Start mavsdk_server
    mavsdk_server = start_mavsdk_server(grpc_port, udp_port)
    
    
    drone = System(mavsdk_server_address="localhost", port=grpc_port)
    print("Attempting to connect to drone...")
    await drone.connect(system_address=f"udp://:{udp_port}")

    print("Checking connection state...")
    async for state in drone.core.connection_state():
        if state.is_connected:
            print(f"Drone connected on UDP Port: {udp_port} and gRPC Port: {grpc_port}")
            break
    else:
        print("Could not establish a connection with the drone.")

    # Perform the action
    try:
        if action == "takeoff":
            await drone.action.set_takeoff_altitude(float(altitude))
            await drone.action.arm()
            await drone.action.takeoff()
        elif action == "land":
            await drone.action.hold()  # Switch to Hold mode
            await asyncio.sleep(1)  # Wait for a short period
            await drone.action.land()  # Then execute land command
        elif action == "hold":
            await drone.action.hold()  # Switch to Hold mode
            pass
        elif action == "test":
            await drone.action.arm()
            await asyncio.sleep(4)
            await drone.action.disarm()
        else:
            print("Invalid action")
    finally:
        if state.is_connected:
            # Terminate MAVSDK server if still running
            is_running, pid = check_mavsdk_server_running(grpc_port)
            if is_running:
                print(f"Terminating MAVSDK server running on port {grpc_port}...")
                psutil.Process(pid).terminate()
                psutil.Process(pid).wait()  # Wait for the process to actually terminate


if __name__ == "__main__":
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Perform actions with drones.")
    parser.add_argument('--action', type=str, required=True, help='Action to perform: takeoff, land, hold')
    parser.add_argument('--altitude', type=float, default=10, help='Altitude for takeoff')

    args = parser.parse_args()

    # Run the main event loop
    loop = asyncio.get_event_loop()
    loop.run_until_complete(perform_action(args.action, args.altitude))
