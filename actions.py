import argparse
import asyncio
import csv
from mavsdk import System
import glob
import os


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
    dronesConfig = []
    HW_ID = read_hw_id()
    with open(filename, newline='') as csvfile:
        reader = csv.reader(csvfile)
        next(reader, None)  # Skip the header
        for row in reader:
            hw_id, pos_id, x, y, ip, mavlink_port, debug_port, gcs_ip = row
            if int(hw_id) == HW_ID:
                droneConfig = {
                    'hw_id': hw_id,
                    'udp_port': mavlink_port,
                    'grpc_port': debug_port
                }
                return droneConfig

async def perform_action(action, altitude):
    """Connect to drone, perform action, then disconnect."""
    droneConfig = read_config()
    
    udp_port = int(droneConfig['udp_port'])
    grpc_port = int(droneConfig['grpc_port'])
    
    drone = System(mavsdk_server_address="localhost", port=grpc_port)
    await drone.connect(system_address=f"udp://:{udp_port}")

    # Ensure drone is connected
    async for state in drone.core.connection_state():
        if state.is_connected:
            print(f"Drone connected on UDP Port: {udp_port} and gRPC Port: {grpc_port}")
            break

    # Perform the action
    try:
        if action == "takeoff":
            await drone.action.arm()
            await drone.action.takeoff()
        elif action == "land":
            await drone.action.land()
        elif action == "hold":
            # Code to hold position
            pass
        elif action == "test":
            await drone.action.arm()
            await asyncio.sleep(4)
            await drone.action.disarm()
        else:
            print("Invalid action")
    finally:
        if state.is_connected:
            await drone.action.disarm()
            await drone.disconnect()

if __name__ == "__main__":
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Perform actions with drones.")
    parser.add_argument('--action', type=str, required=True, help='Action to perform: takeoff, land, hold')
    parser.add_argument('--altitude', type=float, default=10, help='Altitude for takeoff')

    args = parser.parse_args()

    # Run the main event loop
    loop = asyncio.get_event_loop()
    loop.run_until_complete(perform_action(args.action, args.altitude))
