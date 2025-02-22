# gcs-server/command.py

import os
import sys
import requests
import logging
import time
from requests.exceptions import Timeout, ConnectionError, HTTPError
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from params import Params

logger = logging.getLogger(__name__)

def send_command_to_drone(drone, command_data, timeout=5, retries=3):
    """Send a command to a specific drone and handle potential errors with retries."""
    attempt = 0
    backoff_factor = 1
    while attempt < retries:
        try:
            response = requests.post(
                f"http://{drone['ip']}:{Params.drones_flask_port}/{Params.send_drone_command_URI}",
                json=command_data,
                timeout=timeout
            )
            if response.status_code == 200:
                logger.info(
                    f"Command sent successfully to {drone['hw_id']} ({drone['ip']})",
                    extra={'drone_id': drone['hw_id'], 'command': command_data}
                )
                return True
            else:
                logger.error(
                    f"Failed to send command to {drone['hw_id']} (HTTP {response.status_code}): {response.text}",
                    extra={'drone_id': drone['hw_id'], 'command': command_data}
                )
                return False
        except (Timeout, ConnectionError) as e:
            attempt += 1
            wait_time = backoff_factor * (2 ** (attempt - 1))
            logger.warning(
                f"Attempt {attempt}/{retries} failed for drone {drone['hw_id']} due to {e.__class__.__name__}. Retrying in {wait_time} seconds...",
                extra={'drone_id': drone['hw_id'], 'command': command_data}
            )
            time.sleep(wait_time)
        except Exception as e:
            logger.error(
                f"Unexpected error while sending command to {drone['hw_id']}: {e}",
                extra={'drone_id': drone['hw_id'], 'command': command_data}
            )
            return False
    logger.error(
        f"Failed to send command to {drone['hw_id']} after {retries} attempts",
        extra={'drone_id': drone['hw_id'], 'command': command_data}
    )
    return False

def send_commands_to_all(drones, command_data):
    """Send a command to all drones in the list concurrently."""
    total_drones = len(drones)
    max_workers = min(10, total_drones)  # Limit the number of worker threads
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_drone = {
            executor.submit(send_command_to_drone, drone, command_data): drone for drone in drones
        }
        for future in as_completed(future_to_drone):
            drone = future_to_drone[future]
            try:
                success = future.result()
                results[drone['hw_id']] = success
            except Exception as e:
                logger.error(
                    f"Error sending command to drone {drone['hw_id']}: {e}",
                    extra={'drone_id': drone['hw_id'], 'command': command_data}
                )
                results[drone['hw_id']] = False

    success_count = sum(results.values())
    logger.info(
        f"Commands sent successfully to {success_count}/{total_drones} drones",
        extra={'command': command_data}
    )
    return results

def send_commands_to_selected(drones, command_data, target_drone_ids):
    """Send a command to specifically selected drones."""
    # Create a mapping of drone IDs to drone configs
    drone_map = {drone['hw_id']: drone for drone in drones}

    # Filter drones based on target IDs
    selected_drones = []
    for drone_id in target_drone_ids:
        if drone_id in drone_map:
            selected_drones.append(drone_map[drone_id])
        else:
            logger.warning(f"Drone ID {drone_id} not found in configuration")

    if not selected_drones:
        logger.error("No valid drones found in the target list")
        return {}

    total_drones = len(selected_drones)
    max_workers = min(10, total_drones)
    results = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_drone = {
            executor.submit(send_command_to_drone, drone, command_data): drone 
            for drone in selected_drones
        }
        
        for future in as_completed(future_to_drone):
            drone = future_to_drone[future]
            try:
                success = future.result()
                results[drone['hw_id']] = success
            except Exception as e:
                logger.error(
                    f"Error sending command to drone {drone['hw_id']}: {e}",
                    extra={'drone_id': drone['hw_id'], 'command': command_data}
                )
                results[drone['hw_id']] = False

    success_count = sum(results.values())
    logger.info(
        f"Commands sent successfully to {success_count}/{total_drones} selected drones",
        extra={'command': command_data, 'target_drones': target_drone_ids}
    )
    return results
