# gcs-server/git_status.py

import threading
import time
import requests
import logging
from config import load_config
from params import Params

git_status_data_all_drones = {}
data_lock_git_status = threading.Lock()

# Set up logging for git status polling
logger = logging.getLogger('git_status')
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
logger.addHandler(handler)

def poll_git_status(drone):
    """Poll git status from a single drone."""
    while True:
        try:
            full_uri = f"http://{drone['ip']}:{Params.drones_flask_port}/{Params.get_git_status_URI}"
            response = requests.get(full_uri, timeout=Params.HTTP_REQUEST_TIMEOUT)

            if response.status_code == 200:
                with data_lock_git_status:
                    git_status_data_all_drones[drone['hw_id']] = response.json()
                logger.info(f"Git status updated for drone {drone['hw_id']}")
            else:
                logger.warning(f"Failed to fetch git status for drone {drone['hw_id']} (status: {response.status_code})")

        except Exception as e:
            logger.error(f"Error polling git status for drone {drone['hw_id']}: {e}")

        time.sleep(Params.polling_interval)

def start_git_status_polling(drones):
    """Start polling git status for all drones."""
    for drone in drones:
        thread = threading.Thread(target=poll_git_status, args=(drone,))
        thread.daemon = True
        thread.start()
        logger.info(f"Started git status polling for drone {drone['hw_id']}")
