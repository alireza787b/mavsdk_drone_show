#!/usr/bin/env python3
"""
===============================================================
Drone Action Executor with MAVSDK - Multi-Parameter Setting
---------------------------------------------------------------
Usage Examples:
---------------
1) Take off with altitude 15 and set multiple PX4 parameters:
   python3 actions.py --action takeoff --altitude 15 \
       --param MAV_SYS_ID 4 \
       --param MPC_XY_CRUISE 8

2) Land without setting any parameters:
   python3 actions.py --action land

3) Update code from a specific branch (e.g., "new_feature_branch"):
   python3 actions.py --action update_code --branch new_feature_branch

4) Set only parameters (no flight action). If you want to just set parameters,
   you can still pick an action (like "hold") or any other valid action to
   ensure the script runs, but supply all your desired parameters:
   python3 actions.py --action hold \
       --param MAV_SYS_ID 6 \
       --param MPC_XY_VEL_MAX 10 \
       --param MIS_TAKEOFF_ALT 5

5) Initialize the system ID automatically from the detected hardware ID
   and reboot the flight controller:
   python3 actions.py --action init_sysid

6) Apply common parameters from 'common_params.csv' in the project root folder:
   python3 actions.py --action apply_common_params
   (Optionally add --reboot_after to reboot the flight controller right after)

Description:
------------
This script executes various drone actions using MAVSDK:
 - takeoff, land, hold, test, reboot, kill_terminate, update_code,
   return_rtl, init_sysid, apply_common_params, etc.
 - Safely manages MAVSDK server launch/teardown.
 - Provides logging, exit codes, LED status feedback, and robust error handling.
 - Supports setting multiple PX4 parameters in a single run via repeated --param.
 - Supports automatically setting MAV_SYS_ID based on a local .hwID file with 'init_sysid'.
 - Now supports applying a shared set of parameters stored in a 'common_params.csv' file
   via the 'apply_common_params' action.

---------------------------------------------------------------
"""

import argparse
import asyncio
import csv
import os
import requests
import socket
import subprocess
import sys
import time

import psutil
from mavsdk import System, telemetry, action
from mavsdk.action import ActionError
from src.drone_config import ConfigLoader
from src.flight_timeout_utils import calculate_land_disarm_timeout, calculate_rtl_completion_timeout
from src.led_controller import LEDController
from src.params import Params

# Unified logging system
from mds_logging.drone import init_drone_logging
from mds_logging import get_logger, register_component

register_component("actions", "drone", "Drone action execution")
init_drone_logging()
logger = get_logger("actions")

# Return codes: 0 = success, 1 = failure
RETURN_CODE = 0

GRPC_PORT = Params.DEFAULT_GRPC_PORT
UDP_PORT = Params.mavsdk_port
HW_ID = None

# -----------------------
# Helper / Setup Functions
# -----------------------

def fail():
    """
    Sets the return code to 1 indicating failure.
    """
    global RETURN_CODE
    RETURN_CODE = 1

def check_mavsdk_server_running(port):
    """
    Checks if a mavsdk_server process is already running on the specified port.
    Returns (bool, pid).
    """
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            for conn in proc.net_connections(kind='inet'):
                if conn.laddr.port == port:
                    return True, proc.info['pid']
        except Exception:
            pass
    return False, None

def wait_for_port(port, host='localhost', timeout=10.0):
    """
    Waits until a port on the specified host is open, or until timeout is reached.
    Returns True if open, False otherwise.
    """
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            time.sleep(0.2)
    return False

async def log_mavsdk_output(mavsdk_server):
    """
    Asynchronously reads MAVSDK server's stdout/stderr for logging.
    Filters known cleanup messages that appear during normal server shutdown.
    """
    # Known non-error messages that appear during normal MAVSDK cleanup
    CLEANUP_PATTERNS = [
        "Socket closed",
        "connection reset",
        "Broken pipe",
        "Connection refused",
        "EOF",
    ]

    loop = asyncio.get_event_loop()
    try:
        while True:
            line = await loop.run_in_executor(None, mavsdk_server.stdout.readline)
            if not line:
                break
            logger.debug(f"MAVSDK Server: {line.decode().strip()}")
    except Exception:
        logger.exception("Error reading MAVSDK server stdout")

    try:
        while True:
            line = await loop.run_in_executor(None, mavsdk_server.stderr.readline)
            if not line:
                break
            msg = line.decode().strip()
            # Check if this is a known cleanup message (not a real error)
            if any(pattern.lower() in msg.lower() for pattern in CLEANUP_PATTERNS):
                logger.debug(f"MAVSDK cleanup: {msg}")
            else:
                logger.error(f"MAVSDK Server Error: {msg}")
    except Exception:
        logger.exception("Error reading MAVSDK server stderr")

