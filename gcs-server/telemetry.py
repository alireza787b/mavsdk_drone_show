# gcs-server/telemetry.py
"""
Shared telemetry cache and diagnostic helpers.

FastAPI's FleetTelemetryPoller is the sole acquisition owner. This module does
not start threads or perform aircraft network reads.
"""

import os
import sys
import threading
import time
import logging
from typing import Any, Dict

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from params import Params
from heartbeat import last_heartbeats, last_heartbeats_lock

# Unified logging system
from mds_logging.server import get_logger

logger = get_logger("telemetry")

# Thread-safe data structures
telemetry_data_all_drones = {}
last_telemetry_time = {}
telemetry_stats = {}  # Track success/failure rates per drone
data_lock = threading.Lock()


def _build_link_blocker(now_ms: int, message: str) -> Dict[str, Any]:
    return {
        'source': 'link',
        'severity': 'warning',
        'message': message,
        'timestamp': now_ms,
    }


def _build_telemetry_unavailable_record(drone_id: str, drone_ip: str, error_message: str) -> Dict[str, Any]:
    now_ms = int(time.time() * 1000)

    with last_heartbeats_lock:
        heartbeat_data = (last_heartbeats.get(drone_id) or {}).copy()

    existing = telemetry_data_all_drones.get(drone_id) or {}
    degraded = dict(existing)
    degraded.update({
        'hw_id': str(existing.get('hw_id', drone_id)),
        'pos_id': existing.get('pos_id', 'UNKNOWN'),
        'ip': existing.get('ip', drone_ip),
        'telemetry_available': False,
        'telemetry_error': error_message,
        'is_ready_to_arm': False,
        'readiness_status': 'unknown',
        'readiness_summary': 'Telemetry link is stale or lost. Readiness is currently unavailable.',
        'readiness_checks': [],
        'preflight_blockers': [_build_link_blocker(now_ms, 'Telemetry link is stale or lost. Readiness is currently unavailable.')],
        'preflight_warnings': [],
        'preflight_last_update': now_ms,
        'heartbeat_last_seen': heartbeat_data.get('received_at_gcs_ms', heartbeat_data.get('timestamp', 0)),
        'heartbeat_network_info': heartbeat_data.get('network_info', {}),
        'heartbeat_first_seen': _normalize_heartbeat_first_seen(heartbeat_data.get('first_seen')),
    })
    return degraded


def _normalize_heartbeat_first_seen(value):
    """Normalize legacy heartbeat first_seen values into Unix milliseconds."""
    if value in (None, ""):
        return None

    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return None

    if numeric_value <= 0:
        return None

    if numeric_value < 1_000_000_000_000:
        numeric_value *= 1000.0

    return int(numeric_value)


def _log_system_event(message: str, level: str = "INFO", component: str = "telemetry") -> None:
    """Log a telemetry system event with the standard logger interface."""
    target_logger = get_logger(component)
    log_level = getattr(logging, level.upper(), logging.INFO)
    target_logger.log(log_level, message)


def _format_log_value(value):
    if isinstance(value, float):
        return f"{value:.3f}"
    if isinstance(value, (tuple, list)):
        return "[" + ", ".join(_format_log_value(item) for item in value) + "]"
    return str(value)


def _build_telemetry_message(details):
    if not isinstance(details, dict):
        return str(details)

    preferred_order = (
        "message",
        "error",
        "position",
        "battery",
        "mission",
        "status",
        "http_status",
        "consecutive_errors",
        "target_uri",
        "details",
    )

    parts = []
    for key in preferred_order:
        value = details.get(key)
        if value not in (None, "", [], {}):
            parts.append(f"{key}={_format_log_value(value)}")

    for key, value in details.items():
        if key in preferred_order or value in (None, "", [], {}):
            continue
        parts.append(f"{key}={_format_log_value(value)}")

    return "; ".join(parts) if parts else "telemetry event"


def _log_drone_telemetry_event(drone_id: str, success: bool, details) -> None:
    """Log per-drone telemetry events without relying on deprecated logger methods."""
    if success:
        level = logging.INFO if isinstance(details, dict) and details.get("message") else logging.DEBUG
        state = "ok"
    else:
        error_text = str(details.get("error", "")) if isinstance(details, dict) else str(details)
        level = logging.ERROR if error_text.startswith("Unexpected error") else logging.WARNING
        state = "issue"

    logger.log(
        level,
        f"Telemetry {state}: {_build_telemetry_message(details)}",
        extra={"mds_drone_id": str(drone_id)},
    )

