import time
from threading import Lock

from mds_logging import get_logger
from src.settings.runtime import resolve_runtime_mode

logger = get_logger("heartbeat")

# Thread-safe structure to store the last heartbeat for each drone
last_heartbeats = {}  # { hw_id: { "pos_id": ...,"detected_pos_id",..., "ip": ..., "timestamp": ..., "network_info": ... } }
last_heartbeats_lock = Lock()

# Thread-safe structure to store network info extracted from heartbeats
network_info_from_heartbeats = {}  # { hw_id: network_info_dict }
network_info_lock = Lock()
_runtime_mode_notice_lock = Lock()
_missing_runtime_mode_notice_keys = set()
_runtime_mode_mismatch_notice_keys = set()


def _normalize_runtime_mode(value):
    if value is None:
        return None

    normalized = str(value).strip().lower()
    if normalized == "real":
        return "real"
    if normalized == "sitl":
        return "sitl"
    return None


def _resolve_current_runtime_mode():
    try:
        return resolve_runtime_mode().mode
    except Exception:  # pragma: no cover - defensive fallback for runtime bootstrap issues
        return "sitl"


def _log_missing_runtime_mode_once(hw_id):
    with _runtime_mode_notice_lock:
        if hw_id in _missing_runtime_mode_notice_keys:
            return
        _missing_runtime_mode_notice_keys.add(hw_id)

    logger.warning(
        "Ignoring heartbeat from drone %s because runtime_mode is missing or invalid.",
        hw_id,
    )


def _log_runtime_mode_mismatch_once(hw_id, declared_mode, current_mode):
    notice_key = (hw_id, declared_mode, current_mode)
    with _runtime_mode_notice_lock:
        if notice_key in _runtime_mode_mismatch_notice_keys:
            return
        _runtime_mode_mismatch_notice_keys.add(notice_key)

    logger.info(
        "Ignoring heartbeat from drone %s declared for %s while GCS runs %s mode.",
        hw_id,
        declared_mode,
        current_mode,
    )


def handle_heartbeat_post(pos_id, hw_id, detected_pos_id=None, ip=None, timestamp=None, network_info=None, runtime_mode=None):
    """
    Handler for POST /api/v1/fleet/heartbeats
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
        runtime_mode: Canonical runtime mode declared by the node: real or sitl

    Returns:
        dict: Response data
    """
    if not hw_id:
        raise ValueError("Missing hw_id")

    hw_id = str(hw_id).strip()
    if not hw_id:
        raise ValueError("Missing hw_id")

    current_runtime_mode = _resolve_current_runtime_mode()
    declared_runtime_mode = _normalize_runtime_mode(runtime_mode)

    if declared_runtime_mode is None:
        _log_missing_runtime_mode_once(hw_id)
        return {
            "message": "Heartbeat ignored because runtime_mode is missing or invalid",
            "accepted": False,
            "runtime_mode": None,
            "current_mode": current_runtime_mode,
        }

    if declared_runtime_mode != current_runtime_mode:
        _log_runtime_mode_mismatch_once(hw_id, declared_runtime_mode, current_runtime_mode)
        return {
            "message": f"Heartbeat ignored for runtime mode {declared_runtime_mode}",
            "accepted": False,
            "runtime_mode": declared_runtime_mode,
            "current_mode": current_runtime_mode,
        }

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
                "runtime_mode": declared_runtime_mode,
                "first_seen": int(time.time() * 1000),
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
                "network_info": network_info,
                "runtime_mode": declared_runtime_mode,
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
                "runtime_mode": declared_runtime_mode,
                **network_info  # Spread the network info (wifi, ethernet, timestamp)
            }

    return {
        "message": "Heartbeat received",
        "accepted": True,
        "runtime_mode": declared_runtime_mode,
        "current_mode": current_runtime_mode,
    }

def get_all_heartbeats():
    """
    Handler for GET /api/v1/fleet/heartbeats
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
