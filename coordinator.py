
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
import glob
import requests
from geographiclib.geodesic import Geodesic
from mavsdk import System
from mavsdk.offboard import OffboardError, PositionNedYaw, VelocityNedYaw
from src.offboard_controller import OffboardController
import logging
import src.params as params
import struct
from src.drone_communicator import DroneCommunicator
import math
from src.params import Params 
from src.mavlink_manager import MavlinkManager
from enum import Enum
from src.drone_setup import DroneSetup

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




        
        



# Global variable to store the single OffboardController instance
offboard_controller = None


offboard_controller = OffboardController(drone_config)


# Create a DroneSetup object
drone_setup = DroneSetup(params,drone_config, offboard_controller)

def schedule_missions_thread(drone_setup):
    while True:
        drone_setup.schedule_mission()
        time.sleep(1.0 / params.schedule_mission_frequency)

        
def main_loop():
    global mavlink_manager, offboard_controller  # Declare them as global
    try:
        drone_setup.synchronize_time()

        mavlink_manager = MavlinkManager(params, drone_config)
        print("Initializing MAVLink...")
        mavlink_manager.initialize()  # Use MavlinkManager's initialize method
        time.sleep(2)

        last_follow_setpoint_time = 0
        last_schedule_mission_time = 0
        follow_setpoint_interval = 1.0 / params.follow_setpoint_frequency  # time in seconds
        schedule_mission_interval = 1.0 / params.schedule_mission_frequency  # time in seconds


        scheduling_thread = threading.Thread(target=schedule_missions_thread, args=(drone_setup,))
        scheduling_thread.start()

        while True:
            current_time = time.time()
            
            if int(drone_config.mission) == 2:
                
                
                if current_time - last_follow_setpoint_time >= follow_setpoint_interval:
                    offboard_controller.calculate_follow_setpoint()
                    last_follow_setpoint_time = current_time

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