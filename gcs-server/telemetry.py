# gcs-server/telemetry.py
"""
Telemetry Polling System
========================
Updated with clean logging - reduces noise while maintaining visibility 
into telemetry health across large drone swarms.
"""

import os
import sys
import traceback
import requests
import threading
import time
import logging
import math
from typing import Any, Dict

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from drone_api_routes import DRONE_STATE_ROUTE
from params import Params
from enums import Mission, State
from config import load_config
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
        'heartbeat_last_seen': heartbeat_data.get('timestamp', 0),
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

    if not math.isfinite(numeric_value) or numeric_value <= 0:
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

def poll_telemetry(drone):
    """
    Poll telemetry from a single drone with intelligent logging.
    Only logs significant events to reduce terminal noise.
    """
    drone_id = drone['hw_id']
    drone_ip = drone['ip']

    consecutive_errors = 0
    
    while True:
        try:
            # Construct the full URI
            full_uri = f"http://{drone_ip}:{Params.drone_api_port}{DRONE_STATE_ROUTE}"
            
            # Make the HTTP request
            response = requests.get(full_uri, timeout=Params.HTTP_REQUEST_TIMEOUT)

            # Check for a successful response
            if response.status_code == 200:
                telemetry_data = response.json()

                # Get heartbeat data for this drone
                heartbeat_data = {}
                with last_heartbeats_lock:
                    if drone_id in last_heartbeats:
                        heartbeat_data = last_heartbeats[drone_id].copy()

                # Update telemetry data with thread-safe access
                with data_lock:
                    telemetry_data_all_drones[drone_id] = {
                        'hw_id': drone_id,
                        'pos_id': telemetry_data.get('pos_id', 'UNKNOWN'),
                        'detected_pos_id': telemetry_data.get('detected_pos_id', 'UNKNOWN'),
                        'state': telemetry_data.get('state', 999),  # Send numeric value, not enum name
                        'mission': telemetry_data.get('mission', 0),  # Send numeric value for frontend integer mapping
                        'last_mission': telemetry_data.get('last_mission', 0),  # Send numeric value for frontend integer mapping
                        'position_lat': telemetry_data.get('position_lat', 0.0),
                        'position_long': telemetry_data.get('position_long', 0.0),
                        'position_alt': telemetry_data.get('position_alt', 0.0),
                        'velocity_north': telemetry_data.get('velocity_north', 0.0),
                        'velocity_east': telemetry_data.get('velocity_east', 0.0),
                        'velocity_down': telemetry_data.get('velocity_down', 0.0),
                        'yaw': telemetry_data.get('yaw', 0.0),
                        'battery_voltage': telemetry_data.get('battery_voltage', 0.0),
                        'follow_mode': telemetry_data.get('follow_mode', 0),
                        'update_time': telemetry_data.get('update_time', 'UNKNOWN'),
                        'timestamp': telemetry_data.get('timestamp', time.time()),
                        'server_time': telemetry_data.get('server_time'),
                        'telemetry_available': True,
                        'telemetry_error': None,
                        'trigger_time': telemetry_data.get('trigger_time', 0),
                        'flight_mode': telemetry_data.get('flight_mode', 'UNKNOWN'),  # PX4 custom_mode
                        'base_mode': telemetry_data.get('base_mode', 'UNKNOWN'),  # MAVLink base_mode flags
                        'system_status': telemetry_data.get('system_status', 'UNKNOWN'),
                        'is_armed': _get_enhanced_armed_status(telemetry_data),  # Enhanced armed status
                        'is_ready_to_arm': telemetry_data.get('is_ready_to_arm', False),  # Pre-arm checks
                        'home_position_set': telemetry_data.get('home_position_set', False),
                        'distance_to_home_m': telemetry_data.get('distance_to_home_m'),
                        'readiness_status': telemetry_data.get('readiness_status', 'unknown'),
                        'readiness_summary': telemetry_data.get('readiness_summary', 'Readiness unavailable'),
                        'readiness_checks': telemetry_data.get('readiness_checks', []),
                        'preflight_blockers': telemetry_data.get('preflight_blockers', []),
                        'preflight_warnings': telemetry_data.get('preflight_warnings', []),
                        'status_messages': telemetry_data.get('status_messages', []),
                        'preflight_last_update': telemetry_data.get('preflight_last_update', 0),
                        'hdop': telemetry_data.get('hdop', 99.99),
                        'vdop': telemetry_data.get('vdop', 99.99),
                        'gps_fix_type': telemetry_data.get('gps_fix_type', 0),  # GPS fix status
                        'satellites_visible': telemetry_data.get('satellites_visible', 0),  # Number of satellites
                        'local_position_ok': telemetry_data.get('local_position_ok', False),
                        'local_position_north': telemetry_data.get('local_position_north'),
                        'local_position_east': telemetry_data.get('local_position_east'),
                        'local_position_down': telemetry_data.get('local_position_down'),
                        'local_position_time_boot_ms': telemetry_data.get('local_position_time_boot_ms', 0),
                        'ip': telemetry_data.get('ip', 'N/A'),  # Drone IP address from config
                        # Heartbeat data (kept with prefix for clarity)
                        'heartbeat_last_seen': heartbeat_data.get('timestamp', 0),  # Last heartbeat timestamp
                        'heartbeat_network_info': heartbeat_data.get('network_info', {}),  # Network connectivity info
                        'heartbeat_first_seen': _normalize_heartbeat_first_seen(heartbeat_data.get('first_seen')),  # First heartbeat time
                    }
                    last_telemetry_time[drone_id] = time.time()

                # Update statistics
                update_telemetry_stats(drone_id, True)
                
                # Reset consecutive error counter on success
                if consecutive_errors > 0:
                    consecutive_errors = 0
                    # Ultra-quiet: Only log recovery if it's significant
                    if should_log_telemetry_event(drone_id, True):
                        _log_drone_telemetry_event(
                            drone_id, True,
                            {
                                'message': 'Telemetry restored after connectivity issues',
                                'position': (
                                    telemetry_data.get('position_lat', 0.0),
                                    telemetry_data.get('position_long', 0.0),
                                    telemetry_data.get('position_alt', 0.0)
                                ),
                                'battery': telemetry_data.get('battery_voltage', 0.0),
                                'mission': get_enum_name(Mission, telemetry_data.get('mission', 'UNKNOWN')),
                                'status': telemetry_data.get('state', 999)
                            }
                        )

                # Log telemetry only if it's significant (much quieter now)
                elif should_log_telemetry_event(drone_id, True):
                    _log_drone_telemetry_event(
                        drone_id, True,
                        {
                            'position': (
                                telemetry_data.get('position_lat', 0.0),
                                telemetry_data.get('position_long', 0.0),
                                telemetry_data.get('position_alt', 0.0)
                            ),
                            'battery': telemetry_data.get('battery_voltage', 0.0),
                            'mission': get_enum_name(Mission, telemetry_data.get('mission', 'UNKNOWN')),
                            'status': telemetry_data.get('state', 999)
                        }
                    )

            else:
                # HTTP error - professional error handling with throttling
                error_msg = f"HTTP {response.status_code}: {response.text[:100]}"
                consecutive_errors += 1
                update_telemetry_stats(drone_id, False)
                with data_lock:
                    telemetry_data_all_drones[drone_id] = _build_telemetry_unavailable_record(
                        drone_id,
                        drone_ip,
                        error_msg,
                    )

                # Smart error logging: first error + every Nth occurrence
                if should_log_telemetry_event(drone_id, False):
                    _log_drone_telemetry_event(
                        drone_id, False,
                        {
                            'error': error_msg,
                            'consecutive_errors': consecutive_errors,
                            'http_status': response.status_code
                        }
                    )

        except requests.Timeout:
            consecutive_errors += 1
            update_telemetry_stats(drone_id, False)
            with data_lock:
                telemetry_data_all_drones[drone_id] = _build_telemetry_unavailable_record(
                    drone_id,
                    drone_ip,
                    f'Connection timeout after {Params.HTTP_REQUEST_TIMEOUT}s',
                )

            # Log timeout errors with intelligent throttling
            if should_log_telemetry_event(drone_id, False):
                _log_drone_telemetry_event(
                    drone_id, False,
                    {
                        'error': f'Connection timeout after {Params.HTTP_REQUEST_TIMEOUT}s',
                        'consecutive_errors': consecutive_errors,
                        'target_uri': full_uri
                    }
                )
                
        except requests.ConnectionError as e:
            consecutive_errors += 1
            update_telemetry_stats(drone_id, False)
            with data_lock:
                telemetry_data_all_drones[drone_id] = _build_telemetry_unavailable_record(
                    drone_id,
                    drone_ip,
                    f'Connection failed to {drone_ip}',
                )

            # Log connection errors with smart throttling
            if should_log_telemetry_event(drone_id, False):
                _log_drone_telemetry_event(
                    drone_id, False,
                    {
                        'error': f'Connection failed to {drone_ip}',
                        'consecutive_errors': consecutive_errors,
                        'details': str(e)[:100]
                    }
                )
                
        except requests.RequestException as e:
            consecutive_errors += 1
            update_telemetry_stats(drone_id, False)
            with data_lock:
                telemetry_data_all_drones[drone_id] = _build_telemetry_unavailable_record(
                    drone_id,
                    drone_ip,
                    'Request exception',
                )

            # Log request errors with professional throttling
            if should_log_telemetry_event(drone_id, False):
                _log_drone_telemetry_event(
                    drone_id, False,
                    {
                        'error': 'Request exception',
                        'consecutive_errors': consecutive_errors,
                        'details': str(e)[:100]
                    }
                )
                
        except Exception as e:
            consecutive_errors += 1
            update_telemetry_stats(drone_id, False)
            with data_lock:
                telemetry_data_all_drones[drone_id] = _build_telemetry_unavailable_record(
                    drone_id,
                    drone_ip,
                    f'Unexpected error: {type(e).__name__}',
                )
            
            # Log unexpected errors immediately
            _log_drone_telemetry_event(
                drone_id, False,
                {
                    'error': f'Unexpected error: {type(e).__name__}',
                    'consecutive_errors': consecutive_errors,
                    'details': str(e)[:100],
                    'traceback': traceback.format_exc()[-200:]  # Last 200 chars
                }
            )

        # Purge stale telemetry data if no response for extended period
        current_time = time.time()
        with data_lock:
            if current_time - last_telemetry_time.get(drone_id, 0) > Params.HTTP_REQUEST_TIMEOUT * 3:
                if drone_id in telemetry_data_all_drones and telemetry_data_all_drones[drone_id]:
                    _log_system_event(
                        f"Telemetry stale for drone {drone_id} (no successful poll for {Params.HTTP_REQUEST_TIMEOUT * 3}s); preserving identity and marking data unavailable.",
                        "WARNING",
                        "telemetry",
                    )
                    telemetry_data_all_drones[drone_id] = _build_telemetry_unavailable_record(
                        drone_id,
                        drone_ip,
                        'No successful telemetry poll within the stale-data threshold.',
                    )

        # Wait before next poll
        time.sleep(Params.polling_interval)

