import os
import sys
import requests

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from params import Params

def send_command(drone, command_data):
    try:
        response = requests.post(f"http://{drone['ip']}:{Params().drones_flask_port}/command", json=command_data)
        if response.status_code == 200:
            print(f"Command sent successfully to {drone['hw_id']}")
        else:
            print(f"Failed to send command to {drone['hw_id']}: {response.text}")
    except requests.RequestException as e:
        print(f"Error sending command to {drone['hw_id']}: {e}")

def send_commands_to_all(drones, command_data):
    for drone in drones:
        send_command(drone, command_data)
