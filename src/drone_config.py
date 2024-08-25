# src/drone_config.py
import csv
import glob
import logging
import math
from geographiclib.geodesic import Geodesic
import navpy
import numpy as np
import requests
from src.params import Params
from src.filter import KalmanFilter

class DroneConfig:
    def __init__(self,drones, hw_id=None):
        self.hw_id = self.get_hw_id(hw_id)  # Unique hardware ID for the drone
        self.trigger_time = 0
        self.config = self.read_config()  # Read configuration settings
        self.swarm = self.read_swarm()  # Read swarm configuration
        self.state = 0  # Initial state of the drone
        self.pos_id = self.get_hw_id(hw_id)  # Position ID, typically same as hardware ID
        self.mission = 0  # Current mission state
        self.trigger_time = 0  # Time of the last trigger event

        # Position and velocity information
        self.position = {'lat': 0, 'long': 0, 'alt': 0}
        self.velocity = {'north': 0, 'east': 0, 'down': 0}
        self.yaw = 0  # Yaw angle in degrees

        # Battery voltage
        self.battery = 0  # Voltage in volts
        self.last_update_timestamp = 0  # Timestamp of the last telemetry update

        # Home position, set after receiving the first valid HOME_POSITION message
        self.home_position = None

        # Setpoints for position and velocity in both LLA (Lat, Long, Alt) and NED (North, East, Down) coordinates
        self.position_setpoint_LLA = {'lat': 0, 'long': 0, 'alt': 0}
        self.position_setpoint_NED = {'north': 0, 'east': 0, 'down': 0}
        self.velocity_setpoint_NED = {'north': 0, 'east': 0, 'down': 0}
        self.yaw_setpoint = 0  # Yaw setpoint in degrees

        # Target drone for swarm operations (if applicable)
        self.target_drone = None
        self.drones = drones  # List of drones in the swarm

        # Kalman filter instance for state estimation (optional)
        self.kalman_filter = KalmanFilter()  # Initialize Kalman Filter

        # Altitude for takeoff
        self.takeoff_altitude = Params.default_takeoff_alt

        # GPS data
        self.hdop = 0  # Horizontal dilution of precision
        self.vdop = 0  # Vertical dilution of precision (new field)

        # MAVLink mode and system status (new fields)
        self.mav_mode = 0  # MAV_MODE value from the MAVLink HEARTBEAT message
        self.system_status = 0  # System status from the MAVLink HEARTBEAT message

        # Sensor health and calibration statuses
        self.is_gyrometer_calibration_ok = False
        self.is_accelerometer_calibration_ok = False
        self.is_magnetometer_calibration_ok = False


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
        if Params.offline_config:
            return self.read_file('config.csv', 'local CSV file', self.hw_id)
        else:
            print("Loading configuration from online source...")
            try:
                print(f'Attempting to download file from: {Params.config_url}')
                response = requests.get(Params.config_url)

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
        if Params.offline_swarm:
            return self.read_file('swarm.csv', 'local CSV file', self.hw_id)
        else:
            print("Loading swarm configuration from online source...")
            try:
                print(f'Attempting to download file from: {Params.swarm_url}')
                response = requests.get(Params.swarm_url)

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

