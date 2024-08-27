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
    """
    This class holds all configuration and state data for a drone.
    It manages configuration files, swarm behavior, and telemetry data processing.
    """
    def __init__(self, drones, hw_id=None):
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
        """
        Retrieve the hardware ID either from the provided ID or from a local file.
        """
        if hw_id is not None:
            return hw_id

        hw_id_files = glob.glob("*.hwID")
        if hw_id_files:
            hw_id_file = hw_id_files[0]
            logging.info(f"Hardware ID file found: {hw_id_file}")
            hw_id = hw_id_file.split(".")[0]
            logging.info(f"Hardware ID: {hw_id}")
            return hw_id
        else:
            logging.error("Hardware ID file not found. Please check your files.")
            return None

    def read_file(self, filename, source, hw_id):
        """
        Read a CSV configuration file and return the configuration for the given hardware ID.
        """
        try:
            with open(filename, newline='') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    if row['hw_id'] == hw_id:
                        logging.info(f"Configuration for HW_ID {hw_id} found in {source}.")
                        return row
        except FileNotFoundError:
            logging.error(f"File not found: {filename}")
        except Exception as e:
            logging.error(f"Error reading file {filename}: {e}")
        return None

    def read_config(self):
        """
        Read configuration either from a local CSV file or from an online source.
        """
        if Params.offline_config:
            return self.read_file('config.csv', 'local CSV file', self.hw_id)
        else:
            return self.fetch_online_config(Params.config_url, 'online_config.csv')

    def read_swarm(self):
        """
        Reads the swarm configuration file, which includes the list of nodes in the swarm.
        """
        if Params.offline_swarm:
            return self.read_file('swarm.csv', 'local CSV file', self.hw_id)
        else:
            return self.fetch_online_config(Params.swarm_url, 'online_swarm.csv')

    def fetch_online_config(self, url, local_filename):
        """
        Fetch configuration from an online source and save it locally.
        """
        logging.info(f"Loading configuration from {url}...")
        try:
            response = requests.get(url)

            if response.status_code != 200:
                logging.error(f'Error downloading file: {response.status_code} {response.reason}')
                return None

            with open(local_filename, 'w') as f:
                f.write(response.text)

            return self.read_file(local_filename, 'online CSV file', self.hw_id)

        except Exception as e:
            logging.error(f"Failed to load online configuration: {e}")
            return None
    
    def find_target_drone(self):
        """
        Determine which drone this drone should follow in a swarm configuration.
        """
        follow_hw_id = int(self.swarm['follow'])
        if follow_hw_id == 0:
            logging.info(f"Drone {self.hw_id} is a master drone and not following anyone.")
        elif follow_hw_id == self.hw_id:
            logging.error(f"Drone {self.hw_id} is set to follow itself. This is not allowed.")
        else:
            self.target_drone = self.drones.get(follow_hw_id)
            if self.target_drone:
                logging.info(f"Drone {self.hw_id} is following drone {self.target_drone.hw_id}")
            else:
                logging.error(f"No target drone found for drone with hw_id: {self.hw_id}")

    def calculate_position_setpoint_LLA(self):
        """
        Calculate position setpoint in Latitude, Longitude, and Altitude (LLA).
        """
        if self.target_drone:
            offset_n = self.swarm.get('offset_n', 0)
            offset_e = self.swarm.get('offset_e', 0)
            offset_alt = self.swarm.get('offset_alt', 0)

            geod = Geodesic.WGS84  # Define the WGS84 ellipsoid
            g = geod.Direct(float(self.target_drone.position['lat']), float(self.target_drone.position['long']), 90, float(offset_e))
            g = geod.Direct(g['lat2'], g['lon2'], 0, float(offset_n))

            self.position_setpoint_LLA = {
                'lat': g['lat2'],
                'long': g['lon2'],
                'alt': float(self.target_drone.position['alt']) + float(offset_alt),  
            }

            logging.debug(f"Position setpoint for drone {self.hw_id}: {self.position_setpoint_LLA}")
        else:
            logging.error(f"No target drone found for drone with hw_id: {self.hw_id}")
    
    def calculate_setpoints(self):
        """
        Calculate position, velocity, and yaw setpoints based on the current mission.
        """
        if self.mission == 2:
            self.find_target_drone()

            if self.target_drone:
                self.calculate_position_setpoint_NED()
                self.calculate_velocity_setpoint_NED()
                self.calculate_yaw_setpoint()
                logging.debug(f"Setpoint updated | Position: {self.position_setpoint_NED} | Velocity: {self.velocity_setpoint_NED}")

                self.kalman_filter.initialize_if_needed(self.position_setpoint_NED, self.velocity_setpoint_NED)
                self.kalman_filter.predict()
                self.kalman_filter.update(self.build_kalman_measurement())

    def build_kalman_measurement(self):
        """
        Build the measurement array for the Kalman filter update step.
        """
        last_predicted_accel_north = self.kalman_filter.state[2]
        last_predicted_accel_east = self.kalman_filter.state[5]
        last_predicted_accel_down = self.kalman_filter.state[8]

        return np.array([
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

    def calculate_position_setpoint_NED(self):
        """
        Calculate position setpoint in North, East, Down (NED) coordinates.
        """
        if self.target_drone:
            target_position_NED = self.convert_LLA_to_NED(self.target_drone.position)
            self.position_setpoint_NED = {
                'north': target_position_NED['north'] + float(self.swarm.get('offset_n', 0)),
                'east': target_position_NED['east'] + float(self.swarm.get('offset_e', 0)),
                'down': target_position_NED['down'] - float(self.swarm.get('offset_alt', 0)),
            }
        else:
            logging.error(f"No target drone found for drone with hw_id: {self.hw_id}")

    def calculate_velocity_setpoint_NED(self):
        """
        Set the velocity setpoints to match the target drone's velocity.
        """
        if self.target_drone:
            self.velocity_setpoint_NED = self.target_drone.velocity
        else:
            logging.error(f"No target drone found for drone with hw_id: {self.hw_id}")

    def calculate_yaw_setpoint(self):
        """
        Set the yaw setpoint to match the target drone's yaw.
        """
        if self.target_drone:
            self.yaw_setpoint = self.target_drone.yaw
        else:
            logging.error(f"No target drone found for drone with hw_id: {self.hw_id}")

    def convert_LLA_to_NED(self, LLA):
        """
        Convert Latitude, Longitude, Altitude (LLA) to North, East, Down (NED) coordinates.
        """
        if self.home_position:
            ned = navpy.lla2ned(LLA['lat'], LLA['long'], LLA['alt'], self.home_position['lat'], self.home_position['long'], self.home_position['alt'])
            return {'north': ned[0], 'east': ned[1], 'down': ned[2]}
        else:
            logging.error("Home position is not set")
            return None

    def radian_to_degrees_heading(self, yaw_radians):
        """
        Convert the yaw angle from radians to degrees and normalize it to a heading (0-360 degrees).
        """
        yaw_degrees = math.degrees(yaw_radians)
        return yaw_degrees if yaw_degrees >= 0 else yaw_degrees + 360


