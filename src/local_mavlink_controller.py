import threading
import logging
from pymavlink import mavutil
import time

class LocalMavlinkController:
    """
    The LocalMavlinkController class manages telemetry data received from the local Mavlink connection.
    It reads incoming Mavlink messages in a separate thread and updates the drone_config object accordingly.
    
    Args:
        drone_config: A configuration object which contains drone details like position, velocity, etc.
        params: Configuration parameters such as local Mavlink port and telemetry refresh interval.
    """
    
    def __init__(self, drone_config, params):
        """
        Initialize the controller, set up the Mavlink connection, and start the telemetry monitoring thread.
        """
        self.latest_messages = {}
        # Define which message types to listen for
        self.message_filter = [
            'GLOBAL_POSITION_INT', 'HOME_POSITION', 'BATTERY_STATUS', 
            'ATTITUDE', 'HEARTBEAT', 'GPS_RAW_INT', 'SYS_STATUS'
        ]
        
        # Create a Mavlink connection using the provided local Mavlink port
        self.mav = mavutil.mavlink_connection(f"udp:localhost:{params.local_mavlink_port}")
        self.drone_config = drone_config
        self.local_mavlink_refresh_interval = params.local_mavlink_refresh_interval
        self.run_telemetry_thread = threading.Event()
        self.run_telemetry_thread.set()

        # Start the telemetry monitoring thread
        self.telemetry_thread = threading.Thread(target=self.mavlink_monitor)
        self.telemetry_thread.start()
        self.home_position_logged = False

    def mavlink_monitor(self):
        """
        Continuously monitor for incoming Mavlink messages and process them.
        """
        while self.run_telemetry_thread.is_set():
            msg = self.mav.recv_match(type=self.message_filter, blocking=True, timeout=5)  # 5-second timeout
            if msg is not None:
                self.process_message(msg)
                self.latest_messages[msg.get_type()] = msg
            else:
                logging.warning('No MAVLink message received within timeout period')

    def process_message(self, msg):
        """
        Process incoming Mavlink messages based on their type and update the drone_config object.
        """
        msg_type = msg.get_type()
        self.latest_messages[msg_type] = msg

        if msg_type == 'GLOBAL_POSITION_INT':
            self.process_global_position_int(msg)
        elif msg_type == 'HOME_POSITION':
            self.set_home_position(msg)
        elif msg_type == 'BATTERY_STATUS':
            self.process_battery_status(msg)
        elif msg_type == 'ATTITUDE':
            self.process_attitude(msg)
        elif msg_type == 'HEARTBEAT':
            self.process_heartbeat(msg)
        elif msg_type == 'GPS_RAW_INT':
            self.process_gps_raw_int(msg)
        elif msg_type == 'SYS_STATUS':
            self.process_sys_status(msg)
        else:
            logging.debug(f"Received unhandled message type: {msg.get_type()}")

    def process_heartbeat(self, msg):
        """
        Process the HEARTBEAT message and update flight mode and system status.
        """
        # Store the current MAV mode (e.g., armed, preflight, etc.)
        self.drone_config.mav_mode = msg.base_mode
        self.drone_config.system_status = msg.system_status
        logging.debug(f"Updated MAV_MODE to: {self.drone_config.mav_mode}, SYSTEM_STATUS to: {self.drone_config.system_status}")

    def process_sys_status(self, msg):
        """
        Process the SYS_STATUS message and update sensor health statuses.
        """
        # Check if sensors are healthy and calibrated
        self.drone_config.is_gyrometer_calibration_ok = (msg.onboard_control_sensors_health & mavutil.mavlink.MAV_SYS_STATUS_SENSOR_3D_GYRO) != 0
        self.drone_config.is_accelerometer_calibration_ok = (msg.onboard_control_sensors_health & mavutil.mavlink.MAV_SYS_STATUS_SENSOR_3D_ACCEL) != 0
        self.drone_config.is_magnetometer_calibration_ok = (msg.onboard_control_sensors_health & mavutil.mavlink.MAV_SYS_STATUS_SENSOR_3D_MAG) != 0
        logging.debug(f"Sensor health updated: Gyro: {self.drone_config.is_gyrometer_calibration_ok}, "
                      f"Accel: {self.drone_config.is_accelerometer_calibration_ok}, Mag: {self.drone_config.is_magnetometer_calibration_ok}")

    def process_gps_raw_int(self, msg):
        """
        Process the GPS_RAW_INT message and update GPS data including HDOP and VDOP.
        """
        # Update GPS data including HDOP and VDOP (if available)
        self.drone_config.hdop = msg.eph / 1E2  # Horizontal dilution of precision
        self.drone_config.vdop = msg.epv / 1E2  # Vertical dilution of precision (if applicable)
        logging.debug(f"Updated GPS HDOP to: {self.drone_config.hdop}, VDOP to: {self.drone_config.vdop}")

    def process_attitude(self, msg):
        """
        Process the ATTITUDE message and update the yaw value.
        """
        if msg.yaw is not None:
            self.drone_config.yaw = self.drone_config.radian_to_degrees_heading(msg.yaw)
        else:
            logging.error('Received ATTITUDE message with invalid data')

    def set_home_position(self, msg):
        """
        Process the HOME_POSITION message and set the home position.
        """
        if msg.latitude is not None and msg.longitude is not None and msg.altitude is not None:
            self.drone_config.home_position = {
                'lat': msg.latitude / 1E7,
                'long': msg.longitude / 1E7,
                'alt': msg.altitude / 1E3
            }

            if not self.home_position_logged:
                logging.info(f"Home position for drone {self.drone_config.hw_id} is set: {self.drone_config.home_position}")
                self.home_position_logged = True
        else:
            logging.error('Received HOME_POSITION message with invalid data')

    def process_global_position_int(self, msg):
        """
        Process the GLOBAL_POSITION_INT message and update the position and velocity.
        """
        if msg.lat is not None and msg.lon is not None and msg.alt is not None:
            self.drone_config.position = {
                'lat': msg.lat / 1E7,
                'long': msg.lon / 1E7,
                'alt': msg.alt / 1E3
            }
            self.drone_config.velocity = {
                'north': msg.vx / 1E2,
                'east': msg.vy / 1E2,
                'down': msg.vz / 1E2
            }
            self.drone_config.last_update_timestamp = int(time.time())

            if self.drone_config.home_position is None:
                self.drone_config.home_position = self.drone_config.position.copy()
                logging.info(f"Home position for drone {self.drone_config.hw_id} is set to current position: {self.drone_config.home_position}")
        else:
            logging.error('Received GLOBAL_POSITION_INT message with invalid data')

    def process_battery_status(self, msg):
        """
        Process the BATTERY_STATUS message and update the battery voltage.
        """
        if msg.voltages and len(msg.voltages) > 0:
            self.drone_config.battery = msg.voltages[0] / 1E3  # Convert from mV to V
        else:
            logging.error('Received BATTERY_STATUS message with invalid data')

    def __del__(self):
        """
        Ensure the telemetry thread is stopped when the object is deleted.
        """
        self.run_telemetry_thread.clear()

        # Wait for the telemetry thread to stop
        if self.telemetry_thread.is_alive():
            self.telemetry_thread.join()