def stop_mavsdk_server(mavsdk_server):
    """
    Gracefully stops the MAVSDK server if it's still running.
    """
    if mavsdk_server and mavsdk_server.poll() is None:
        logger.info("Stopping MAVSDK server...")
        mavsdk_server.terminate()
        try:
            mavsdk_server.wait(timeout=5)
            logger.info("MAVSDK server terminated gracefully.")
        except subprocess.TimeoutExpired:
            logger.warning("MAVSDK server did not terminate. Killing it.")
            mavsdk_server.kill()
            mavsdk_server.wait()
            logger.info("MAVSDK server killed.")
    else:
        logger.debug("MAVSDK server already stopped or never started.")

def find_mavsdk_server():
    """
    Finds the path to the mavsdk_server binary.
    Priority:
    1. MAVSDK_SERVER_PATH environment variable.
    2. Current script directory (relative to __file__).
    3. Default fallback directory: project root.
    """
    # 1. Check environment variable
    mavsdk_server_path = os.environ.get("MAVSDK_SERVER_PATH")
    if mavsdk_server_path and os.path.isfile(mavsdk_server_path):
        return mavsdk_server_path

    # 2. Check script directory (relative to __file__)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    mavsdk_server_path = os.path.join(script_dir, "mavsdk_server")
    if os.path.isfile(mavsdk_server_path):
        return mavsdk_server_path

    # 3. Check fallback directory (project root)
    fallback_path = os.path.join(script_dir, "..", "mavsdk_server")
    if os.path.isfile(fallback_path):
        return fallback_path

    return None

