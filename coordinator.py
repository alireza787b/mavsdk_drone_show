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
import asyncio
import csv
import datetime
import glob
import json
import socket
import threading
import os
import time
import pandas as pd
import requests
import urllib3
import subprocess

import time
import threading
from pymavlink import mavutil
import logging

import csv
import glob
import requests
from geographiclib.geodesic import Geodesic
from mavsdk import System
from mavsdk.offboard import OffboardError, PositionNedYaw, VelocityNedYaw



# Set up logging
logging.basicConfig(level=logging.INFO)

# Global variable to store telemetry
global_telemetry = {}

# Flag to indicate whether the telemetry thread should run
run_telemetry_thread = threading.Event()
run_telemetry_thread.set()






# Configuration Variables
config_url = 'https://alumsharif.org/download/config.csv'  # URL for the configuration file
swarm_url = 'https://alumsharif.org/download/swarm.csv'  # URL for the swarm file
sim_mode = False  # Simulation mode switch
serial_mavlink = False # set true if raspbberry is connected to Pixhawk using serial. otherwise for UDP set it to False
sleep_interval = 0.1  # Sleep interval for the main loop in seconds
offline_config = True  # Offline configuration switch
offline_swarm = True
default_sitl = True  # If set to True, will use default 14550 port . good for real life and single drone sim. for multple 
online_sync_time = False #If set to True it will check to sync time from Internet Time Servers
#drone sim we should set it to False so the sitl_port will be read from config.csv mavlink_port

# Variables to aid in Mavlink connection and telemetry
serial_mavlink = '/dev/ttyAMA0'  # Default serial for Raspberry Pi Zero
serial_baudrate = 57600  # Default baudrate
sitl_port = 14550  # Default SITL port
gcs_mavlink_port = 14550 #if send on 14550 to GCS, QGC will auto connect
mavsdk_port = 14540  # Default MAVSDK port
local_mavlink_port = 12550
extra_devices = [f"127.0.0.1:{local_mavlink_port}"]  # List of extra devices (IP:Port) to route Mavlink
TELEM_SEND_INTERVAL = 1 # send telemetry data every TELEM_SEND_INTERVAL seconds
local_mavlink_refresh_interval = 0.1
broadcast_mode  = True
telem_packet_size = 69
command_packet_size = 10
income_packet_check_interval = 0.1
default_GRPC_port = 50051
offboard_follow_update_interval = 0.2

# Remember to manually change the system ID for each Gazebo instance
# for each drone SITL instance in different VMware nodes by following these steps:
#
# 1. Navigate to the PX4-Autopilot repository on your local machine.
# 2. Locate the configuration file for the SITL instance you are using.
#    This file is typically located in the `ROMFS/px4fmu_common/init.d-posix` directory.
# 3. Open the configuration file `10016_iris` in a text editor.
# 4. Look for the line that sets the SYSID_THISMAV parameter. It should look like this:
#      param set SYSID_THISMAV 1
# 5. Change the value `1` to the desired system ID for your drone instance.
# 6. Save the configuration file and close the text editor.
# 7. Run `make px4_sitl gazebo` again. The drone instance should now have the new system ID you assigned.
#
# Note: Ensure that the system ID is unique for each drone instance if you are running multiple instances simultaneously.


# Initialize an empty dictionary to store drones  a dict
#example on how to access drone 4 lat      lat_drone_4 = drones[4].position['lat']

drones = {}



