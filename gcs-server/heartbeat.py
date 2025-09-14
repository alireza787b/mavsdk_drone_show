import logging
import time
from flask import request, jsonify
from threading import Lock

logger = logging.getLogger(__name__)

# Thread-safe structure to store the last heartbeat for each drone
last_heartbeats = {}  # { hw_id: { "pos_id": ...,"detected_pos_id",..., "ip": ..., "timestamp": ... } }
last_heartbeats_lock = Lock()

def handle_heartbeat_post():
    """
    Handler for POST /drone-heartbeat
    Expects JSON data with 'hw_id', 'pos_id', 'detected_pos_id', 'ip', 'timestamp'.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data in heartbeat"}), 400

    hw_id = data.get("hw_id")
    pos_id = data.get("pos_id")
    detected_pos_id = data.get("detected_pos_id")
    ip = data.get("ip")
    timestamp = data.get("timestamp")

    if not hw_id:
        return jsonify({"error": "Missing hw_id"}), 400

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
                "timestamp": timestamp
            })

            # Log periodic confirmation (every 5 minutes)
            if (time.time() - last_heartbeats[hw_id].get('last_logged', 0)) > 300:
                logger.info(f"💓 Heartbeat active from drone {hw_id} (IP: {ip}, Pos: {pos_id})")
                last_heartbeats[hw_id]['last_logged'] = time.time()
    return jsonify({"message": "Heartbeat received"}), 200

def get_all_heartbeats():
    """
    Handler for GET /get-heartbeats
    Returns the latest heartbeat data for all drones.
    """
    with last_heartbeats_lock:
        # Return a copy or direct dictionary
        # If you want to ensure no partial reads, do a .copy() or deep copy
        return jsonify(last_heartbeats), 200
