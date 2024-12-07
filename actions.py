#!/usr/bin/env python3
"""
actions.py - Drone Action Executor

This script allows for executing various actions on a drone, such as takeoff, land, hold, test, reboot, and update code.
It utilizes MAVSDK for drone communication and provides visual feedback via LEDs.

Usage Examples:
    python actions.py --action takeoff --altitude 20
    python actions.py --action update_code --branch feature-branch
    python actions.py --action update_code  # Update code without specifying a branch
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
from mavsdk import System
from src.led_controller import LEDController
from src.params import Params

# Global return code: 0 for success, 1 for any failure
RETURN_CODE = 0

# =======================
# Configuration Constants
# =======================

GRPC_PORT = Params.DEFAULT_GRPC_PORT
UDP_PORT = Params.mavsdk_port
HW_ID = None  # Will be set by read_hw_id()

# =======================
# Configure Logging
# =======================

logs_directory = os.path.join("logs", "action_logs")
os.makedirs(logs_directory, exist_ok=True)

logger = logging.getLogger("action_logger")
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter(
    fmt='%(asctime)s - %(levelname)s - %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)

log_file = os.path.join(logs_directory, "actions.log")
file_handler = logging.handlers.RotatingFileHandler(
    log_file, maxBytes=10*1024*1024, backupCount=5
)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)

logger.addHandler(console_handler)
logger.addHandler(file_handler)

# =======================
# Helper Functions
# =======================

def check_mavsdk_server_running(port):
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            for conn in proc.net_connections(kind='inet'):
                if conn.laddr.port == port:
                    return True, proc.info['pid']
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False, None

def wait_for_port(port, host='localhost', timeout=10.0):
    start_time = time.time()
    while True:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (ConnectionRefusedError, socket.timeout, OSError) as e:
            logger.debug(f"Waiting for port {port} on {host}: {e}")
            if time.time() - start_time >= timeout:
                return False
            time.sleep(0.1)

def start_mavsdk_server(grpc_port, udp_port):
    is_running, pid = check_mavsdk_server_running(grpc_port)
    if is_running:
        logger.info(f"MAVSDK server already running on port {grpc_port}. Terminating...")
        try:
            psutil.Process(pid).terminate()
            psutil.Process(pid).wait(timeout=5)
            logger.info(f"Terminated existing MAVSDK server with PID: {pid}")
        except psutil.NoSuchProcess:
            logger.warning(f"No process found with PID: {pid} to terminate.")
        except psutil.TimeoutExpired:
            logger.warning(f"Process with PID: {pid} did not terminate gracefully. Killing it.")
            psutil.Process(pid).kill()
            psutil.Process(pid).wait()
            logger.info(f"Killed MAVSDK server with PID: {pid}")

    logger.info(f"Starting MAVSDK server on gRPC port: {grpc_port}, UDP port: {udp_port}")

    mavsdk_server_path = os.path.join(os.getcwd(), "mavsdk_server")

    if not os.path.isfile(mavsdk_server_path):
        logger.error(f"mavsdk_server executable not found at '{mavsdk_server_path}'.")
        global RETURN_CODE
        RETURN_CODE = 1
        sys.exit(1)

    try:
        mavsdk_server = subprocess.Popen(
            [mavsdk_server_path, "-p", str(grpc_port), f"udp://:{udp_port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        asyncio.create_task(log_mavsdk_output(mavsdk_server))

        if not wait_for_port(grpc_port, timeout=10):
            logger.error(f"MAVSDK server did not start listening on port {grpc_port} within timeout.")
            mavsdk_server.terminate()
            RETURN_CODE = 1
            sys.exit(1)

        logger.info("MAVSDK server is now listening on gRPC port.")
        return mavsdk_server
    except FileNotFoundError:
        logger.error("mavsdk_server executable not found. Ensure it's in the current directory.")
        RETURN_CODE = 1
        sys.exit(1)
    except Exception:
        logger.exception("Failed to start MAVSDK server")
        RETURN_CODE = 1
        sys.exit(1)

async def log_mavsdk_output(mavsdk_server):
    try:
        while True:
            line = await asyncio.get_event_loop().run_in_executor(None, mavsdk_server.stdout.readline)
            if not line:
                break
            logger.debug(f"MAVSDK Server: {line.decode().strip()}")
    except Exception:
        logger.exception("Error while reading MAVSDK server stdout")

    try:
        while True:
            line = await asyncio.get_event_loop().run_in_executor(None, mavsdk_server.stderr.readline)
            if not line:
                break
            logger.error(f"MAVSDK Server Error: {line.decode().strip()}")
    except Exception:
        logger.exception("Error while reading MAVSDK server stderr")

def read_hw_id():
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
            logger.error(f"Invalid hardware ID format in file: {filename}. Expected an integer.")
            return None
    else:
        logger.warning("Hardware ID file not found.")
        return None

def read_config(filename=Params.config_csv_name):
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
                    logger.info(f"Drone configuration found: {drone_config}")
                    return drone_config
        logger.warning(f"No matching hardware ID {HW_ID} found in the configuration file.")
    except FileNotFoundError:
        logger.error(f"Config file '{filename}' not found.")
    except Exception:
        logger.exception(f"Error reading config file '{filename}'")
    return None

def stop_mavsdk_server(mavsdk_server):
    try:
        if mavsdk_server and mavsdk_server.poll() is None:  
            logger.info("Stopping MAVSDK server...")
            mavsdk_server.terminate()
            try:
                mavsdk_server.wait(timeout=5)
                logger.info("MAVSDK server terminated gracefully.")
            except subprocess.TimeoutExpired:
                logger.warning("MAVSDK server did not terminate gracefully. Killing it.")
                mavsdk_server.kill()
                mavsdk_server.wait()
                logger.info("MAVSDK server killed forcefully.")
        else:
            logger.debug("MAVSDK server has already terminated.")
    except Exception:
        logger.exception("Error stopping MAVSDK server")

async def set_parameters(drone, parameters):
    for param_name, param_value in parameters.items():
        try:
            logger.info(f"Setting parameter '{param_name}' to {param_value}")
            await drone.param.set_param_int(param_name, param_value)
            logger.info(f"Parameter '{param_name}' set to {param_value} successfully.")
        except Exception:
            global RETURN_CODE
            RETURN_CODE = 1
            logger.exception(f"Failed to set parameter '{param_name}'")

async def perform_action(action, altitude=None, parameters=None, branch=None):
    global RETURN_CODE
    logger.info("Starting to perform action...")

    if action == "update_code":
        await update_code(branch)
        return  # Return after update_code finishes, return_code set if error occurs

    HW_ID = read_hw_id()
    if HW_ID is None:
        logger.error("Hardware ID could not be determined. Exiting...")
        RETURN_CODE = 1
        return

    drone_config = read_config()
    if not drone_config:
        logger.error("Drone configuration not found. Exiting...")
        RETURN_CODE = 1
        return

    grpc_port = GRPC_PORT
    udp_port = UDP_PORT

    logger.info(f"gRPC Port: {grpc_port}, UDP Port: {udp_port}")

    mavsdk_server = start_mavsdk_server(grpc_port, udp_port)
    if mavsdk_server is None:
        logger.error("Failed to start MAVSDK server.")
        RETURN_CODE = 1
        return

    drone = System(mavsdk_server_address="localhost", port=grpc_port)
    logger.info("Attempting to connect to drone...")

    try:
        await drone.connect(system_address=f"udp://:{udp_port}")
    except Exception:
        logger.exception("Failed to connect to MAVSDK server")
        RETURN_CODE = 1
        stop_mavsdk_server(mavsdk_server)
        return

    logger.info("Checking connection state...")
    connected = False
    start_time = time.time()
    timeout = 10  # seconds
    try:
        async for state in drone.core.connection_state():
            if state.is_connected:
                logger.info(f"Drone connected on UDP Port: {udp_port} and gRPC Port: {grpc_port}")
                connected = True
                break
            if time.time() - start_time > timeout:
                logger.error("Timed out waiting for connection to drone.")
                break
    except Exception:
        logger.exception("Error while checking connection state")
        RETURN_CODE = 1
        stop_mavsdk_server(mavsdk_server)
        return

    if not connected:
        logger.error("Could not establish a connection with the drone.")
        RETURN_CODE = 1
        stop_mavsdk_server(mavsdk_server)
        return

    try:
        if parameters:
            await set_parameters(drone, parameters)

        # Perform action
        if action == "takeoff":
            if not await safe_action(takeoff, drone, altitude):
                RETURN_CODE = 1
        elif action == "land":
            if not await safe_action(land, drone):
                RETURN_CODE = 1
        elif action == "return_rtl":
            if not await safe_action(return_rtl, drone):
                RETURN_CODE = 1
        elif action == "hold":
            if not await safe_action(hold, drone):
                RETURN_CODE = 1
        elif action == "kill_terminate":
            if not await safe_action(kill_terminate, drone):
                RETURN_CODE = 1
        elif action == "test":
            if not await safe_action(test, drone):
                RETURN_CODE = 1
        elif action == "reboot_fc":
            if not await safe_action(reboot, drone, fc_flag=True, sys_flag=False):
                RETURN_CODE = 1
        elif action == "reboot_sys":
            if not await safe_action(reboot, drone, fc_flag=False, sys_flag=True):
                RETURN_CODE = 1
        else:
            logger.error(f"Invalid action specified: '{action}'")
            RETURN_CODE = 1
    except Exception:
        logger.exception(f"Error performing action '{action}'")
        RETURN_CODE = 1
    finally:
        stop_mavsdk_server(mavsdk_server)
        logger.info("Action completed.")

async def safe_action(func, *args, **kwargs):
    """
    Wrapper to run an action function and return True on success, False on failure.
    Any exception inside the action will be logged and indicated by return False.
    """
    try:
        await func(*args, **kwargs)
        logger.info(f"Action {func.__name__} completed successfully.")
        return True
    except Exception:
        logger.exception(f"Action {func.__name__} failed.")
        return False

# =======================
# Action Implementations
# =======================

async def takeoff(drone, altitude):
    led_controller = LEDController.get_instance()
    led_controller.set_color(255, 255, 0)  # Yellow
    await asyncio.sleep(0.5)

    await drone.action.set_takeoff_altitude(float(altitude))
    await drone.action.arm()
    led_controller.set_color(255, 255, 255)  # White
    await asyncio.sleep(0.5)
    await drone.action.takeoff()

    for _ in range(3):
        led_controller.set_color(0, 255, 0)  # Green
        await asyncio.sleep(0.2)
        led_controller.turn_off()
        await asyncio.sleep(0.2)
    led_controller.turn_off()

async def land(drone):
    led_controller = LEDController.get_instance()
    led_controller.set_color(255, 255, 0)  # Yellow
    await asyncio.sleep(0.5)

    await drone.action.hold()
    await asyncio.sleep(1)

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

async def return_rtl(drone):
    led_controller = LEDController.get_instance()
    led_controller.set_color(255, 0, 255)
    await asyncio.sleep(0.5)

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

async def kill_terminate(drone):
    led_controller = LEDController.get_instance()
    led_controller.set_color(255, 0, 0)
    await asyncio.sleep(0.2)
    led_controller.set_color(0, 0, 0)
    led_controller.set_color(255, 0, 0)
    await asyncio.sleep(0.2)

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

async def hold(drone):
    led_controller = LEDController.get_instance()
    led_controller.set_color(0, 0, 255)
    await asyncio.sleep(0.5)

    await drone.action.hold()
    led_controller.set_color(0, 0, 255)
    await asyncio.sleep(1)
    led_controller.turn_off()

async def test(drone):
    led_controller = LEDController.get_instance()

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

async def reboot(drone, fc_flag, sys_flag, force_reboot=True):
    led_controller = LEDController.get_instance()
    led_controller.set_color(255, 255, 0)
    await asyncio.sleep(0.5)

    if fc_flag:
        await drone.action.reboot()
        for _ in range(3):
            led_controller.set_color(0, 255, 0)
            await asyncio.sleep(0.2)
            led_controller.turn_off()
            await asyncio.sleep(0.2)
        logger.info("Flight controller reboot successful.")

    if sys_flag:
        logger.info("Initiating system reboot...")
        led_controller.turn_off()
        await reboot_system()

    led_controller.turn_off()

async def reboot_system():
    process = await asyncio.create_subprocess_exec(
        'dbus-send', '--system', '--print-reply', '--dest=org.freedesktop.login1',
        '/org/freedesktop/login1', 'org.freedesktop.login1.Manager.Reboot', 'boolean:true',
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        logger.error(f"System reboot via D-Bus failed: {stderr.decode().strip()}")
    else:
        logger.info("System reboot command executed successfully via D-Bus.")

async def update_code(branch=None):
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
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error(f"Update script failed: {stderr.decode().strip()}")
            RETURN_CODE = 1
            for _ in range(3):
                led_controller.set_color(255, 0, 0)
                await asyncio.sleep(0.2)
                led_controller.turn_off()
                await asyncio.sleep(0.2)
        else:
            logger.info(f"Update script executed successfully: {stdout.decode().strip()}")
            for _ in range(3):
                led_controller.set_color(0, 255, 0)
                await asyncio.sleep(0.2)
    except Exception:
        logger.exception("Update code action failed")
        RETURN_CODE = 1
        for _ in range(3):
            led_controller.set_color(255, 0, 0)
            await asyncio.sleep(0.2)
            led_controller.turn_off()
            await asyncio.sleep(0.2)
    finally:
        led_controller.turn_off()

# =======================
# Entry Point
# =======================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Perform actions with drones.")
    parser.add_argument('--action', type=str, required=True,
                        help='Action: takeoff, land, hold, test, reboot_fc, reboot_sys, update_code, return_rtl, kill_terminate')
    parser.add_argument('--altitude', type=float, default=10,
                        help='Altitude for takeoff')
    parser.add_argument('--param', action='append', nargs=2, metavar=('param_name', 'param_value'),
                        help='Set parameters in the form param_name param_value')
    parser.add_argument('--branch', type=str, help='Branch name for code update')

    args = parser.parse_args()
    parameters = {param[0]: int(param[1]) for param in args.param} if args.param else None

    try:
        asyncio.run(perform_action(args.action, args.altitude, parameters, args.branch))
    except Exception:
        logger.exception("An unexpected error occurred")
        RETURN_CODE = 1
    finally:
        logger.info("Operation completed.")
        sys.exit(RETURN_CODE)
