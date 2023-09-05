# -----------------------------------------------------------------------------
# coordinator.py
# Version: 0.5
#
# Authors: Alireza Ghaderi
# Email: p30planets@gmail.com
# GitHub: https://github.com/Alireza787b
#
# This script coordinates the operations of a drone show. Its responsibilities include:
# - Sending node info state to Ground Control Station (GCS)
# - Listening to the commands from GCS
# - Connecting to the pixhawk via serial (in real life) or SITL (in sim mode) and routing the mavlink messages
#   (requires mavlink-router to be installed) to GCS and other nodes (in real life over Zerotier network, 
#   in sim mode just send to the IP of the GCS locally)
# - Syncing and setting the time to accurate internet time
# - Setting a trigger time so all the drones can start the mission at a specified time in future for synced shows
# - Allowing to unset the triggered time
# - Autostarting when OS loads
# 
# More features might be added as the project progresses.
#
# This script is a part of mavsdk_drone_show repository available at:
# https://github.com/Alireza787b/mavsdk_drone_show
#
# Last updated: June 2023
# -----------------------------------------------------------------------------

# Importing the necessary libraries
import asyncio
import csv
import datetime
import glob
import json
import socket
import threading
import os
import time
import pandas as pd
import requests
import urllib3
import subprocess
import navpy

import time
import threading
from src.drone_config import DroneConfig
from src.local_mavlink_controller import LocalMavlinkController
import logging
import struct
import csv
import glob
import requests
from geographiclib.geodesic import Geodesic
from mavsdk import System
from mavsdk.offboard import OffboardError, PositionNedYaw, VelocityNedYaw
from src.offboard_controller import OffboardController
import os
import datetime
import logging
import src.params as params
import struct
from src.drone_communicator import DroneCommunicator
import math
from src.params import Params 

from enum import Enum

class Mission(Enum):
    NONE = 0
    DRONE_SHOW_FROM_CSV = 1
    SMART_SWARM = 2
    TAKE_OFF = 10
    LAND = 101
    HOLD = 102
    TEST = 100



# Set up logging
logging.basicConfig(level=logging.INFO)

# Global variable to store telemetry
global_telemetry = {}

# Flag to indicate whether the telemetry thread should run
run_telemetry_thread = threading.Event()
run_telemetry_thread.set()
# Initialize an empty dictionary to store drones  a dict
#example on how to access drone 4 lat      lat_drone_4 = drones[4].position['lat']

drones = {}

# Create global instance
params = params.Params()

# Initialize DroneConfig
drone_config = DroneConfig(drones)


 






# Function to initialize MAVLink connection
def initialize_mavlink():

    # Depending on the sim_mode, connect to either the SITL or the Raspberry Pi GPIO serial
    if params.sim_mode:
        print("Sim mode is enabled. Connecting to SITL...")
        if (params.default_sitl == True):
            mavlink_source = f"0.0.0.0:{params.sitl_port}"
        else:
            mavlink_source = f"0.0.0.0:{drone_config.config['mavlink_port']}"
    else:
        if(params.serial_mavlink==True):
            print("Real mode is enabled. Connecting to Pixhawk via serial...")
            mavlink_source = f"/dev/{params.serial_mavlink}:{params.serial_baudrate}"
        else:
            print("Real mode is enabled. Connecting to Pixhawk via UDP...")
            mavlink_source = f"127.0.0.1:{params.sitl_port}"

    # Prepare endpoints for mavlink-router
    endpoints = [f"-e {device}" for device in params.extra_devices]

    if params.sim_mode:
        # In sim mode, route the MAVLink messages to the GCS locally
        endpoints.append(f"-e {drone_config.config['gcs_ip']}:{params.mavsdk_port}")
    else:
        # In real life, route the MAVLink messages to the GCS and other drones over a Zerotier network
        if(params.shared_gcs_port):
            endpoints.append(f"-e {drone_config.config['gcs_ip']}:{params.gcs_mavlink_port}")
        else:
            endpoints.append(f"-e {drone_config.config['gcs_ip']}:{int(drone_config.config['mavlink_port'])}")


    # Command to start mavlink-router
    mavlink_router_cmd = "mavlink-routerd " + ' '.join(endpoints) + ' ' + mavlink_source

    # Start mavlink-router and keep track of the process
    print(f"Starting MAVLink routing: {mavlink_router_cmd}")
    mavlink_router_process = subprocess.Popen(mavlink_router_cmd, shell=True)
    return mavlink_router_process




