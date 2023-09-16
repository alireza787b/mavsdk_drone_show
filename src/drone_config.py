"""
DroneConfig class:

    Holds drone configuration data and handles related operations, including reading configuration files, 
    calculating setpoints, and converting coordinates.

Variables:
    hw_id (str): The hardware ID of the drone.
    trigger_time (int): The time of the trigger event.
    config (dict): Drone configuration read from a CSV file.
    swarm (dict): Swarm configuration read from a CSV file.
    state (int): The current state of the drone.
    pos_id (int): The positional ID of the drone.
    mission (int): The mission that the drone is on.
    position (dict): Current drone position in the format {'lat': 0, 'long': 0, 'alt': 0}.
    velocity (dict): Current drone velocity in the format {'vel_n': 0, 'vel_e': 0, 'vel_d': 0}.
    yaw (float): The yaw of the drone.
    battery (float): The battery voltage of the drone.
    last_update_timestamp (float): The timestamp of the last update.
    home_position (dict): Drone's home position.
    position_setpoint_LLA (dict): Desired position setpoint in LLA format {'lat': 0, 'long': 0, 'alt': 0}.
    position_setpoint_NED (dict): Desired position setpoint in NED format {'north': 0, 'east': 0, 'down': 0}.
    velocity_setpoint_NED (dict): Desired velocity setpoint in NED format {'north': 0, 'east': 0, 'down': 0}.
    yaw_setpoint (float): Desired yaw setpoint.
    target_drone (DroneConfig): The drone instance that this drone is following.
    drones (dict): A dictionary of drones where the key is the hardware ID of the drone and the value is a DroneConfig instance.

Methods:
    get_hw_id(hw_id=None): Returns the hardware ID of the drone.
        Inputs:
            - hw_id (str): Optional. The hardware ID. If not specified, it reads from a .hwID file.
        Outputs:
            - hw_id (str): The hardware ID of the drone.

    read_file(filename, source, hw_id): Reads a configuration file and returns configuration for the drone with the specified hardware ID.
        Inputs:
            - filename (str): The filename of the CSV file to read.
            - source (str): The source of the file ('local CSV file' or 'online CSV file').
            - hw_id (str): The hardware ID of the drone.
        Outputs:
            - config (dict): The configuration for the drone.

    read_config(): Reads the drone configuration file and returns the configuration for the drone. Supports offline and online modes.
        Outputs:
            - config (dict): The configuration for the drone.

    read_swarm(): Reads the swarm configuration file and returns the swarm configuration for the drone. Supports offline and online modes.
        Outputs:
            - swarm (dict): The swarm configuration for the drone.

    calculate_setpoints(): Finds the drone to follow and calculates position, velocity, and yaw setpoints.

    find_target_drone(): Determines the drone that this drone should follow.

    calculate_position_setpoint_LLA(): Calculates position setpoint in LLA format based on target drone's position and offset.

    calculate_position_setpoint_NED(): Converts position setpoint from LLA format to NED format.

    calculate_velocity_setpoint_NED(): Sets the velocity setpoint to match the target drone's velocity.

    calculate_yaw_setpoint(): Sets the yaw setpoint to match the target drone's yaw.

    convert_LLA_to_NED(LLA): Converts coordinates from LLA format to NED format.
        Inputs:
            - LLA (dict): Position in LLA format {'lat': 0, 'long': 0, 'alt': 0}.
        Outputs:
            - position_NED (dict): Position in NED format {'north': 0, 'east': 0, 'down': 0}.

    radian_to_degrees_heading(yaw_radians): Converts yaw from radians to degrees heading.
        Inputs:
            - yaw_radians (float): Yaw in radians.
        Outputs:
            - yaw_degrees (float): Yaw in degrees heading (0-360 degrees).
"""



import csv
import glob
import logging
import math
from geographiclib.geodesic import Geodesic
import navpy
import numpy as np
import requests
from src.params import Params as params
from src.filter import KalmanFilter

