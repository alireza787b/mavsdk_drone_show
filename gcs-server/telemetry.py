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
        if record.levelno == logging.INFO:
            return f"{self.formatTime(record, '%Y-%m-%d %H:%M:%S')} | {record.getMessage()}"
        elif record.levelno == logging.ERROR:
            return f"{self.formatTime(record, '%Y-%m-%d %H:%M:%S')} | ERROR | Drone {record.drone_id}: {record.getMessage()}"
        return super().format(record)

# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(CustomFormatter())
logger.addHandler(handler)

def initialize_telemetry_tracking(drones):
    for drone in drones:
        last_telemetry_time[drone['hw_id']] = 0
    logger.info(f"Initialized tracking for {len(drones)} drones")

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
                    'Position': f"({telemetry_data.get('position_lat'):.6f}, {telemetry_data.get('position_long'):.6f}, {telemetry_data.get('position_alt'):.2f})",
                    'Velocity': f"({telemetry_data.get('velocity_north'):.2f}, {telemetry_data.get('velocity_east'):.2f}, {telemetry_data.get('velocity_down'):.2f})",
                    'Yaw': f"{telemetry_data.get('yaw'):.2f}",
                    'Battery': f"{telemetry_data.get('battery_voltage'):.2f}V",
                    'Follow_Mode': telemetry_data.get('follow_mode'),
                    'Update_Time': datetime.fromtimestamp(telemetry_data.get('update_time')).strftime('%H:%M:%S'),
                    'Flight_Mode': telemetry_data.get('flight_mode_raw'),
                    'Hdop': f"{telemetry_data.get('hdop'):.2f}"
                }
                last_telemetry_time[drone['hw_id']] = time.time()
                logger.info(f"Drone {drone['hw_id']} | {telemetry_data_all_drones[drone['hw_id']]['State']} | {telemetry_data_all_drones[drone['hw_id']]['Mission']} | Pos: {telemetry_data_all_drones[drone['hw_id']]['Position']} | Batt: {telemetry_data_all_drones[drone['hw_id']]['Battery']}")
            else:
                logger.error(f"Request failed: Status {response.status_code}", extra={'drone_id': drone['hw_id']})
        except requests.Timeout:
            logger.error("Timeout occurred", extra={'drone_id': drone['hw_id']})
        except requests.RequestException as e:
            logger.error(f"Connection failed: {e}", extra={'drone_id': drone['hw_id']})

        time.sleep(Params.polling_interval)

def start_telemetry_polling(drones):
    initialize_telemetry_tracking(drones)
    
    for drone in drones:
        thread = threading.Thread(target=poll_telemetry, args=(drone,))
        thread.daemon = True
        thread.start()
        logger.info(f"Started polling for Drone {drone['hw_id']}")

if __name__ == "__main__":
    drones = load_config()
    start_telemetry_polling(drones)

    while True:
        time.sleep(1)