class DroneConfig:
    def __init__(self, hw_id=None):
        self.hw_id = self.get_hw_id(hw_id)
        self.trigger_time = 0
        self.config = self.read_config()
        self.swarm = self.read_swarm()
        self.state = 0
        self.pos_id = self.get_hw_id(hw_id)
        self.mission = 0
        self.trigger_time = 0
        self.position = {'lat': 0, 'long': 0, 'alt': 0}
        self.velocity = {'vel_n': 0, 'vel_e': 0, 'vel_d': 0}
        self.battery = 0
        self.last_update_timestamp = 0
        self.home_position = None
        self.position_setpoint_LLA = {'lat': 0, 'long': 0, 'alt': 0}
        self.position_setpoint_NED = {'north': 0, 'east': 0, 'down': 0}
        self.velocity_setpoint_NED = {'north': 0, 'east': 0, 'down': 0}
        self.target_drone = None

    def get_hw_id(self, hw_id=None):
        if hw_id is not None:
            return hw_id

        hw_id_files = glob.glob("*.hwID")
        if hw_id_files:
            hw_id_file = hw_id_files[0]
            print(f"Hardware ID file found: {hw_id_file}")
            hw_id = hw_id_file.split(".")[0]
            print(f"Hardware ID: {hw_id}")
            return hw_id
        else:
            print("Hardware ID file not found. Please check your files.")
            return None

    def read_file(self, filename, source, hw_id):
        with open(filename, newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                if row['hw_id'] == hw_id:
                    print(f"Configuration for HW_ID {hw_id} found in {source}.")
                    return row
        return None

    def read_config(self):
        if offline_config:
            return self.read_file('config.csv', 'local CSV file', self.hw_id)
        else:
            print("Loading configuration from online source...")
            try:
                print(f'Attempting to download file from: {config_url}')
                response = requests.get(config_url)

                if response.status_code != 200:
                    print(f'Error downloading file: {response.status_code} {response.reason}')
                    return None

                with open('online_config.csv', 'w') as f:
                    f.write(response.text)

                return self.read_file('online_config.csv', 'online CSV file', self.hw_id)

            except Exception as e:
                print(f"Failed to load online configuration: {e}")
        
        print("Configuration not found.")
        return None

    def read_swarm(self):
        """
        Reads the swarm configuration file, which includes the list of nodes in the swarm.
        The function supports both online and offline modes.
        In online mode, it downloads the swarm configuration file from the specified URL.
        In offline mode, it reads the swarm configuration file from the local disk.
        """
        if offline_swarm:
            return self.read_file('swarm.csv', 'local CSV file', self.hw_id)
        else:
            print("Loading swarm configuration from online source...")
            try:
                print(f'Attempting to download file from: {swarm_url}')
                response = requests.get(swarm_url)

                if response.status_code != 200:
                    print(f'Error downloading file: {response.status_code} {response.reason}')
                    return None

                with open('online_swarm.csv', 'w') as f:
                    f.write(response.text)

                return self.read_file('online_swarm.csv', 'online CSV file', self.hw_id)

            except Exception as e:
                print(f"Failed to load online swarm configuration: {e}")
        
        print("Swarm configuration not found.")
        return None
    def calculate_setpoints(self):
        self.find_target_drone()

        if self.target_drone:
            self.calculate_position_setpoint_LLA()
            self.calculate_position_setpoint_NED()
            self.calculate_velocity_setpoint_NED()
        elif self.swarm.get('follow') == 0:
            print(f"Drone {self.hw_id} is a master drone and not following anyone.")
        else:
            print(f"No drone to follow for drone with hw_id: {self.hw_id}")

    def find_target_drone(self):
        # find which drone it should follow
        follow_hw_id = int(self.swarm['follow'])
        if follow_hw_id == 0:
            print(f"Drone {self.hw_id} is a master drone and not following anyone.")
        elif follow_hw_id == self.hw_id:
            print(f"Drone {self.hw_id} is set to follow itself. This is not allowed.")
        else:
            self.target_drone = drones[follow_hw_id]
            if self.target_drone:
                print(f"Drone {self.hw_id} is following drone {self.target_drone.hw_id}")
                pass
            else:
                print(f"No target drone found for drone with hw_id: {self.hw_id}")

    def calculate_position_setpoint_LLA(self):
        # find its setpoints
        offset_n = self.swarm.get('offset_n', 0)
        offset_e = self.swarm.get('offset_e', 0)
        offset_alt = self.swarm.get('offset_alt', 0)

        # find its target drone position
        if self.target_drone:
            # Calculate new LLA with offset
            geod = Geodesic.WGS84  # define the WGS84 ellipsoid
            g = geod.Direct(float(self.target_drone.position['lat']), float(self.target_drone.position['long']), 90, float(offset_e))
            g = geod.Direct(g['lat2'], g['lon2'], 0, float(offset_n))

            self.position_setpoint_LLA = {
                'lat': g['lat2'],
                'long': g['lon2'],
                'alt': float(self.target_drone.position['alt']) + float(offset_alt),  
            }

            # The above method calculates a new LLA coordinate by moving a certain distance 
            # in the north (latitude) and east (longitude) direction. This is an approximation, 
            # and it assumes that a degree of latitude and longitude represents the same distance 
            # everywhere on the globe. For small distances, this should be a reasonable approximation, 
            # but for larger distances, this approximation may not hold true. If more accuracy is 
            # required, one should use a more advanced method or library that can account for the 
            # curvature of the earth.

            #print(f"Position setpoint for drone {self.hw_id}: {self.position_setpoint_LLA}")
        else:
            print(f"No target drone found for drone with hw_id: {self.hw_id}")

    def calculate_position_setpoint_NED(self):
        if self.target_drone:
            self.position_setpoint_NED = self.convert_LLA_to_NED(self.position_setpoint_LLA)
            #print(f"NED Position setpoint for drone {self.hw_id}: {self.position_setpoint_NED}")
        else:
            print(f"No target drone found for drone with hw_id: {self.hw_id}")


    def calculate_velocity_setpoint_NED(self):
        # velocity setpoints is exactly the same as the target drone velocity
        if self.target_drone:
            self.velocity_setpoint_NED = self.target_drone.velocity
            #print(f"NED Velocity setpoint for drone {self.hw_id}: {self.velocity_setpoint_NED}")
        else:
            print(f"No target drone found for drone with hw_id: {self.hw_id}")

    def convert_LLA_to_NED(self, LLA):
        if self.home_position:
            lat = LLA['lat']
            long = LLA['long']
            alt = LLA['alt']
            home_lat = self.home_position['lat']
            home_long = self.home_position['long']
            home_alt = self.home_position['alt']

            ned = navpy.lla2ned(lat, long, alt, home_lat, home_long, home_alt)

            position_NED = {
                'north': ned[0],
                'east': ned[1],
                'down': ned[2]
            }

            return position_NED
        else:
            print("Home position is not set")
            return None



# Initialize DroneConfig
drone_config = DroneConfig()

import navpy

def get_NED_position(self):
    """
    Calculates the North-East-Down (NED) position from the current latitude, longitude, and altitude.
    The position is relative to the home position (launch point), which is defined in the config.
    The function returns a tuple (north, east, down).

    Uses navpy library to perform the geographic to Cartesian coordinate conversion.

    Returns:
        tuple: North, East, and Down position relative to the home position (in meters)
    """

    # return north, east, down


 

def start_offboard_mode():
    async def start_offboard():
        drone = System(mavsdk_server_address='localhost',port=default_GRPC_port)
        await drone.connect()

        logging.info("Waiting for drone to connect...")
        async for state in drone.core.connection_state():
            if state.is_connected:
                logging.info("Drone discovered")
                break

        # Set initial setpoint to the current position of the drone
        initial_pos = PositionNedYaw(
            drone_config.position_setpoint_NED['north'], 
            drone_config.position_setpoint_NED['east'], 
            drone_config.position_setpoint_NED['down'], 
            0.0)
        await drone.offboard.set_position_ned(initial_pos)
        
        logging.info(f"Initial setpoint: {initial_pos}")
        
        # Start offboard mode
        try:
            await drone.offboard.start()
            logging.info("Offboard start")                    

        except OffboardError as error:
            logging.error(f"Starting offboard mode failed with error code: {error._result.result}")
            return

        # Continuously set position and velocity setpoints
        while True:
            pos_ned_yaw = PositionNedYaw(
                drone_config.position_setpoint_NED['north'],
                drone_config.position_setpoint_NED['east'],
                drone_config.position_setpoint_NED['down'],
                0.0
            )

            vel_ned_yaw = VelocityNedYaw(
                drone_config.velocity_setpoint_NED['vel_n'],
                drone_config.velocity_setpoint_NED['vel_e'],
                drone_config.velocity_setpoint_NED['vel_d'],
                0.0
            )

            await drone.offboard.set_position_velocity_ned(pos_ned_yaw, vel_ned_yaw)
             # find its setpoints
            #logging.info(f"Setpoint sent: {pos_ned_yaw}, {vel_ned_yaw}. following drone {drone_config.target_drone.hw_id}, with offsets [N:{drone_config.swarm.get('offset_n', 0)},E:{drone_config.swarm.get('offset_e', 0)},Alt:{drone_config.swarm.get('offset_alt', 0)}]")
            await asyncio.sleep(offboard_follow_update_interval)  # send setpoints every 200ms (5Hz)

    asyncio.run(start_offboard())





# Function to initialize MAVLink connection
def initialize_mavlink():

    # Depending on the sim_mode, connect to either the SITL or the Raspberry Pi GPIO serial
    if sim_mode:
        print("Sim mode is enabled. Connecting to SITL...")
        if (default_sitl == True):
            mavlink_source = f"0.0.0.0:{sitl_port}"
        else:
            mavlink_source = f"0.0.0.0:{drone_config.config['mavlink_port']}"
    else:
        if(serial_mavlink==True):
            print("Real mode is enabled. Connecting to Pixhawk via serial...")
            mavlink_source = f"/dev/{serial_mavlink}:{serial_baudrate}"
        else:
            print("Real mode is enabled. Connecting to Pixhawk via UDP...")
            mavlink_source = f"127.0.0.1:{sitl_port}"

    # Prepare endpoints for mavlink-router
    endpoints = [f"-e {device}" for device in extra_devices]

    if sim_mode:
        # In sim mode, route the MAVLink messages to the GCS locally
        endpoints.append(f"-e {drone_config.config['gcs_ip']}:{mavsdk_port}")
    else:
        # In real life, route the MAVLink messages to the GCS and other drones over a Zerotier network
        # *************** I have a doubt here . if I send from each drone to gcs_ip:14550 why GCS wont auto connect to these? temporary rverting to different port....
        endpoints.append(f"-e {drone_config.config['gcs_ip']}:{drone_config.config['mavlink_port']}")
        #endpoints.append(f"-e {drone_config.config['gcs_ip']}:{gcs_mavlink_port}")

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
        run_telemetry_thread.clear()
        telemetry_thread.join()  # wait for the telemetry thread to finish
        mavlink_router_process = None
    else:
        print("MAVLink routing is not running.")



# Create a connection to the drone
#we used pymavlink since another mavsdk instance will run by offboard control and runing several is not reasonable 
mav = mavutil.mavlink_connection(f"udp:localhost:{local_mavlink_port}")

import logging

logging.basicConfig(level=logging.INFO)

# Function to monitor telemetry
def mavlink_monitor(mav):
    while run_telemetry_thread.is_set():
        try:
            msg = mav.recv_match(blocking=True, timeout=5)  # Block until a message is received or timeout after 5 seconds
            if msg is not None:
                process_message(msg)
            else:
                logging.debug('No message received within timeout')
        except Exception as e:
            logging.error(f"An error occurred while receiving message: {e}")
        time.sleep(local_mavlink_refresh_interval)  # Sleep for a specified interval


def process_message(msg):
    if msg.get_type() == 'GLOBAL_POSITION_INT':
        process_global_position_int(msg)
    elif msg.get_type() == 'BATTERY_STATUS':
        process_battery_status(msg)
    else:
        logging.debug(f"Received unhandled message type: {msg.get_type()}")


def process_global_position_int(msg):
    logging.debug(f"Received GLOBAL_POSITION_INT: {msg}")
    valid_msg = msg.lat is not None and msg.lon is not None and msg.alt is not None
    if not valid_msg:
        logging.error('Received GLOBAL_POSITION_INT message with invalid data')
        return

    # Check if home position is set
    if drone_config.home_position is None:
        set_home_position(msg)
    else:
        update_drone_position(msg)


def set_home_position(msg):
    # Update home position with the first received position
    drone_config.home_position = {
        'lat': msg.lat / 1E7,
        'long': msg.lon / 1E7,
        'alt': msg.alt / 1E3
    }
    logging.info(f"Home position for drone {drone_config.hw_id} is set: {drone_config.home_position}")


def update_drone_position(msg):
    # Update position
    drone_config.position = {
        'lat': msg.lat / 1E7,
        'long': msg.lon / 1E7,
        'alt': msg.alt / 1E3
    }

    # Update velocity
    drone_config.velocity = {
        'vel_n': msg.vx / 1E2,
        'vel_e': msg.vy / 1E2,
        'vel_d': msg.vz / 1E2
    }
    logging.debug(f"Updated position and velocity for drone {drone_config.hw_id}")


def process_battery_status(msg):
    logging.debug(f"Received BATTERY_STATUS: {msg}")
    valid_msg = msg.voltages and len(msg.voltages) > 0
    if not valid_msg:
        logging.error('Received BATTERY_STATUS message with invalid data')
        return

    # Update battery
    drone_config.battery = msg.voltages[0] / 1E3  # convert from mV to V
    logging.debug(f"Updated battery voltage for drone {drone_config.hw_id}: {drone_config.battery}V")





# Start telemetry monitoring
telemetry_thread = threading.Thread(target=mavlink_monitor, args=(mav,))
telemetry_thread.start()

import struct


def send_packet_to_node(packet, ip, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(packet, (ip, port))

def get_nodes():
    # Cache nodes to avoid reading the file every time
    if hasattr(get_nodes, "nodes"):
        return get_nodes.nodes

    with open("config.csv", "r") as file:
        get_nodes.nodes = list(csv.DictReader(file))
    return get_nodes.nodes

# Function to get the current state of the drone
def get_drone_state():
    """
    Fetches the current state of the drone, including hardware id (hw_id), 
    position id (pos_id), current state, trigger time, position, velocity,
    battery voltage, and follow mode.
    
    The state variable indicates: 
    0 for unset trigger time, 1 for set trigger time, 2 for flying
    The trigger time is set to 0 if it has not been set yet

    Returns:
    dict: A dictionary containing the current state of the drone
    """
    drone_state = {
    "hw_id": int(drone_config.hw_id),
    "pos_id": int(drone_config.config['pos_id']),
    "state": int(drone_config.state),
    "mission": int(drone_config.mission),
    "trigger_time": int(drone_config.trigger_time),
    "position_lat": drone_config.position['lat'],
    "position_long": drone_config.position['long'],
    "position_alt": drone_config.position['alt'],
    "velocity_north": drone_config.velocity['vel_n'],
    "velocity_east": drone_config.velocity['vel_e'],
    "velocity_down": drone_config.velocity['vel_d'],
    "battery_voltage": drone_config.battery,
    "follow_mode": int(drone_config.swarm['follow'])
}


    return drone_state

def send_drone_state():
    """
    Sends the drone state over UDP to the GCS and optionally to other drones in the swarm.

    The state information includes hardware id, position id, current state, 
    trigger time, position, velocity, battery voltage, and follow mode.
    
    Each state variable is packed into a binary packet and sent every `TELEM_SEND_INTERVAL` seconds.
    If `broadcast_mode` is True, the state is also sent to all other drones in the swarm.

    The structure of the packet is as follows:
    - Start of packet (uint8)
    - Hardware ID (uint16)
    - Position ID (uint16)
    - State (uint8)
    - Trigger Time (uint32)
    - Latitude, Longitude, Altitude (double)
    - North, East, Down velocities (double)
    - Battery Voltage (double)
    - Follow Mode (uint8)
    - End of packet (uint8)
    """
    udp_ip = drone_config.config['gcs_ip']  # IP address of the ground station
    udp_port = int(drone_config.config['debug_port'])  # UDP port to send telemetry data to

    while True:
        drone_state = get_drone_state()

        # Create a struct format string based on the data types
        struct_fmt = '=BHHBBIdddddddBB'  # update this to match your data types
        # H is for uint16
        # B is for uint8
        # I is for uint32
        # d is for double (float64)
        # Pack the telemetry data into a binary packet
        #print(drone_state)
        packet = struct.pack(struct_fmt,
                             77,  # start of packet
                             drone_state['hw_id'],
                             drone_state['pos_id'],
                             drone_state['state'],
                             drone_state['mission'],
                             drone_state['trigger_time'],
                             drone_state['position_lat'],
                             drone_state['position_long'],
                             drone_state['position_alt'],
                             drone_state['velocity_north'],
                             drone_state['velocity_east'],
                             drone_state['velocity_down'],
                             drone_state['battery_voltage'],
                             drone_state['follow_mode'],
                             88)  # end of packet
        telem_packet_size = len(packet)
        # If broadcast_mode is True, send to all nodes
        if broadcast_mode:
            nodes = get_nodes()
            # Send to all other nodes
            for node in nodes:
                if int(node["hw_id"]) != drone_state['hw_id']:
                    send_packet_to_node(packet, node["ip"], int(node["debug_port"]))
                    #print(f'Sent telemetry {telem_packet_size} Bytes to drone {int(node["hw_id"])} with IP: {node["ip"]} ')


        # Always send to GCS
        send_packet_to_node(packet, udp_ip, udp_port)

        #print(f"Sent telemetry data to GCS: {packet}")
        #print(f"Sent telemetry {telem_packet_size} Bytes to GCS")
        #print(f"Values: hw_id: {drone_state['hw_id']}, state: {drone_state['state']}, Mission: {drone_state['mission']}, Latitude: {drone_state['position_lat']}, Longitude: {drone_state['position_long']}, Altitude : {drone_state['position_alt']}, follow_mode: {drone_state['follow_mode']}, trigger_time: {drone_state['trigger_time']}")
        current_time = int(time.time())
        #print(f"Current system time: {current_time}")
        
        # Update the global variable to keep track of the packet size

        time.sleep(TELEM_SEND_INTERVAL)  # send telemetry data every TELEM_SEND_INTERVAL seconds





def read_packets():
    """
    Reads and decodes new packets from the ground station over the debug vector.
    The packets can be either commands or telemetry data, depending on the header and terminator.

    For commands, the packets include the hardware id (hw_id), position id (pos_id), current state, and trigger time.
    For telemetry data, the packets include hardware id, position id, current state, trigger time, position, velocity, 
    battery voltage, and follow mode.

    After receiving a packet, the function checks the header and terminator to determine the type of the packet.
    Then, it unpacks the packet accordingly and processes the data.
    """
    udp_port = int(drone_config.config['debug_port'])  # UDP port to receive packets

    sock = socket.socket(socket.AF_INET,  # Internet
                         socket.SOCK_DGRAM)  # UDP
    sock.bind(('0.0.0.0', udp_port))
    while True:
        data, addr = sock.recvfrom(1024)  # buffer size is 1024 bytes
        header, terminator = struct.unpack('BB', data[0:1] + data[-1:])  # get the header and terminator

        # Check if it's a command packet
        if header == 55 and terminator == 66 and len(data) == command_packet_size:
            header, hw_id, pos_id, mission, state, trigger_time, terminator = struct.unpack('=B B B B B I B', data)
            print("Received command from GCS")
            #print(f"Values: hw_id: {hw_id}, pos_id: {pos_id}, mission: {mission}, state: {state}, trigger_time: {trigger_time}")
            drone_config.hw_id = hw_id
            drone_config.pos_id = pos_id
            drone_config.mission = mission
            drone_config.state = state
            drone_config.trigger_time = trigger_time
            # Add additional logic here to handle the received command


        # Check if it's a telemetry packet
        elif header == 77 and terminator == 88 and len(data) == telem_packet_size:
            
            # Decode the data
            struct_fmt = '=BHHBBIdddddddBB'  # Updated to match the new packet format
            header, hw_id, pos_id, state, mission, trigger_time, position_lat, position_long, position_alt, velocity_north, velocity_east, velocity_down, battery_voltage, follow_mode, terminator = struct.unpack(struct_fmt, data)
            #print(f"Received telemetry from Drone {hw_id}")
            #print(f"Received telemetry: Header={header}, HW_ID={hw_id}, Pos_ID={pos_id}, State={state}, mission={mission}, Trigger Time={trigger_time}, Position Lat={position_lat}, Position Long={position_long}, Position Alt={position_alt}, Velocity North={velocity_north}, Velocity East={velocity_east}, Velocity Down={velocity_down}, Battery Voltage={battery_voltage}, Follow Mode={follow_mode}, Terminator={terminator}")
            if hw_id not in drones:
                # Create a new instance for the drone
                drones[hw_id] = DroneConfig(hw_id)
        
            # Update the drone instance with the received telemetry data
            drones[hw_id].state = state
            drones[hw_id].mission = mission
            drones[hw_id].trigger_time = trigger_time
            drones[hw_id].mission = mission
            drones[hw_id].position = {'lat': position_lat, 'long': position_long, 'alt': position_alt}
            drones[hw_id].velocity = {'vel_n': velocity_north, 'vel_e': velocity_east, 'vel_d': velocity_down}
            drones[hw_id].battery = battery_voltage
            drones[hw_id].last_update_timestamp = time.time()  # Current timestamp
        
            # Add processing of the received telemetry data here
        else:
            print(f"Received packet of incorrect size or header.got {len(data)}.")
                
        if(drone_config.mission==2 and drone_config.state != 0 and int(drone_config.swarm.get('follow')) != 0 ):
            drone_config.calculate_setpoints()
        time.sleep(income_packet_check_interval)  # check for new packets every second 

        
        



# Function to synchronize time with a reliable internet source
def synchronize_time():
    # Report current time before sync

    if(online_sync_time):
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
    else:
        print(f"Using Current System Time witout Online synchronization: {datetime.datetime.now()}")

        


# Function to schedule the drone mission
def schedule_mission():
    # Constantly checks the current time vs trigger time
    # If it's time to trigger, it opens the offboard_from_csv_multiple.py separately

    current_time = int(time.time())
    #print(f"Current system time: {current_time}")
    #print(f"Target Trigger Time: {drone_config.trigger_time}")
    
    if drone_config.state == 1 and current_time >= drone_config.trigger_time:
        print("Trigger time reached. Starting drone mission...")
        # Reset the state and trigger time
        drone_config.state = 2
        drone_config.trigger_time = 0

        # Check the mission code
        if drone_config.mission == 1:  # For csv_droneshow
            # Run the mission script in a new process
            mission_process = subprocess.Popen(["python3", "offboard_multiple_from_csv.py"])
            
            # Note: Replace "offboard_from_csv_multiple.py" with the actual script for the drone mission
        elif drone_config.mission == 2:  # For smart_swarm
            print("Smart swarm mission should be started")
            # You can add logic here to start the smart swarm mission
            if(int(drone_config.swarm.get('follow')) != 0): 
                start_offboard_mode()
            



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
        time.sleep(2)
        # Start the telemetry thread
        print("Starting telemetry thread...")
        telemetry_thread = threading.Thread(target=send_drone_state)
        telemetry_thread.start()

        # Start the command reading thread
        print("Starting command reading thread...")
        command_thread = threading.Thread(target=read_packets)
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