def get_enum_name(enum_class, value):
    """
    Helper function to safely get the name of an Enum member.
    Tries to get the enum member by value or name; returns 'UNKNOWN' if not found.
    """
    try:
        if isinstance(value, int):
            return enum_class(value).name
        elif isinstance(value, str):
            return enum_class[value.upper()].name
    except (ValueError, KeyError, TypeError):
        return 'UNKNOWN'

def initialize_telemetry_tracking(drones):
    """Initialize telemetry tracking structures"""
    with data_lock:
        for drone in drones:
            hw_id = drone['hw_id']
            telemetry_data_all_drones[hw_id] = {}
            last_telemetry_time[hw_id] = 0
            telemetry_stats[hw_id] = {
                'success_count': 0,
                'failure_count': 0,
                'last_success': 0,
                'consecutive_failures': 0
            }

    _log_system_event(
        f"Initialized telemetry tracking for {len(drones)} drones", 
        "INFO", "telemetry"
    )

def update_telemetry_stats(drone_id: str, success: bool):
    """Update success/failure statistics for a drone"""
    with data_lock:
        stats = telemetry_stats.get(drone_id, {})
        
        if success:
            stats['success_count'] = stats.get('success_count', 0) + 1
            stats['last_success'] = time.time()
            stats['consecutive_failures'] = 0
        else:
            stats['failure_count'] = stats.get('failure_count', 0) + 1
            stats['consecutive_failures'] = stats.get('consecutive_failures', 0) + 1
        
        telemetry_stats[drone_id] = stats

def _get_enhanced_armed_status(telemetry_data):
    """
    Enhanced arming detection for SITL and real operations.
    Cross-references armed flag with flight mode and system status.
    """
    raw_armed = telemetry_data.get('is_armed', False)
    flight_mode = telemetry_data.get('flight_mode', 0)
    system_status = telemetry_data.get('system_status', 0)

    if raw_armed:
        # If raw armed flag is true, verify with flight mode
        if flight_mode == 0 and system_status == 4:
            # SITL special case: armed flag set but flight mode is 0 (Initializing)
            # This typically means ready but not actually armed for flight
            return False
        else:
            # Normal case: armed flag set and flight mode is valid
            return True
    else:
        # Raw armed flag is false
        return False

def should_log_telemetry_event(drone_id: str, success: bool) -> bool:
    """
    Ultra-quiet logging decision - absolute minimum noise for production.
    Only logs critical events and significant state changes.
    """
    from params import Params

    # Ultra-quiet mode - extremely selective logging
    if Params.ULTRA_QUIET_MODE:
        stats = telemetry_stats.get(drone_id, {})
        consecutive_failures = stats.get('consecutive_failures', 0)

        if not success:
            # Only log after multiple failures to avoid single connection hiccups
            if consecutive_failures >= Params.MIN_ERROR_THRESHOLD:
                # Then log every Nth failure to avoid spam
                return consecutive_failures % Params.ERROR_REPORT_THROTTLE == 0
            return False

        # Log recovery only after significant failures, and only if enabled
        if not Params.SUPPRESS_RECOVERY_MESSAGES and consecutive_failures >= Params.MIN_ERROR_THRESHOLD:
            return True

        # Never log routine successful polls in ultra-quiet mode
        return False

    # Regular quiet mode behavior
    elif Params.POLLING_QUIET_MODE:
        stats = telemetry_stats.get(drone_id, {})
        if not success:
            consecutive_failures = stats.get('consecutive_failures', 0)
            return consecutive_failures == 1 or consecutive_failures % Params.ERROR_REPORT_THROTTLE == 0
        if stats.get('consecutive_failures', 0) > 0:
            return True
        return False

    # Legacy behavior for verbose mode
    stats = telemetry_stats.get(drone_id, {})
    if not success:
        return True
    if stats.get('consecutive_failures', 0) > 0:
        return True
    success_count = stats.get('success_count', 0)
    if success_count > 0 and success_count % 100 == 0:
        return True
    return False

def get_telemetry_summary():
    """Get a summary of telemetry system health"""
    with data_lock:
        total_drones = len(telemetry_stats)
        active_drones = 0
        failed_drones = 0
        
        current_time = time.time()
        for drone_id, stats in telemetry_stats.items():
            last_success = stats.get('last_success', 0)
            consecutive_failures = stats.get('consecutive_failures', 0)
            
            if current_time - last_success < 60:  # Active if success within 60s
                active_drones += 1
            elif consecutive_failures > 5:  # Failed if 5+ consecutive failures
                failed_drones += 1
        
        return {
            'total_drones': total_drones,
            'active_drones': active_drones, 
            'failed_drones': failed_drones,
            'inactive_drones': total_drones - active_drones - failed_drones
        }
