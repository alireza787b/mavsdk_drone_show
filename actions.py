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

Description:
------------
This script executes various drone actions using MAVSDK:
 - takeoff, land, hold, test, reboot, kill_terminate, update_code, etc.
 - Safely manages MAVSDK server launch/teardown.
 - Provides logging, exit codes, LED status feedback, and robust error handling.
 - Supports setting multiple PX4 parameters in a single run via repeated --param.

---------------------------------------------------------------
"""

import argparse
import asyncio
import csv
import glob
import logging
import logging.handlers
import os
import socket
import subprocess
import sys
import time

import psutil
from mavsdk import System, telemetry, action
from mavsdk.action import ActionError
from src.led_controller import LEDController
from src.params import Params

# Return codes: 0 = success, 1 = failure
RETURN_CODE = 0

GRPC_PORT = Params.DEFAULT_GRPC_PORT
UDP_PORT = Params.mavsdk_port
HW_ID = None

# Configure logging
logs_directory = os.path.join("logs", "action_logs")
os.makedirs(logs_directory, exist_ok=True)

logger = logging.getLogger("action_logger")
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s: %(message)s', '%Y-%m-%d %H:%M:%S')

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)

log_file = os.path.join(logs_directory, "actions.log")
file_handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)

logger.addHandler(console_handler)
logger.addHandler(file_handler)

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
    """
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
            logger.error(f"MAVSDK Server Error: {line.decode().strip()}")
    except Exception:
        logger.exception("Error reading MAVSDK server stderr")

def read_hw_id():
    """
    Attempts to read the first *.hwID file in the current directory
    and parse it as an integer hardware ID.
    """
    hwid_files = glob.glob('*.hwID')
    if hwid_files:
        filename = hwid_files[0]
        hw_id_str = os.path.splitext(filename)[0]
        logger.info(f"Hardware ID file detected: {filename}")
        try:
            hw_id = int(hw_id_str)
            logger.info(f"Hardware ID {hw_id} detected.")
            return hw_id
        except ValueError:
            logger.error(f"Invalid hardware ID format in {filename}. Expected an integer.")
            return None
    else:
        logger.warning("No .hwID file found.")
        return None

