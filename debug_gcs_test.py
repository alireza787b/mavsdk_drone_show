"""
Author: Alireza Ghaderi
Email: p30planets@gmail.com
GitHub: alireza787b
Repository: github.com/alireza787b/mavsdk_drone_show
Date: June 2023
---------------------------------------------------------------------------

Ground Control Station (GCS) Script for Drone Telemetry and Command Control
---------------------------------------------------------------------------

This script is designed to function as a Ground Control Station (GCS) in a drone network, providing functionality for receiving telemetry data from drones and
sending commands to them. The script communicates with the drones over User Datagram Protocol (UDP), and it can be easily configured and expanded to 
handle multiple drones simultaneously.

Setup and Configuration:
------------------------
The script is set up to read its configuration from a .csv file named 'config.csv' which should be located in the same directory as the script. The columns
in 'config.csv' should be as follows: hw_id, pos_id, x, y, ip, mavlink_port, debug_port, gcs_ip.

Each row in 'config.csv' corresponds to a drone. The 'hw_id' column indicates the hardware ID of the drone, the 'pos_id' gives its position ID, 'x' and 'y'
provide coordinates, 'ip' specifies the drone's IP address, 'mavlink_port' and 'debug_port' provide the ports for MAVLink communication and debug information,
and 'gcs_ip' specifies the IP address of the GCS.

The script supports both single-drone and multiple-drone modes. The mode is determined by the 'single_drone' variable in the script. 
If 'single_drone' is True, the script will function in single-drone mode, where it communicates with a single drone specified by the hardware ID in a file 
named 'i.hwID', where 'i' is the hardware ID of the drone. This file should be located in the same directory as the script.
If 'single_drone' is False, the script operates in multiple-drone mode, communicating with all drones specified in the 'config.csv' file.

Sim Mode:
---------
The script includes a 'sim_mode' boolean variable that allows the user to switch between simulation mode and real-world mode. When 'sim_mode' is set to True,
the script is in simulation mode, and the IP address of the coordinator (essentially the drone control node) is manually defined in the code. 
If 'sim_mode' is False, the script uses the IP address from 'config.csv' for the drones.

Communication Protocol:
-----------------------
The script communicates with the drones over UDP using binary packets. For telemetry data, these packets have the following structure:

- Header (1 byte): A constant value of 77. 
- HW_ID (1 byte): The hardware ID of the drone.
- Pos_ID (1 byte): The position ID of the drone.
- State (1 byte): The current state of the drone.
- Trigger Time (4 bytes): The Unix timestamp when the data was sent.
- Terminator (1 byte): A constant value of 88.

For commands, the packets have a similar structure, but the header value is 55 and the terminator value is 66.

Each part of the packet is packed into a binary format using the struct.pack method from Python's 'struct' library.
The '=' character ensures that the bytes are packed in standard size, 'B' specifies an unsigned char (1 byte), and 'I' specifies an unsigned int (4 bytes).

Example:
--------
For example, a command packet could look like this in binary:

Header = 55 (in binary: 00110111)
HW_ID = 3 (in binary: 00000011)
Pos_ID = 3 (in binary: 

00000011)
State = 1 (in binary: 00000001)
Trigger Time = 1687840743 (in binary: 11001010001100001101101100111111)
Terminator = 66 (in binary: 01000010)

The whole packet in binary would look like this:
00110111 00000011 00000011 00000001 11001010001100001101101100111111 01000010

Please note that the actual binary representation would be a sequence of 8-bit binary numbers.
The above representation is simplified to demonstrate the concept.

Running the script:
-------------------
To run the script, simply execute it in a Python environment. You will be prompted to enter commands for the drone.
You can enter 't' to send a command to the drone or 'q' to quit the script. If you choose to send a command,
you will be asked to enter the number of seconds for the trigger time. During this time, telemetry data will not be printed. 
You can enter '0' to cancel the command and resume printing of telemetry data.

License:
--------
This script is open-source and available to use and modify as per the terms of the license agreement.

Disclaimer:
-----------
The script is provided as-is, and the authors and contributors are not responsible for any damage or loss resulting from its use.
Always ensure that you comply with all local laws and regulations when operating drones.

"""

