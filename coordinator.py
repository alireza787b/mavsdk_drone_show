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
import sdnotify  # For systemd watchdog notifications
import asyncio  # For async mission scheduling
from enum import Enum
from typing import Callable, Optional, Any

# Import necessary modules and classes
from src.drone_config import DroneConfig
from src.local_mavlink_controller import LocalMavlinkController
from src.drone_communicator import DroneCommunicator
from src.drone_setup import DroneSetup
from src.params import Params
# MavlinkManager REMOVED - MAVLink routing is now EXTERNAL:
#   - SITL: run_mavlink_router.sh started by startup_sitl.sh
#   - Real: mavlink-anywhere systemd service (user must configure)
from src.drone_api_server import DroneAPIServer
from src.led_controller import LEDController
from src.connectivity_checker import ConnectivityChecker
from src.enums import State  # Import State enum
from src.led_colors import LEDColors, LEDState  # Unified LED color system
from src.heartbeat_sender import HeartbeatSender
from src.pos_id_auto_detector import PosIDAutoDetector  # Import the new class

# Unified logging system
from mds_logging.drone import init_drone_logging
from mds_logging import get_logger, register_component

register_component("coordinator", "drone", "System initialization and heartbeat")
init_drone_logging()
logger = get_logger("coordinator")

# -----------------------------------------------------------------------------
# Startup State Machine
# -----------------------------------------------------------------------------

class StartupState(Enum):
    """Tracks coordinator startup progress for diagnostics and LED feedback."""
    INITIALIZING = "initializing"
    LED_INIT = "led_init"
    MAVLINK_INIT = "mavlink_init"
    COMMUNICATOR_INIT = "communicator_init"
    API_SERVER_INIT = "api_server_init"
    HEARTBEAT_INIT = "heartbeat_init"
    DRONE_SETUP_INIT = "drone_setup_init"
    VALIDATION = "validation"
    READY = "ready"
    FAILED = "failed"


class StartupError(Exception):
    """Exception raised when a startup component fails to initialize."""
    pass


# Current startup state (for diagnostics)
_startup_state = StartupState.INITIALIZING


def safe_init(
    name: str,
    init_func: Callable[[], Any],
    led_controller_instance=None,
    critical: bool = True
) -> Optional[Any]:
    """
    Safely initialize a component with error handling and LED feedback.

    Args:
        name: Human-readable component name for logging
        init_func: Function that initializes the component
        led_controller_instance: Optional LED controller for status feedback
        critical: If True, raises StartupError on failure; if False, logs warning and returns None

    Returns:
        The result of init_func(), or None if non-critical and failed

    Raises:
        StartupError: If critical=True and initialization fails
    """
    global _startup_state
    try:
        logger.info(f"Initializing {name}...")
        result = init_func()
        logger.info(f"{name} initialized successfully")
        return result
    except Exception as e:
        _startup_state = StartupState.FAILED
        logger.error(f"Failed to initialize {name}: {e}", exc_info=True)

        if led_controller_instance:
            try:
                led_controller_instance.set_color(*LEDColors.ERROR)
            except Exception:
                pass

        if critical:
            raise StartupError(f"{name} initialization failed: {e}") from e
        else:
            logger.warning(f"{name} failed but marked non-critical, continuing...")
            return None


def validate_startup_prerequisites() -> bool:
    """
    Validate that necessary files and configurations exist before starting.

    Returns:
        True if all prerequisites are met, False otherwise
    """
    issues = []

    # Check config file exists
    config_file = Params.config_file_name
    if not os.path.exists(config_file):
        issues.append(f"Config file not found: {config_file}")

    # Check venv exists (for real mode)
    if not Params.sim_mode:
        venv_python = os.path.join(os.path.dirname(__file__), 'venv', 'bin', 'python')
        if not os.path.exists(venv_python):
            logger.warning(f"venv not found at expected location (non-critical)")

    if issues:
        for issue in issues:
            logger.error(f"Startup prerequisite failed: {issue}")
        return False

    logger.info("Startup prerequisites validated")
    return True


# -----------------------------------------------------------------------------
# Global Variables and Component Initialization
# -----------------------------------------------------------------------------

