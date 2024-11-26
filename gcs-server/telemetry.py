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

# Define colors and symbols for terminal output
RESET = "\x1b[0m"
RED = "\x1b[31m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
BLUE = "\x1b[34m"
MAGENTA = "\x1b[35m"
CYAN = "\x1b[36m"
WHITE = "\x1b[37m"
BOLD = "\x1b[1m"

SUCCESS_SYMBOL = GREEN + "✔️" + RESET
ERROR_SYMBOL = RED + "❌" + RESET
WARNING_SYMBOL = YELLOW + "⚠️" + RESET
INFO_SYMBOL = BLUE + "ℹ️" + RESET

class ColoredFormatter(logging.Formatter):
    def format(self, record):
        levelno = record.levelno
        if levelno >= logging.CRITICAL:
            color = RED
        elif levelno >= logging.ERROR:
            color = RED
        elif levelno >= logging.WARNING:
            color = YELLOW
        elif levelno >= logging.INFO:
            color = GREEN
        else:
            color = RESET
        formatter = logging.Formatter(f"{color}%(asctime)s | Drone %(drone_id)s | %(message)s{RESET}", "%Y-%m-%d %H:%M:%S")
        return formatter.format(record)

# Set up logging
logger = logging.getLogger('telemetry')
logger.setLevel(logging.INFO)
logger.propagate = False  # Prevent propagation to root logger
handler = logging.StreamHandler()
handler.setFormatter(ColoredFormatter())
logger.handlers = [handler]  # Replace existing handlers

def get_enum_name(enum_class, value):
    """
    Helper function to safely get the name of an Enum member.
    Tries to get the enum member by value or name; returns 'UNKNOWN' if not found.
    """
    try:
        if isinstance(value, int):
            return enum_class(value).name
        elif isinstance(value, str):
            return enum_class[value.upper()].name
    except (ValueError, KeyError, TypeError):
        return 'UNKNOWN'

def initialize_telemetry_tracking(drones):
    for drone in drones:
        with data_lock:
            telemetry_data_all_drones[drone['hw_id']] = {}
        last_telemetry_time[drone['hw_id']] = 0
    logger.info(f"{INFO_SYMBOL} Initialized tracking for {len(drones)} drones", extra={'drone_id': 'System'})

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
                        'Pos_ID': telemetry_data.get('pos_id', 'UNKNOWN'),
                        'State': get_enum_name(State, telemetry_data.get('state', 'UNKNOWN')),
                        'Mission': get_enum_name(Mission, telemetry_data.get('mission', 'UNKNOWN')),
                        'lastMission': get_enum_name(Mission, telemetry_data.get('last_mission', 'UNKNOWN')),
                        'Position_Lat': telemetry_data.get('position_lat', 0.0),
                        'Position_Long': telemetry_data.get('position_long', 0.0),
                        'Position_Alt': telemetry_data.get('position_alt', 0.0),
                        'Velocity_North': telemetry_data.get('velocity_north', 0.0),
                        'Velocity_East': telemetry_data.get('velocity_east', 0.0),
                        'Velocity_Down': telemetry_data.get('velocity_down', 0.0),
                        'Yaw': telemetry_data.get('yaw', 0.0),
                        'Battery_Voltage': telemetry_data.get('battery_voltage', 0.0),
                        'Follow_Mode': telemetry_data.get('follow_mode', 'UNKNOWN'),
                        'Update_Time': telemetry_data.get('update_time', 'UNKNOWN'),
                        'Timestamp': telemetry_data.get('timestamp', time.time()),
                        'Flight_Mode': telemetry_data.get('flight_mode_raw', 'UNKNOWN'),
                        'System_Status': telemetry_data.get('system_status', 'UNKNOWN'),  # MAVLink system status
                        'Hdop': telemetry_data.get('hdop', 99.99),
                        'Vdop': telemetry_data.get('vdop', 99.99),  # Vertical dilution of precision
                    }
                    last_telemetry_time[drone['hw_id']] = time.time()

                # Log success
                logger.info(
                    f"{SUCCESS_SYMBOL} Telemetry updated successfully",
                    extra={'drone_id': drone['hw_id']}
                )

            else:
                # Log detailed HTTP error information
                logger.error(
                    f"{ERROR_SYMBOL} Request failed with status {response.status_code}: {response.text}",
                    extra={'drone_id': drone['hw_id']}
                )

        except requests.Timeout:
            logger.error(
                f"{ERROR_SYMBOL} Connection timeout while polling telemetry",
                extra={'drone_id': drone['hw_id']}
            )
        except requests.ConnectionError as e:
            logger.error(
                f"{ERROR_SYMBOL} No route to host: {drone['ip']}. Error: {str(e)}",
                extra={'drone_id': drone['hw_id']}
            )
        except requests.RequestException as e:
            logger.error(
                f"{ERROR_SYMBOL} RequestException occurred: {str(e)}",
                extra={'drone_id': drone['hw_id']}
            )
        except Exception as e:
            logger.error(
                f"{ERROR_SYMBOL} Unexpected error: {str(e)}",
                extra={'drone_id': drone['hw_id']}
            )

        # Purge stale telemetry data if no response for a certain period
        current_time = time.time()
        with data_lock:
            if current_time - last_telemetry_time[drone['hw_id']] > Params.HTTP_REQUEST_TIMEOUT:
                logger.warning(
                    f"{WARNING_SYMBOL} No telemetry received for over {Params.HTTP_REQUEST_TIMEOUT} seconds. Purging stale data.",
                    extra={'drone_id': drone['hw_id']}
                )
                telemetry_data_all_drones[drone['hw_id']] = {}

        time.sleep(Params.polling_interval)

def start_telemetry_polling(drones):
    initialize_telemetry_tracking(drones)
    
    for drone in drones:
        thread = threading.Thread(target=poll_telemetry, args=(drone,))
        thread.daemon = True
        thread.start()
        logger.info(f"{INFO_SYMBOL} Started polling", extra={'drone_id': drone['hw_id']})

if __name__ == "__main__":
    drones = load_config()
    start_telemetry_polling(drones)

    while True:
        time.sleep(1)
