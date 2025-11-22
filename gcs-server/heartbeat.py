import logging
import time
from threading import Lock

logger = logging.getLogger(__name__)

# Thread-safe structure to store the last heartbeat for each drone
last_heartbeats = {}  # { hw_id: { "pos_id": ...,"detected_pos_id",..., "ip": ..., "timestamp": ..., "network_info": ... } }
last_heartbeats_lock = Lock()

# Thread-safe structure to store network info extracted from heartbeats
network_info_from_heartbeats = {}  # { hw_id: network_info_dict }
network_info_lock = Lock()

def handle_heartbeat_post(pos_id, hw_id, detected_pos_id=None, ip=None, timestamp=None, network_info=None):
    """
    Handler for POST /drone-heartbeat
    Backend-agnostic function that accepts heartbeat data as parameters.

    Args:
        pos_id: Position ID of the drone
        hw_id: Hardware ID of the drone
        detected_pos_id: Detected position ID (optional)
        ip: IP address of the drone (optional)
        timestamp: Timestamp of the heartbeat (optional)
        network_info: Network information dict (optional)
            Format: {
                "wifi": {"ssid": "...", "signal_strength_percent": 85},
                "ethernet": {"interface": "eth0", "connection_name": "..."},
                "timestamp": 1234567890
            }

    Returns:
        dict: Response data
    """
    if not hw_id:
        raise ValueError("Missing hw_id")

    # We can do further validation if needed
    with last_heartbeats_lock:
        # Professional heartbeat logging: Only log first heartbeat and periodic confirmations
        is_first_heartbeat = hw_id not in last_heartbeats

        # Update heartbeat data
        if is_first_heartbeat:
            last_heartbeats[hw_id] = {
                "pos_id": pos_id,
                "detected_pos_id": detected_pos_id,
                "ip": ip,
                "timestamp": timestamp,
                "network_info": network_info,
                "first_seen": time.time(),
                "last_logged": time.time()
            }
            logger.info(f"💓 Heartbeat established from drone {hw_id} (IP: {ip}, Pos: {pos_id})")
        else:
            # Update existing heartbeat
            last_heartbeats[hw_id].update({
                "pos_id": pos_id,
                "detected_pos_id": detected_pos_id,
                "ip": ip,
                "timestamp": timestamp,
                "network_info": network_info
            })

            # Log periodic confirmation (every 5 minutes)
            if (time.time() - last_heartbeats[hw_id].get('last_logged', 0)) > 300:
                logger.info(f"💓 Heartbeat active from drone {hw_id} (IP: {ip}, Pos: {pos_id})")
                last_heartbeats[hw_id]['last_logged'] = time.time()

    # Store network info separately for /get-network-info endpoint
    if network_info:
        with network_info_lock:
            network_info_from_heartbeats[hw_id] = {
                "hw_id": hw_id,
                **network_info  # Spread the network info (wifi, ethernet, timestamp)
            }

    return {"message": "Heartbeat received"}

def get_all_heartbeats():
    """
    Handler for GET /get-heartbeats
    Returns the latest heartbeat data for all drones.
    Backend-agnostic function that returns dict data.
    """
    with last_heartbeats_lock:
        # Return a copy to ensure thread safety
        return dict(last_heartbeats)

def get_network_info_from_heartbeats():
    """
    Get network info for all drones from heartbeat data.
    Returns data in the format expected by the UI.
    Backend-agnostic function that returns list data.
    """
    with network_info_lock:
        # Convert to list format expected by UI
        network_info_list = []
        for hw_id, network_data in network_info_from_heartbeats.items():
            network_info_list.append(network_data)
        return network_info_list
