# gcs-server/command.py
"""
Drone Command Distribution System
================================
Updated with intelligent logging - tracks command success/failure patterns
without overwhelming terminal output during large swarm operations.
"""

import os
import sys
import requests
import time
from requests.exceptions import Timeout, ConnectionError, HTTPError
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Tuple

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from params import Params

# Import the new logging system
from logging_config import (
    get_logger, log_drone_command, log_system_error, log_system_warning
)

def send_command_to_drone(drone: Dict[str, str], command_data: Dict[str, Any], 
                         timeout: int = 5, retries: int = 3) -> Tuple[bool, str]:
    """
    Send a command to a specific drone with retries and intelligent logging.
    
    Returns:
        Tuple[bool, str]: (success, error_message)
    """
    drone_id = drone['hw_id']
    drone_ip = drone['ip'] 
    command_type = command_data.get('missionType', 'UNKNOWN')
    
    attempt = 0
    backoff_factor = 1
    last_error = ""

    # Ensure missionType is string for drone API compatibility
    command_payload = command_data.copy()
    if 'missionType' in command_payload:
        command_payload['missionType'] = str(command_payload['missionType'])

    while attempt < retries:
        try:
            response = requests.post(
                f"http://{drone_ip}:{Params.drone_api_port}/{Params.send_drone_command_URI}",
                json=command_payload,
                timeout=timeout
            )
            
            if response.status_code == 200:
                # Success - log only for important commands or first success after failures
                if attempt > 0:  # Recovery from previous failures
                    log_drone_command(
                        drone_id, 
                        f"{command_type} (recovered after {attempt} failures)", 
                        True
                    )
                elif command_type in ['TAKEOFF', 'LAND', 'RTL', 'ARM', 'DISARM']:  # Critical commands
                    log_drone_command(drone_id, command_type, True)
                # Don't log routine successful commands to reduce noise
                
                return True, ""
                
            else:
                last_error = f"HTTP {response.status_code}: {response.text[:100]}"
                
        except (Timeout, ConnectionError) as e:
            attempt += 1
            last_error = f"{e.__class__.__name__}: Connection issue"
            
            if attempt < retries:
                wait_time = backoff_factor * (2 ** (attempt - 1))
                # Only log retry attempts for critical commands or on last attempt
                if command_type in ['TAKEOFF', 'LAND', 'RTL', 'EMERGENCY'] or attempt == retries:
                    get_logger().log_drone_event(
                        drone_id, "command", 
                        f"Retry {attempt}/{retries} for {command_type} in {wait_time}s due to {e.__class__.__name__}",
                        "WARNING"
                    )
                time.sleep(wait_time)
                continue
                
        except Exception as e:
            last_error = f"Unexpected error: {str(e)[:100]}"
            break  # Don't retry on unexpected errors
            
        attempt += 1
    
    # Command failed after all retries
    log_drone_command(drone_id, command_type, False, last_error)
    return False, last_error

