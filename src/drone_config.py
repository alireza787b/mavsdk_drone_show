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
from src.drone_setup import DroneSetup

class DroneConfig:
    """
    This class holds all configuration and state data for a drone.
    It manages configuration files, swarm behavior, and telemetry data processing.
    """
    def __init__(self, drones, hw_id=None):
        """
        Initializes the drone configuration, including hardware ID, swarm setup,
        and configuration files.
        """
        self.hw_id = self.get_hw_id(hw_id)  # Unique hardware ID for the drone
        self.config = self.read_config()  # Read configuration settings from CSV or online source
        self.swarm = self.read_swarm()  # Read swarm configuration
        self.pos_id = self.config.get('pos_id', self.hw_id)  # Initialize pos_id from config or hw_id
        self.detected_pos_id = 0  # Initially, detected pos_id is 0 meaning undetected
        self.state = 0  # Initial state of the drone
        self.mission = 0  # Current mission state
        self.last_mission = 0
        self.trigger_time = 0  # Time of the last trigger event
        self.drone_setup = None
        self.position = {'lat': 0, 'long': 0, 'alt': 0}  # Initial position (lat, long, alt)
        self.velocity = {'north': 0, 'east': 0, 'down': 0}  # Initial velocity components
        self.yaw = 0  # Yaw angle in degrees

        # Battery voltage and last update timestamp
        self.battery = 0  # Battery voltage in volts
        self.last_update_timestamp = 0  # Timestamp of the last telemetry update

        # Home position (initialized after receiving the first valid HOME_POSITION message)
        self.home_position = None

        # Target drone for swarm operations (if applicable)
        self.target_drone = None
        self.drones = drones  # List of drones in the swarm

        # Altitude for takeoff (from Params)
        self.takeoff_altitude = Params.default_takeoff_alt

        # GPS and MAVLink data
        self.hdop = 0  # Horizontal dilution of precision
        self.vdop = 0  # Vertical dilution of precision
        self.mav_mode = 0  # MAVLink mode
        self.system_status = 0  # System status from MAVLink HEARTBEAT message

        # Sensor calibration statuses
        self.is_gyrometer_calibration_ok = False
        self.is_accelerometer_calibration_ok = False
        self.is_magnetometer_calibration_ok = False

        # Load all configurations for auto-detection
        self.all_configs = self.load_all_configs()

    def get_hw_id(self, hw_id=None):
        """
        Retrieve the hardware ID either from the provided ID or from a local file.
        If hw_id is provided, it is used; otherwise, it is fetched from a .hwID file.
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
        If offline_config is true, local CSV is used; otherwise, the configuration is fetched online.
        """
        if Params.offline_config:
            return self.read_file(Params.config_csv_name, 'local CSV file', self.hw_id)
        else:
            return self.fetch_online_config(Params.config_url, 'online_config.csv')

    def read_swarm(self):
        """
        Reads the swarm configuration file, which includes the list of nodes in the swarm.
        """
        if Params.offline_swarm:
            return self.read_file(Params.swarm_csv_name, 'local CSV file', self.hw_id)
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
    
    def load_all_configs(self):
        """
        Load all drone configurations from config.csv.
        """
        all_configs = {}
        try:
            with open(Params.config_csv_name, newline='') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    pos_id = int(row['pos_id'])
                    x = float(row['x'])
                    y = float(row['y'])
                    all_configs[pos_id] = {'x': x, 'y': y}
            logging.info("All drone configurations loaded successfully.")
        except FileNotFoundError:
            logging.error(f"Config file {Params.config_csv_name} not found.")
        except Exception as e:
            logging.error(f"Error loading all drone configurations: {e}")
        return all_configs

    def find_target_drone(self):
        """
        Determine which drone this drone should follow in a swarm configuration.
        This is useful for swarm behavior where one drone follows another.
        """
        follow_hw_id = int(self.swarm.get('follow', 0))  # Get the target drone's hw_id
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

    def radian_to_degrees_heading(self, yaw_radians):
        """
        Convert the yaw angle from radians to degrees and normalize it to a heading (0-360 degrees).
        """
        yaw_degrees = math.degrees(yaw_radians)
        return yaw_degrees if yaw_degrees >= 0 else yaw_degrees + 360
