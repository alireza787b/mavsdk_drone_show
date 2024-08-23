import threading
import logging
from pymavlink import mavutil
import time

class LocalMavlinkController:
    """
    The LocalMavlinkController class is responsible for managing the telemetry data received from the local Mavlink 
    connection. It reads incoming Mavlink messages in a separate thread and updates the drone_config object accordingly.
    
    Args:
        drone_config: A configuration object which contains drone details like position, velocity, etc.
        local_mavlink_port
        local_mavlink_refresh_interval: The time interval in seconds between two telemetry updates.
    """
    
    def __init__(self, drone_config, params):
        """
        The constructor starts a new thread which reads Mavlink messages and updates the drone_config object.
        """
        
        # Create a dictionary to store the latest message of each type
        self.latest_messages = {}
        # Set the message filter to include additional types for flight mode, HDOP, and system status
        self.message_filter = ['GLOBAL_POSITION_INT', 'HOME_POSITION', 'BATTERY_STATUS', 'ATTITUDE', 'HEARTBEAT', 'GPS_RAW_INT', 'SYS_STATUS']
        
        # Create a Mavlink connection to the drone. Replace "local_mavlink_port" with the actual port.
        self.mav = mavutil.mavlink_connection(f"udp:localhost:{params.local_mavlink_port}")
        self.drone_config = drone_config
        self.local_mavlink_refresh_interval = params.local_mavlink_refresh_interval
        self.run_telemetry_thread = threading.Event()
        self.run_telemetry_thread.set()

        # Start telemetry monitoring
        self.telemetry_thread = threading.Thread(target=self.mavlink_monitor)
        self.telemetry_thread.start()
        self.home_position_logged = False
    
    def mavlink_monitor(self):
        while self.run_telemetry_thread.is_set():
            msg = self.mav.recv_match(type=self.message_filter, blocking=True, timeout=5)  # 5-second timeout
            if msg is not None:
                self.process_message(msg)
                self.latest_messages[msg.get_type()] = msg
            else:
                logging.warning('No MAVLink message received within timeout period')

    def process_message(self, msg):
        # Update the latest message of the received type
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
        # Store the raw flight mode
        self.drone_config.flight_mode_raw = msg.custom_mode

        # Check if the system is armable
        is_armable = (msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED) == 0 and \
                     (msg.system_status == mavutil.mavlink.MAV_STATE_STANDBY)

        # Update armable status
        self.drone_config.is_armable = is_armable
        logging.debug(f"Updated armable status to: {self.drone_config.is_armable}")

    def process_sys_status(self, msg):
        # Check if sensors are healthy and calibrated
        is_gyrometer_calibration_ok = (msg.onboard_control_sensors_health & mavutil.mavlink.MAV_SYS_STATUS_SENSOR_3D_GYRO) != 0
        is_accelerometer_calibration_ok = (msg.onboard_control_sensors_health & mavutil.mavlink.MAV_SYS_STATUS_SENSOR_3D_ACCEL) != 0
        is_magnetometer_calibration_ok = (msg.onboard_control_sensors_health & mavutil.mavlink.MAV_SYS_STATUS_SENSOR_3D_MAG) != 0

        # Update health status in drone_config
        self.drone_config.is_gyrometer_calibration_ok = is_gyrometer_calibration_ok
        self.drone_config.is_accelerometer_calibration_ok = is_accelerometer_calibration_ok
        self.drone_config.is_magnetometer_calibration_ok = is_magnetometer_calibration_ok
        logging.debug(f"Sensor calibration status updated: Gyro: {is_gyrometer_calibration_ok}, "
                      f"Accel: {is_accelerometer_calibration_ok}, Mag: {is_magnetometer_calibration_ok}")

    def process_gps_raw_int(self, msg):
        # Store HDOP value directly
        self.drone_config.hdop = msg.eph / 1E2
        # logging.debug(f"Updated HDOP to: {self.drone_config.hdop}")

    def process_attitude(self, msg):
        valid_msg = msg.yaw is not None
        if not valid_msg:
            logging.error('Received ATTITUDE message with invalid data')
            return

        # Update yaw
        self.drone_config.yaw = self.drone_config.radian_to_degrees_heading(msg.yaw)

    def set_home_position(self, msg):
        valid_msg = msg.latitude is not None and msg.longitude is not None and msg.altitude is not None
        if not valid_msg:
            logging.error('Received HOME_POSITION message with invalid data')
            return
        
        # Update home position
        self.drone_config.home_position = {
            'lat': msg.latitude / 1E7,
            'long': msg.longitude / 1E7,
            'alt': msg.altitude / 1E3
        }

        if not self.home_position_logged:
            logging.info(f"Home position for drone {self.drone_config.hw_id} is set: {self.drone_config.home_position}")
            self.home_position_logged = True

    def process_global_position_int(self, msg):
        valid_msg = msg.lat is not None and msg.lon is not None and msg.alt is not None
        if not valid_msg:
            logging.error('Received GLOBAL_POSITION_INT message with invalid data')
            return

        # Update position and velocity
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

    def process_battery_status(self, msg):
        valid_msg = msg.voltages and len(msg.voltages) > 0
        if not valid_msg:
            logging.error('Received BATTERY_STATUS message with invalid data')
            return

        # Update battery
        self.drone_config.battery = msg.voltages[0] / 1E3  # convert from mV to V

    def __del__(self):
        # Clear the telemetry thread stop event
        self.run_telemetry_thread.clear()

        # Wait for the telemetry thread to stop
        if self.telemetry_thread.is_alive():
            self.telemetry_thread.join()
