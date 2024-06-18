import os
import sys
import requests
import threading
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from params import Params

telemetry_data_all_drones = {}

def poll_telemetry(drone):
    while True:
        try:
            response = requests.get(f"http://{drone['ip']}:{Params().drones_flask_port}/{Params.get_drone_state_URI}}")
            if response.status_code == 200:
                telemetry_data_all_drones[drone['hw_id']] = response.json()
        except requests.RequestException as e:
            print(f"Error polling telemetry from {drone['hw_id']}: {e}")
        time.sleep(Params().polling_interval)

def start_telemetry_polling(drones):
    for drone in drones:
        thread = threading.Thread(target=poll_telemetry, args=(drone,))
        thread.start()
