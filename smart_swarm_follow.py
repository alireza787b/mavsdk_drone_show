import os
import asyncio
from mavsdk import System
import csv
from mavsdk.offboard import PositionNedYaw, VelocityNedYaw, AccelerationNed, OffboardError
from mavsdk.telemetry import LandedState
from mavsdk.action import ActionError
from mavsdk.telemetry import *
import subprocess
import signal
from collections import namedtuple
import functions.global_to_local
import glob



    
    
# Constants
STEP_TIME = 0.05
DEFAULT_Z = 0.83
GRPC_PORT_BASE = 50041
#UDP_PORT_BASE = 14541
SHOW_DEVIATIONS = False
SIM_MODE = False
#if set to false each drone will read its own HW_ID and initialize its offboard, otherwise all droness are being commanded
#set to False when uploaded to the companion computer to run in real world or doing HITL
#set to True for just visulizing all drones in one PC for SITL

config_file_name = 'config.csv'
swarm_file_name = 'swarm.csv' 

import os
import glob
import csv

class DroneConfig:
    def __init__(self, hw_id=None):
        self.hw_id = hw_id if hw_id is not None else self.find_hw_id()
        self.pos_id = None
        self.x = None
        self.y = None
        self.ip = None
        self.mavlink_port = None
        self.debug_port = None
        self.gcs_ip = None
        self.trigger_time = 0
        self.state = 0
        self.position = {'lat': 0, 'long': 0, 'alt': 0}
        self.velocity = {'vel_n': 0, 'vel_e': 0, 'vel_d': 0}
        self.battery = None
        self.follow = None
        self.offset_n = None
        self.offset_e = None
        self.offset_alt = None
        
        # Call to populate drone config and swarm details
        self.read_config()
        self.read_swarm()

    @staticmethod
    def find_hw_id():
        hwid_files = glob.glob('*.hwID')
        if hwid_files:
            filename = hwid_files[0]
            hw_id = os.path.splitext(filename)[0]  # Get filename without extension
            print(f"Hardware ID {hw_id} detected.")
            return int(hw_id)
        else:
            print("Hardware ID file not found.")
            return None

    def drones_count():
        with open(config_file_name, newline='') as csvfile:
            reader = csv.reader(csvfile)
            next(reader, None)  # Skip the header
            drone_count = sum(1 for row in reader)  # Count the number of rows
        return drone_count
    
    def read_config(self):
        with open(config_file_name, newline='') as csvfile:
            reader = csv.reader(csvfile)
            next(reader, None)  # Skip the header
            for row in reader:
                hw_id, pos_id, x, y, ip, mavlink_port, debug_port, gcs_ip = row
                if int(hw_id) == self.hw_id:
                    self.pos_id = pos_id
                    self.x = float(x)
                    self.y = float(y)
                    self.ip = ip
                    self.mavlink_port = mavlink_port
                    self.debug_port = debug_port
                    self.gcs_ip = gcs_ip
                    break

    def read_swarm(self):
        with open(swarm_file_name, newline='') as csvfile:
            reader = csv.reader(csvfile)
            next(reader, None)  # Skip the header
            for row in reader:
                hw_id, follow, offset_n, offset_e, offset_alt = row
                if int(hw_id) == self.hw_id:
                    self.follow = int(follow)
                    self.offset_n = float(offset_n)
                    self.offset_e = float(offset_e)
                    self.offset_alt = float(offset_alt)
                    break



if SIM_MODE:
    drone_ids = range(1, DroneConfig.drones_count() + 1)
    dronesConfig = {drone_id: DroneConfig(drone_id) for drone_id in drone_ids}
else:
    HW_ID = DroneConfig.find_hw_id()
    dronesConfig = {HW_ID: DroneConfig()}








global_position_telemetry = {}



async def get_global_position_telemetry(drone_id, drone):
    async for global_position in drone.telemetry.position():
        global_position_telemetry[drone_id] = global_position
        pass




