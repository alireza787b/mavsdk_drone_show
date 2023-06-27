# -----------------------------------------------------------------------------
# coordinator.py
# Version: 1.0
#
# Authors: Alireza Ghaderi
# Email: p30planets@gmail.com
# GitHub: https://github.com/Alireza787b
#
# This script coordinates the operations of a drone show. Its responsibilities include:
# - Sending node info state to Ground Control Station (GCS)
# - Listening to the commands from GCS
# - Connecting to the pixhawk via serial (in real life) or SITL (in sim mode) and routing the mavlink messages
#   (requires mavlink-router to be installed) to GCS and other nodes (in real life over Zerotier network, 
#   in sim mode just send to the IP of the GCS locally)
# - Syncing and setting the time to accurate internet time
# - Setting a trigger time so all the drones can start the mission at a specified time in future for synced shows
# - Allowing to unset the triggered time
# - Autostarting when OS loads
# 
# More features might be added as the project progresses.
#
# This script is a part of mavsdk_drone_show repository available at:
# https://github.com/Alireza787b/mavsdk_drone_show
#
# Last updated: June 2023
# -----------------------------------------------------------------------------

# Importing the necessary libraries
import csv
import datetime
import glob
import json
import socket
import threading
import os
import time
import requests
import urllib3

# Configuration Variables
config_url = 'config_url'  # URL for the configuration file
sim_mode = True  # Simulation mode switch
sleep_interval = 0.1  # Sleep interval for the main loop in seconds
offline_config = True  # Offline configuration switch

# Variables to aid in Mavlink connection and telemetry
serial_mavlink = '/dev/ttyAMA0'  # Default serial for Raspberry Pi Zero
serial_baudrate = 57600  # Default baudrate
sitl_port = 14550  # Default SITL port
mavsdk_port = 14540  # Default MAVSDK port
extra_devices = ['172.22.128.1:14550']  # List of extra devices (IP:Port) to route Mavlink

# Define DroneConfig class
class DroneConfig:
    def __init__(self, offline_config):
        self.offline_config = offline_config
        self.hw_id = self.get_hw_id()
        self.trigger_time = 0
        self.config = self.read_config()
        self.config['state'] = 0

    def get_hw_id(self):
        # Check the files in the current directory and find the hwID file
        hw_id_files = glob.glob("*.hwID")
        if hw_id_files:
            hw_id_file = hw_id_files[0]
            print(f"Hardware ID file found: {hw_id_file}")
            # Return the hardware ID without the extension (.hwID)
            hw_id = hw_id_file.split(".")[0]
            print(f"Hardware ID: {hw_id}")
            return hw_id
        else:
            print("Hardware ID file not found. Please check your files.")
            return None

    def read_config(self):
        # If offline_config is True, read the configuration from the local CSV file
        if self.offline_config:
            with open('config.csv', newline='') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    if row['hw_id'] == self.hw_id:
                        print(f"Configuration for HW_ID {self.hw_id} found in local CSV file.")
                        return row

        # Else, download the configuration from the provided URL and read it
        else:
            with urllib3.request.urlopen(config_url) as url:
                data = json.loads(url.read().decode())
                for config in data:
                    if config['hw_id'] == self.hw_id:
                        print(f"Configuration for HW_ID {self.hw_id} found in the URL.")
                        return config

        print("Configuration not found.")
        return None

# Initialize DroneConfig
drone_config = DroneConfig(offline_config)

import subprocess

# Function to initialize MAVLink connection
def initialize_mavlink():

    # Depending on the sim_mode, connect to either the SITL or the Raspberry Pi GPIO serial
    if sim_mode:
        print("Sim mode is enabled. Connecting to SITL...")
        mavlink_source = f"0.0.0.0:{sitl_port}"
    else:
        print("Real mode is enabled. Connecting to Pixhawk via serial...")
        mavlink_source = f"/dev/{serial_mavlink}:{serial_baudrate}"

    # Prepare endpoints for mavlink-router
    endpoints = [f"-e {device}" for device in extra_devices]

    if sim_mode:
        # In sim mode, route the MAVLink messages to the GCS locally
        endpoints.append(f"-e {drone_config.config['gcs_ip']}:{mavsdk_port}")
    else:
        # In real life, route the MAVLink messages to the GCS and other drones over a Zerotier network
        endpoints.append(f"-e {drone_config.config['gcs_ip']}:{mavsdk_port}")

    # Command to start mavlink-router
    mavlink_router_cmd = "mavlink-routerd " + ' '.join(endpoints) + ' ' + mavlink_source

    # Start mavlink-router and keep track of the process
    print(f"Starting MAVLink routing: {mavlink_router_cmd}")
    mavlink_router_process = subprocess.Popen(mavlink_router_cmd, shell=True)
    return mavlink_router_process




# Function to stop MAVLink routing
def stop_mavlink_routing(mavlink_router_process):

    if mavlink_router_process:
        print("Stopping MAVLink routing...")
        mavlink_router_process.terminate()
        mavlink_router_process = None
    else:
        print("MAVLink routing is not running.")



# Function to get the current state of the drone
def get_drone_state():
    # Fetch the current state of the drone, including hw_id, pos_id, state, and trigger time
    # The state variable indicates: 0 for unset trigger time, 1 for set trigger time, 2 for flying
    # The trigger time is set to 0 if it has not been set yet

    drone_state = {
        "hw_id": drone_config.hw_id,
        "pos_id": drone_config.config['pos_id'],
        "state": drone_config.config['state'],
        "trigger_time": drone_config.trigger_time
    }

    return drone_state

