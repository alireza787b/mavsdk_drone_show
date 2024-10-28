import requests
import logging
from config import load_config
from params import Params

# Setup logging
logger = logging.getLogger(__name__)

def get_network_info_for_all_drones():
    """
    Fetch network information for all drones.
    Queries each drone individually and returns a list of network info.
    :return: List of dictionaries containing network info for each drone.
    """
    try:
        drones = load_config()
        if not drones:
            return {"error": "No drones found in the configuration"}, 500

        network_info_list = []

        for drone in drones:
            drone_ip = drone.get('ip')
            if not drone_ip:
                logger.error(f"No IP found for drone {drone['hw_id']}")
                continue

            drone_uri = f"http://{drone_ip}:{Params.drones_flask_port}/get-network-status"
            logger.info(f"Fetching network info for drone {drone['hw_id']} from {drone_uri}")

            try:
                response = requests.get(drone_uri, timeout=5)
                if response.status_code == 200:
                    network_info = response.json()
                    network_info['hw_id'] = drone['hw_id']  # Add drone ID to the response
                    network_info_list.append(network_info)
                else:
                    logger.error(f"Failed to get network info for drone {drone['hw_id']}: {response.status_code}")
                    network_info_list.append({
                        "hw_id": drone['hw_id'],
                        "error": f"Failed to get network info: {response.status_code}"
                    })
            except requests.RequestException as e:
                logger.error(f"Error while fetching network info for drone {drone['hw_id']}: {str(e)}")
                network_info_list.append({
                    "hw_id": drone['hw_id'],
                    "error": f"Request failed: {str(e)}"
                })

        return network_info_list, 200

    except Exception as e:
        logger.error(f"Error in get_network_info_for_all_drones: {str(e)}", exc_info=True)
        return {"error": f"Error retrieving network info: {str(e)}"}, 500
