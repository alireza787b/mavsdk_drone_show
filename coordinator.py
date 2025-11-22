#!/usr/bin/env python3
"""
Coordinator Application for Drone Management

This script initializes and coordinates various components of the drone management system:
- Logging setup with log rotation.
- MAVLink communication.
- Drone communication and mission scheduling.
- LED control based on connectivity status.
- Systemd watchdog notifications.

Key components:
    - ConnectivityChecker: Pings a specified IP and updates LED status.
    - DroneCommunicator and DroneAPIServer: Handle communication and HTTP server.
    - HeartbeatSender: Sends regular heartbeat signals.
    - PosIDAutoDetector: Automatically detects position ID (if enabled).
"""

import os
import sys
import time
import threading
import datetime
import logging
import sdnotify  # For systemd watchdog notifications
import asyncio  # For async mission scheduling

# Import necessary modules and classes
from src.drone_config import DroneConfig
from src.local_mavlink_controller import LocalMavlinkController
from src.drone_communicator import DroneCommunicator
from src.drone_setup import DroneSetup
from src.params import Params
from src.mavlink_manager import MavlinkManager
from src.drone_api_server import DroneAPIServer
from src.led_controller import LEDController
from src.connectivity_checker import ConnectivityChecker
from src.enums import State  # Import State enum
from src.heartbeat_sender import HeartbeatSender
from src.pos_id_auto_detector import PosIDAutoDetector  # Import the new class

# For log rotation
from logging.handlers import RotatingFileHandler

# -----------------------------------------------------------------------------
# Logging Setup
# -----------------------------------------------------------------------------

LOG_DIR = 'logs'
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

now = datetime.datetime.now()
current_time = now.strftime("%Y-%m-%d_%H-%M-%S")
log_filename = os.path.join(LOG_DIR, f'{current_time}.log')

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)

file_handler = RotatingFileHandler(log_filename, maxBytes=5 * 1024 * 1024, backupCount=5)
file_handler.setLevel(logging.DEBUG)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s',
                              datefmt='%Y-%m-%d %H:%M:%S')
console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)

logger.addHandler(console_handler)
logger.addHandler(file_handler)

# -----------------------------------------------------------------------------
# Global Variables and Component Initialization
# -----------------------------------------------------------------------------

mavlink_manager = None
global_telemetry = {}
run_telemetry_thread = threading.Event()
run_telemetry_thread.set()
drones = {}
params = Params()
drone_config = DroneConfig(drones)
drone_comms = None
drone_setup = None
heartbeat_sender = None
connectivity_checker = None
pos_id_auto_detector = None
api_server = None

# Initialize LEDController instance if not in simulation mode
if not Params.sim_mode:
    try:
        led_controller = LEDController.get_instance()  # Get the singleton instance
    except Exception as e:
        logger.error("Failed to initialize LEDController: %s", e)
        led_controller = None
else:
    led_controller = None

# Initialize systemd notifier for watchdog notifications
notifier = sdnotify.SystemdNotifier()

# -----------------------------------------------------------------------------
# Mission Scheduling Functions
# -----------------------------------------------------------------------------

def schedule_missions_thread(drone_setup_instance):
    """
    Wrapper function to run the asynchronous schedule_missions_async function.
    This is launched in a separate thread.
    """
    asyncio.run(schedule_missions_async(drone_setup_instance))

async def schedule_missions_async(drone_setup_instance):
    """
    Asynchronous function that continuously schedules missions.
    Notifies the systemd watchdog and logs scheduling details.
    """
    while True:
        notifier.notify("WATCHDOG=1")
        logger.info(
            f"Checking Scheduler: Mission Code: {drone_config.mission}, "
            f"State: {drone_config.state}, "
            f"Trigger Time: {drone_config.trigger_time}, "
            f"Current Time: {int(time.time())}"
        )

        # Optionally, check if a new command has arrived and terminate old processes:
        # if some_condition_for_new_command:
        #     await drone_setup_instance.terminate_all_running_processes()
        # Then, start the new command.

        await drone_setup_instance.schedule_mission()
        await asyncio.sleep(1.0 / params.schedule_mission_frequency)

# -----------------------------------------------------------------------------
# Main Loop
# -----------------------------------------------------------------------------

