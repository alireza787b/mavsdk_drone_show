# gcs-server/network_status.py

import threading
import time
import requests
import logging
from config import load_config
from params import Params

# Global dictionary to store network status data for all drones
network_status_data_all_drones = {}
# Lock to ensure thread-safe operations on the network status data
data_lock_network_status = threading.Lock()

# Setup logging specifically for network status polling
logger = logging.getLogger('network_status')
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
# Avoid adding multiple handlers if the logger already has handlers
if not logger.handlers:
    logger.addHandler(handler)

def poll_network_status(drone):
    """
    Poll network status from a single drone in an infinite loop.
    
    Args:
        drone (dict): A dictionary containing drone details such as 'ip' and 'hw_id'.
    """
    while True:
        try:
            drone_ip = drone.get('ip')
            if not drone_ip:
                logger.error(f"Drone {drone.get('hw_id')} does not have an IP address configured.")
                time.sleep(Params.polling_interval)
                continue

            # Construct the URI to fetch network status from the drone
            full_uri = f"http://{drone_ip}:{Params.drones_flask_port}/get-network-status"
            logger.debug(f"Polling network status for drone {drone['hw_id']} at {full_uri}")

            # Make the HTTP GET request to the drone's network status endpoint
            response = requests.get(full_uri, timeout=Params.HTTP_REQUEST_TIMEOUT)

            if response.status_code == 200:
                network_info = response.json()
                with data_lock_network_status:
                    # Store the fetched network information, keyed by the drone's hardware ID
                    network_status_data_all_drones[drone['hw_id']] = network_info
                logger.info(f"Network status updated for drone {drone['hw_id']}")
            else:
                logger.warning(f"Failed to fetch network status for drone {drone['hw_id']} (status: {response.status_code})")

        except requests.RequestException as req_err:
            logger.error(f"Request exception while polling network status for drone {drone['hw_id']}: {req_err}")
        except Exception as e:
            logger.error(f"Unexpected error while polling network status for drone {drone['hw_id']}: {e}", exc_info=True)

        # Wait for the specified polling interval before the next poll
        time.sleep(Params.polling_interval)

def start_network_status_polling(drones):
    """
    Initialize and start polling threads for network status for all drones.
    
    Args:
        drones (list): A list of dictionaries, each containing drone details.
    """
    if not drones:
        logger.warning("No drones available to start network status polling.")
        return

    for drone in drones:
        thread = threading.Thread(target=poll_network_status, args=(drone,), name=f"NetworkPoll-{drone['hw_id']}")
        thread.daemon = True  # Daemonize thread to ensure it exits with the main program
        thread.start()
        logger.info(f"Started network status polling for drone {drone['hw_id']} on thread {thread.name}")

def get_network_info_for_all_drones():
    """
    Retrieve the latest network status data for all drones.
    
    Returns:
        dict: A dictionary containing network status for each drone.
    """
    # with data_lock_network_status:
    #     # Return a copy to prevent race conditions
    #     return network_status_data_all_drones.copy()
    pass
