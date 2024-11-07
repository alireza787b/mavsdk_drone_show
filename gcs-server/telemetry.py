# gcs-server/telemetry.py
import os
import sys
import asyncio
import aiohttp
import logging
import time
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from params import Params
from enums import Mission, State
from config import load_config

# Telemetry data storage
telemetry_data_all_drones = {}
last_telemetry_time = {}

# Set up logging
logger = logging.getLogger('telemetry')
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
logger.addHandler(handler)

class TelemetryPoller:
    def __init__(self, drones):
        self.drones = drones
        self.telemetry_data = {}
        self.last_telemetry_time = {}
        self.polling_interval = Params.polling_interval
        self.timeout = Params.HTTP_REQUEST_TIMEOUT
        self.semaphore = asyncio.Semaphore(Params.MAX_CONCURRENT_REQUESTS)  # Limit concurrent requests

        # Initialize telemetry data
        for drone in drones:
            self.telemetry_data[drone['hw_id']] = {}
            self.last_telemetry_time[drone['hw_id']] = 0

    async def fetch_telemetry(self, session, drone):
        hw_id = drone['hw_id']
        ip = drone['ip']
        uri = f"http://{ip}:{Params.drones_flask_port}/{Params.get_drone_state_URI}"

        try:
            async with self.semaphore:
                async with session.get(uri, timeout=self.timeout) as response:
                    if response.status == 200:
                        telemetry_data = await response.json()
                        self.telemetry_data[hw_id] = {
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
                        self.last_telemetry_time[hw_id] = time.time()
                        logger.info(f"Successfully fetched telemetry for drone {hw_id}")
                    else:
                        logger.error(
                            f"Failed to fetch telemetry from drone {hw_id} (HTTP {response.status})",
                            extra={'drone_id': hw_id, 'error_type': 'HTTP'}
                        )
        except asyncio.TimeoutError:
            logger.error(
                f"Timeout while fetching telemetry from drone {hw_id}",
                extra={'drone_id': hw_id, 'error_type': 'Timeout'}
            )
        except aiohttp.ClientError as e:
            logger.error(
                f"Client error while fetching telemetry from drone {hw_id}: {e}",
                extra={'drone_id': hw_id, 'error_type': 'ClientError'}
            )
        except Exception as e:
            logger.error(
                f"Unexpected error while fetching telemetry from drone {hw_id}: {e}",
                extra={'drone_id': hw_id, 'error_type': 'UnexpectedError'}
            )

    async def poll_telemetry(self):
        async with aiohttp.ClientSession() as session:
            while True:
                tasks = [self.fetch_telemetry(session, drone) for drone in self.drones]
                await asyncio.gather(*tasks)
                self.purge_stale_data()
                await asyncio.sleep(self.polling_interval)

    def purge_stale_data(self):
        current_time = time.time()
        for hw_id in list(self.telemetry_data.keys()):
            if current_time - self.last_telemetry_time[hw_id] > self.timeout:
                logger.warning(f"No telemetry received from drone {hw_id} for over {self.timeout} seconds. Purging data.")
                self.telemetry_data[hw_id] = {}

    def get_telemetry_data(self):
        return self.telemetry_data

def start_telemetry_polling(drones):
    poller = TelemetryPoller(drones)
    loop = asyncio.get_event_loop()
    asyncio.ensure_future(poller.poll_telemetry())
    return poller

# Update the global telemetry data variable
poller = None

if __name__ == "__main__":
    drones = load_config()
    poller = start_telemetry_polling(drones)
    loop = asyncio.get_event_loop()
    loop.run_forever()
