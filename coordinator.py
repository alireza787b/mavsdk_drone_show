#!/usr/bin/env python3
"""
Coordinator Application for Drone Management
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
from src.led_controller import LEDController
from src.connectivity_checker import ConnectivityChecker
from src.enums import State  # Import State enum
from src.heartbeat_sender import HeartbeatSender
from src.pos_id_auto_detector import PosIDAutoDetector  # Import the new class

# For log rotation
from logging.handlers import RotatingFileHandler

# Set up logging directory and configuration
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

file_handler = RotatingFileHandler(
    log_filename, maxBytes=5 * 1024 * 1024, backupCount=5
)
file_handler.setLevel(logging.DEBUG)

formatter = logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'
)
console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)

logger.addHandler(console_handler)
logger.addHandler(file_handler)

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
flask_handler = None

if not Params.sim_mode:
    try:
        led_controller = LEDController.get_instance()
    except Exception as e:
        logger.error("Failed to initialize LEDController: %s", e)
else:
    led_controller = None

notifier = sdnotify.SystemdNotifier()

def schedule_missions_thread(drone_setup_instance):
    asyncio.run(schedule_missions_async(drone_setup_instance))

async def schedule_missions_async(drone_setup_instance):
    while True:
        notifier.notify("WATCHDOG=1")
        logger.info(
            f"Checking Scheduler: Mission Code:{drone_config.mission}, "
            f"State: {drone_config.state}, "
            f"Trigger Time:{drone_config.trigger_time}, "
            f"Current Time:{int(time.time())}"
        )

        # Possibly check if a new command arrived and forcibly kill old scripts:
        # Example:
        # if some_condition_for_new_command:
        #     await drone_setup_instance.terminate_all_running_processes()
        # Then start new command.

        await drone_setup_instance.schedule_mission()
        await asyncio.sleep(1.0 / params.schedule_mission_frequency)

def main_loop():
    global mavlink_manager, drone_comms, drone_setup, connectivity_checker, heartbeat_sender, pos_id_auto_detector, flask_handler
    try:
        logger.info("Starting the main loop...")
        LEDController.set_color(0, 0, 255)  # Blue

        if params.online_sync_time:
            drone_setup.synchronize_time()
            logger.info("Time synchronized.")

        LEDController.set_color(0, 255, 0)  # Green
        logger.info("Initialization successful. MAVLink is ready.")

        scheduling_thread = threading.Thread(
            target=schedule_missions_thread,
            args=(drone_setup,),
            daemon=True
        )
        scheduling_thread.start()
        logger.info("Mission scheduling thread started.")

        connectivity_checker = ConnectivityChecker(params, LEDController)

        last_state_value = None
        last_mission_value = None

        while True:
            current_time = time.time()
            notifier.notify("WATCHDOG=1")

            current_state = drone_config.state
            current_mission = drone_config.mission

            if current_mission != last_mission_value:
                drone_config.last_mission = last_mission_value
                last_mission_value = current_mission
                logger.info(f"Drone mission changed to {current_mission}")

            if current_state != last_state_value:
                last_state_value = current_state
                logger.info(f"Drone state changed to {current_state}")

                if current_state == State.IDLE.value:
                    if current_mission == 0:
                        if not connectivity_checker.is_running:
                            connectivity_checker.start()
                            logger.debug("Connectivity checker started.")
                    logger.debug("Drone is idle on ground (state == IDLE).")
                elif current_state == State.ARMED.value:
                    if connectivity_checker.is_running:
                        connectivity_checker.stop()
                        logger.debug("Connectivity checker stopped.")
                    LEDController.set_color(255, 165, 0)  # Orange
                    logger.debug(f"Trigger time received({drone_config.trigger_time}).")
                elif current_state == State.TRIGGERED.value:
                    if connectivity_checker.is_running:
                        connectivity_checker.stop()
                        logger.debug("Connectivity checker stopped.")
                    logger.info("Mission started (state == TRIGGERED).")
                else:
                    if connectivity_checker.is_running:
                        connectivity_checker.stop()
                        logger.debug("Connectivity checker stopped.")
                    LEDController.set_color(255, 0, 0)
                    logger.warning(f"Unknown drone state: {current_state}")

            time.sleep(params.sleep_interval)

    except Exception as e:
        logger.error(f"An error occurred in main loop: {e}", exc_info=True)
        LEDController.set_color(255, 0, 0)
    finally:
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

def main():
    global drone_comms, drone_setup, mavlink_manager, heartbeat_sender
    logger.info("Starting the coordinator application...")

    mavlink_manager = MavlinkManager(params, drone_config)
    logger.info("Initializing MAVLink...")
    mavlink_manager.initialize()
    time.sleep(2)

    local_drone_controller = LocalMavlinkController(drone_config, params, False)
    logger.info("LocalMavlinkController initialized.")

    global drone_comms, flask_handler
    drone_comms = DroneCommunicator(drone_config, params, drones)
    flask_handler = FlaskHandler(params, drone_config)

    drone_comms.set_flask_handler(flask_handler)
    logger.info("DroneCommunicator's FlaskHandler set.")

    flask_handler.set_drone_communicator(drone_comms)
    logger.info("FlaskHandler's DroneCommunicator set.")

    drone_comms.start_communication()
    logger.info("DroneCommunicator communication started.")

    if params.enable_drones_http_server:
        flask_thread = threading.Thread(target=flask_handler.run, daemon=True)
        flask_thread.start()
        logger.info("Flask HTTP server started.")
        
    heartbeat_sender = HeartbeatSender(drone_config)
    heartbeat_sender.start()
    logger.info("HeartbeatSender has been started.")

    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # Initialize DroneSetup with new override logic
    # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<
    global drone_setup
    drone_setup = DroneSetup(params, drone_config)
    logger.info("DroneSetup initialized.")
    
    if params.auto_detection_enabled:
        global pos_id_auto_detector
        pos_id_auto_detector = PosIDAutoDetector(drone_config, params, flask_handler)
        pos_id_auto_detector.start()
    else:
        logger.info("PosIDAutoDetector is disabled via parameters.")

    main_loop()

if __name__ == "__main__":
    main()
