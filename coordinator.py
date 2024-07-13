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
from src.flask_handler import FlaskHandler
#import sdnotify  # For systemd watchdog notifications

# Ensure the 'logs' directory exists
if not os.path.exists('logs'):
    os.makedirs('logs')

# Set up logging with the current date and time
now = datetime.datetime.now()
log_filename = os.path.join('logs', f'{now.strftime("%Y-%m-%d_%H-%M-%S")}.log')
logging.basicConfig(filename=log_filename, level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize system parameters and configurations
params = Params()
drone_config = DroneConfig({})  # Initialize DroneConfig with an empty dictionary

# Create necessary service components
local_drone_controller = LocalMavlinkController(drone_config, params)
drone_comms = DroneCommunicator(drone_config, params, {})
drone_comms.start_communication()
offboard_controller = OffboardController(drone_config)
drone_setup = DroneSetup(params, drone_config, offboard_controller)

# Setup Flask server for HTTP drone control (if enabled)
if params.enable_drones_http_server:
    flask_handler = FlaskHandler(params, drone_comms)
    flask_thread = threading.Thread(target=flask_handler.run, daemon=True)
    flask_thread.start()

# Systemd watchdog notifier
#notifier = sdnotify.SystemdNotifier()

def schedule_missions_thread(drone_setup):
    """ Thread to continuously schedule drone missions. """
    asyncio.run(schedule_missions_async(drone_setup))

async def schedule_missions_async(drone_setup):
    """ Asynchronously schedule drone missions at specified intervals. """
    while True:
        await drone_setup.schedule_mission()
        await asyncio.sleep(1.0 / params.schedule_mission_frequency)

def main_loop():
    """ Main application loop handling drone operations and system monitoring. """
    global mavlink_manager  # Global reference for Mavlink manager

    try:
        if params.online_sync_time:
            drone_setup.synchronize_time()

        mavlink_manager = MavlinkManager(params, drone_config)
        logging.info("Initializing MAVLink...")
        mavlink_manager.initialize()

        try:
            print("before sleep")
            time.sleep(2)
            print("after sleep")
        except Exception as e:
            logging.error(f"Error after sleep: {e}")



        last_follow_setpoint_time = 0
        follow_setpoint_interval = 1.0 / params.follow_setpoint_frequency

        # Start the mission scheduling thread
        scheduling_thread = threading.Thread(target=schedule_missions_thread, args=(drone_setup,))
        scheduling_thread.start()

        while True:
            current_time = time.time()
            if current_time - last_follow_setpoint_time >= follow_setpoint_interval:
                offboard_controller.calculate_follow_setpoint()
                last_follow_setpoint_time = current_time

            # Notify systemd watchdog
            #notifier.notify("WATCHDOG=1")

            time.sleep(params.sleep_interval)

    except Exception as e:
        logging.error(f"An error occurred: {e}")

    finally:
        logging.info("Closing threads and stopping communication.")
        if mavlink_manager:
            mavlink_manager.terminate()
        drone_comms.stop_communication()

        logging.info("Exiting the application.")

def main():
    """ Entry point of the application. """
    logging.info("Starting the main function...")
    main_loop()

if __name__ == "__main__":
    main()