import struct

# Function to send the drone state to the ground station
def send_drone_state():
    # Sends the drone state to the ground station over UDP debug port at a fixed interval (2 seconds)
    # This state includes the same data as get_drone_state
    udp_ip = drone_config.config['gcs_ip']  # IP address of the ground station
    udp_port = int(drone_config.config['debug_port'])  # UDP port to send telemetry data to

    sock = socket.socket(socket.AF_INET,  # Internet
                         socket.SOCK_DGRAM)  # UDP

    while True:
        drone_state = get_drone_state()

        # Pack the data into a binary format
        # 'B' unsigned char (1 byte)
        # 'I' unsigned int (4 bytes)
        # The header is 1 byte (77)
        # The hw_id, pos_id, and state are unsigned chars, 1 byte each
        # The trigger time is an unsigned int, 4 bytes
        # The terminator is 1 byte (88)
        # Therefore, the total packet size is 9 bytes
        packet = struct.pack('BBBBIB',
                             77,
                             int(drone_state['hw_id']),
                             int(drone_state['pos_id']),
                             int(drone_state['state']),
                             int(drone_state['trigger_time']),
                             88)

        sock.sendto(packet, (udp_ip, udp_port))

        print(f"Sent telemetry data to GCS: {packet}")
        print(f"Values: hw_id: {drone_state['hw_id']}, pos_id: {drone_state['pos_id']}, state: {drone_state['state']}, trigger_time: {drone_state['trigger_time']}")

        time.sleep(2)  # send telemetry data every 2 seconds



# Function to read and decode new commands
def read_commands():
    # Reads and decodes new commands from the ground station over the debug vector
    # The commands include the hw_id, pos_id, state, and trigger time
    udp_port = int(drone_config.config['debug_port'])  # UDP port to send telemetry data to

    sock = socket.socket(socket.AF_INET,  # Internet
                         socket.SOCK_DGRAM)  # UDP
    sock.bind(('0.0.0.0', udp_port))

    while True:
        data, addr = sock.recvfrom(1024)  # buffer size is 1024 bytes
        if len(data) == 9:  # Packet size should be 9 bytes
            header, hw_id, pos_id, state, trigger_time, terminator = struct.unpack('BBBBIB', data)

            # Check if header and terminator are as expected
            if header == 55 and terminator == 66:
                print("Received command from GCS")
                print(f"Values: hw_id: {hw_id}, pos_id: {pos_id}, state: {state}, trigger_time: {trigger_time}")
                drone_config.hw_id = hw_id
                drone_config.pos_id = pos_id
                drone_config.state = state
                drone_config.trigger_time = trigger_time

                # You can add additional logic here to handle the received command

        time.sleep(1)  # check for commands every second


# Function to synchronize time with a reliable internet source
def synchronize_time():
    # Report current time before sync
    print(f"Current system time before synchronization: {datetime.datetime.now()}")

    # Attempt to get the time from a reliable source
    print("Attempting to synchronize time with a reliable internet source...")
    response = requests.get("http://worldtimeapi.org/api/ip")
    
    if response.status_code == 200:
        # Time server and result
        server_used = response.json()["client_ip"]
        current_time = response.json()["datetime"]
        print(f"Time server used: {server_used}")
        print(f"Time reported by server: {current_time}")
        
        # Set this time as system time
        print("Setting system time...")
        os.system(f"sudo date -s '{current_time}'")
        
        # Report current time after sync
        print(f"Current system time after synchronization: {datetime.datetime.now()}")
    else:
        print("Failed to sync time with an internet source.")


# Function to schedule the drone mission
def schedule_mission():
    # Constantly checks the current time vs trigger time
    # If it's time to trigger, it opens the offboard_from_csv_multiple.py separately

    current_time = int(time.time())
    if drone_config.state == 1 and current_time >= drone_config.trigger_time:
        print("Trigger time reached. Starting drone mission...")

        # Reset the state and trigger time
        drone_config.state = 0
        drone_config.trigger_time = 0

        # Run the mission script in a new process
        mission_process = subprocess.Popen(["python3", "offboard_from_csv_multiple.py"])
        
        # Note: Replace "offboard_from_csv_multiple.py" with the actual script for the drone mission


# Main function
def main():
    print("Starting the main function...")

    try:
        # Synchronize time once
        print("Synchronizing time...")
        synchronize_time()

        # Initialize MAVLink
        print("Initializing MAVLink...")
        mavlink_router_process = initialize_mavlink()

        # Start the telemetry thread
        print("Starting telemetry thread...")
        telemetry_thread = threading.Thread(target=send_drone_state)
        telemetry_thread.start()

        # Start the command reading thread
        print("Starting command reading thread...")
        command_thread = threading.Thread(target=read_commands)
        command_thread.start()

        # Enter a loop where the application will continue running
        while True:
            # Get the drone state
            #drone_state = get_drone_state()

            # Schedule the drone mission if the trigger time has been reached
            schedule_mission()

            # Sleep for a short interval to prevent the loop from running too fast
            time.sleep(sleep_interval)

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        # Close the threads before the application closes
        print("Closing threads...")
        telemetry_thread.join()
        command_thread.join()

    print("Exiting the application...")

if __name__ == "__main__":
    main()