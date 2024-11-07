# gcs-server/telemetry.py
import os
import sys
import asyncio
import threading
import aiohttp
import logging
import time
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from params import Params
from enums import Mission, State
from config import load_config

telemetry_data_all_drones = {}
last_telemetry_time = {}
data_lock = threading.Lock()


# Set up logging
logger = logging.getLogger('telemetry')
logger.setLevel(logging.INFO)
logger.propagate = False  # Prevent propagation to root logger
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s | Drone %(drone_id)s | %(levelname)s | %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

def initialize_telemetry_tracking(drones):
    for drone in drones:
        telemetry_data_all_drones[drone['hw_id']] = {}
        last_telemetry_time[drone['hw_id']] = 0
    logger.info(f"Initialized tracking for {len(drones)} drones", extra={'drone_id': 'System'})

async def fetch_telemetry(session, drone, retries=3, backoff_factor=1):
    attempt = 0
    wait_time = 0
    while attempt < retries:
        if wait_time > 0:
            await asyncio.sleep(wait_time)
        try:
            full_uri = f"http://{drone['ip']}:{Params.drones_flask_port}/{Params.get_drone_state_URI}"
            async with session.get(full_uri, timeout=Params.HTTP_REQUEST_TIMEOUT) as response:
                if response.status == 200:
                    telemetry_data = await response.json()
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
                            'System_Status': telemetry_data.get('system_status', 'Unknown'),
                            'Hdop': telemetry_data.get('hdop', 99.99),
                            'Vdop': telemetry_data.get('vdop', 99.99),
                        }
                    last_telemetry_time[drone['hw_id']] = time.time()
                    logger.info(f"Telemetry updated", extra={'drone_id': drone['hw_id']})
                    return
                else:
                    logger.error(
                        f"HTTP Error {response.status}: {response.reason}",
                        extra={'drone_id': drone['hw_id']}
                    )
                    return
        except asyncio.TimeoutError:
            logger.error(
                "Timeout while fetching telemetry",
                extra={'drone_id': drone['hw_id']}
            )
        except aiohttp.ClientConnectionError as e:
            logger.error(
                f"Connection error: {e}",
                extra={'drone_id': drone['hw_id']}
            )
        except Exception as e:
            logger.error(
                f"Unexpected error: {e}",
                extra={'drone_id': drone['hw_id']}
            )
        attempt += 1
        wait_time = backoff_factor * (2 ** (attempt - 1))
        logger.warning(
            f"Retrying ({attempt}/{retries}) after {wait_time} seconds",
            extra={'drone_id': drone['hw_id']}
        )
    # Purge stale data after retries
    telemetry_data_all_drones[drone['hw_id']] = {}
    logger.warning(
        f"Failed to fetch telemetry after {retries} attempts",
        extra={'drone_id': drone['hw_id']}
    )

async def poll_telemetry(drones):
    connector = aiohttp.TCPConnector(limit=100)  # Adjust limit based on system capabilities
    timeout = aiohttp.ClientTimeout(total=Params.HTTP_REQUEST_TIMEOUT)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        while True:
            tasks = []
            for drone in drones:
                tasks.append(fetch_telemetry(session, drone))
            await asyncio.gather(*tasks)
            await asyncio.sleep(Params.polling_interval)

def start_telemetry_polling(drones):
    initialize_telemetry_tracking(drones)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(poll_telemetry(drones))
    loop.run_forever()

# Start the polling in a separate thread
def start_telemetry_thread(drones):
    thread = threading.Thread(target=start_telemetry_polling, args=(drones,))
    thread.daemon = True
    thread.start()
    logger.info("Telemetry polling started", extra={'drone_id': 'System'})
