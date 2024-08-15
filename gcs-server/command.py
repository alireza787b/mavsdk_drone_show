import os
import sys
import requests
import logging
from requests.exceptions import Timeout, ConnectionError, HTTPError

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from params import Params

logger = logging.getLogger(__name__)

def send_command(drone, command_data, timeout=10):
    """Send a command to a specific drone and handle potential errors."""
    try:
        response = requests.post(
            f"http://{drone['ip']}:{Params.drones_flask_port}/{Params.send_drone_command_URI}",
            json=command_data,
            timeout=timeout
        )
        if response.status_code == 200:
            logger.info(f"Command sent successfully to {drone['hw_id']} ({drone['ip']})",
                        extra={'drone_id': drone['hw_id'], 'command': command_data})
            return True
        else:
            logger.error(f"Failed to send command to {drone['hw_id']} (HTTP {response.status_code}): {response.text}",
                         extra={'drone_id': drone['hw_id'], 'command': command_data})
            return False
    except Timeout:
        logger.error(f"Timeout occurred while sending command to {drone['hw_id']} ({drone['ip']})",
                     extra={'drone_id': drone['hw_id'], 'command': command_data})
        return False
    except ConnectionError:
        logger.error(f"Connection error while sending command to {drone['hw_id']} at {drone['ip']}",
                     extra={'drone_id': drone['hw_id'], 'command': command_data})
        return False
    except HTTPError as e:
        logger.error(f"HTTP error while sending command to {drone['hw_id']}: {e}",
                     extra={'drone_id': drone['hw_id'], 'command': command_data})
        return False
    except Exception as e:
        logger.error(f"Unexpected error while sending command to {drone['hw_id']}: {e}",
                     extra={'drone_id': drone['hw_id'], 'command': command_data})
        return False

def send_commands_to_all(drones, command_data):
    """Send a command to all drones in the list."""
    success_count = 0
    for drone in drones:
        success = send_command(drone, command_data)
        if success:
            success_count += 1

    logger.info(f"Commands sent successfully to {success_count}/{len(drones)} drones",
                extra={'command': command_data})