async def initial_setup_and_connection(drone_id, udp_port):
    if (SIM_MODE==True):
        grpc_port = GRPC_PORT_BASE + drone_id
    else:
        grpc_port = GRPC_PORT_BASE - 1
    home_position = None
    
    mode_descriptions = {
    0: "On the ground",
    10: "Initial climbing state",
    20: "Initial holding after climb",
    30: "Moving to start point",
    40: "Holding at start point",
    50: "Moving to maneuvering start point",
    60: "Holding at maneuver start point",
    70: "Maneuvering (trajectory)",
    80: "Holding at the end of the trajectory coordinate",
    90: "Returning to home coordinate",
    100: "Landing"
    }

    drone = System(mavsdk_server_address="127.0.0.1", port=grpc_port)
    await drone.connect(system_address=f"udp://:{udp_port}")
    print(f"Drone connecting with UDP: {udp_port}")

    # Ensure future telem data
    asyncio.ensure_future(get_global_position_telemetry(drone_id, drone))
    
    # Check if the drone is connected
    async for state in drone.core.connection_state():
        if state.is_connected:
            print(f"Drone id {drone_id+1} connected on Port: {udp_port} and grpc Port: {grpc_port}")
            break

    return drone, home_position


async def pre_flight_checks(drone_id, drone):
    # Wait for the drone to have a global position estimate
    async for health in drone.telemetry.health():
        if health.is_global_position_ok and health.is_home_position_ok:
            print(f"Global position estimate ok {drone_id+1}")
            home_position = global_position_telemetry[drone_id]
            print(f"Home Position of {drone_id+1} set to: {home_position}")
            break

    return home_position


async def starting_offboard_mode(drone_id, drone):
    print(f"-- Setting initial setpoint {drone_id+1}")
    await drone.offboard.set_position_ned(PositionNedYaw(0.0, 0.0, 0.0, 0.0))
   #first offboard setpoint should be current position of drone not 0 0 0 .
    print(f"-- Starting offboard {drone_id+1}")
    try:
        await drone.offboard.start()
    except OffboardError as error:
        print(f"-- Disarming {drone_id+1}")
        await drone.action.disarm()
        return


async def perform_landing(drone_id, drone):
    print(f"-- Landing {drone_id+1}")
    await drone.action.land()

    async for state in drone.telemetry.landed_state():
        if state == LandedState.ON_GROUND:
            break

async def stop_offboard_mode(drone_id, drone):
    print(f"-- Stopping offboard {drone_id+1}")
    try:
        await drone.offboard.stop()
    except Exception as error:
        print(f"Stopping offboard mode failed with error: {error}")

async def disarm_drone(drone_id, drone):
    print(f"-- Disarming {drone_id+1}")
    await drone.action.disarm()



def start_mavsdk_servers(num_drones):
    # Start mavsdk_server instances for each drone
    mavsdk_servers = []
    for i in range(num_drones):
        if (SIM_MODE == True):
            port = GRPC_PORT_BASE + i
            mavsdk_server = subprocess.Popen(["./mavsdk_server", "-p", str(port), f"udp://:{dronesConfig[i].mavlink_port}"])
        else:
            port = 50040
            mavsdk_server = subprocess.Popen(["./mavsdk_server", "-p", str(port), f"udp://:{dronesConfig[HW_ID].mavlink_port}"])
        
        mavsdk_servers.append(mavsdk_server)
    return mavsdk_servers

async def run_all_drones(num_drones,home_positions, traejctory_offset, udp_ports):
    tasks = []
    for i in range(num_drones):
        if (SIM_MODE == True):
            drone_id = i
        else:
            drone_id = HW_ID
        tasks.append(asyncio.create_task(run_drone(drone_id,home_positions[i], dronesConfig[i].mavlink_port)))
    await asyncio.gather(*tasks)

def stop_all_mavsdk_servers(mavsdk_servers):
    # Kill all mavsdk_server processes
    for mavsdk_server in mavsdk_servers:
        os.kill(mavsdk_server.pid, signal.SIGTERM)


async def run_drone(drone_id,home_position_NED, trajectory_offset, udp_port, time_offset, altitude_offset):
    if (SIM_MODE == False):
        drone_id = 0
    # Call the initial setup and connection function
    drone, home_position = await initial_setup_and_connection(drone_id, udp_port)
    
    # Add time offset before starting the maneuver
    await asyncio.sleep(time_offset)


    # Perform pre-flight checks
    home_position = await pre_flight_checks(drone_id, drone)

    # start offboard mode
    await starting_offboard_mode(drone_id, drone)

   #here we should send offbaord position and velocitry setpoints

    


async def main():
    num_drones =  DroneConfig.drones_count()

    mavsdk_servers = start_mavsdk_servers(num_drones)
    await run_all_drones(num_drones,home_positions)
    stop_all_mavsdk_servers(mavsdk_servers)
    print("All tasks completed. Exiting program.")

if __name__ == "__main__":
    asyncio.run(main())
