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
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from params import Params
from enums import Mission, State
from config import load_config

# Import the new logging system
from logging_config import (
    get_logger, log_drone_telemetry, log_system_error, log_system_warning
)

# Thread-safe data structures
telemetry_data_all_drones = {}
last_telemetry_time = {}
telemetry_stats = {}  # Track success/failure rates per drone
data_lock = threading.Lock()

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
    logger = get_logger()
    
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
    
    logger.log_system_event(
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

def should_log_telemetry_event(drone_id: str, success: bool) -> bool:
    """
    Intelligent logging decision - reduce noise from successful polling
    but ensure we capture important state changes and failures.
    """
    stats = telemetry_stats.get(drone_id, {})
    
    # Always log failures
    if not success:
        return True
    
    # Always log first success after failure(s)
    if stats.get('consecutive_failures', 0) > 0:
        return True
    
    # Log periodic success confirmations (every 100 successful polls)
    success_count = stats.get('success_count', 0)
    if success_count > 0 and success_count % 100 == 0:
        return True
    
    # Otherwise, don't log routine successful telemetry
    return False

def poll_telemetry(drone):
    """
    Poll telemetry from a single drone with intelligent logging.
    Only logs significant events to reduce terminal noise.
    """
    drone_id = drone['hw_id']
    drone_ip = drone['ip']
    
    logger = get_logger()
    consecutive_errors = 0
    last_logged_error = None
    
    while True:
        try:
            # Construct the full URI
            full_uri = f"http://{drone_ip}:{Params.drones_flask_port}/{Params.get_drone_state_URI}"
            
            # Make the HTTP request
            response = requests.get(full_uri, timeout=Params.HTTP_REQUEST_TIMEOUT)

            # Check for a successful response
            if response.status_code == 200:
                telemetry_data = response.json()

                # Update telemetry data with thread-safe access
                with data_lock:
                    telemetry_data_all_drones[drone_id] = {
                        'Pos_ID': telemetry_data.get('pos_id', 'UNKNOWN'),
                        'Detected_Pos_ID': telemetry_data.get('detected_pos_id', 'UNKNOWN'),
                        'State': get_enum_name(State, telemetry_data.get('state', 'UNKNOWN')),
                        'Mission': get_enum_name(Mission, telemetry_data.get('mission', 'UNKNOWN')),
                        'lastMission': get_enum_name(Mission, telemetry_data.get('last_mission', 'UNKNOWN')),
                        'Position_Lat': telemetry_data.get('position_lat', 0.0),
                        'Position_Long': telemetry_data.get('position_long', 0.0),
                        'Position_Alt': telemetry_data.get('position_alt', 0.0),
                        'Velocity_North': telemetry_data.get('velocity_north', 0.0),
                        'Velocity_East': telemetry_data.get('velocity_east', 0.0),
                        'Velocity_Down': telemetry_data.get('velocity_down', 0.0),
                        'Yaw': telemetry_data.get('yaw', 0.0),
                        'Battery_Voltage': telemetry_data.get('battery_voltage', 0.0),
                        'Follow_Mode': telemetry_data.get('follow_mode', 'UNKNOWN'),
                        'Update_Time': telemetry_data.get('update_time', 'UNKNOWN'),
                        'Timestamp': telemetry_data.get('timestamp', time.time()),
                        'Flight_Mode': telemetry_data.get('flight_mode_raw', 'UNKNOWN'),
                        'System_Status': telemetry_data.get('system_status', 'UNKNOWN'),
                        'Hdop': telemetry_data.get('hdop', 99.99),
                        'Vdop': telemetry_data.get('vdop', 99.99),
                    }
                    last_telemetry_time[drone_id] = time.time()

                # Update statistics
                update_telemetry_stats(drone_id, True)
                
                # Reset consecutive error counter on success
                if consecutive_errors > 0:
                    consecutive_errors = 0
                    # Log recovery from errors
                    log_drone_telemetry(
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
                            'status': get_enum_name(State, telemetry_data.get('state', 'UNKNOWN'))
                        }
                    )

                # Log telemetry only if it's significant
                elif should_log_telemetry_event(drone_id, True):
                    log_drone_telemetry(
                        drone_id, True,
                        {
                            'position': (
                                telemetry_data.get('position_lat', 0.0),
                                telemetry_data.get('position_long', 0.0),
                                telemetry_data.get('position_alt', 0.0)
                            ),
                            'battery': telemetry_data.get('battery_voltage', 0.0),
                            'mission': get_enum_name(Mission, telemetry_data.get('mission', 'UNKNOWN')),
                            'status': get_enum_name(State, telemetry_data.get('state', 'UNKNOWN'))
                        }
                    )

            else:
                # HTTP error - log with details but avoid spam
                error_msg = f"HTTP {response.status_code}: {response.text[:100]}"
                consecutive_errors += 1
                update_telemetry_stats(drone_id, False)
                
                # Log error if it's new or every 10 consecutive errors
                if (error_msg != last_logged_error or 
                    consecutive_errors % 10 == 0):
                    
                    log_drone_telemetry(
                        drone_id, False,
                        {
                            'error': error_msg,
                            'consecutive_errors': consecutive_errors,
                            'http_status': response.status_code
                        }
                    )
                    last_logged_error = error_msg

        except requests.Timeout:
            consecutive_errors += 1
            update_telemetry_stats(drone_id, False)
            
            # Log timeout errors periodically
            if consecutive_errors == 1 or consecutive_errors % 10 == 0:
                log_drone_telemetry(
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
            
            # Log connection errors periodically
            if consecutive_errors == 1 or consecutive_errors % 10 == 0:
                log_drone_telemetry(
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
            
            # Log other request errors periodically  
            if consecutive_errors == 1 or consecutive_errors % 10 == 0:
                log_drone_telemetry(
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
            
            # Log unexpected errors immediately
            log_drone_telemetry(
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
                    get_logger().log_system_event(
                        f"Purging stale telemetry data for drone {drone_id} (no data for {Params.HTTP_REQUEST_TIMEOUT * 3}s)",
                        "WARNING", "telemetry"
                    )
                    telemetry_data_all_drones[drone_id] = {}

        # Wait before next poll
        time.sleep(Params.polling_interval)

def start_telemetry_polling(drones):
    """Start telemetry polling threads for all drones"""
    if not drones:
        log_system_error("Cannot start telemetry polling: no drones provided", "telemetry")
        return
    
    # Initialize tracking
    initialize_telemetry_tracking(drones)
    
    logger = get_logger()
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
            log_system_error(
                f"Failed to start telemetry thread for drone {drone['hw_id']}: {e}",
                "telemetry"
            )
    
    logger.log_system_event(
        f"Started {started_threads}/{len(drones)} telemetry polling threads",
        "INFO" if started_threads == len(drones) else "WARNING",
        "telemetry"
    )

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
    from logging_config import initialize_logging, LogLevel, DisplayMode
    
    parser = argparse.ArgumentParser(description='Test telemetry polling system')
    parser.add_argument('--log-level', choices=['QUIET', 'NORMAL', 'VERBOSE', 'DEBUG'], 
                       default='VERBOSE', help='Log level')
    parser.add_argument('--display-mode', choices=['DASHBOARD', 'STREAM', 'HYBRID'],
                       default='HYBRID', help='Display mode')
    args = parser.parse_args()
    
    # Initialize logging
    initialize_logging(
        LogLevel[args.log_level],
        DisplayMode[args.display_mode]
    )
    
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