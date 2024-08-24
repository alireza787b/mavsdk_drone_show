import os
import sys
import traceback
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
data_lock = threading.Lock()  # Ensure thread-safe access to shared data

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
        with data_lock:
            telemetry_data_all_drones[drone['hw_id']] = {}
        last_telemetry_time[drone['hw_id']] = 0
    logger.info(f"Initialized tracking for {len(drones)} drones", extra={'drone_id': 'System'})

def poll_telemetry(drone):
    while True:
        try:
            # Construct the full URI
            full_uri = f"http://{drone['ip']}:{Params.drones_flask_port}/{Params.get_drone_state_URI}"
            
            # Make the HTTP request
            response = requests.get(full_uri, timeout=Params.HTTP_REQUEST_TIMEOUT)

            # Check for a successful response
            if response.status_code == 200:
                telemetry_data = response.json()

                # Update telemetry data with thread-safe access
                with data_lock:
                    telemetry_data_all_drones[drone['hw_id']] = {
                        'Pos_ID': telemetry_data.get('pos_id', 'Unknown'),
                        'State': State(telemetry_data.get('state', 'UNKNOWN')).name,
                        'Mission': Mission(telemetry_data.get('mission', 'UNKNOWN')).name,
                        'Position_Lat': telemetry_data.get('position_lat', 0.0),
                        'Position_Long': telemetry_data.get('position_long', 0.0),
                        'Position_Alt': telemetry_data.get('position_alt', 0.0),
                        'Velocity_North': telemetry_data.get('velocity_north', 0.0),
                        'Velocity_East': telemetry_data.get('velocity_east', 0.0),
                        'Velocity_Down': telemetry_data.get('velocity_down', 0.0),
                        'Yaw': telemetry_data.get('yaw', 0.0),
                        'Battery_Voltage': telemetry_data.get('battery_voltage', 0.0),
                        'Follow_Mode': telemetry_data.get('follow_mode', 'Unknown'),
                        'Update_Time': telemetry_data.get('update_time', 'Unknown'),
                        'Timestamp': telemetry_data.get('timestamp', time.time()),
                        'Flight_Mode': telemetry_data.get('flight_mode_raw', 'Unknown'),
                        'Hdop': telemetry_data.get('hdop', 99.99),
                        'Is_Armable': telemetry_data.get('is_armable', False),
                    }
                    last_telemetry_time[drone['hw_id']] = time.time()

                # Log the main telemetry details
                # logger.info(
                #     f"Updated telemetry for drone {drone['hw_id']}: State={telemetry_data_all_drones[drone['hw_id']]['State']} | "
                #     f"Mission={telemetry_data_all_drones[drone['hw_id']]['Mission']} | "
                #     f"Batt={telemetry_data_all_drones[drone['hw_id']]['Battery_Voltage']:.2f}V | "
                #     f"Armable={telemetry_data_all_drones[drone['hw_id']]['Is_Armable']}",
                #     extra={'drone_id': drone['hw_id']}
                # )

            else:
                # Log detailed HTTP error information
                logger.error(
                    f"Request failed with status {response.status_code}: {response.text}",
                    extra={'drone_id': drone['hw_id'], 'error_type': 'HTTP', 'status_code': response.status_code}
                )

        except requests.Timeout:
            logger.error(
                "Connection timeout while polling telemetry",
                extra={'drone_id': drone['hw_id'], 'error_type': 'Timeout'}
            )
        except requests.ConnectionError as e:
            logger.error(
                f"No route to host: {drone['ip']}. Error: {str(e)}",
                extra={'drone_id': drone['hw_id'], 'error_type': 'ConnectionError'}
            )
        except requests.RequestException as e:
            logger.error(
                f"RequestException occurred: {str(e)}",
                extra={'drone_id': drone['hw_id'], 'error_type': 'RequestException', 'traceback': traceback.format_exc()}
            )
        except Exception as e:
            logger.error(
                f"Unexpected error: {str(e)}",
                extra={'drone_id': drone['hw_id'], 'error_type': 'UnexpectedError', 'traceback': traceback.format_exc()}
            )

        # Purge stale telemetry data if no response for a certain period
        current_time = time.time()
        with data_lock:
            if current_time - last_telemetry_time[drone['hw_id']] > Params.HTTP_REQUEST_TIMEOUT:
                logger.warning(f"No telemetry received for drone {drone['hw_id']} for over {Params.HTTP_REQUEST_TIMEOUT} seconds. Purging stale data.")
                telemetry_data_all_drones[drone['hw_id']] = {}

        time.sleep(Params.polling_interval)


def start_telemetry_polling(drones):
    initialize_telemetry_tracking(drones)
    
    for drone in drones:
        thread = threading.Thread(target=poll_telemetry, args=(drone,))
        thread.daemon = True
        thread.start()
        logger.info(f"Started polling for drone {drone['hw_id']}", extra={'drone_id': drone['hw_id']})

if __name__ == "__main__":
    drones = load_config()
    start_telemetry_polling(drones)

    while True:
        time.sleep(1)
