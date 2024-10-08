# actions.py
# Usage: python actions.py --action takeoff --altitude 20 --param MAV_SYS_ID 2 --param PARAM2 3

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

# =======================
# Configuration Constants
# =======================

GRPC_PORT = 50040
UDP_PORT = 14540
HW_ID = None  # Will be set by read_hw_id()

# =======================
# Configure Logging
# =======================

# Create logs directory if it doesn't exist
logs_directory = os.path.join("logs", "action_logs")
os.makedirs(logs_directory, exist_ok=True)

# Configure the logger
logger = logging.getLogger("action_logger")
logger.setLevel(logging.DEBUG)

# Create formatter
formatter = logging.Formatter(
    fmt='%(asctime)s - %(levelname)s - %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Create console handler with a higher log level
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)

# Create rotating file handler
log_file = os.path.join(logs_directory, "actions.log")
file_handler = logging.handlers.RotatingFileHandler(
    log_file, maxBytes=10*1024*1024, backupCount=5
)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)

# Add handlers to the logger
logger.addHandler(console_handler)
logger.addHandler(file_handler)

# =======================
# Helper Functions
# =======================

def check_mavsdk_server_running(port):
    """
    Checks if the MAVSDK server is running on the specified gRPC port.

    Args:
        port (int): The gRPC port to check.

    Returns:
        tuple: (is_running (bool), pid (int or None))
    """
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            for conn in proc.connections(kind='inet'):
                if conn.laddr.port == port:
                    return True, proc.info['pid']
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False, None

def wait_for_port(port, host='localhost', timeout=10.0):
    """
    Wait until a port starts accepting TCP connections.

    Args:
        port (int): The port to check.
        host (str): The hostname to check.
        timeout (float): The maximum time to wait in seconds.

    Returns:
        bool: True if the port is open, False if the timeout was reached.
    """
    start_time = time.time()
    while True:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (ConnectionRefusedError, socket.timeout):
            if time.time() - start_time >= timeout:
                return False
            time.sleep(0.1)