# Imports
import logging
import socket
import struct
import threading
import time
import pandas as pd
import os

from enum import Enum

class State(Enum):
    IDLE = 0
    ARMED = 1
    TRIGGERED = 2

class Mission(Enum):
    NONE = 0
    DRONE_SHOW_FROM_CSV = 1
    SMART_SWARM = 2


# Sim Mode
sim_mode = False  # Set this variable to True for simulation mode (the ip of all drones will be the same)

telem_struct_fmt = '=BHHBBIddddddddBB'
command_struct_fmt = '=B B B B B I B'

telem_packet_size = struct.calcsize(telem_struct_fmt)
command_packet_size = struct.calcsize(command_struct_fmt)

# Setup logger
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Single Drone
single_drone = False  # Set this to True for single drone connection

# Read the config file
config_df = pd.read_csv('config.csv')

# Drones list
drones = []

if single_drone:
    # Read the hardware ID from the '.hwID' file
    hw_id_file = [file for file in os.listdir() if file.endswith('.hwID')][0]  # Assuming there's only one such file
    hw_id = int(hw_id_file.split('.')[0])  # Extract the hw_id

    # Find the configuration for the drone in the 'config.csv' file
    drone_config = config_df.loc[config_df['hw_id'] == hw_id].iloc[0]
    drones = [drone_config]
else:
    # Add all drones from config file to drones list
    drones = [drone for _, drone in config_df.iterrows()]

# Function to send commands
def send_command(n, sock, coordinator_ip, debug_port, hw_id, pos_id, mission, state):
    """
    This function prepares and sends commands.

    :param n: An integer used to compute trigger_time.
    :param sock: The socket through which data will be sent.
    :param coordinator_ip: The IP address of the coordinator.
    :param debug_port: The port used for sending data.
    :param hw_id: The hardware ID.
    :param pos_id: The position ID.
    :param mission: The mission ID.
    :param state: The state value.
    """
    try:
        # Prepare the command data
        header = 55  # Constant
        trigger_time = int(time.time()) + n  # Now + n seconds
        terminator = 66  # Constant

        # Encode the data
        data = struct.pack(command_struct_fmt, header, hw_id, pos_id, mission, state, trigger_time, terminator)

        # Send the command data
        sock.sendto(data, (coordinator_ip, debug_port))
        logger.info(f"Sent {len(data)} byte command: Header={header}, HW_ID={hw_id}, Pos_ID={pos_id}, Mission={mission}, State={state}, Trigger Time={trigger_time}, Terminator={terminator}")

    except (OSError, struct.error) as e:
        # If there is an OSError or an error in packing the data, log the error
        logger.error(f"An error occurred: {e}")

import math



def handle_telemetry(keep_running, print_telemetry, sock):
    """
    This function continuously receives and handles telemetry data.

    :param keep_running: A control flag for the while loop. 
                         When it's False, the function stops receiving data.
    :param print_telemetry: A flag to control if the telemetry data should be printed.
    :param sock: The socket from which data will be received.
    """
    while keep_running[0]:
        try:
            # Receive telemetry data
            data, addr = sock.recvfrom(1024)

            # If received data is not of correct size, log the error and continue
            if len(data) != telem_packet_size:
                logger.error(f"Received packet of incorrect size. Expected {telem_packet_size}, got {len(data)}.")
                continue

            # Decode the data
            telemetry_data = struct.unpack(telem_struct_fmt, data)
            header, terminator = telemetry_data[0], telemetry_data[-1]

            # If header or terminator are not as expected, log the error and continue
            if header != 77 or terminator != 88:
                logger.error("Invalid header or terminator received in telemetry data.")
                continue

            # If the print_telemetry flag is True, print the decoded data
            if print_telemetry[0]:
                hw_id, pos_id, state, mission, trigger_time, position_lat, position_long, position_alt, velocity_north, velocity_east, velocity_down, yaw, battery_voltage, follow_mode = telemetry_data[1:-1]
                # Debug log with all details
                logger.info(f"Received telemetry: Header={header}, HW_ID={hw_id}, Pos_ID={pos_id}, State={State(state).name}, Mission={Mission(mission).name}, Trigger Time={trigger_time}, Position Lat={position_lat}, Position Long={position_long}, Position Alt={position_alt:.1f}, Velocity North={velocity_north:.1f}, Velocity East={velocity_east:.1f}, Velocity Down={velocity_down:.1f}, Yaw={yaw:.1f}, Battery Voltage={battery_voltage:.1f}, Follow Mode={follow_mode}, Terminator={terminator}")
                
        except (OSError, struct.error) as e:
            # If there is an OSError or an error in unpacking the data, log the error and break the loop
            logger.error(f"An error occurred: {e}")
            break
        