def start_telemetry_polling(drones):
    """Start telemetry polling threads for all drones with professional reporting"""
    if not drones:
        _log_system_event("Cannot start telemetry polling: no drones provided", "ERROR", "telemetry")
        return

    # Initialize tracking
    initialize_telemetry_tracking(drones)

    started_threads = 0

    # Start polling threads
    for drone in drones:
        try:
            thread = threading.Thread(
                target=poll_telemetry,
                args=(drone,),
                name=f"telemetry-{drone['hw_id']}",
                daemon=True
            )
            thread.start()
            started_threads += 1

        except Exception as e:
            _log_system_event(
                f"Failed to start telemetry thread for drone {drone['hw_id']}: {e}",
                "ERROR",
                "telemetry",
            )

    # Start periodic status reporter
    _start_telemetry_reporter()

    _log_system_event(
        f"Started {started_threads}/{len(drones)} telemetry polling threads with professional reporting",
        "INFO" if started_threads == len(drones) else "WARNING",
        "telemetry"
    )

def _start_telemetry_reporter():
    """Start background thread for periodic telemetry status reports"""
    def telemetry_reporter():
        from params import Params

        while True:
            try:
                time.sleep(Params.TELEMETRY_REPORT_INTERVAL)
                summary = get_telemetry_summary()

                # Generate professional status report
                active = summary['active_drones']
                total = summary['total_drones']
                failed = summary['failed_drones']
                inactive = summary['inactive_drones']

                if failed > 0:
                    level = "WARNING"
                    status = f"⚠️  TELEMETRY: {active}/{total} active, {failed} failed, {inactive} inactive"
                elif inactive > 0:
                    level = "INFO"
                    status = f"📊 TELEMETRY: {active}/{total} active, {inactive} inactive"
                else:
                    level = "INFO"
                    status = f"✅ TELEMETRY: All {total} drones active and responsive"

                # Only report if there are drones configured
                if total > 0:
                    _log_system_event(status, level, "telemetry-report")

                # Additional details for failed drones
                if failed > 0:
                    with data_lock:
                        failed_drones = []
                        current_time = time.time()
                        for drone_id, stats in telemetry_stats.items():
                            if stats.get('consecutive_failures', 0) > 5:
                                last_error = telemetry_data_all_drones.get(drone_id, {}).get('last_error')
                                age = int(current_time - stats.get('last_success', 0))
                                failed_drones.append(f"D{drone_id} ({age}s ago)")

                        if failed_drones:
                            _log_system_event(
                                f"Failed drones: {', '.join(failed_drones[:5])}{'...' if len(failed_drones) > 5 else ''}",
                                "WARNING", "telemetry-report"
                            )

            except Exception as e:
                _log_system_event(f"Telemetry reporter error: {e}", "ERROR", "telemetry")
                time.sleep(60)  # Wait a minute before retrying

    reporter_thread = threading.Thread(target=telemetry_reporter, daemon=True, name="telemetry-reporter")
    reporter_thread.start()

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

# Standalone test mode
if __name__ == "__main__":
    import argparse
    from mds_logging.server import init_server_logging
    from mds_logging.cli import add_log_arguments, apply_log_args

    parser = argparse.ArgumentParser(description='Test telemetry polling system')
    add_log_arguments(parser)
    args = parser.parse_args()

    # Initialize logging
    apply_log_args(args)
    init_server_logging()
    
    # Load drones and start polling
    drones = load_config()
    if not drones:
        print("No drones found in configuration!")
        sys.exit(1)
    
    print(f"Starting telemetry polling test for {len(drones)} drones...")
    start_telemetry_polling(drones)
    
    try:
        while True:
            time.sleep(10)
            summary = get_telemetry_summary()
            print(f"Telemetry Summary: {summary}")
    except KeyboardInterrupt:
        print("\nTest completed!")