# mavlink_manager REMOVED - external routing via mavlink-anywhere/run_mavlink_router.sh
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
    Notifies the systemd watchdog and logs state changes (not every tick).
    """
    drone_setup_instance.bind_mission_event_loop()
    # Track last state to implement change-based logging
    last_mission = None
    last_state = None
    last_trigger_time = None
    last_summary_time = 0
    SUMMARY_INTERVAL = 60  # Log status summary every 60 seconds

    while True:
        notifier.notify("WATCHDOG=1")
        current_time = int(time.time())

        # Detect changes
        mission_changed = drone_config.mission != last_mission
        state_changed = drone_config.state != last_state
        trigger_changed = drone_config.trigger_time != last_trigger_time

        # Log only on state changes (INFO level - visible)
        if mission_changed or state_changed or trigger_changed:
            changes = []
            if mission_changed:
                changes.append(f"Mission: {last_mission} → {drone_config.mission}")
            if state_changed:
                changes.append(f"State: {last_state} → {drone_config.state}")
            if trigger_changed:
                changes.append(f"Trigger: {last_trigger_time} → {drone_config.trigger_time}")

            logger.info(f"Scheduler state change: {', '.join(changes)}")

            # Update tracked values
            last_mission = drone_config.mission
            last_state = drone_config.state
            last_trigger_time = drone_config.trigger_time

        # Periodic summary (every SUMMARY_INTERVAL seconds) - helps confirm system is alive
        elif current_time - last_summary_time >= SUMMARY_INTERVAL:
            logger.debug(
                f"Scheduler status: Mission={drone_config.mission}, "
                f"State={drone_config.state}, Trigger={drone_config.trigger_time}"
            )
            last_summary_time = current_time

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
    global drone_comms, drone_setup, connectivity_checker, heartbeat_sender, pos_id_auto_detector, api_server

    try:
        logger.info("Starting the main loop...")
        # Note: LED already set to IDLE_CONNECTED in main() before entering loop

        # Synchronize time if enabled
        if params.online_sync_time:
            if params.sim_mode:
                logger.info("Skipping time synchronization in simulation mode.")
            else:
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
                        led_controller.set_color(*LEDColors.MISSION_ARMED)  # Orange
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
                        led_controller.set_color(*LEDColors.ERROR)  # Red
                    logger.warning(f"Unknown drone state: {current_state}")

            time.sleep(params.sleep_interval)

    except Exception as e:
        logger.error(f"An error occurred in main loop: {e}", exc_info=True)
        if led_controller:
            led_controller.set_color(*LEDColors.ERROR)  # Red to indicate error
    finally:
        # Clean up threads and components on exit
        logger.info("Closing threads and cleaning up...")
        if connectivity_checker and connectivity_checker.is_running:
            connectivity_checker.stop()
            logger.info("Connectivity checker stopped.")
        # mavlink_manager termination REMOVED - routing is external
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

    Uses safe_init() wrapper for error handling and LED feedback during startup.
    """
    global drone_comms, drone_setup, heartbeat_sender, _startup_state

    logger.info("=" * 60)
    logger.info("Starting the coordinator application...")
    logger.info(f"Mode: {'SIMULATION' if Params.sim_mode else 'REAL HARDWARE'}")
    logger.info(f"GCS IP: {Params.GCS_IP}")
    logger.info("=" * 60)

    # Set initial LED state
    if led_controller:
        led_controller.set_color(*LEDColors.NETWORK_INIT)  # Blue during init

    # Validate prerequisites
    _startup_state = StartupState.VALIDATION
    if not validate_startup_prerequisites():
        logger.error("Startup prerequisites not met - check configuration")
        if led_controller:
            led_controller.set_color(*LEDColors.ERROR)
        # Continue anyway for graceful degradation in some cases

    # MAVLink routing is now EXTERNAL:
    #   - SITL: run_mavlink_router.sh started by startup_sitl.sh
    #   - Real: mavlink-anywhere systemd service (user must configure)
    # See docs/guides/mavlink-routing-setup.md for configuration
    logger.info("MAVLink routing expected from external source (mavlink-anywhere or run_mavlink_router.sh)")

    try:
        # Initialize local MAVLink controller for local operations
        _startup_state = StartupState.MAVLINK_INIT
        local_drone_controller = safe_init(
            "LocalMavlinkController",
            lambda: LocalMavlinkController(drone_config, params, False),
            led_controller,
            critical=True
        )

        # Initialize DroneCommunicator and DroneAPIServer for communications
        _startup_state = StartupState.COMMUNICATOR_INIT
        global api_server
        drone_comms = safe_init(
            "DroneCommunicator",
            lambda: DroneCommunicator(drone_config, params, drones),
            led_controller,
            critical=True
        )

        _startup_state = StartupState.API_SERVER_INIT
        api_server = safe_init(
            "DroneAPIServer",
            lambda: DroneAPIServer(params, drone_config),
            led_controller,
            critical=True
        )

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
        _startup_state = StartupState.HEARTBEAT_INIT
        heartbeat_sender = safe_init(
            "HeartbeatSender",
            lambda: HeartbeatSender(drone_config),
            led_controller,
            critical=False  # Non-critical - can run without heartbeat
        )
        if heartbeat_sender:
            heartbeat_sender.start()
            logger.info("HeartbeatSender has been started.")

        # Initialize DroneSetup for mission scheduling and execution
        _startup_state = StartupState.DRONE_SETUP_INIT
        global drone_setup
        drone_setup = safe_init(
            "DroneSetup",
            lambda: DroneSetup(params, drone_config),
            led_controller,
            critical=True
        )
        if drone_setup:
            drone_config.drone_setup = drone_setup

        # Optionally, start the PosIDAutoDetector if auto-detection is enabled
        if params.auto_detection_enabled:
            global pos_id_auto_detector
            pos_id_auto_detector = safe_init(
                "PosIDAutoDetector",
                lambda: PosIDAutoDetector(drone_config, params, api_server),
                led_controller,
                critical=False  # Non-critical
            )
            if pos_id_auto_detector:
                pos_id_auto_detector.start()
        else:
            logger.info("PosIDAutoDetector is disabled via parameters.")

        # Startup complete - set LED to indicate ready state
        _startup_state = StartupState.READY
        if led_controller:
            led_controller.set_color(*LEDColors.STARTUP_COMPLETE)  # White flash
            time.sleep(0.5)  # Brief flash
            led_controller.set_color(*LEDColors.IDLE_CONNECTED)  # Green

        logger.info("=" * 60)
        logger.info("Coordinator startup complete - entering main loop")
        logger.info("=" * 60)

        # Enter the main application loop
        main_loop()

    except StartupError as e:
        logger.critical(f"Startup failed: {e}")
        if led_controller:
            led_controller.set_color(*LEDColors.ERROR)
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Unexpected error during startup: {e}", exc_info=True)
        if led_controller:
            led_controller.set_color(*LEDColors.ERROR)
        sys.exit(1)

if __name__ == "__main__":
    main()