# Drones threads
drones_threads = []

# This flag indicates if the telemetry threads should keep running.
# We use a list so the changes in the main thread can be seen by the telemetry threads.
keep_running = [True]

try:
    for drone_config in drones:
        # Extract variables
        if sim_mode:
            coordinator_ip = '172.22.141.34'  # WSL IP
        else:
            coordinator_ip = drone_config['ip']
        debug_port = int(drone_config['debug_port'])  # Debug port
        gcs_ip = drone_config['gcs_ip']  # GCS IP
        hw_id = drone_config['hw_id']  # Hardware ID
        pos_id = drone_config['pos_id']  # Position ID

        # Log information
        logger.info(f"Drone {hw_id} is listening and sending on IP {coordinator_ip} and port {debug_port}")

        # Socket for communication
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((gcs_ip, debug_port))

        # This flag controls whether telemetry is printed to the screen. 
        # We use a list so the changes in the main thread can be seen by the telemetry threads.
        print_telemetry = [True]

        # Start the telemetry thread
        telemetry_thread = threading.Thread(target=handle_telemetry, args=(keep_running, print_telemetry, sock))
        telemetry_thread.start()

        # Add to the drones_threads
        drones_threads.append((sock, telemetry_thread, coordinator_ip, debug_port, hw_id, pos_id))

    # Main loop for command input
    mission = 0
    state = 0
    n = 0
    while True:
        command = input("\n Enter 's' for swarm, 'c' for csv_droneshow, 'n' for none, 'q' to quit: \n")
        if command.lower() == 'q':
            break
        elif command.lower() == 's':
            mission = 2  # Setting mission to smart_swarm
            n = input("\n Enter the number of seconds for the trigger time (or '0' to cancel): \n")
            if int(n) == 0:
                continue
            state = 1
        elif command.lower() == 'c':
            mission = 1  # Setting mission to csv_droneshow
            n = input("\n Enter the number of seconds for the trigger time (or '0' to cancel): \n")
            if int(n) == 0:
                continue
            state = 1
        elif command.lower() == 'n':
            mission = 0  # Unsetting the mission
            state = 0
            n = 0  # Unsetting the trigger time
        else:
            logger.warning("Invalid command.")
            continue

        # Turn off telemetry printing while sending commands
        for _, _, _, _, _, _ in drones_threads:
            print_telemetry[0] = False
        # Send command to each drone
        for sock, _, coordinator_ip, debug_port, hw_id, pos_id in drones_threads:
            send_command(int(n), sock, coordinator_ip, debug_port, hw_id, pos_id, mission, state)
        # Turn on telemetry printing after sending commands
        for _, _, _, _, _, _ in drones_threads:
            print_telemetry[0] = True
except (ValueError, OSError, KeyboardInterrupt) as e:
    # Catch any exceptions that occur during the execution
    logger.error(f"An error occurred: {e}")
finally:
    # When KeyboardInterrupt happens or an error occurs, stop the telemetry threads
    keep_running[0] = False

    for sock, telemetry_thread, _, _, _, _ in drones_threads:
        # Close the socket
        sock.close()
        # Join the thread
        telemetry_thread.join()

logger.info("Exiting the application...")