# Function to stop MAVLink routing
def stop_mavlink_routing(mavlink_router_process):

    if mavlink_router_process:
        print("Stopping MAVLink routing...")
        mavlink_router_process.terminate()
        run_telemetry_thread.clear()
        drone_comms.stop_communication()
    else:
        print("MAVLink routing is not running.")




# Create an instance of LocalMavlinkController. This instance will start a new thread that reads incoming Mavlink
# messages from the drone, processes these messages, and updates the drone_config object accordingly.
# When this instance is no longer needed, simply let it fall out of scope or explicitly delete it to stop the telemetry thread.
local_drone_controller = LocalMavlinkController(drone_config, params)



drone_comms = DroneCommunicator(drone_config, params, drones)
drone_comms.start_communication()



# Function to synchronize time with a reliable internet source
def synchronize_time():
    # Report current time before sync

    if(params.online_sync_time):
        print(f"Current system time before synchronization: {datetime.datetime.now()}")
        # Attempt to get the time from a reliable source
        print("Attempting to synchronize time with a reliable internet source...")
        response = requests.get("http://worldtimeapi.org/api/ip")
        
        if response.status_code == 200:
            # Time server and result
            server_used = response.json()["client_ip"]
            current_time = response.json()["datetime"]
            print(f"Time server used: {server_used}")
            print(f"Time reported by server: {current_time}")
            
            # Set this time as system time
            print("Setting system time...")
            os.system(f"sudo date -s '{current_time}'")
            
            # Report current time after sync
            print(f"Current system time after synchronization: {datetime.datetime.now()}")
        else:
            print("Failed to sync time with an internet source.")
    else:
        print(f"Using Current System Time witout Online synchronization: {datetime.datetime.now()}")

def run_mission_script(script_name, *args):
        cmd = ["python3", script_name] + list(map(str, args))
        try:
            completed_process = subprocess.run(cmd, check=True)
            if completed_process.returncode == 0:
                print(f"{script_name} executed successfully.")
                return True
        except subprocess.CalledProcessError as e:
            print(f"Error in executing {script_name}: {e}")
        return False
        
def schedule_mission():
    current_time = int(time.time())
    
    success = False

    if drone_config.mission in [1, 2]:
        if drone_config.state == 1 and current_time >= drone_config.trigger_time:
            print("Trigger time reached. Starting drone mission...")

            # Reset the state and trigger time
            drone_config.state = 2
            drone_config.trigger_time = 0

            if drone_config.mission == 1:
                success = run_mission_script("offboard_multiple_from_csv.py")

            elif drone_config.mission == 2:
                success = run_mission_script("smart_swarm_mission.py")

    elif drone_config.mission >= 10 and drone_config.mission < 100:
        altitude = drone_config.mission % 10
        if altitude > 50:
            altitude = 50
        success = run_mission_script("takeoff_mission.py", altitude)

    elif drone_config.mission == 101:
        success = run_mission_script("land_mission.py")

    elif drone_config.mission == 102:
        success = run_mission_script("hold_mission.py")

    elif drone_config.mission == 100:
        success = run_mission_script("test_mission.py")

    if success:
        # Reset mission to NONE after performing it
        drone_config.mission = 0
            
# Create 'logs' directory if it doesn't exist
if not os.path.exists('logs'):
    os.makedirs('logs')

# Get current datetime to use in the filename
now = datetime.datetime.now()
current_time = now.strftime("%Y-%m-%d_%H-%M-%S")

# Set up logging
log_filename = os.path.join('logs', f'{current_time}.log')
logging.basicConfig(filename=log_filename, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# Main function
def main():
    print("Starting the main function...")

    try:
        # Synchronize time once
        print("Synchronizing time...")
        synchronize_time()

        # Initialize MAVLink
        print("Initializing MAVLink...")
        mavlink_router_process = initialize_mavlink()
        time.sleep(2)

        # Enter a loop where the application will continue running
        while True:
            # Get the drone state
            #drone_state = get_drone_state()

            if drone_config.mission == 2 and drone_config.state != 0 and int(drone_config.swarm.get('follow')) != 0:
                drone_config.calculate_setpoints()
            
            # Schedule the drone mission if the trigger time has been reached
            schedule_mission()

            # Sleep for a short interval to prevent the loop from running too fast
            time.sleep(params.sleep_interval)

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        # Close the threads before the application closes
        print("Closing threads...")
        drone_comms.stop_communication()

    print("Exiting the application...")

if __name__ == "__main__":
    main()