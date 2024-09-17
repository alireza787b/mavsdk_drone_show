#actions.py
#usage: python action.py --action takeoff --altitude 20 --param MAV_SYS_ID 2 --param PARAM2 3
import argparse
import asyncio
import csv
from src.led_controller import LEDController
from mavsdk import System
import glob
import os
import subprocess
import logging
import psutil
from src.params import Params

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Function to check if MAVSDK server is running
def check_mavsdk_server_running(port):
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            for conn in proc.connections(kind='inet'):
                if conn.laddr.port == port:
                    return True, proc.info['pid']
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False, None

# Modified start_mavsdk_server function
def start_mavsdk_server(grpc_port, udp_port):
    is_running, pid = check_mavsdk_server_running(grpc_port)
    if is_running:
        logger.info(f"MAVSDK server already running on port {grpc_port}. Terminating...")
        psutil.Process(pid).terminate()
        psutil.Process(pid).wait()  # Wait for the process to actually terminate
    
    logger.info(f"Starting mavsdk_server on gRPC port: {grpc_port}, UDP port: {udp_port}")
    mavsdk_server = subprocess.Popen(["./mavsdk_server", "-p", str(grpc_port), f"udp://:{udp_port}"])
    return mavsdk_server

def read_hw_id():
    hwid_files = glob.glob('*.hwID')
    if hwid_files:
        filename = hwid_files[0]
        hw_id = os.path.splitext(filename)[0]  # Get filename without extension
        logger.info(f"Hardware ID {hw_id} detected.")
        return int(hw_id)
    else:
        logger.warning("Hardware ID file not found.")
        return None

def read_config(filename='config.csv'):
    logger.info("Reading drone configuration...")
    dronesConfig = []
    try:
        with open(filename, newline='') as csvfile:
            reader = csv.reader(csvfile)
            next(reader, None)  # Skip the header
            for row in reader:
                hw_id, pos_id, x, y, ip, mavlink_port, debug_port, gcs_ip = row
                if int(hw_id) == HW_ID:
                    logger.info(f"Matching hardware ID found: {hw_id}")
                    droneConfig = {
                        'hw_id': hw_id,
                        'udp_port': mavlink_port,
                        'grpc_port': debug_port
                    }
                    logger.info(f"Drone configuration: {droneConfig}")
                    return droneConfig
    except FileNotFoundError as e:
        logger.error(f"Config file not found: {e}")
    except Exception as e:
        logger.error(f"Error reading config file {filename}: {e}")
    logger.warning("No matching hardware ID found in the configuration file.")
    return None
            
SIM_MODE = False  # or True based on your setting
GRPC_PORT_BASE = 50041
HW_ID = read_hw_id()

def stop_mavsdk_server(mavsdk_server):
    logger.info("Stopping mavsdk_server")
    mavsdk_server.terminate()

async def set_parameters(drone, parameters):
    """
    Function to set one or more parameters on the drone.
    Parameters should be passed as a dictionary, e.g., {"MAV_SYS_ID": 2}
    """
    for param_name, param_value in parameters.items():
        try:
            logger.info(f"Setting parameter {param_name} to {param_value}")
            await drone.param.set_param_int(param_name, param_value)
            logger.info(f"Parameter {param_name} set to {param_value} successfully.")
        except Exception as e:
            logger.error(f"Failed to set parameter {param_name}: {e}")

async def perform_action(action, altitude=None, parameters=None):
    logging.info("Starting to perform action...")
    droneConfig = read_config()
    if not droneConfig:
        logging.error("Drone configuration not found. Exiting...")
        return
    
    grpc_port = GRPC_PORT_BASE + HW_ID if SIM_MODE else GRPC_PORT_BASE - 1
    udp_port = 14540 if not SIM_MODE else int(droneConfig['udp_port'])

    logging.info(f"gRPC Port: {grpc_port}, UDP Port: {udp_port}")

    mavsdk_server = start_mavsdk_server(grpc_port, udp_port)
    
    drone = System(mavsdk_server_address="localhost", port=grpc_port)
    logging.info("Attempting to connect to drone...")
    await drone.connect(system_address=f"udp://:{udp_port}")

    logging.info("Checking connection state...")
    async for state in drone.core.connection_state():
        if state.is_connected:
            logging.info(f"Drone connected on UDP Port: {udp_port} and gRPC Port: {grpc_port}")
            break
    else:
        logging.error("Could not establish a connection with the drone.")
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
        elif action == "reboot":
            await reboot(drone)
        else:
            logging.error("Invalid action specified.")
    except Exception as e:
        logging.error(f"Error performing action {action}: {e}")
    finally:
        is_running, pid = check_mavsdk_server_running(grpc_port)
        if is_running:
            logging.info(f"Terminating MAVSDK server running on port {grpc_port}...")
            psutil.Process(pid).terminate()
            psutil.Process(pid).wait()
        logging.info("Action completed.")

