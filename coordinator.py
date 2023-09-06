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
from src.mavlink_manager import MavlinkManager
from enum import Enum

class Mission(Enum):
    NONE = 0
    DRONE_SHOW_FROM_CSV = 1
    SMART_SWARM = 2
    TAKE_OFF = 10
    LAND = 101
    HOLD = 102
    TEST = 100

# Create 'logs' directory if it doesn't exist
if not os.path.exists('logs'):
    os.makedirs('logs')

# Get current datetime to use in the filename
now = datetime.datetime.now()
current_time = now.strftime("%Y-%m-%d_%H-%M-%S")

# Set up logging
log_filename = os.path.join('logs', f'{current_time}.log')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')



mavlink_manager = None

# Global variable to store telemetry
global_telemetry = {}


# Global variable to store OffboardController instances
offboard_controllers = {}


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
def run_mission_script(command):
    print(f"Running mission script: {command}")  # Debug print
    try:
        subprocess.run(command.split(), check=True)
        print("Mission script completed successfully.")  # Debug print
        return True
    except subprocess.CalledProcessError:
        print("Mission script encountered an error.")  # Debug print
        return False

# Global variable to store the single OffboardController instance
offboard_controller = None

def schedule_mission():
    """
    Schedule and execute various drone missions based on the current mission code and state.
    """
    global offboard_controller  # Declare it as global to modify it
    
    # Get the current time
    current_time = int(time.time())
    success = False  # Initialize success flag
    
    # print(f"Current mission code: {drone_config.mission}, Current state: {drone_config.state}")  # Debug output
    
    # If the mission is 1 (Drone Show) or 2 (Swarm Mission)
    if drone_config.mission in [1, 2]:
        if drone_config.state == 1 and current_time >= drone_config.trigger_time:
            # Update state and reset trigger time
            drone_config.state = 2
            drone_config.trigger_time = 0
            
            if drone_config.mission == 1:
                print("Starting Drone Show")
                success = run_mission_script("python offboard_multiple_from_csv.py")
            elif drone_config.mission == 2:
                print("Starting Swarm Mission")
                if int(drone_config.swarm.get('follow')) != 0:
                    offboard_controller = OffboardController(drone_config)
                    asyncio.run(offboard_controller.start_offboard_follow())
                success = True  # Assume success for now
    
    # If the mission is to take off to a certain altitude
    elif 10 <= drone_config.mission < 100:
        altitude = float(drone_config.mission) - 10
        altitude = min(altitude, 50)  # Limit altitude to 50m
        print(f"Starting Takeoff to {altitude}m")
        success = run_mission_script(f"python actions.py --action=takeoff --altitude={altitude}")
    
    # If the mission is to land
    elif drone_config.mission == 101:
        print("Starting Land")
        if int(drone_config.swarm.get('follow')) != 0 and offboard_controller:  # Check if it's a follower
            print("Is a follower and offboard_controller exists.")  # Debug output
            if offboard_controller.is_offboard:  # Check if it's in offboard mode
                print("Is in Offboard mode. Attempting to stop offboard.")  # Debug output
                asyncio.run(offboard_controller.stop_offboard())  # Stop offboard
                asyncio.sleep(1)  # Wait for a second
        success = run_mission_script("python actions.py --action=land")
    
    # If the mission is to hold the position
    elif drone_config.mission == 102:
        print("Starting Hold Position")
        success = run_mission_script("python actions.py --action=hold")
    
    # If the mission is a test
    elif drone_config.mission == 100:
        print("Starting Test")
        success = run_mission_script("python actions.py --action=test")
    
    # Reset mission and state if successful
    if success:
        print("Mission completed successfully.")
        if drone_config.mission != 2:  # Don't reset if it's a Smart Swarm mission
            print("Resetting mission code and state.")
            drone_config.mission = 0
            drone_config.state = 0




# Function to handle drone states
def handle_follow_setpoint():
    if drone_config.mission == 2 and drone_config.state != 0 and int(drone_config.swarm.get('follow')) != 0:
        drone_config.calculate_setpoints()
        
        
def main_loop():
    global mavlink_manager  # Declare it as global
    try:
        synchronize_time()
        mavlink_manager = MavlinkManager(params, drone_config)
        print("Initializing MAVLink...")
        mavlink_manager.initialize()  # Use MavlinkManager's initialize method
        time.sleep(2)

        while True:
            handle_follow_setpoint()
            schedule_mission()
            time.sleep(params.sleep_interval)

    except Exception as e:
        print(f"An error occurred: {e}")
        logging.error(f"An error occurred: {e}")

    finally:
        print("Closing threads...")
        if mavlink_manager:
            mavlink_manager.terminate()  # Terminate MavlinkManager
        drone_comms.stop_communication()
        logging.info("Closing threads and stopping communication.")

    print("Exiting the application...")
    logging.info("Exiting the application.")

# Main function
def main():
    print("Starting the main function...")
    main_loop()

if __name__ == "__main__":
    main()