class DroneConfig:
    def __init__(self,drones, hw_id=None):
        self.hw_id = self.get_hw_id(hw_id)
        self.trigger_time = 0
        self.config = self.read_config()
        self.swarm = self.read_swarm()
        self.state = 0
        self.pos_id = self.get_hw_id(hw_id)
        self.mission = 0
        self.trigger_time = 0
        self.position = {'lat': 0, 'long': 0, 'alt': 0}
        self.velocity = {'nort': 0, 'east': 0, 'down': 0}
        self.yaw = 0
        self.battery = 0
        self.last_update_timestamp = 0
        self.home_position = None
        self.position_setpoint_LLA = {'lat': 0, 'long': 0, 'alt': 0}
        self.position_setpoint_NED = {'north': 0, 'east': 0, 'down': 0}
        self.velocity_setpoint_NED = {'north': 0, 'east': 0, 'down': 0}
        self.yaw_setpoint=0
        self.target_drone = None
        self.drones = drones
        self.kalman_filter = KalmanFilter() # New line


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
        if params.offline_config:
            return self.read_file('config.csv', 'local CSV file', self.hw_id)
        else:
            print("Loading configuration from online source...")
            try:
                print(f'Attempting to download file from: {params.config_url}')
                response = requests.get(params.config_url)

                if response.status_code != 200:
                    print(f'Error downloading file: {response.status_code} {response.reason}')
                    return None

                with open('online_params.csv', 'w') as f:
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
        if params.offline_swarm:
            return self.read_file('swarm.csv', 'local CSV file', self.hw_id)
        else:
            print("Loading swarm configuration from online source...")
            try:
                print(f'Attempting to download file from: {params.swarm_url}')
                response = requests.get(params.swarm_url)

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
    
    def find_target_drone(self):
        # find which drone it should follow
        follow_hw_id = int(self.swarm['follow'])
        if follow_hw_id == 0:
            print(f"Drone {self.hw_id} is a master drone and not following anyone.")
        elif follow_hw_id == self.hw_id:
            print(f"Drone {self.hw_id} is set to follow itself. This is not allowed.")
        else:
            self.target_drone = self.drones[follow_hw_id]
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
    
    def calculate_setpoints(self):
        if self.mission == 2:
            self.find_target_drone()

            if self.target_drone:
                self.calculate_position_setpoint_NED()
                self.calculate_velocity_setpoint_NED()
                self.calculate_yaw_setpoint()
                logging.debug(f"Setpoint updated | Position: [N:{self.position_setpoint_NED.get('north')}, E:{self.position_setpoint_NED.get('east')}, D:{self.position_setpoint_NED.get('down')}] | Velocity: [N:{self.velocity_setpoint_NED.get('north')}, E:{self.velocity_setpoint_NED.get('east')}, D:{self.velocity_setpoint_NED.get('down')}] | following drone {self.target_drone.hw_id}, with offsets [N:{self.swarm.get('offset_n', 0)},E:{self.swarm.get('offset_e', 0)},Alt:{self.swarm.get('offset_alt', 0)}]")

                # Initialize the Kalman Filter with the first setpoint if needed
                self.kalman_filter.initialize_if_needed(self.position_setpoint_NED, self.velocity_setpoint_NED)

                # Prediction Step
                self.kalman_filter.predict()

                # Get the last predicted accelerations from the Kalman Filter's state
                last_predicted_accel_north = self.kalman_filter.state[2]
                last_predicted_accel_east = self.kalman_filter.state[5]
                last_predicted_accel_down = self.kalman_filter.state[8]

                # Update Step using the setpoints as the measurement
                measurement = np.array([
                    self.position_setpoint_NED['north'],
                    self.velocity_setpoint_NED['north'],
                    last_predicted_accel_north,
                    self.position_setpoint_NED['east'],
                    self.velocity_setpoint_NED['east'],
                    last_predicted_accel_east,
                    self.position_setpoint_NED['down'],
                    self.velocity_setpoint_NED['down'],
                    last_predicted_accel_down
                ])
                self.kalman_filter.update(measurement)


    def calculate_position_setpoint_NED(self):
        if self.target_drone:
            # Convert the target drone's LLA to NED
            target_position_NED = self.convert_LLA_to_NED(self.target_drone.position)

            # Get the offsets
            offset_n = float(self.swarm.get('offset_n', 0))
            offset_e = float(self.swarm.get('offset_e', 0))
            offset_alt = float(self.swarm.get('offset_alt', 0))

            # Apply the offsets
            self.position_setpoint_NED = {
                'north': target_position_NED['north'] + offset_n,
                'east': target_position_NED['east'] + offset_e,
                'down': target_position_NED['down'] - offset_alt,
            }
        else:
            print(f"No target drone found for drone with hw_id: {self.hw_id}")


    def calculate_velocity_setpoint_NED(self):
        # velocity setpoints is exactly the same as the target drone velocity
        if self.target_drone:
            self.velocity_setpoint_NED = self.target_drone.velocity
            #print(f"NED Velocity setpoint for drone {self.hw_id}: {self.velocity_setpoint_NED}")
        else:
            print(f"No target drone found for drone with hw_id: {self.hw_id}")

    def calculate_yaw_setpoint(self):
        if self.target_drone:
            self.yaw_setpoint = self.target_drone.yaw
            #print(f"Yaw setpoint for drone {self.hw_id}: {self.yaw_setpoint}")
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

        
    def radian_to_degrees_heading(self,yaw_radians):
        # Convert the yaw angle to degrees
        yaw_degrees = math.degrees(yaw_radians)

        # Normalize to a heading (0-360 degrees)
        if yaw_degrees < 0:
            yaw_degrees += 360

        return yaw_degrees