def send_commands_to_all(drones: List[Dict[str, str]], command_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send a command to all drones concurrently with comprehensive result tracking.
    
    Returns:
        Dict with success/failure counts and details
    """
    if not drones:
        log_system_warning("No drones provided for command execution", "command")
        return {'success': 0, 'failed': 0, 'total': 0, 'results': {}}
    
    command_type = command_data.get('missionType', 'UNKNOWN')
    logger = get_logger()
    
    # Log command initiation for swarm operations
    logger.log_system_event(
        f"Sending '{command_type}' command to {len(drones)} drones",
        "INFO", "command"
    )
    
    start_time = time.time()
    results = {}
    success_count = 0
    failed_count = 0
    
    # Execute commands concurrently
    with ThreadPoolExecutor(max_workers=min(len(drones), 20)) as executor:
        # Submit all commands
        future_to_drone = {
            executor.submit(send_command_to_drone, drone, command_data): drone
            for drone in drones
        }
        
        # Collect results as they complete
        for future in as_completed(future_to_drone):
            drone = future_to_drone[future]
            drone_id = drone['hw_id']
            
            try:
                success, error = future.result()
                results[drone_id] = {
                    'success': success,
                    'error': error if error else None,
                    'drone_ip': drone['ip']
                }
                
                if success:
                    success_count += 1
                else:
                    failed_count += 1
                    
            except Exception as e:
                # Thread execution error
                error_msg = f"Thread execution failed: {str(e)}"
                results[drone_id] = {
                    'success': False,
                    'error': error_msg,
                    'drone_ip': drone['ip']
                }
                failed_count += 1
                log_drone_command(drone_id, command_type, False, error_msg)
    
    # Calculate execution time
    execution_time = time.time() - start_time
    
    # Log comprehensive summary
    success_rate = (success_count / len(drones)) * 100 if drones else 0
    
    if success_count == len(drones):
        # Perfect success
        logger.log_system_event(
            f"Command '{command_type}' completed successfully on all {len(drones)} drones in {execution_time:.2f}s",
            "INFO", "command"
        )
    elif success_count > 0:
        # Partial success
        logger.log_system_event(
            f"Command '{command_type}' completed: {success_count}/{len(drones)} successful ({success_rate:.1f}%) in {execution_time:.2f}s",
            "WARNING", "command"
        )
    else:
        # Complete failure
        logger.log_system_event(
            f"Command '{command_type}' FAILED on all {len(drones)} drones in {execution_time:.2f}s",
            "ERROR", "command"
        )
    
    # Log details of failed drones if there are failures
    if failed_count > 0:
        failed_drones = [drone_id for drone_id, result in results.items() if not result['success']]
        
        # Group failures by error type for cleaner reporting
        error_groups = {}
        for drone_id in failed_drones:
            error = results[drone_id]['error'] or "Unknown error"
            error_type = error.split(':')[0]  # Get error type
            if error_type not in error_groups:
                error_groups[error_type] = []
            error_groups[error_type].append(drone_id)
        
        for error_type, drone_list in error_groups.items():
            logger.log_system_event(
                f"Command '{command_type}' {error_type} on drones: {', '.join(drone_list[:10])}{'...' if len(drone_list) > 10 else ''}",
                "ERROR", "command"
            )
    
    return {
        'success': success_count,
        'failed': failed_count,
        'total': len(drones),
        'success_rate': success_rate,
        'execution_time': execution_time,
        'results': results
    }

def send_commands_to_selected(drones: List[Dict[str, str]], command_data: Dict[str, Any], 
                            target_drone_ids: List[str]) -> Dict[str, Any]:
    """
    Send commands to specific drones only.
    
    Args:
        drones: All available drones
        command_data: Command to send
        target_drone_ids: List of specific drone IDs to target
        
    Returns:
        Dict with execution results
    """
    if not target_drone_ids:
        log_system_warning("No target drones specified for selective command", "command")
        return {'success': 0, 'failed': 0, 'total': 0, 'results': {}}
    
    # Filter drones to only target ones
    target_drones = [
        drone for drone in drones 
        if drone['hw_id'] in target_drone_ids
    ]
    
    if len(target_drones) != len(target_drone_ids):
        found_ids = [drone['hw_id'] for drone in target_drones]
        missing_ids = set(target_drone_ids) - set(found_ids)
        
        log_system_warning(
            f"Some target drones not found in configuration: {', '.join(missing_ids)}",
            "command"
        )
    
    if not target_drones:
        log_system_error("No valid target drones found for selective command", "command")
        return {'success': 0, 'failed': 0, 'total': 0, 'results': {}}
    
    # Use the same logic as send_commands_to_all but with filtered drones
    return send_commands_to_all(target_drones, command_data)

def validate_command_data(command_data: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Validate command data structure and content.
    
    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    """
    if not isinstance(command_data, dict):
        return False, "Command data must be a dictionary"
    
    # Check required fields
    required_fields = ['missionType']
    missing_fields = [field for field in required_fields if field not in command_data]
    
    if missing_fields:
        return False, f"Missing required fields: {', '.join(missing_fields)}"
    
    # Validate mission type
    mission_type = command_data.get('missionType')
    if not isinstance(mission_type, (int, str)):
        return False, "missionType must be an integer or string"
    
    # Additional validation can be added here for specific command types
    
    return True, ""

def execute_drone_command(drones: List[Dict[str, str]], command_data: Dict[str, Any], 
                         target_drone_ids: List[str] = None) -> Dict[str, Any]:
    """
    Main entry point for drone command execution with validation and logging.
    
    Args:
        drones: Available drones
        command_data: Command to execute
        target_drone_ids: Optional list of specific drones to target
        
    Returns:
        Dict with execution results and status
    """
    logger = get_logger()
    
    # Validate command data
    is_valid, error_msg = validate_command_data(command_data)
    if not is_valid:
        log_system_error(f"Invalid command data: {error_msg}", "command")
        return {
            'status': 'error',
            'message': f"Invalid command data: {error_msg}",
            'results': {}
        }
    
    # Validate drone list
    if not drones:
        log_system_error("No drones available for command execution", "command")
        return {
            'status': 'error', 
            'message': "No drones available",
            'results': {}
        }
    
    try:
        # Execute command
        if target_drone_ids:
            results = send_commands_to_selected(drones, command_data, target_drone_ids)
        else:
            results = send_commands_to_all(drones, command_data)
        
        # Determine overall status
        if results['failed'] == 0:
            status = 'success'
            message = f"Command executed successfully on all {results['total']} drones"
        elif results['success'] > 0:
            status = 'partial'
            message = f"Command partially successful: {results['success']}/{results['total']} drones"
        else:
            status = 'failed'
            message = f"Command failed on all {results['total']} drones"
        
        return {
            'status': status,
            'message': message,
            'results': results
        }
        
    except Exception as e:
        error_msg = f"Unexpected error during command execution: {str(e)}"
        log_system_error(error_msg, "command")
        return {
            'status': 'error',
            'message': error_msg,
            'results': {}
        }

# Command execution statistics for monitoring
_command_stats = {
    'total_commands': 0,
    'successful_commands': 0,
    'failed_commands': 0,
    'start_time': time.time()
}

def get_command_statistics() -> Dict[str, Any]:
    """Get command execution statistics"""
    uptime = time.time() - _command_stats['start_time']
    
    return {
        'total_commands': _command_stats['total_commands'],
        'successful_commands': _command_stats['successful_commands'], 
        'failed_commands': _command_stats['failed_commands'],
        'success_rate': (_command_stats['successful_commands'] / max(_command_stats['total_commands'], 1)) * 100,
        'uptime_hours': uptime / 3600,
        'commands_per_hour': _command_stats['total_commands'] / max(uptime / 3600, 0.01)
    }

def update_command_statistics(success_count: int, failed_count: int):
    """Update global command statistics"""
    _command_stats['total_commands'] += success_count + failed_count
    _command_stats['successful_commands'] += success_count
    _command_stats['failed_commands'] += failed_count

# Integration with the updated system - wrap the statistics updates
_original_send_commands_to_all = send_commands_to_all

def send_commands_to_all_with_stats(drones: List[Dict[str, str]], command_data: Dict[str, Any]) -> Dict[str, Any]:
    """Wrapper to include statistics tracking"""
    result = _original_send_commands_to_all(drones, command_data)
    update_command_statistics(result.get('success', 0), result.get('failed', 0))
    return result

# Replace the original function
send_commands_to_all = send_commands_to_all_with_stats

# Standalone test mode
if __name__ == "__main__":
    import argparse
    from logging_config import initialize_logging, LogLevel, DisplayMode
    from config import load_config
    
    parser = argparse.ArgumentParser(description='Test drone command system')
    parser.add_argument('--log-level', choices=['QUIET', 'NORMAL', 'VERBOSE', 'DEBUG'],
                       default='VERBOSE', help='Log level')
    parser.add_argument('--command', required=True, help='Command to send (e.g., ARM, TAKEOFF, LAND)')
    parser.add_argument('--drones', nargs='*', help='Specific drone IDs to target')
    args = parser.parse_args()
    
    # Initialize logging
    initialize_logging(LogLevel[args.log_level], DisplayMode.STREAM)
    
    # Load drones
    drones = load_config()
    if not drones:
        print("No drones found in configuration!")
        sys.exit(1)
    
    # Prepare command data
    command_data = {
        'missionType': args.command.upper(),
        'triggerTime': '0',
        'target_drones': args.drones or []
    }
    
    print(f"Sending {args.command.upper()} command to {'specific' if args.drones else 'all'} drones...")
    
    # Execute command
    result = execute_drone_command(drones, command_data, args.drones)
    
    print(f"Command execution result: {result['status']}")
    print(f"Message: {result['message']}")
    
    if 'results' in result and result['results']:
        stats = result['results']
        print(f"Success rate: {stats.get('success_rate', 0):.1f}%")
        print(f"Execution time: {stats.get('execution_time', 0):.2f}s")