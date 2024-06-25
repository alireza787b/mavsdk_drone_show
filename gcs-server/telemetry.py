import os
import sys
import requests
import threading
import time
import logging

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from params import Params
from enums import Mission, State
from config import load_config

telemetry_data_all_drones = {}
last_telemetry_time = {}

def initialize_telemetry_tracking(drones):
    """
    Initialize the last telemetry tracking dictionary with drone IDs and initial timestamp.
    """
    for drone in drones:
        last_telemetry_time[drone['hw_id']] = 0  # Initialize with 0 or a very old timestamp
    logging.info(f"Initialized telemetry tracking for {len(drones)} drones.")

def poll_telemetry(drone):
    """
    Poll telemetry data from the drone's HTTP server and update the shared telemetry data.
    """
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
                last_telemetry_time[drone['hw_id']] = time.time()  # Update the last telemetry received time
                logging.info(f"Telemetry updated for drone {drone['hw_id']}.")
            else:
                logging.warning(f"Request failed for drone {drone['hw_id']} with status code {response.status_code}. Response: {response.text}")
        except requests.Timeout:
            logging.error(f"Timeout occurred when polling drone {drone['hw_id']}.")
        except requests.RequestException as e:
            logging.error(f"Exception when polling drone {drone['hw_id']}: {e}")

        time.sleep(Params.polling_interval)

def start_telemetry_polling(drones):
    """
    Start a polling thread for each drone to continuously update telemetry data.
    """
    initialize_telemetry_tracking(drones)
    
    for drone in drones:
        thread = threading.Thread(target=poll_telemetry, args=(drone,))
        thread.daemon = True  # Allow thread to exit when main program exits
        thread.start()
        logging.info(f"Started telemetry polling thread for drone {drone['hw_id']}")

# Example usage:
if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(level=logging.INFO)
    
    drones = load_config()
    start_telemetry_polling(drones)

    # Keep the main thread alive to allow daemon threads to keep running
    while True:
        time.sleep(1)