def start_mavsdk_server(grpc_port, udp_port):
    """
    Starts or restarts the MAVSDK server, ensuring any previously running server
    on the same gRPC port is stopped first. Returns the subprocess.Popen instance.
    """
    is_running, pid = check_mavsdk_server_running(grpc_port)
    if is_running:
        logger.info(f"MAVSDK server already running on port {grpc_port}, terminating it.")
        try:
            psutil.Process(pid).terminate()
            psutil.Process(pid).wait(timeout=5)
            logger.info(f"Terminated existing MAVSDK server (PID: {pid}).")
        except psutil.NoSuchProcess:
            logger.warning(f"No process found with PID {pid}.")
        except psutil.TimeoutExpired:
            logger.warning(f"Process {pid} did not terminate, killing it.")
            psutil.Process(pid).kill()
            psutil.Process(pid).wait()
            logger.info(f"Killed MAVSDK server (PID: {pid}).")

    mavsdk_server_path = find_mavsdk_server()
    if not mavsdk_server_path:
        logger.error("mavsdk_server executable not found.")
        fail()
        sys.exit(1)

    logger.info(f"Starting MAVSDK server: {mavsdk_server_path} on gRPC:{grpc_port}, UDP:{udp_port}")
    try:
        mavsdk_server = subprocess.Popen(
            [mavsdk_server_path, "-p", str(grpc_port), f"udp://:{udp_port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        asyncio.create_task(log_mavsdk_output(mavsdk_server))

        if not wait_for_port(grpc_port, timeout=10):
            logger.error("MAVSDK server did not start listening in time.")
            mavsdk_server.terminate()
            fail()
            sys.exit(1)

        logger.info("MAVSDK server ready.")
        return mavsdk_server
    except Exception:
        logger.exception("Failed to start MAVSDK server")
        fail()
        sys.exit(1)


# -----------------------
# Core Action Execution
# -----------------------

async def perform_action(action, altitude=None, parameters=None, branch=None, reboot_after=False):
    """
    Main entry to perform the requested action with optional altitude/parameters/branch, plus
    an optional reboot_after boolean for certain actions like apply_common_params.
    """
    logger.info(f"Requested action: {action}, altitude: {altitude}, parameters: {parameters}, "
                f"branch: {branch}, reboot_after: {reboot_after}")
    global HW_ID

    # Special case: code update
    if action == "update_code":
        await update_code(branch)
        return

    # For init_sysid, we do need a valid HW_ID. That is checked later in init_sysid logic.
    # For apply_common_params or normal flight actions, we also read HW_ID for consistency.
    HW_ID = ConfigLoader.get_hw_id()

    if action not in ["init_sysid", "update_code"]:
        # For normal flight actions (and apply_common_params), we also read config
        if HW_ID is None:
            logger.error("No valid HW_ID found, cannot proceed.")
            fail()
            return

        drone_config = ConfigLoader.read_config(HW_ID)  # Returns raw CSV row dict (keys: hw_id, pos_id, ip, mavlink_port, serial_port, baudrate)
        if not drone_config:
            logger.error("Drone config not found, cannot proceed.")
            fail()
            return

    # Start MAVSDK if not just "update_code" (that doesn't need flight connect).
    grpc_port = GRPC_PORT
    udp_port = UDP_PORT
    logger.info(f"MAVSDK: gRPC Port: {grpc_port}, UDP Port: {udp_port}")

    mavsdk_server = start_mavsdk_server(grpc_port, udp_port)
    if not mavsdk_server:
        logger.error("Failed to start MAVSDK server.")
        fail()
        return

    drone = System(mavsdk_server_address="localhost", port=grpc_port)
    logger.info("Connecting to drone...")
    try:
        await drone.connect(system_address=f"udp://:{udp_port}")
    except Exception:
        logger.exception("Failed to connect to MAVSDK server")
        fail()
        stop_mavsdk_server(mavsdk_server)
        return

    # Wait for connection
    if not await wait_for_drone_connection(drone):
        logger.error("Drone not connected in time.")
        fail()
        stop_mavsdk_server(mavsdk_server)
        return

    # Set parameters if provided via CLI
    if parameters:
        await set_parameters(drone, parameters)

    # Execute the requested action safely
    try:
        if action == "takeoff":
            if not await safe_action(takeoff, drone, altitude):
                fail()
        elif action == "land":
            if not await safe_action(land, drone):
                fail()
        elif action == "return_rtl":
            if not await safe_action(return_rtl, drone):
                fail()
        elif action == "hold":
            if not await safe_action(hold, drone):
                fail()
        elif action == "kill_terminate":
            if not await safe_action(kill_terminate, drone):
                fail()
        elif action == "test":
            if not await safe_action(test, drone):
                fail()
        elif action == "reboot_fc":
            if not await safe_action(reboot, drone, fc_flag=True, sys_flag=False):
                fail()
        elif action == "reboot_sys":
            if not await safe_action(reboot, drone, fc_flag=False, sys_flag=True):
                fail()
        elif action == "init_sysid":
            # automatically set MAV_SYS_ID from HW_ID, then reboot FC
            if not await safe_action(init_sysid, drone):
                fail()
        elif action == "apply_common_params":
            if not await safe_action(apply_common_params, drone, reboot_after):
                fail()
        else:
            logger.error(f"Invalid action specified: {action}")
            fail()
    except Exception:
        logger.exception(f"Error performing action '{action}'")
        fail()
    finally:
        stop_mavsdk_server(mavsdk_server)
        logger.info("Action completed.")

async def wait_for_drone_connection(drone, timeout=10):
    """
    Waits up to 'timeout' seconds for drone connection.
    Returns True if connected, else False.
    """
    logger.info("Waiting for drone connection state...")
    start = time.time()
    async for state in drone.core.connection_state():
        if state.is_connected:
            logger.info("Drone connected successfully.")
            return True
        if time.time() - start > timeout:
            return False
        await asyncio.sleep(0.5)


async def wait_for_telemetry_condition(stream_factory, predicate, description, timeout=20):
    """
    Wait until a MAVSDK telemetry stream satisfies a predicate.

    This keeps action completion aligned with actual vehicle state changes
    instead of treating MAVSDK RPC acceptance as the terminal success signal.
    """
    deadline = time.monotonic() + timeout
    async for sample in stream_factory():
        if predicate(sample):
            logger.info(f"{description} confirmed.")
            return sample
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Timed out waiting for {description}")


def _get_local_drone_state_snapshot(timeout: float = 1.0):
    """Read the local drone API state as a fallback readiness signal for this container."""
    try:
        response = requests.get(
            f"http://127.0.0.1:{Params.drone_api_port}/get_drone_state",
            timeout=timeout,
        )
        if response.status_code == 200:
            return response.json()
    except requests.RequestException:
        return None
    return None


def _get_local_home_position_snapshot(timeout: float = 1.0):
    """Read the local drone API home position as a fallback altitude reference."""
    try:
        response = requests.get(
            f"http://127.0.0.1:{Params.drone_api_port}/{Params.get_drone_home_URI}",
            timeout=timeout,
        )
        if response.status_code == 200:
            return response.json()
    except requests.RequestException:
        return None
    return None


def _get_local_relative_altitude_snapshot(timeout: float = 1.0):
    """Derive relative altitude from the local drone API when MAVSDK telemetry lags."""
    drone_state = _get_local_drone_state_snapshot(timeout=timeout)
    home_position = _get_local_home_position_snapshot(timeout=timeout)
    if not drone_state or not home_position:
        return None

    try:
        current_altitude = float(drone_state.get("position_alt"))
        home_altitude = float(home_position.get("altitude"))
    except (TypeError, ValueError):
        return None

    return current_altitude - home_altitude


async def _get_current_relative_altitude(drone, timeout: float = 3.0):
    """Capture the current relative altitude, preferring the local API snapshot."""
    local_relative_altitude = _get_local_relative_altitude_snapshot(timeout=1.0)
    if local_relative_altitude is not None:
        return local_relative_altitude

    deadline = time.monotonic() + timeout
    position_stream = drone.telemetry.position()
    while time.monotonic() < deadline:
        try:
            position = await asyncio.wait_for(anext(position_stream), timeout=max(0.1, deadline - time.monotonic()))
        except (StopAsyncIteration, TimeoutError, asyncio.TimeoutError):
            break
        return getattr(position, "relative_altitude_m", None)
    return None


async def _get_current_landed_state(drone, timeout: float = 3.0):
    """Read the current landed state without treating the read as a logged milestone."""
    deadline = time.monotonic() + timeout
    landed_state_stream = drone.telemetry.landed_state()
    while time.monotonic() < deadline:
        try:
            return await asyncio.wait_for(anext(landed_state_stream), timeout=max(0.1, deadline - time.monotonic()))
        except (StopAsyncIteration, TimeoutError, asyncio.TimeoutError):
            break
    return None


async def wait_until_armed_state(drone, expected: bool, timeout=15):
    state_label = "armed" if expected else "disarmed"
    return await wait_for_telemetry_condition(
        drone.telemetry.armed,
        lambda armed: armed is expected,
        f"vehicle to become {state_label}",
        timeout=timeout,
    )


async def wait_until_landed_state(drone, expected_states, description, timeout=20):
    expected_states = set(expected_states)
    return await wait_for_telemetry_condition(
        drone.telemetry.landed_state,
        lambda state: state in expected_states,
        description,
        timeout=timeout,
    )


async def wait_until_flight_mode(drone, expected_mode, timeout=15):
    return await wait_for_telemetry_condition(
        drone.telemetry.flight_mode,
        lambda mode: mode == expected_mode,
        f"flight mode {expected_mode.name}",
        timeout=timeout,
    )


async def wait_until_relative_altitude(drone, minimum_relative_altitude_m: float, timeout=30):
    try:
        return await wait_for_telemetry_condition(
            drone.telemetry.position,
            lambda position: position.relative_altitude_m >= minimum_relative_altitude_m,
            f"relative altitude >= {minimum_relative_altitude_m:.1f}m",
            timeout=timeout,
        )
    except TimeoutError:
        local_relative_altitude = _get_local_relative_altitude_snapshot(timeout=1.0)
        if (
            local_relative_altitude is not None
            and local_relative_altitude >= minimum_relative_altitude_m
        ):
            logger.warning(
                "Relative altitude confirmed via local drone API fallback: %.2fm >= %.2fm",
                local_relative_altitude,
                minimum_relative_altitude_m,
            )
            return local_relative_altitude
        raise

async def safe_action(func, *args, **kwargs):
    """
    Wraps an action function with exception handling.
    Logs start/end, returns True if success, False if failure.
    """
    action_name = func.__name__
    logger.info(f"Starting action: {action_name}")
    try:
        await func(*args, **kwargs)
        logger.info(f"Action {action_name} completed successfully.")
        return True
    except ActionError as ae:
        logger.error(f"Action {action_name} failed with ActionError: {ae}")
        return False
    except Exception:
        logger.exception(f"Action {action_name} failed with an unexpected error.")
        return False

# Mapping of parameter names to their expected types
PARAM_TYPES = {
    "COM_RCL_EXCEPT": "int",
    "GF_ACTION": "int",
    "GF_MAX_HOR_DIST": "float",
    "GF_MAX_VER_DIST": "float",
}

def parse_param_value(raw_value, param_name):
    """
    Parses the raw parameter value string into the correct type based on the
    expected type for the parameter as defined in PARAM_TYPES.
    """
    expected_type = PARAM_TYPES.get(param_name)
    try:
        if expected_type == "int":
            return int(raw_value), "int"
        elif expected_type == "float":
            return float(raw_value), "float"
        else:
            # Fallback: if no mapping exists, try guessing based on a decimal point.
            if '.' in raw_value:
                return float(raw_value), "float"
            else:
                return int(raw_value), "int"
    except ValueError as e:
        logger.error(f"Failed to parse value '{raw_value}' for parameter '{param_name}' with expected type '{expected_type}'")
        raise e

async def set_parameters(drone, parameters):
    """
    Sets multiple parameters on the drone using MAVSDK's param interface.
    The `parameters` dict should be {param_name: param_value_str}.
    """
    for param_name, raw_value in parameters.items():
        try:
            param_value, param_type = parse_param_value(raw_value, param_name)
            logger.info(f"Setting param '{param_name}' to {param_value} (type: {param_type})")
            if param_type == "int":
                await drone.param.set_param_int(param_name, param_value)
            elif param_type == "float":
                await drone.param.set_param_float(param_name, param_value)
            else:
                raise ValueError(f"Unsupported parameter type for {param_name}")
            logger.info(f"Param '{param_name}' set successfully.")
        except Exception as e:
            logger.exception(f"Failed to set param '{param_name}': {e}")
            fail()  # Assuming fail() handles the error as per your project's conventions

async def apply_common_params(drone, reboot_after=False):
    """
    Reads a 'common_params.csv' file from the project root, applies each parameter to
    the drone, and optionally reboots the flight controller.
    
    The expected CSV format is:
      param_name,param_value
    Example:
      COM_RCL_EXCEPT,7
      GF_ACTION,3
      GF_MAX_HOR_DIST,3000
      GF_MAX_VER_DIST,120
    """
    led_controller = LEDController.get_instance()
    common_file = 'common_params.csv'

    # Indicate start with a distinct LED color (e.g., magenta)
    led_controller.set_color(255, 0, 255)
    await asyncio.sleep(0.5)

    if not os.path.isfile(common_file):
        logger.error(f"Common parameter file '{common_file}' not found.")
        fail()
        return

    logger.info(f"Loading common parameters from {common_file} ...")
    try:
        common_params = {}
        with open(common_file, newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                param_name = row['param_name'].strip()
                param_value = row['param_value'].strip()
                common_params[param_name] = param_value

        logger.info(f"Found {len(common_params)} common parameters. Applying now...")
        await set_parameters(drone, common_params)

        # Blink green a few times for success feedback
        for _ in range(3):
            led_controller.set_color(0, 255, 0)
            await asyncio.sleep(0.2)
            led_controller.turn_off()
            await asyncio.sleep(0.2)

        if reboot_after:
            logger.info("Rebooting flight controller as requested...")
            await drone.action.reboot()
            led_controller.set_color(255, 255, 0)
            await asyncio.sleep(1.0)

        logger.info("apply_common_params action completed successfully.")
    except Exception:
        logger.exception("Error applying common parameters")
        fail()
    finally:
        led_controller.turn_off()

# -----------------------
# Action Implementations
# -----------------------

async def ensure_ready_for_flight(drone, timeout: float | None = None):
    """
    Before takeoff, ensure the drone is healthy, global position is good,
    and home position is set.
    """
    preflight_timeout = float(timeout or getattr(Params, "TAKEOFF_PREFLIGHT_TIMEOUT_SEC", 30))
    logger.info("Checking preflight conditions...")
    start = time.monotonic()
    gps_ok = False
    home_ok = False
    last_reported_state = None
    async for health in drone.telemetry.health():
        if health.is_global_position_ok:
            gps_ok = True
        if health.is_home_position_ok:
            home_ok = True

        local_state = _get_local_drone_state_snapshot()
        local_home_ok = bool(local_state and local_state.get("home_position_set"))
        if local_home_ok:
            home_ok = True

        home_source = "mavsdk" if health.is_home_position_ok else ("drone_api" if local_home_ok else "pending")
        current_state = (gps_ok, home_ok, home_source)
        if current_state != last_reported_state:
            logger.info(
                "Preflight health update: gps_ok=%s, home_ok=%s, home_source=%s, elapsed=%.1fs/%.1fs",
                gps_ok,
                home_ok,
                home_source,
                time.monotonic() - start,
                preflight_timeout,
            )
            last_reported_state = current_state
        if gps_ok and home_ok:
            logger.info("Preflight checks passed: GPS and Home position are good.")
            return True
        if time.monotonic() - start > preflight_timeout:
            logger.error(
                "Preflight checks timed out. GPS or Home not ready (gps_ok=%s, home_ok=%s, timeout=%.1fs).",
                gps_ok,
                home_ok,
                preflight_timeout,
            )
            return False
        await asyncio.sleep(1)

async def takeoff(drone, altitude):
    """
    Arms and takes off to the specified altitude (in meters).
    """
    led_controller = LEDController.get_instance()
    # Check preflight conditions
    if not await ensure_ready_for_flight(drone):
        raise Exception("Preflight conditions not met (GPS/Home)")

    # Try arming
    try:
        target_altitude = float(altitude)
        led_controller.set_color(255, 255, 0)  # Yellow: starting
        await asyncio.sleep(0.5)
        await drone.action.set_takeoff_altitude(target_altitude)
        await drone.action.arm()
        await wait_until_armed_state(drone, True, timeout=10)
        led_controller.set_color(255, 255, 255)  # White: armed
        await asyncio.sleep(0.5)
        await drone.action.takeoff()
        await wait_until_landed_state(
            drone,
            {telemetry.LandedState.TAKING_OFF, telemetry.LandedState.IN_AIR},
            "takeoff state transition",
            timeout=15,
        )
        minimum_altitude = max(1.5, min(target_altitude - 0.5, target_altitude * 0.8))
        await wait_until_relative_altitude(
            drone,
            minimum_altitude,
            timeout=Params.TAKEOFF_ALTITUDE_CONFIRM_TIMEOUT_SEC,
        )
    except ActionError as e:
        logger.error(f"Failed to take off: {e}")
        raise
    except Exception:
        logger.exception("Unexpected error during takeoff")
        raise

    # Indicate success with green blinks
    for _ in range(3):
        led_controller.set_color(0, 255, 0)
        await asyncio.sleep(0.2)
        led_controller.turn_off()
        await asyncio.sleep(0.2)
    led_controller.turn_off()
    logger.info("Takeoff successful.")

async def land(drone):
    """
    Commands the drone to land safely.
    """
    led_controller = LEDController.get_instance()
    led_controller.set_color(255, 255, 0)  # Yellow
    await asyncio.sleep(0.5)

    try:
        await drone.action.hold()
        await wait_until_flight_mode(drone, telemetry.FlightMode.HOLD, timeout=10)
        await asyncio.sleep(1)

        # Indicate landing in progress (blue pulses)
        for _ in range(3):
            led_controller.set_color(0, 0, 255)
            await asyncio.sleep(0.5)
            led_controller.turn_off()
            await asyncio.sleep(0.5)

        await drone.action.land()
        await wait_until_landed_state(
            drone,
            {telemetry.LandedState.LANDING, telemetry.LandedState.ON_GROUND},
            "landing state transition",
            timeout=15,
        )

        relative_altitude = await _get_current_relative_altitude(drone)
        disarm_timeout = calculate_land_disarm_timeout(relative_altitude)
        altitude_message = (
            f"{relative_altitude:.1f}m"
            if isinstance(relative_altitude, (int, float))
            else "unknown"
        )
        logger.info(
            "Waiting up to %.0fs for landing disarm confirmation (relative altitude: %s).",
            disarm_timeout,
            altitude_message,
        )

        try:
            await wait_until_armed_state(drone, False, timeout=disarm_timeout)
        except TimeoutError:
            landed_state = await _get_current_landed_state(drone)
            if landed_state == telemetry.LandedState.ON_GROUND:
                touchdown_grace = int(getattr(Params, "LAND_ACTION_TOUCHDOWN_DISARM_GRACE_SEC", 20))
                logger.warning(
                    "Drone is on ground but still armed after %.0fs; issuing explicit disarm and waiting %.0fs more.",
                    disarm_timeout,
                    touchdown_grace,
                )
                await drone.action.disarm()
                await wait_until_armed_state(drone, False, timeout=touchdown_grace)
            else:
                raise

        for _ in range(3):
            led_controller.set_color(0, 255, 0)
            await asyncio.sleep(0.2)
            led_controller.turn_off()
            await asyncio.sleep(0.2)
        led_controller.turn_off()
        logger.info("Landing successful.")
    except ActionError as e:
        logger.error(f"Landing failed: {e}")
        raise
    except Exception:
        logger.exception("Unexpected error during landing")
        raise

async def return_rtl(drone):
    """
    Commands the drone to return to launch (home) position.
    """
    led_controller = LEDController.get_instance()
    led_controller.set_color(255, 0, 255)  # Purple start
    await asyncio.sleep(0.5)

    try:
        await drone.action.hold()
        await wait_until_flight_mode(drone, telemetry.FlightMode.HOLD, timeout=10)
        await asyncio.sleep(1)

        for _ in range(3):
            led_controller.set_color(0, 0, 255)
            await asyncio.sleep(0.5)
            led_controller.turn_off()
            await asyncio.sleep(0.5)

        await drone.action.return_to_launch()
        await wait_until_flight_mode(drone, telemetry.FlightMode.RETURN_TO_LAUNCH, timeout=15)

        relative_altitude = await _get_current_relative_altitude(drone)
        completion_timeout = calculate_rtl_completion_timeout(relative_altitude)
        altitude_message = (
            f"{relative_altitude:.1f}m"
            if isinstance(relative_altitude, (int, float))
            else "unknown"
        )
        logger.info(
            "Waiting up to %.0fs for RTL landing/disarm completion (relative altitude: %s).",
            completion_timeout,
            altitude_message,
        )

        try:
            await wait_until_armed_state(drone, False, timeout=completion_timeout)
        except TimeoutError:
            landed_state = await _get_current_landed_state(drone)
            if landed_state == telemetry.LandedState.ON_GROUND:
                touchdown_grace = int(getattr(Params, "LAND_ACTION_TOUCHDOWN_DISARM_GRACE_SEC", 20))
                logger.warning(
                    "Drone reached the ground during RTL but stayed armed after %.0fs; issuing explicit disarm and waiting %.0fs more.",
                    completion_timeout,
                    touchdown_grace,
                )
                await drone.action.disarm()
                await wait_until_armed_state(drone, False, timeout=touchdown_grace)
            else:
                raise

        for _ in range(3):
            led_controller.set_color(0, 255, 0)
            await asyncio.sleep(0.2)
            led_controller.turn_off()
            await asyncio.sleep(0.2)
        led_controller.turn_off()
        logger.info("RTL successful.")
    except ActionError as e:
        logger.error(f"RTL failed: {e}")
        raise
    except Exception:
        logger.exception("Unexpected error during RTL")
        raise

async def kill_terminate(drone):
    """
    Immediately terminates the drone (emergency kill).
    """
    led_controller = LEDController.get_instance()
    led_controller.set_color(255, 0, 0)
    await asyncio.sleep(0.2)
    led_controller.set_color(0, 0, 0)
    led_controller.set_color(255, 0, 0)
    await asyncio.sleep(0.2)

    try:
        await drone.action.terminate()
        await wait_until_armed_state(drone, False, timeout=10)
        for _ in range(3):
            led_controller.set_color(0, 255, 0)
            await asyncio.sleep(0.2)
            led_controller.turn_off()
            await asyncio.sleep(0.2)
        led_controller.turn_off()
        await asyncio.sleep(0.2)
        led_controller.set_color(255, 0, 0)
        logger.info("Kill and Terminate successful.")
    except ActionError as e:
        logger.error(f"Kill terminate failed: {e}")
        raise
    except Exception:
        logger.exception("Unexpected error during kill terminate")
        raise

async def hold(drone):
    """
    Commands the drone to hold (loiter) at current position.
    """
    led_controller = LEDController.get_instance()
    led_controller.set_color(0, 0, 255)
    await asyncio.sleep(0.5)
    try:
        await drone.action.hold()
        await wait_until_flight_mode(drone, telemetry.FlightMode.HOLD, timeout=10)
        led_controller.set_color(0, 0, 255)
        await asyncio.sleep(1)
        led_controller.turn_off()
        logger.info("Hold successful.")
    except ActionError as e:
        logger.error(f"Hold failed: {e}")
        raise
    except Exception:
        logger.exception("Unexpected error during hold")
        raise

async def test(drone):
    """
    A simple test action to verify connectivity and LED control.
    """
    led_controller = LEDController.get_instance()
    try:
        led_controller.set_color(255, 0, 0)
        await asyncio.sleep(1)
        await drone.action.arm()
        led_controller.set_color(255, 255, 255)
        await asyncio.sleep(1)
        led_controller.set_color(0, 0, 255)
        await asyncio.sleep(1)
        led_controller.set_color(0, 255, 0)
        await asyncio.sleep(1)
        await drone.action.disarm()
        led_controller.turn_off()
        logger.info("Test action successful.")
    except ActionError as e:
        logger.error(f"Test action failed: {e}")
        raise
    except Exception:
        logger.exception("Unexpected error during test")
        raise

async def reboot(drone, fc_flag, sys_flag, force_reboot=True):
    """
    Reboots flight controller or entire system (Linux-based), or both.
    """
    led_controller = LEDController.get_instance()
    led_controller.set_color(255, 255, 0)
    await asyncio.sleep(0.5)

    try:
        if fc_flag:
            await drone.action.reboot()
            for _ in range(3):
                led_controller.set_color(0, 255, 0)
                await asyncio.sleep(0.2)
                led_controller.turn_off()
                await asyncio.sleep(0.2)
            logger.info("FC reboot successful.")

        if sys_flag:
            logger.info("Initiating system reboot...")
            led_controller.turn_off()
            await reboot_system()

        led_controller.turn_off()
    except ActionError as e:
        logger.error(f"Reboot failed: {e}")
        raise
    except Exception:
        logger.exception("Unexpected error during reboot")
        raise

async def reboot_system():
    """
    Reboots the entire system via D-Bus (for Linux-based OS).
    """
    process = await asyncio.create_subprocess_exec(
        'dbus-send', '--system', '--print-reply', '--dest=org.freedesktop.login1',
        '/org/freedesktop/login1', 'org.freedesktop.login1.Manager.Reboot', 'boolean:true',
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        logger.error(f"System reboot via D-Bus failed: {stderr.decode().strip()}")
    else:
        logger.info("System reboot command executed successfully.")

async def update_code(branch=None):
    """
    Pulls latest code from a git repository (via tools/update_repo_ssh.sh).
    Optionally checks out a specific branch.
    """
    global RETURN_CODE
    led_controller = LEDController.get_instance()
    led_controller.set_color(255, 255, 0)
    await asyncio.sleep(0.5)

    try:
        script_path = os.path.join('tools', 'update_repo_ssh.sh')
        command = [script_path]
        if branch:
            command.extend(['--branch', branch])
        logger.info(f"Executing update script: {' '.join(command)}")

        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            stderr_text = stderr.decode().strip()
            stdout_text = stdout.decode().strip()
            logger.error(f"Update script failed (exit={process.returncode}): {stderr_text}")
            # Parse structured failure result if available
            for line in stdout_text.splitlines():
                if line.startswith("GIT_SYNC_RESULT="):
                    try:
                        import json
                        result = json.loads(line[len("GIT_SYNC_RESULT="):])
                        logger.error(f"Sync failure detail: error={result.get('error')}, "
                                     f"message={result.get('message')}")
                    except Exception:
                        pass
                    break
            fail()
            for _ in range(3):
                led_controller.set_color(255, 0, 0)
                await asyncio.sleep(0.2)
                led_controller.turn_off()
                await asyncio.sleep(0.2)
        else:
            stdout_text = stdout.decode().strip()
            logger.info(f"Update script successful: {stdout_text}")
            # Parse structured result if available
            for line in stdout_text.splitlines():
                if line.startswith("GIT_SYNC_RESULT="):
                    try:
                        import json
                        result = json.loads(line[len("GIT_SYNC_RESULT="):])
                        logger.info(f"Sync result: branch={result.get('branch')}, "
                                    f"commit={result.get('commit')}, "
                                    f"duration={result.get('duration')}s")
                    except (json.JSONDecodeError, Exception) as parse_err:
                        logger.warning(f"Could not parse GIT_SYNC_RESULT: {parse_err}")
                    break
            for _ in range(3):
                led_controller.set_color(0, 255, 0)
                await asyncio.sleep(0.2)
    except Exception:
        logger.exception("Update code action failed")
        fail()
        for _ in range(3):
            led_controller.set_color(255, 0, 0)
            await asyncio.sleep(0.2)
            led_controller.turn_off()
            await asyncio.sleep(0.2)
    finally:
        led_controller.turn_off()

# -----------------------
# Action: init_sysid
# -----------------------

async def init_sysid(drone):
    """
    Automatically set MAV_SYS_ID based on the hardware ID file and
    then reboot the flight controller.
    """
    led_controller = LEDController.get_instance()

    # We rely on the global HW_ID already read in perform_action().
    global HW_ID

    if HW_ID is None:
        raise Exception("HW_ID not found or invalid. Cannot init system ID.")

    logger.info(f"Initializing system ID: MAV_SYS_ID = {HW_ID}")

    try:
        # Indicate start with yellow LED
        led_controller.set_color(255, 255, 0)
        await asyncio.sleep(0.5)

        # TODO(deferred): Decouple hw_id from MAV_SYS_ID for >254 drone support.
        # Currently hw_id == MAV_SYS_ID. MAVLink limits to uint8 (1-254).
        # See docs/TODO_deferred.md #1
        await drone.param.set_param_int("MAV_SYS_ID", HW_ID)
        logger.info("MAV_SYS_ID parameter set successfully.")

        # Reboot FC to make the new system ID take effect
        led_controller.set_color(0, 255, 255)  # Cyan to indicate reboot in progress
        await asyncio.sleep(0.5)

        logger.info("Rebooting flight controller for system ID change...")
        await drone.action.reboot()

        # Blink green a few times for success
        for _ in range(3):
            led_controller.set_color(0, 255, 0)
            await asyncio.sleep(0.2)
            led_controller.turn_off()
            await asyncio.sleep(0.2)

        logger.info("init_sysid action completed successfully.")
    except ActionError as e:
        logger.error(f"init_sysid failed with ActionError: {e}")
        raise
    except Exception:
        logger.exception("Unexpected error during init_sysid")
        raise
    finally:
        led_controller.turn_off()

# -----------------------
# Main Entry Point
# -----------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Perform actions with drones.")
    parser.add_argument('--action',
                        help='Actions: takeoff, land, hold, test, reboot_fc, reboot_sys, update_code, '
                             'return_rtl, kill_terminate, init_sysid, apply_common_params')
    parser.add_argument('--altitude', type=float, default=10.0, help='Altitude (meters) for takeoff')
    parser.add_argument('--param', action='append', nargs=2, metavar=('param_name', 'param_value'),
                        help='Set one or more PX4 parameters, e.g.: --param MPC_XY_CRUISE 5.0 --param MAV_SYS_ID 4')
    parser.add_argument('--branch', type=str, help='Branch name for code update')
    parser.add_argument('--reboot_after', action='store_true',
                        help='If set, certain actions (e.g. apply_common_params) will reboot FC at the end')

    args = parser.parse_args()

    # Convert all param pairs into a dictionary { 'param_name': 'param_value_str', ... }
    parameters = {p[0]: p[1] for p in args.param} if args.param else None

    try:
        asyncio.run(
            perform_action(
                action=args.action,
                altitude=args.altitude,
                parameters=parameters,
                branch=args.branch,
                reboot_after=args.reboot_after
            )
        )
    except Exception:
        logger.exception("An unexpected error occurred in the main block.")
        fail()
    finally:
        logger.info("Operation completed.")
        sys.exit(RETURN_CODE)
