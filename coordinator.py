#!/usr/bin/env python3
"""
Coordinator Application for Drone Management

This script initializes and manages various components related to drone operations,
including MAVLink communication, mission scheduling. It also
provides LED feedback based on the drone's state to aid field operations.

Author: Alireza Ghaderi
GitHub Repository: https://github.com/alireza787b
Date: September 2024
"""

import os
import sys
import time
import threading
import datetime
import logging
import sdnotify  # For systemd watchdog notifications
import asyncio  # Needed for async functions

# Import necessary modules and classes
from src.drone_config import DroneConfig
from src.local_mavlink_controller import LocalMavlinkController
from src.drone_communicator import DroneCommunicator
from src.drone_setup import DroneSetup
from src.params import Params
from src.mavlink_manager import MavlinkManager
from src.flask_handler import FlaskHandler
from src.led_controller import LEDController  # Import LEDController

# For log rotation
from logging.handlers import RotatingFileHandler

# Set up logging directory and configuration
LOG_DIR = 'logs'
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# Get current datetime to use in the filename
now = datetime.datetime.now()
current_time = now.strftime("%Y-%m-%d_%H-%M-%S")
log_filename = os.path.join(LOG_DIR, f'{current_time}.log')

# Set up logging with rotation
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Create handlers
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)

file_handler = RotatingFileHandler(
    log_filename, maxBytes=5 * 1024 * 1024, backupCount=5
)  # 5 MB per file, keep 5 backups
file_handler.setLevel(logging.DEBUG)

# Create formatter and add it to handlers
formatter = logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'
)
console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)

# Add handlers to logger
logger.addHandler(console_handler)
logger.addHandler(file_handler)

# Global variables
mavlink_manager = None
global_telemetry = {}  # Store telemetry data
run_telemetry_thread = threading.Event()
run_telemetry_thread.set()
drones = {}  # Dictionary to store drone information
params = Params()  # Global parameters instance
drone_config = DroneConfig(drones)  # Initialize DroneConfig
drone_comms = None  # Initialize drone_comms as None
drone_setup = None  # Initialize drone_setup as None

# Initialize LEDController only if not in simulation mode
if not Params.sim_mode:
    try:
        led_controller = LEDController.get_instance()
    except Exception as e:
        logger.error("Failed to initialize LEDController: %s", e)
else:
    led_controller = None  # Or use a mock controller if needed

# Systemd watchdog notifier
notifier = sdnotify.SystemdNotifier()

def schedule_missions_thread(drone_setup_instance):
    """
    Thread target function to schedule missions asynchronously.
    """
    asyncio.run(schedule_missions_async(drone_setup_instance))

async def schedule_missions_async(drone_setup_instance):
    """
    Asynchronous function to schedule missions at a specified frequency.
    """
    while True:
        logger.info(f"Checking Scheduler: Mission Code:{drone_config.mission}, State: {drone_config.state}, Trigger Time:{drone_config.trigger_time}, Current Time:{int(time.time())}")
        await drone_setup_instance.schedule_mission()
        await asyncio.sleep(1.0 / params.schedule_mission_frequency)

def main_loop():
    """
    Main loop of the coordinator application.
    """
    global mavlink_manager, drone_comms, drone_setup  # Declare as global variables
    try:
        logger.info("Starting the main loop...")
        # Set LEDs to Blue to indicate initialization in progress
        LEDController.set_color(0, 0, 255)  # Blue
        logger.info("After intial LED set color...")

        # Synchronize time if enabled
        if params.online_sync_time:
            drone_setup.synchronize_time()
            logger.info("Time synchronized.")

        

        # Initialization successful
        LEDController.set_color(0, 255, 0)  # Green
        logger.info("Initialization successful. MAVLink is ready.")


        # Start mission scheduling thread
        scheduling_thread = threading.Thread(target=schedule_missions_thread, args=(drone_setup,))
        scheduling_thread.start()
        logger.info("Mission scheduling thread started.")

        # Variable to track the last state value
        last_state_value = None

        while True:
            current_time = time.time()
            # Notify systemd watchdog
            notifier.notify("WATCHDOG=1")

            # Check drone state and update LEDs accordingly
            current_state = drone_config.state
            current_mission = drone_config.mission

            if current_mission != last_mission_value:
                last_mission_value = current_mission
                logger.info(f"Drone mission changed to {current_mission}")

            if current_state != last_state_value:
                last_state_value = current_state
                logger.info(f"Drone state changed to {current_state}")

                if current_state == 0:
                    # Idle state on ground
                    LEDController.set_color(0, 0, 255)  # Blue
                    logger.debug("Drone is idle on ground (state == 0).")
                elif current_state == 1:
                    # Trigger time received; ready to fly
                    LEDController.set_color(255, 165, 0)  # Orange
                    logger.debug(f"Trigger time received({drone_config.trigger_time}). Drone is ready to fly (state == 1).")
                elif current_state == 2:
                    # Maneuver started; stop changing LEDs
                    logger.info(f"Mission ({current_mission}) started (state == 2).")
                    # Do not change LEDs anymore; drone show script will take over
                else:
                    # Unknown state; set LEDs to Red
                    LEDController.set_color(255, 0, 0)  # Red
                    logger.warning(f"Unknown drone state: {current_state}")


            time.sleep(params.sleep_interval)  # Sleep for defined interval

    except Exception as e:
        logger.error(f"An error occurred in main loop: {e}", exc_info=True)
        LEDController.set_color(255, 0, 0)  # Red for error state

    finally:
        logger.info("Closing threads and cleaning up...")
        if mavlink_manager:
            mavlink_manager.terminate()  # Terminate MavlinkManager
            logger.info("MAVLink manager terminated.")
        if drone_comms:
            drone_comms.stop_communication()
            logger.info("Drone communication stopped.")
        # Optionally, turn off LEDs or set to a default color
        # LEDController.turn_off()

def main():
    """
    Main function to start the coordinator application.
    """
    global drone_comms, drone_setup , mavlink_manager # Declare as global variables
    logger.info("Starting the coordinator application...")

    # Initialize MAVLink communication
    mavlink_manager = MavlinkManager(params, drone_config)
    logger.info("Initializing MAVLink...")
    mavlink_manager.initialize()
    time.sleep(2)  # Wait for initialization

    # Initialize LocalMavlinkController
    local_drone_controller = LocalMavlinkController(drone_config, params, False)
    logger.info("LocalMavlinkController initialized.")

    # Step 1: Initialize DroneCommunicator and FlaskHandler without dependencies
    drone_comms = DroneCommunicator(drone_config, params, drones)
    flask_handler = FlaskHandler(params, drone_config)

    # Step 2: Inject the dependencies afterward (setters)
    drone_comms.set_flask_handler(flask_handler)
    logger.info("DroneCommunicator's FlaskHandler set.")

    flask_handler.set_drone_communicator(drone_comms)
    logger.info("FlaskHandler's DroneCommunicator set.")

    # Step 3: Start DroneCommunicator communication
    drone_comms.start_communication()
    logger.info("DroneCommunicator communication started.")

    # Step 4: Start Flask HTTP server if enabled
    if params.enable_drones_http_server:
        flask_thread = threading.Thread(target=flask_handler.run, daemon=True)
        flask_thread.start()
        logger.info("Flask HTTP server started.")

    # Step 5: Initialize DroneSetup
    drone_setup = DroneSetup(params, drone_config)
    logger.info("DroneSetup initialized.")

    # Step 6: Start the main loop
    main_loop()

if __name__ == "__main__":
    main()