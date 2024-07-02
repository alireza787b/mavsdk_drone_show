import os
import sys
import requests
import threading
import time
import logging
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from params import Params
from enums import Mission, State
from config import load_config

telemetry_data_all_drones = {}
last_telemetry_time = {}

# Custom logging formatter
class CustomFormatter(logging.Formatter):
    def format(self, record):
        timestamp = self.formatTime(record, '%Y-%m-%d %H:%M:%S')
        if record.levelno == logging.INFO:
            return f"{timestamp} | Drone {record.drone_id} | SUCCESS | {record.getMessage()}"
        elif record.levelno == logging.ERROR:
            return f"{timestamp} | Drone {record.drone_id} | ERROR | {record.error_type}: {record.getMessage()}"
        return super().format(record)

# Set up logging
logger = logging.getLogger('telemetry')
logger.setLevel(logging.INFO)
logger.propagate = False  # Prevent propagation to root logger
handler = logging.StreamHandler()
handler.setFormatter(CustomFormatter())
logger.addHandler(handler)

def initialize_telemetry_tracking(drones):
    for drone in drones:
        last_telemetry_time[drone['hw_id']] = 0
    logger.info(f"Initialized tracking for {len(drones)} drones", extra={'drone_id': 'System'})

def poll_telemetry(drone):
    while True:
        try:
            response = requests.get(
                f"http://{drone['ip']}:{Params.drones_flask_port}/{Params.get_drone_state_URI}",
                timeout=Params.HTTP_REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                telemetry_data = response.json()
                telemetry_data_all_drones[drone['hw_id']] = {
                    'Pos_ID': telemetry_data.get('pos_id'),
                    'State': State(telemetry_data.get('state')).name,
                    'Mission': Mission(telemetry_data.get('mission')).name,
                    'Position_Lat': telemetry_data.get('position_lat'),
                    'Position_Long': telemetry_data.get('position_long'),
                    'Position_Alt': telemetry_data.get('position_alt'),
                    'Velocity_North': telemetry_data.get('velocity_north'),
                    'Velocity_East': telemetry_data.get('velocity_east'),
                    'Velocity_Down': telemetry_data.get('velocity_down'),
                    'Yaw': telemetry_data.get('yaw'),
                    'Battery_Voltage': telemetry_data.get('battery_voltage'),
                    'Follow_Mode': telemetry_data.get('follow_mode'),
                    'Update_Time': telemetry_data.get('update_time'),
                    'Timestamp': telemetry_data.get('timestamp'),
                    'Flight_Mode': telemetry_data.get('flight_mode_raw'),
                    'Hdop': telemetry_data.get('hdop')
                }
                last_telemetry_time[drone['hw_id']] = time.time()
                logger.info(f"{telemetry_data_all_drones[drone['hw_id']]['State']} | "
                            f"{telemetry_data_all_drones[drone['hw_id']]['Mission']} | "
                            f"Batt: {telemetry_data_all_drones[drone['hw_id']]['Battery_Voltage']:.2f}V",
                            extra={'drone_id': drone['hw_id']})
            else:
                logger.error(f"Request failed: Status {response.status_code}", extra={'drone_id': drone['hw_id'], 'error_type': 'HTTP'})
        except requests.Timeout:
            logger.error("Connection timeout", extra={'drone_id': drone['hw_id'], 'error_type': 'Timeout'})
        except requests.ConnectionError:
            logger.error(f"No route to host: {drone['ip']}", extra={'drone_id': drone['hw_id'], 'error_type': 'ConnectionError'})
        except requests.RequestException:
            logger.error(f"Request failed", extra={'drone_id': drone['hw_id'], 'error_type': 'RequestException'})

        time.sleep(Params.polling_interval)

def start_telemetry_polling(drones):
    initialize_telemetry_tracking(drones)
    
    for drone in drones:
        thread = threading.Thread(target=poll_telemetry, args=(drone,))
        thread.daemon = True
        thread.start()
        logger.info(f"Started polling", extra={'drone_id': drone['hw_id']})

if __name__ == "__main__":
    drones = load_config()
    start_telemetry_polling(drones)

    while True:
        time.sleep(1)