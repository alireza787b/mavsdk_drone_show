# actions.py
# Usage: python actions.py --action takeoff --altitude 20 --param MAV_SYS_ID 2 --param PARAM2 3

import argparse
import asyncio
import csv
import glob
import logging
import os
import signal
import subprocess
import sys

import psutil
from mavsdk import System
from src.led_controller import LEDController
from src.params import Params

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("actions.log")
    ]
)
logger = logging.getLogger(__name__)

# Global shutdown event
shutdown_event = asyncio.Event()

def handle_termination_signal(signum, frame):
    """
    Signal handler to set the shutdown_event when termination signals are received.
    """
    logger.info(f"Received termination signal: {signum}. Initiating shutdown...")
    shutdown_event.set()

# Register signal handlers for graceful termination
signal.signal(signal.SIGTERM, handle_termination_signal)
signal.signal(signal.SIGINT, handle_termination_signal)

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
            continue
    return False, None

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
    mavsdk_server = subprocess.Popen(
        ["./mavsdk_server", "-p", str(grpc_port), f"udp://:{udp_port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    return mavsdk_server

def read_hw_id():
    """
    Reads the hardware ID from files with the '.hwID' extension.

    Returns:
        int or None: The hardware ID if found, else None.
    """
    hwid_files = glob.glob('*.hwID')
    if hwid_files:
        filename = hwid_files[0]
        hw_id = os.path.splitext(os.path.basename(filename))[0]  # Correctly extract filename without extension
        logger.info(f"Hardware ID {hw_id} detected.")
        try:
            return int(hw_id)
        except ValueError:
            logger.error(f"Invalid hardware ID format in file: {filename}")
            return None
    else:
        logger.warning("Hardware ID file not found.")
        return None


def read_config(filename='config.csv'):
    """
    Reads the drone configuration from a CSV file based on the hardware ID.

    Args:
        filename (str): The path to the configuration CSV file.

    Returns:
        dict or None: The drone configuration if found, else None.
    """
    hw_id = read_hw_id()
    if hw_id is None:
        logger.error("Hardware ID is not available.")
        return None
    
    logger.info("Reading drone configuration...")
    try:
        with open(filename, newline='') as csvfile:
            reader = csv.reader(csvfile)
            next(reader, None)  # Skip the header
            for row in reader:
                if len(row) < 8:
                    logger.warning(f"Incomplete configuration row: {row}")
                    continue
                file_hw_id, pos_id, x, y, ip, mavlink_port, debug_port, gcs_ip = row
                if int(file_hw_id) == hw_id:
                    logger.info(f"Matching hardware ID found: {file_hw_id}")
                    drone_config = {
                        'hw_id': int(file_hw_id),
                        'udp_port': int(mavlink_port),
                        'grpc_port': int(debug_port)
                    }
                    logger.info(f"Drone configuration: {drone_config}")
                    return drone_config
    except FileNotFoundError:
        logger.error(f"Config file '{filename}' not found.")
    except Exception as e:
        logger.error(f"Error reading config file '{filename}': {e}")
    logger.warning("No matching hardware ID found in the configuration file.")
    return None


def stop_mavsdk_server(mavsdk_server):
    """
    Terminates the MAVSDK server subprocess.

    Args:
        mavsdk_server (subprocess.Popen): The subprocess running the MAVSDK server.
    """
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
        except Exception as e:
            logger.error(f"Failed to set parameter '{param_name}': {e}")

async def execute_action(drone, action, altitude, parameters):
    """
    Executes the specified drone action.

    Args:
        drone (System): The MAVSDK drone system.
        action (str): The action to perform (takeoff, land, hold, test, reboot).
        altitude (float): The altitude for takeoff (if applicable).
        parameters (dict): Parameters to set on the drone (if any).
    """
    led_controller = LEDController.get_instance()
    
    try:
        # Set parameters if provided
        if parameters:
            await set_parameters(drone, parameters)
        
        # Perform action based on the specified command
        if action == "takeoff":
            await takeoff(drone, altitude, led_controller)
        elif action == "land":
            await land(drone, led_controller)
        elif action == "hold":
            await hold(drone, led_controller)
        elif action == "test":
            await test(drone, led_controller)
        elif action == "reboot":
            await reboot(drone, led_controller)
        else:
            logger.error(f"Invalid action specified: '{action}'")
    except asyncio.CancelledError:
        logger.info("Action execution was cancelled.")
    except Exception as e:
        logger.error(f"Error performing action '{action}': {e}")

async def perform_action(action, altitude=None, parameters=None):
    """
    Orchestrates the entire action execution process, including starting and stopping the MAVSDK server.

    Args:
        action (str): The action to perform.
        altitude (float, optional): The altitude for takeoff.
        parameters (dict, optional): Parameters to set on the drone.
    """
    logger.info("Starting to perform action...")
    drone_config = read_config()
    if not drone_config:
        logger.error("Drone configuration not found. Exiting...")
        return
    
    grpc_port = drone_config['grpc_port']
    udp_port = drone_config['udp_port']
    
    logger.info(f"gRPC Port: {grpc_port}, UDP Port: {udp_port}")
    
    # Start the MAVSDK server
    mavsdk_server = start_mavsdk_server(grpc_port, udp_port)
    
    # Initialize the MAVSDK drone system
    drone = System(mavsdk_server_address="localhost", port=grpc_port)
    logger.info("Attempting to connect to drone...")
    await drone.connect(system_address=f"udp://:{udp_port}")
    
    # Check connection state
    logger.info("Checking connection state...")
    async for state in drone.core.connection_state():
        if state.is_connected:
            logger.info(f"Drone connected on UDP Port: {udp_port} and gRPC Port: {grpc_port}")
            break
    else:
        logger.error("Could not establish a connection with the drone.")
        stop_mavsdk_server(mavsdk_server)
        return

    # Create the action execution task
    action_task = asyncio.create_task(execute_action(drone, action, altitude, parameters))
    
    # Wait for either the action to complete or a shutdown event
    done, pending = await asyncio.wait(
        [action_task, shutdown_event.wait()],
        return_when=asyncio.FIRST_COMPLETED
    )
    
    if shutdown_event.is_set():
        logger.info("Shutdown event detected. Cancelling action task...")
        action_task.cancel()
        try:
            await action_task
        except asyncio.CancelledError:
            logger.info("Action task cancelled successfully.")
    
    # Ensure MAVSDK server is terminated
    stop_mavsdk_server(mavsdk_server)
    logger.info("Action completed.")

async def takeoff(drone, altitude, led_controller):
    """
    Executes the takeoff action.

    Args:
        drone (System): The MAVSDK drone system.
        altitude (float): The altitude to take off to.
        led_controller (LEDController): The LED controller instance.
    """
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
    except Exception as e:
        logger.error(f"Takeoff failed: {e}")
        # Indicate takeoff failure with red blinks
        for _ in range(3):
            led_controller.set_color(255, 0, 0)  # Red
            await asyncio.sleep(0.2)
            led_controller.turn_off()
            await asyncio.sleep(0.2)
    finally:
        # Turn off LEDs after feedback
        led_controller.turn_off()

async def land(drone, led_controller):
    """
    Executes the land action.

    Args:
        drone (System): The MAVSDK drone system.
        led_controller (LEDController): The LED controller instance.
    """
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
    except Exception as e:
        logger.error(f"Landing failed: {e}")
        # Indicate landing failure with red blinks
        for _ in range(3):
            led_controller.set_color(255, 0, 0)  # Red
            await asyncio.sleep(0.2)
            led_controller.turn_off()
            await asyncio.sleep(0.2)
    finally:
        # Turn off LEDs after feedback
        led_controller.turn_off()

async def hold(drone, led_controller):
    """
    Executes the hold position action.

    Args:
        drone (System): The MAVSDK drone system.
        led_controller (LEDController): The LED controller instance.
    """
    # Indicate hold command received with blue color
    led_controller.set_color(0, 0, 255)  # Blue
    await asyncio.sleep(0.5)

    try:
        await drone.action.hold()  # Switch to Hold mode
        
        # Indicate successful hold with a solid blue color
        led_controller.set_color(0, 0, 255)  # Solid Blue
        await asyncio.sleep(1)
        
        logger.info("Hold position successful.")
    except Exception as e:
        logger.error(f"Hold failed: {e}")
        # Indicate hold failure with red blinks
        for _ in range(3):
            led_controller.set_color(255, 0, 0)  # Red
            await asyncio.sleep(0.2)
            led_controller.turn_off()
            await asyncio.sleep(0.2)
    finally:
        # Turn off LEDs after feedback
        led_controller.turn_off()

async def test(drone, led_controller):
    """
    Executes the test action, which includes arming and disarming the drone with LED feedback.

    Args:
        drone (System): The MAVSDK drone system.
        led_controller (LEDController): The LED controller instance.
    """
    try:
        # Step 1: Set LEDs to red before attempting to arm
        led_controller.set_color(255, 0, 0)  # Red
        await asyncio.sleep(1)  # Wait to show red color

        # Step 2: Arm the drone
        await drone.action.arm()

        # Step 3: Set LEDs to white after arming
        led_controller.set_color(255, 255, 255)  # White
        await asyncio.sleep(1)  # Wait to show white color

        # Step 4: Change LED colors during the 3-second wait
        led_controller.set_color(0, 0, 255)  # Blue
        await asyncio.sleep(1)  # Wait to show blue color

        led_controller.set_color(0, 255, 0)  # Green
        await asyncio.sleep(1)  # Wait to show green color

        # Step 5: Disarm the drone
        await drone.action.disarm()
        logger.info("Test action successful.")

        # Step 6: Turn off LEDs after disarming
        led_controller.turn_off()
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        # Indicate test failure with red blinks
        led_controller.set_color(255, 0, 0)  # Red
    finally:
        # Ensure LEDs are turned off
        led_controller.turn_off()

async def reboot(drone, led_controller, force_reboot=Params.force_reboot):
    """
    Executes the reboot action, optionally forcing a system reboot.

    Args:
        drone (System): The MAVSDK drone system.
        led_controller (LEDController): The LED controller instance.
        force_reboot (bool): Whether to force a system reboot despite drone errors.
    """
    # Indicate reboot initiation with yellow color
    led_controller.set_color(255, 255, 0)  # Yellow
    await asyncio.sleep(0.5)  # Brief feedback

    try:
        # Attempt to reboot the drone
        await drone.action.reboot()
        
        # Indicate successful reboot with green blinks
        for _ in range(3):
            led_controller.set_color(0, 255, 0)  # Green
            await asyncio.sleep(0.2)
            led_controller.turn_off()
            await asyncio.sleep(0.2)

        logger.info("Drone reboot successful.")

    except Exception as e:
        logger.error(f"Drone reboot failed: {e}")
        # Indicate reboot failure with red blinks
        for _ in range(3):
            led_controller.set_color(255, 0, 0)  # Red
            await asyncio.sleep(0.2)
            led_controller.turn_off()
            await asyncio.sleep(0.2)

        # Check if force reboot is enabled
        if force_reboot:
            logger.info("Force reboot enabled, proceeding with system reboot despite drone error.")
            
            # Indicate force reboot with alternating red and white
            for _ in range(5):
                led_controller.set_color(255, 0, 0)  # Red
                await asyncio.sleep(0.2)
                led_controller.set_color(255, 255, 255)  # White
                await asyncio.sleep(0.2)
            
    finally:
        if force_reboot:
            logger.info("Initiating full system reboot...")
            led_controller.turn_off()
            try:
                subprocess.run(['sudo', 'reboot'], check=True)
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to reboot system: {e}")
        else:
            # Turn off LEDs after feedback
            led_controller.turn_off()

async def main():
    """
    Main entry point for executing drone actions based on command-line arguments.
    """
    parser = argparse.ArgumentParser(description="Perform actions with drones.")
    parser.add_argument('--action', type=str, required=True, help='Action to perform: takeoff, land, hold, test, reboot')
    parser.add_argument('--altitude', type=float, default=10, help='Altitude for takeoff')
    parser.add_argument('--param', action='append', nargs=2, metavar=('param_name', 'param_value'),
                        help='Set parameters in the form param_name param_value')

    args = parser.parse_args()

    # Convert parameter arguments to dictionary
    parameters = {param[0]: int(param[1]) for param in args.param} if args.param else None

    try:
        await perform_action(args.action, args.altitude, parameters)
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
    finally:
        logger.info("Operation completed.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Program interrupted by user. Exiting...")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