def start_mavsdk_server(grpc_port, udp_port):
    """
    Starts the MAVSDK server on the specified gRPC and UDP ports.
    If a server is already running on the gRPC port, it terminates it before starting a new one.

    Args:
        grpc_port (int): The gRPC port for MAVSDK server.
        udp_port (int): The UDP port for MAVSDK server.

    Returns:
        subprocess.Popen: The subprocess running the MAVSDK server.
    """
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
    try:
        mavsdk_server = subprocess.Popen(
            ["./mavsdk_server", "-p", str(grpc_port), f"udp://:{udp_port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # Wait until the server is listening on the gRPC port
        if not wait_for_port(grpc_port, timeout=10):
            logger.error(f"MAVSDK server did not start listening on port {grpc_port} within timeout.")
            mavsdk_server.terminate()
            sys.exit(1)

        logger.info("MAVSDK server is now listening on gRPC port.")
        return mavsdk_server
    except FileNotFoundError:
        logger.error("mavsdk_server executable not found. Ensure it's in the current directory.")
        sys.exit(1)
    except Exception as e:
        logger.exception("Failed to start MAVSDK server")
        sys.exit(1)

def read_hw_id():
    """
    Reads the hardware ID from files with the '.hwID' extension.

    Returns:
        int or None: The hardware ID if found, else None.
    """
    hwid_files = glob.glob('*.hwID')
    if hwid_files:
        filename = hwid_files[0]
        hw_id_str = os.path.splitext(filename)[0]  # Get filename without extension
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

def read_config(filename='config.csv'):
    """
    Reads the drone configuration from a CSV file based on the hardware ID.

    Returns:
        dict or None: The drone configuration if found, else None.
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
                    logger.info(f"Drone configuration found: {drone_config}")
                    return drone_config
        logger.warning(f"No matching hardware ID {HW_ID} found in the configuration file.")
    except FileNotFoundError:
        logger.error(f"Config file '{filename}' not found.")
    except Exception:
        logger.exception(f"Error reading config file '{filename}'")
    return None

def stop_mavsdk_server(mavsdk_server):
    """
    Terminates the MAVSDK server subprocess.

    Args:
        mavsdk_server (subprocess.Popen): The subprocess running the MAVSDK server.
    """
    try:
        if mavsdk_server.poll() is None:  # Process is still running
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
    """
    Sets one or more parameters on the drone.

    Args:
        drone (System): The MAVSDK drone system.
        parameters (dict): Dictionary of parameter names and their integer values.
    """
    for param_name, param_value in parameters.items():
        try:
            logger.info(f"Setting parameter '{param_name}' to {param_value}")
            await drone.param.set_param_int(param_name, param_value)
            logger.info(f"Parameter '{param_name}' set to {param_value} successfully.")
        except Exception:
            logger.exception(f"Failed to set parameter '{param_name}'")

async def perform_action(action, altitude=None, parameters=None):
    """
    Orchestrates the entire action execution process, including starting and stopping the MAVSDK server.

    Args:
        action (str): The action to perform.
        altitude (float, optional): The altitude for takeoff.
        parameters (dict, optional): Parameters to set on the drone.
    """
    logger.info("Starting to perform action...")

    # Retrieve Hardware ID
    global HW_ID
    HW_ID = read_hw_id()
    if HW_ID is None:
        logger.error("Hardware ID could not be determined. Exiting...")
        return

    # Read Drone Configuration
    drone_config = read_config()
    if not drone_config:
        logger.error("Drone configuration not found. Exiting...")
        return

    # Define MAVSDK Ports since its on each system its constant
    grpc_port = GRPC_PORT
    udp_port = UDP_PORT

    logger.info(f"gRPC Port: {grpc_port}, UDP Port: {udp_port}")

    # Start the MAVSDK server
    mavsdk_server = start_mavsdk_server(grpc_port, udp_port)

    # Initialize the MAVSDK drone system
    drone = System(mavsdk_server_address="localhost", port=grpc_port)
    logger.info("Attempting to connect to drone...")

    try:
        await drone.connect(system_address=f"udp://:{udp_port}")
    except Exception:
        logger.exception("Failed to connect to MAVSDK server")
        stop_mavsdk_server(mavsdk_server)
        return

    # Check connection state with a timeout
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
        stop_mavsdk_server(mavsdk_server)
        return

    if not connected:
        logger.error("Could not establish a connection with the drone.")
        stop_mavsdk_server(mavsdk_server)
        return

    try:
        # Set parameters if provided
        if parameters:
            await set_parameters(drone, parameters)

        # Perform action
        if action == "takeoff":
            await takeoff(drone, altitude)
        elif action == "land":
            await land(drone)
        elif action == "hold":
            await hold(drone)
        elif action == "test":
            await test(drone)
        elif action == "reboot_fc":
            await reboot(drone, fc_flag=True, sys_flag=False)
        elif action == "reboot_sys":
            await reboot(drone, fc_flag=False, sys_flag=True)
        else:
            logger.error(f"Invalid action specified: '{action}'")
    except Exception:
        logger.exception(f"Error performing action '{action}'")
    finally:
        stop_mavsdk_server(mavsdk_server)
        logger.info("Action completed.")

# =======================
# Action Implementations
# =======================

async def takeoff(drone, altitude):
    """
    Executes the takeoff action.

    Args:
        drone (System): The MAVSDK drone system.
        altitude (float): The altitude to take off to.
    """
    led_controller = LEDController.get_instance()

    # Indicate takeoff initiation with yellow color
    led_controller.set_color(255, 255, 0)  # Yellow
    await asyncio.sleep(0.5)

    try:
        await drone.action.set_takeoff_altitude(float(altitude))
        await drone.action.arm()

        # Indicate arming with white color
        led_controller.set_color(255, 255, 255)  # White
        await asyncio.sleep(0.5)

        await drone.action.takeoff()

        # Indicate successful takeoff with green blinks
        for _ in range(3):
            led_controller.set_color(0, 255, 0)  # Green
            await asyncio.sleep(0.2)
            led_controller.turn_off()
            await asyncio.sleep(0.2)

        logger.info("Takeoff successful.")
    except Exception:
        logger.exception("Takeoff failed")
        # Indicate takeoff failure with red blinks
        for _ in range(3):
            led_controller.set_color(255, 0, 0)  # Red
            await asyncio.sleep(0.2)
            led_controller.turn_off()
            await asyncio.sleep(0.2)
    finally:
        # Turn off LEDs after feedback
        led_controller.turn_off()

async def land(drone):
    """
    Executes the land action.

    Args:
        drone (System): The MAVSDK drone system.
    """
    led_controller = LEDController.get_instance()

    # Indicate landing initiation with yellow color
    led_controller.set_color(255, 255, 0)  # Yellow
    await asyncio.sleep(0.5)

    try:
        await drone.action.hold()  # Switch to Hold mode
        await asyncio.sleep(1)  # Wait for a short period

        # Indicate landing in progress with blue slow pulse
        for _ in range(3):
            led_controller.set_color(0, 0, 255)  # Blue
            await asyncio.sleep(0.5)
            led_controller.turn_off()
            await asyncio.sleep(0.5)

        await drone.action.land()  # Execute land command

        # Indicate successful landing with green blinks
        for _ in range(3):
            led_controller.set_color(0, 255, 0)  # Green
            await asyncio.sleep(0.2)
            led_controller.turn_off()
            await asyncio.sleep(0.2)

        logger.info("Landing successful.")
    except Exception:
        logger.exception("Landing failed")
        # Indicate landing failure with red blinks
        for _ in range(3):
            led_controller.set_color(255, 0, 0)  # Red
            await asyncio.sleep(0.2)
            led_controller.turn_off()
            await asyncio.sleep(0.2)
    finally:
        # Turn off LEDs after feedback
        led_controller.turn_off()

async def hold(drone):
    """
    Executes the hold position action.

    Args:
        drone (System): The MAVSDK drone system.
    """
    led_controller = LEDController.get_instance()

    # Indicate hold command received with blue color
    led_controller.set_color(0, 0, 255)  # Blue
    await asyncio.sleep(0.5)

    try:
        await drone.action.hold()  # Switch to Hold mode

        # Indicate successful hold with a solid blue color
        led_controller.set_color(0, 0, 255)  # Solid Blue
        await asyncio.sleep(1)

        logger.info("Hold position successful.")
    except Exception:
        logger.exception("Hold failed")
        # Indicate hold failure with red blinks
        for _ in range(3):
            led_controller.set_color(255, 0, 0)  # Red
            await asyncio.sleep(0.2)
            led_controller.turn_off()
            await asyncio.sleep(0.2)
    finally:
        # Turn off LEDs after feedback
        led_controller.turn_off()

async def test(drone):
    """
    Executes the test action, which includes arming and disarming the drone with LED feedback.

    Args:
        drone (System): The MAVSDK drone system.
    """
    led_controller = LEDController.get_instance()

    try:
        # Step 1: Set LEDs to red before attempting to arm
        led_controller.set_color(255, 0, 0)  # Red
        await asyncio.sleep(1)  # Wait to show red color

        # Step 2: Arm the drone
        await drone.action.arm()

        # Indicate arming with white color
        led_controller.set_color(255, 255, 255)  # White
        await asyncio.sleep(1)  # Wait to show white color

        # Step 3: Change LED colors during the 3-second wait
        led_controller.set_color(0, 0, 255)  # Blue
        await asyncio.sleep(1)  # Wait to show blue color

        led_controller.set_color(0, 255, 0)  # Green
        await asyncio.sleep(1)  # Wait to show green color

        # Step 4: Disarm the drone
        await drone.action.disarm()
        logger.info("Test action successful.")

        # Step 5: Turn off LEDs after disarming
        led_controller.turn_off()

    except Exception:
        logger.exception("Test failed")
        # Indicate test failure with red blinks
        for _ in range(3):
            led_controller.set_color(255, 0, 0)  # Red
            await asyncio.sleep(0.2)
            led_controller.turn_off()
            await asyncio.sleep(0.2)
    finally:
        # Ensure LEDs are turned off
        led_controller.turn_off()

async def reboot(drone, fc_flag, sys_flag, force_reboot=True):
    """
    Reboots the flight controller, system, or both, with optional forced reboot.

    Args:
        drone (System): MAVSDK drone system.
        fc_flag (bool): Whether to reboot the flight controller.
        sys_flag (bool): Whether to reboot the Raspberry Pi system.
        force_reboot (bool): Whether to force a system reboot if the initial reboot fails.
    """
    led_controller = LEDController.get_instance()

    # Indicate reboot initiation with yellow color
    led_controller.set_color(255, 255, 0)  # Yellow
    await asyncio.sleep(0.5)  # Brief feedback

    if fc_flag:
        try:
            # Attempt to reboot the flight controller (drone)
            await drone.action.reboot()

            # Indicate success with green blinks
            for _ in range(3):
                led_controller.set_color(0, 255, 0)  # Green
                await asyncio.sleep(0.2)
                led_controller.turn_off()
                await asyncio.sleep(0.2)

            logger.info("Flight controller reboot successful.")
        except Exception:
            logger.exception("Flight controller reboot failed")

            # Indicate failure with red blinks
            for _ in range(3):
                led_controller.set_color(255, 0, 0)  # Red
                await asyncio.sleep(0.2)
                led_controller.turn_off()
                await asyncio.sleep(0.2)

            if force_reboot:
                logger.info("Force reboot enabled after flight controller reboot failure.")

    if sys_flag:
        try:
            # Attempt system (Raspberry Pi) reboot
            logger.info("Initiating system reboot...")
            led_controller.turn_off()

            # Use the reboot_system() function to reboot
            await reboot_system()
        except Exception:
            logger.exception("System reboot failed")

            if force_reboot:
                logger.info("Force reboot enabled, attempting forced system reboot.")
                try:
                    await reboot_system()
                except Exception:
                    logger.exception("Forced system reboot failed")

    # Final LED cleanup
    led_controller.turn_off()

async def reboot_system():
    """
    Reboots the Raspberry Pi using the D-Bus system interface.
    """
    try:
        # Use D-Bus to initiate the reboot without sudo
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
    except Exception:
        logger.exception("System reboot failed")

# =======================
# Entry Point
# =======================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Perform actions with drones.")
    parser.add_argument('--action', type=str, required=True,
                        help='Action to perform: takeoff, land, hold, test, reboot_fc, reboot_sys')
    parser.add_argument('--altitude', type=float, default=10,
                        help='Altitude for takeoff')
    parser.add_argument('--param', action='append', nargs=2, metavar=('param_name', 'param_value'),
                        help='Set parameters in the form param_name param_value')

    args = parser.parse_args()

    # Convert parameter arguments to dictionary
    parameters = {param[0]: int(param[1]) for param in args.param} if args.param else None

    try:
        asyncio.run(perform_action(args.action, args.altitude, parameters))
    except Exception:
        logger.exception("An unexpected error occurred")
    finally:
        logger.info("Operation completed.")