def read_config(filename=Params.config_csv_name):
    """
    Reads the drone configuration from a CSV file matching the HW_ID.
    Returns a dictionary with drone_config or None if not found/failed.
    """
    global HW_ID
    logger.info("Reading drone configuration...")
    try:
        with open(filename, newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                hw_id = int(row.get('hw_id', -1))
                if hw_id == HW_ID:
                    drone_config = {
                        'hw_id': hw_id,
                        'pos_id': int(row.get('pos_id', -1)),
                        'x': float(row.get('x', 0.0)),
                        'y': float(row.get('y', 0.0)),
                        'ip': row.get('ip', ''),
                        'udp_port': int(row.get('mavlink_port', UDP_PORT)),
                        'grpc_port': int(row.get('debug_port', GRPC_PORT)),
                        'gcs_ip': row.get('gcs_ip', ''),
                    }
                    logger.info(f"Drone configuration: {drone_config}")
                    return drone_config
        logger.warning(f"No matching HW_ID {HW_ID} found in config file.")
    except FileNotFoundError:
        logger.error(f"Config file '{filename}' not found.")
    except Exception:
        logger.exception("Error reading config file")
    return None

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

def start_mavsdk_server(grpc_port, udp_port):
    """
    Starts or restarts the MAVSDK server, ensuring any previously running server on
    the same gRPC port is stopped first. Returns the subprocess.Popen instance.
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

    logger.info(f"Starting MAVSDK server on gRPC:{grpc_port}, UDP:{udp_port}")
    mavsdk_server_path = os.path.join(os.getcwd(), "mavsdk_server")

    if not os.path.isfile(mavsdk_server_path):
        logger.error(f"mavsdk_server not found at '{mavsdk_server_path}'")
        fail()
        sys.exit(1)

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
    except FileNotFoundError:
        logger.error("mavsdk_server executable not found.")
        fail()
        sys.exit(1)
    except Exception:
        logger.exception("Failed to start MAVSDK server")
        fail()
        sys.exit(1)

def parse_param_value(value_str):
    """
    Attempt to parse the string value for a PX4 param as an integer.
    If that fails, parse as float. Raises ValueError if neither works.
    Returns: (value, value_type) -> (int or float, 'int' or 'float')
    """
    try:
        val_int = int(value_str)
        return val_int, 'int'
    except ValueError:
        pass

    try:
        val_float = float(value_str)
        return val_float, 'float'
    except ValueError:
        logger.error(f"Could not parse parameter value '{value_str}' as int or float.")
        raise ValueError(f"Invalid param value: {value_str}")

async def set_parameters(drone, parameters):
    """
    Sets multiple parameters on the drone using MAVSDK's param interface.
    parameters is a dict {param_name: param_value_str}, where param_value_str can be int or float in string form.
    """
    for param_name, raw_value in parameters.items():
        try:
            param_value, param_type = parse_param_value(raw_value)
            logger.info(f"Setting param '{param_name}' to {param_value} (type: {param_type})")

            if param_type == 'int':
                await drone.param.set_param_int(param_name, param_value)
            else:
                await drone.param.set_param_float(param_name, param_value)

            logger.info(f"Param '{param_name}' set successfully.")
        except Exception:
            fail()
            logger.exception(f"Failed to set param '{param_name}'")

# -----------------------
# Core Action Execution
# -----------------------

async def perform_action(action, altitude=None, parameters=None, branch=None):
    """
    Main entry to perform the requested action with optional altitude/parameters/branch.
    """
    logger.info(f"Requested action: {action}, altitude: {altitude}, parameters: {parameters}, branch: {branch}")
    global HW_ID

    # Special case: code update
    if action == "update_code":
        await update_code(branch)
        return

    # Read hardware ID from .hwID file
    HW_ID = read_hw_id()
    if HW_ID is None:
        logger.error("No valid HW_ID found, cannot proceed.")
        fail()
        return

    drone_config = read_config()
    if not drone_config:
        logger.error("Drone config not found, cannot proceed.")
        fail()
        return

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

    # Set parameters if provided
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

async def safe_action(func, *args, **kwargs):
    """
    Wraps an action function with exception handling.
    Logs start/end, returns True if success, False otherwise.
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

# -----------------------
# Action Implementations
# -----------------------

async def ensure_ready_for_flight(drone):
    """
    Before takeoff, ensure the drone is healthy, global position is good,
    and home position is set.
    """
    logger.info("Checking preflight conditions...")
    start = time.time()
    gps_ok = False
    home_ok = False
    async for health in drone.telemetry.health():
        if health.is_global_position_ok:
            gps_ok = True
        if health.is_home_position_ok:
            home_ok = True
        if gps_ok and home_ok:
            logger.info("Preflight checks passed: GPS and Home position are good.")
            return True
        if time.time() - start > 15:
            logger.error("Preflight checks timed out. GPS or Home not ready.")
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
        led_controller.set_color(255, 255, 0)  # Yellow: starting
        await asyncio.sleep(0.5)
        await drone.action.set_takeoff_altitude(float(altitude))
        await drone.action.arm()
        led_controller.set_color(255, 255, 255)  # White: armed
        await asyncio.sleep(0.5)
        await drone.action.takeoff()
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
        await asyncio.sleep(1)

        # Indicate landing in progress (blue pulses)
        for _ in range(3):
            led_controller.set_color(0, 0, 255)
            await asyncio.sleep(0.5)
            led_controller.turn_off()
            await asyncio.sleep(0.5)

        await drone.action.land()

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
        await asyncio.sleep(1)

        for _ in range(3):
            led_controller.set_color(0, 0, 255)
            await asyncio.sleep(0.5)
            led_controller.turn_off()
            await asyncio.sleep(0.5)

        await drone.action.return_to_launch()

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
        await asyncio.sleep(1)
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
            command.append(branch)
        logger.info(f"Executing update script: {' '.join(command)}")

        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error(f"Update script failed: {stderr.decode().strip()}")
            fail()
            for _ in range(3):
                led_controller.set_color(255, 0, 0)
                await asyncio.sleep(0.2)
                led_controller.turn_off()
                await asyncio.sleep(0.2)
        else:
            logger.info(f"Update script successful: {stdout.decode().strip()}")
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
# Main Entry Point
# -----------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Perform actions with drones.")
    parser.add_argument('--action',
                        help='Actions: takeoff, land, hold, test, reboot_fc, reboot_sys, update_code, return_rtl, kill_terminate')
    parser.add_argument('--altitude', type=float, default=10.0, help='Altitude (meters) for takeoff')
    parser.add_argument('--param', action='append', nargs=2, metavar=('param_name', 'param_value'),
                        help='Set one or more PX4 parameters, e.g.: --param MPC_XY_CRUISE 5.0 --param MAV_SYS_ID 4')
    parser.add_argument('--branch', type=str, help='Branch name for code update')

    args = parser.parse_args()

    # Convert all param pairs into a dictionary { 'param_name': 'param_value_str', ... }
    parameters = {p[0]: p[1] for p in args.param} if args.param else None

    try:
        asyncio.run(perform_action(args.action, args.altitude, parameters, args.branch))
    except Exception:
        logger.exception("An unexpected error occurred in the main block.")
        fail()
    finally:
        logger.info("Operation completed.")
        sys.exit(RETURN_CODE)