def main_loop():
    """
    Main loop of the coordinator application.
    Monitors drone state changes, updates LED status via ConnectivityChecker,
    sends watchdog notifications, and manages thread cleanup on exit.
    """
    global mavlink_manager, drone_comms, drone_setup, connectivity_checker, heartbeat_sender, pos_id_auto_detector, api_server

    try:
        logger.info("Starting the main loop...")

        # Set initial LED color to Cyan to indicate startup
        

        # Synchronize time if enabled
        if params.online_sync_time:
            drone_setup.synchronize_time()
            logger.info("Time synchronized.")

        logger.info("Initialization successful. MAVLink is ready.")

        # Start the mission scheduling thread
        scheduling_thread = threading.Thread(
            target=schedule_missions_thread,
            args=(drone_setup,),
            daemon=True
        )
        scheduling_thread.start()
        logger.info("Mission scheduling thread started.")

        # Instantiate ConnectivityChecker with the correct LEDController instance
        connectivity_checker = ConnectivityChecker(params, led_controller)

        last_state_value = None
        last_mission_value = None

        while True:
            notifier.notify("WATCHDOG=1")
            current_state = drone_config.state
            current_mission = drone_config.mission

            # Log mission changes
            if current_mission != last_mission_value:
                drone_config.last_mission = last_mission_value
                last_mission_value = current_mission
                logger.info(f"Drone mission changed to {current_mission}")

            # Handle state changes and associated actions
            if current_state != last_state_value:
                last_state_value = current_state
                logger.info(f"Drone state changed to {current_state}")

                if current_state == State.IDLE.value:
                    # In IDLE state, start connectivity checking only if no mission
                    # and if connectivity check is enabled via params.
                    if current_mission == 0 and params.enable_connectivity_check:
                        if not connectivity_checker.is_running:
                            connectivity_checker.start()
                            logger.debug("Connectivity checker started.")
                    logger.debug("Drone is idle on ground (state == IDLE).")
                elif current_state == State.MISSION_READY.value:
                    # Stop connectivity checking and set LED to Orange when armed
                    if connectivity_checker.is_running:
                        connectivity_checker.stop()
                        logger.debug("Connectivity checker stopped.")
                    if led_controller:
                        led_controller.set_color(255, 165, 0)  # Orange
                    logger.debug(f"Trigger time received ({drone_config.trigger_time}).")
                elif current_state == State.MISSION_EXECUTING.value:
                    # Stop connectivity checking when mission is triggered
                    if connectivity_checker.is_running:
                        connectivity_checker.stop()
                        logger.debug("Connectivity checker stopped.")
                    logger.info("Mission started (state == TRIGGERED).")
                else:
                    # Unknown state: stop connectivity checking and set LED to Red
                    if connectivity_checker.is_running:
                        connectivity_checker.stop()
                        logger.debug("Connectivity checker stopped.")
                    if led_controller:
                        led_controller.set_color(255, 0, 0)  # Red
                    logger.warning(f"Unknown drone state: {current_state}")

            time.sleep(params.sleep_interval)

    except Exception as e:
        logger.error(f"An error occurred in main loop: {e}", exc_info=True)
        if led_controller:
            led_controller.set_color(255, 0, 0)  # Red to indicate error
    finally:
        # Clean up threads and components on exit
        logger.info("Closing threads and cleaning up...")
        if connectivity_checker and connectivity_checker.is_running:
            connectivity_checker.stop()
            logger.info("Connectivity checker stopped.")
        if mavlink_manager:
            mavlink_manager.terminate()
            logger.info("MAVLink manager terminated.")
        if drone_comms:
            drone_comms.stop_communication()
            logger.info("Drone communication stopped.")
        if heartbeat_sender:
            heartbeat_sender.stop()
            logger.info("HeartbeatSender stopped.")
        if pos_id_auto_detector:
            pos_id_auto_detector.stop()
            logger.info("PosIDAutoDetector stopped.")

# -----------------------------------------------------------------------------
# Main Entry Point
# -----------------------------------------------------------------------------

def main():
    """
    Main entry point for the coordinator application.
    Initializes all necessary components and starts the main loop.
    """
    global drone_comms, drone_setup, mavlink_manager, heartbeat_sender

    logger.info("Starting the coordinator application...")

    # Initialize MAVLink manager and wait briefly to ensure proper startup
    mavlink_manager = MavlinkManager(params, drone_config)
    logger.info("Initializing MAVLink...")
    mavlink_manager.initialize()
    time.sleep(2)

    # Initialize local MAVLink controller for local operations
    local_drone_controller = LocalMavlinkController(drone_config, params, False)
    logger.info("LocalMavlinkController initialized.")

    # Initialize DroneCommunicator and DroneAPIServer for communications
    global api_server
    drone_comms = DroneCommunicator(drone_config, params, drones)
    api_server = DroneAPIServer(params, drone_config)

    drone_comms.set_api_server(api_server)
    logger.info("DroneCommunicator's DroneAPIServer set.")

    api_server.set_drone_communicator(drone_comms)
    logger.info("DroneAPIServer's DroneCommunicator set.")

    drone_comms.start_communication()
    logger.info("DroneCommunicator communication started.")

    # Start the FastAPI HTTP server if enabled in the parameters
    if params.enable_drones_http_server:
        api_thread = threading.Thread(target=api_server.run, daemon=True)
        api_thread.start()
        logger.info("FastAPI HTTP server started.")

    # Start the HeartbeatSender to send periodic heartbeat signals
    heartbeat_sender = HeartbeatSender(drone_config)
    heartbeat_sender.start()
    logger.info("HeartbeatSender has been started.")

    # Initialize DroneSetup for mission scheduling and execution
    global drone_setup
    drone_setup = DroneSetup(params, drone_config)
    logger.info("DroneSetup initialized.")

    # Optionally, start the PosIDAutoDetector if auto-detection is enabled
    if params.auto_detection_enabled:
        global pos_id_auto_detector
        pos_id_auto_detector = PosIDAutoDetector(drone_config, params, api_server)
        pos_id_auto_detector.start()
    else:
        logger.info("PosIDAutoDetector is disabled via parameters.")

    if led_controller:
            led_controller.set_color(0, 255, 255)  # Cyan
    # Enter the main application loop
    main_loop()

if __name__ == "__main__":
    main()