async def takeoff(drone, altitude):
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

        logging.info("Takeoff successful.")
    except Exception as e:
        # Indicate takeoff failure with red blinks
        for _ in range(3):
            led_controller.set_color(255, 0, 0)  # Red
            await asyncio.sleep(0.2)
            led_controller.turn_off()
            await asyncio.sleep(0.2)

        logging.error(f"Takeoff failed: {e}")
    finally:
        # Turn off LEDs after feedback
        led_controller.turn_off()

async def land(drone):
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

        await drone.action.land()  # Then execute land command
        
        # Indicate successful landing with green blinks
        for _ in range(3):
            led_controller.set_color(0, 255, 0)  # Green
            await asyncio.sleep(0.2)
            led_controller.turn_off()
            await asyncio.sleep(0.2)

        logging.info("Landing successful.")
    except Exception as e:
        # Indicate landing failure with red blinks
        for _ in range(3):
            led_controller.set_color(255, 0, 0)  # Red
            await asyncio.sleep(0.2)
            led_controller.turn_off()
            await asyncio.sleep(0.2)

        logging.error(f"Landing failed: {e}")
    finally:
        # Turn off LEDs after feedback
        led_controller.turn_off()

async def hold(drone):
    led_controller = LEDController.get_instance()

    # Indicate hold command received with blue color
    led_controller.set_color(0, 0, 255)  # Blue
    await asyncio.sleep(0.5)

    try:
        await drone.action.hold()  # Switch to Hold mode
        
        # Indicate successful hold with a solid blue or slow blue pulse
        led_controller.set_color(0, 0, 255)  # Solid Blue
        await asyncio.sleep(1)
        
        logging.info("Hold position successful.")
    except Exception as e:
        # Indicate hold failure with red blinks
        for _ in range(3):
            led_controller.set_color(255, 0, 0)  # Red
            await asyncio.sleep(0.2)
            led_controller.turn_off()
            await asyncio.sleep(0.2)

        logging.error(f"Hold failed: {e}")
    finally:
        # Turn off LEDs after feedback
        led_controller.turn_off()


async def test(drone):
    # Get the singleton instance of LEDController
    led_controller = LEDController.get_instance()

    try:
        # Step 1: Set LEDs to red before attempting to arm
        led_controller.set_color(255, 0, 0)  # Red
        await asyncio.sleep(1)  # Wait for a moment to show red color

        # Step 2: Arm the drone
        await drone.action.arm()

        # Step 3: Set LEDs to white after arming
        led_controller.set_color(255, 255, 255)  # White
        await asyncio.sleep(1)  # Wait for 1 second to show white color

        # Step 4: Change LED colors during the 3-second wait
        led_controller.set_color(0, 0, 255)  # Blue
        await asyncio.sleep(1)  # Wait 1 second for blue color

        led_controller.set_color(0, 255, 0)  # Green
        await asyncio.sleep(1)  # Wait 1 second for green color

        # Step 5: Disarm the drone
        await drone.action.disarm()
        logging.info("Test action successful.")

        # Step 6: Turn off LEDs after disarming
        led_controller.turn_off()
        
    except Exception as e:
        logging.error(f"Test failed: {e}")
        led_controller.set_color(255, 0, 0)  # Red
    finally:
        # Ensure LEDs will remain red in case of an exception
        #led_controller.turn_off()
        pass
        


async def reboot(drone, force_reboot=Params.force_reboot):
    # Get the singleton instance of LEDController
    led_controller = LEDController.get_instance()

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

        logging.info("Drone reboot successful.")

    except Exception as e:
        # Indicate reboot failure with red blinks
        for _ in range(3):
            led_controller.set_color(255, 0, 0)  # Red
            await asyncio.sleep(0.2)
            led_controller.turn_off()
            await asyncio.sleep(0.2)

        logging.error(f"Drone reboot failed: {e}")

        # Check if force reboot is enabled
        if force_reboot:
            logging.info("Force reboot enabled, proceeding with system reboot despite drone error.")
            
            # Indicate force reboot with alternating red and white
            for _ in range(5):
                led_controller.set_color(255, 0, 0)  # Red
                await asyncio.sleep(0.2)
                led_controller.set_color(255, 255, 255)  # White
                await asyncio.sleep(0.2)
            
    finally:
        if force_reboot:
            logging.info("Initiating full system reboot...")
            led_controller.turn_off()
            os.system('sudo reboot')
        else:
            # Turn off LEDs after feedback
            led_controller.turn_off()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Perform actions with drones.")
    parser.add_argument('--action', type=str, required=True, help='Action to perform: takeoff, land, hold, test, reboot')
    parser.add_argument('--altitude', type=float, default=10, help='Altitude for takeoff')
    parser.add_argument('--param', action='append', nargs=2, metavar=('param_name', 'param_value'), help='Set parameters in the form param_name param_value')

    args = parser.parse_args()

    # Convert parameter arguments to dictionary
    parameters = {param[0]: int(param[1]) for param in args.param} if args.param else None

    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(perform_action(args.action, args.altitude, parameters))
    except Exception as e:
        logging.error(f"An error occurred: {e}")
    finally:
        loop.close()  # Ensure the loop is closed properly
        logging.info("Operation completed, event loop closed.")
