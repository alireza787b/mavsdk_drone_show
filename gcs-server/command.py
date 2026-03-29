# gcs-server/command.py
"""
Drone Command Distribution System
================================
Updated with intelligent logging - tracks command success/failure patterns
without overwhelming terminal output during large swarm operations.
"""

import os
import sys
import logging
import requests
import time
from requests.exceptions import Timeout, ConnectionError
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Tuple, Iterable

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from params import Params
from enums import CommandResultCategory, Mission
from heartbeat import get_all_heartbeats

# Unified logging system
from mds_logging.server import get_logger

logger = get_logger("command")

_MISSION_NAME_ALIASES = {
    "TAKEOFF": Mission.TAKE_OFF,
    "TAKE_OFF": Mission.TAKE_OFF,
    "LAND": Mission.LAND,
    "HOLD": Mission.HOLD,
    "RTL": Mission.RETURN_RTL,
    "RETURN_RTL": Mission.RETURN_RTL,
    "RETURNRTL": Mission.RETURN_RTL,
    "KILL": Mission.KILL_TERMINATE,
    "TERMINATE": Mission.KILL_TERMINATE,
    "KILL_TERMINATE": Mission.KILL_TERMINATE,
    "TEST": Mission.TEST,
    "REBOOT_FC": Mission.REBOOT_FC,
    "REBOOT_SYS": Mission.REBOOT_SYS,
    "TEST_LED": Mission.TEST_LED,
    "UPDATE": Mission.UPDATE_CODE,
    "UPDATE_CODE": Mission.UPDATE_CODE,
    "INIT_SYSID": Mission.INIT_SYSID,
    "APPLY_COMMON_PARAMS": Mission.APPLY_COMMON_PARAMS,
    "DRONE_SHOW": Mission.DRONE_SHOW_FROM_CSV,
    "DRONE_SHOW_FROM_CSV": Mission.DRONE_SHOW_FROM_CSV,
    "CUSTOM_CSV_DRONE_SHOW": Mission.CUSTOM_CSV_DRONE_SHOW,
    "SMART_SWARM": Mission.SMART_SWARM,
    "SWARM_TRAJECTORY": Mission.SWARM_TRAJECTORY,
    "QUICKSCOUT": Mission.QUICKSCOUT,
    "HOVER_TEST": Mission.HOVER_TEST,
}

_CRITICAL_MISSIONS = {
    Mission.TAKE_OFF,
    Mission.LAND,
    Mission.HOLD,
    Mission.RETURN_RTL,
    Mission.KILL_TERMINATE,
}
_MISSIONS_REQUIRING_ARMABILITY_GATE = {
    Mission.TAKE_OFF,
    Mission.DRONE_SHOW_FROM_CSV,
    Mission.CUSTOM_CSV_DRONE_SHOW,
    Mission.SWARM_TRAJECTORY,
    Mission.QUICKSCOUT,
    Mission.HOVER_TEST,
}
_COMMAND_HEARTBEAT_GRACE_SECONDS = max(Params.TELEMETRY_POLLING_TIMEOUT, Params.heartbeat_interval * 2)

def normalize_drone_id(drone_id: Any) -> str:
    """Normalize hardware/position identifiers to strings for consistent routing."""
    return str(drone_id)


def normalize_drone_ids(drone_ids: Iterable[Any]) -> List[str]:
    """Normalize a collection of drone identifiers to strings."""
    return [normalize_drone_id(drone_id) for drone_id in drone_ids]


def _has_recent_heartbeat(heartbeat: Dict[str, Any] | None, now: float) -> bool:
    """Check whether a drone has a heartbeat recent enough for command dispatch."""
    if not heartbeat:
        return False

    timestamp_ms = heartbeat.get('timestamp')
    if not timestamp_ms:
        return False

    try:
        age_seconds = now - (float(timestamp_ms) / 1000.0)
    except (TypeError, ValueError):
        return False

    return age_seconds <= _COMMAND_HEARTBEAT_GRACE_SECONDS


def _partition_recently_online_drones(
    drones: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]], bool]:
    """Split targets into active and clearly-offline groups using recent heartbeats."""
    try:
        heartbeats = get_all_heartbeats()
    except Exception as exc:
        logger.warning(f"Failed to load heartbeats before command dispatch: {exc}")
        return drones, {}, False

    if not heartbeats:
        return drones, {}, False

    now = time.time()
    recent_presence_detected = any(
        _has_recent_heartbeat(heartbeat, now) for heartbeat in heartbeats.values()
    )
    if not recent_presence_detected:
        return drones, {}, False

    active_drones: List[Dict[str, Any]] = []
    preclassified_offline: Dict[str, Dict[str, Any]] = {}

    for drone in drones:
        drone_id = normalize_drone_id(drone.get('hw_id'))
        heartbeat = heartbeats.get(drone_id)

        if _has_recent_heartbeat(heartbeat, now):
            active_drones.append(drone)
            continue

        reason = "No recent heartbeat"
        if heartbeat and heartbeat.get('timestamp'):
            try:
                age_seconds = now - (float(heartbeat['timestamp']) / 1000.0)
                reason = f"Heartbeat stale ({age_seconds:.1f}s old)"
            except (TypeError, ValueError):
                reason = "Heartbeat timestamp invalid"

        preclassified_offline[drone_id] = {
            'success': False,
            'category': CommandResultCategory.OFFLINE.value,
            'error': reason,
            'drone_ip': drone.get('ip'),
        }

    return active_drones, preclassified_offline, True


def resolve_mission_type(mission_type: Any) -> Mission | None:
    """Resolve mission codes and legacy mission names to a Mission enum."""
    if isinstance(mission_type, Mission):
        return mission_type

    enum_value = getattr(mission_type, "value", None)
    if enum_value is not None:
        try:
            mission = Mission._value2member_map_.get(int(enum_value))
        except (TypeError, ValueError):
            mission = None
        if mission is not None:
            return mission

        enum_name = getattr(mission_type, "name", None)
        if isinstance(enum_name, str):
            normalized_name = enum_name.strip().upper().replace("-", "_").replace(" ", "_")
            return _MISSION_NAME_ALIASES.get(normalized_name) or Mission.__members__.get(normalized_name)

    if isinstance(mission_type, int):
        return Mission._value2member_map_.get(mission_type)

    if isinstance(mission_type, str):
        normalized = mission_type.strip()
        if not normalized:
            return None

        try:
            return Mission._value2member_map_.get(int(normalized))
        except ValueError:
            pass

        normalized_name = normalized.upper().replace("-", "_").replace(" ", "_")
        return _MISSION_NAME_ALIASES.get(normalized_name) or Mission.__members__.get(normalized_name)

    return None


def normalize_mission_type(mission_type: Any) -> Tuple[str, str, Mission | None]:
    """Return a drone-API-safe mission value plus a stable log label."""
    mission = resolve_mission_type(mission_type)
    if mission is not None:
        return str(mission.value), f"{mission.name} ({mission.value})", mission

    normalized = str(mission_type).strip() if mission_type is not None else "UNKNOWN"
    normalized = normalized or "UNKNOWN"
    return normalized, normalized, None


def is_critical_mission(mission: Mission | None) -> bool:
    """Identify commands worth always logging at INFO/WARNING on first attempt."""
    return mission in _CRITICAL_MISSIONS


def mission_requires_launch_armability_probe(mission: Mission | None) -> bool:
    """Launch-style missions should be gated on a live MAVSDK armability probe."""
    return resolve_mission_type(mission) in _MISSIONS_REQUIRING_ARMABILITY_GATE


def _log_command_event(message: str, level: str = "INFO", drone_id: Any | None = None) -> None:
    """Emit command logs through the standard MDS logger interface."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    extra = {"mds_drone_id": normalize_drone_id(drone_id)} if drone_id is not None else None
    logger.log(log_level, message, extra=extra)


def _log_drone_command_result(drone_id: Any, command_type: Any, success: bool, detail: str = "") -> None:
    """Log a normalized per-drone command outcome."""
    status = "accepted" if success else "failed"
    message = f"{command_type}: {status}"
    if detail:
        message = f"{message} - {detail}"
    level = "INFO" if success else "ERROR"
    _log_command_event(message, level, drone_id=drone_id)


def _summarize_ack_error(payload: Dict[str, Any]) -> str:
    """Build a concise error summary from a drone ACK payload."""
    message = str(payload.get('message') or 'Drone rejected command')
    error_code = payload.get('error_code')
    if error_code:
        return f"{error_code}: {message}"
    return message


def parse_command_ack_response(response: requests.Response) -> Tuple[bool, str, str]:
    """
    Interpret drone command ACKs.

    Drone API returns HTTP 200 for both accepted and rejected commands, with the
    actual ACK status carried in the JSON payload.
    """
    if response.status_code != 200:
        return (
            False,
            f"HTTP {response.status_code}: {response.text[:100]}",
            CommandResultCategory.REJECTED.value,
        )

    try:
        payload = response.json()
    except ValueError:
        # Older/legacy handlers may not return structured JSON. Preserve the
        # historical 200 == accepted behavior for that case.
        return True, "", CommandResultCategory.ACCEPTED.value

    if not isinstance(payload, dict):
        return True, "", CommandResultCategory.ACCEPTED.value

    status = str(payload.get('status', '')).strip().lower()
    if status in {"", "accepted", "success", "submitted"}:
        return True, "", CommandResultCategory.ACCEPTED.value

    if status == CommandResultCategory.REJECTED.value:
        return False, _summarize_ack_error(payload), CommandResultCategory.REJECTED.value

    if status == CommandResultCategory.OFFLINE.value:
        return False, _summarize_ack_error(payload), CommandResultCategory.OFFLINE.value

    return False, _summarize_ack_error(payload), CommandResultCategory.ERROR.value


def send_command_to_drone(drone: Dict[str, str], command_data: Dict[str, Any],
                         timeout: int = 5, retries: int = 3) -> Tuple[bool, str, str]:
    """
    Send a command to a specific drone with retries and intelligent logging.

    Returns:
        Tuple[bool, str, str]: (success, error_message, category)

    Categories:
        - 'accepted': Command accepted by drone
        - 'offline': Drone unreachable (timeout/connection refused) - NOT an error
        - 'rejected': Drone returned non-200 status
        - 'error': Unexpected error occurred
    """
    drone_id = normalize_drone_id(drone['hw_id'])
    drone_ip = drone['ip'] 
    raw_command_type = command_data.get('missionType', 'UNKNOWN')
    normalized_mission_type, command_type, mission = normalize_mission_type(raw_command_type)
    
    attempt = 0
    backoff_factor = 1
    last_error = ""
    last_category = CommandResultCategory.ERROR.value  # Default category for failures

    # Ensure missionType is string for drone API compatibility
    command_payload = command_data.copy()
    if 'missionType' in command_payload:
        command_payload['missionType'] = normalized_mission_type
    if 'triggerTime' in command_payload:
        command_payload['triggerTime'] = str(command_payload['triggerTime'])

    while attempt < retries:
        try:
            response = requests.post(
                f"http://{drone_ip}:{Params.drone_api_port}/{Params.send_drone_command_URI}",
                json=command_payload,
                timeout=timeout
            )
            
            success, error_message, response_category = parse_command_ack_response(response)
            if success:
                # Success - log only for important commands or first success after failures
                if attempt > 0:  # Recovery from previous failures
                    _log_drone_command_result(
                        drone_id,
                        command_type,
                        True,
                        f"recovered after {attempt} failure(s)"
                    )
                elif is_critical_mission(mission):
                    _log_drone_command_result(drone_id, command_type, True)
                # Don't log routine successful commands to reduce noise

                return True, "", CommandResultCategory.ACCEPTED.value
            else:
                last_error = error_message
                last_category = response_category

        except (Timeout, ConnectionError) as e:
            attempt += 1
            last_error = f"{e.__class__.__name__}: Connection issue"
            last_category = CommandResultCategory.OFFLINE.value  # Network issues = drone offline (NOT an error)

            if attempt < retries:
                wait_time = backoff_factor * (2 ** (attempt - 1))
                # Only log retry attempts for critical commands or on last attempt
                if is_critical_mission(mission) or attempt == retries:
                    _log_command_event(
                        f"Retry {attempt}/{retries} for {command_type} in {wait_time}s due to {e.__class__.__name__}",
                        "WARNING",
                        drone_id=drone_id,
                    )
                time.sleep(wait_time)
                continue
                
        except Exception as e:
            last_error = f"Unexpected error: {str(e)[:100]}"
            break  # Don't retry on unexpected errors
            
        attempt += 1
    
    # Command failed after all retries
    # Only log as error for actual errors, not offline drones
    if last_category != CommandResultCategory.OFFLINE.value:
        _log_drone_command_result(drone_id, command_type, False, last_error)
    # Offline drones are logged at DEBUG level (not worth cluttering logs)

    return False, last_error, last_category


def probe_live_armability_for_drone(
    drone: Dict[str, Any],
    *,
    require_global_position: bool = True,
    timeout: float | None = None,
) -> Dict[str, Any]:
    """Query the drone-side live armability endpoint."""
    drone_id = normalize_drone_id(drone['hw_id'])
    drone_ip = drone['ip']
    request_timeout = float(timeout or getattr(Params, "LIVE_ARMABILITY_PROBE_TIMEOUT_SEC", 6.0) + 1.0)

    try:
        response = requests.get(
            f"http://{drone_ip}:{Params.drone_api_port}/api/live-armability",
            params={"require_global_position": str(bool(require_global_position)).lower()},
            timeout=request_timeout,
        )
        response.raise_for_status()
        payload = response.json()
        ready = bool(payload.get("ready"))
        return {
            "drone_id": drone_id,
            "success": bool(payload.get("success", True)),
            "ready": ready,
            "summary": str(payload.get("summary") or ("Ready for launch" if ready else "Live armability probe reported not ready")),
            "details": payload,
            "category": "ready" if ready else "blocked",
        }
    except (Timeout, ConnectionError) as exc:
        return {
            "drone_id": drone_id,
            "success": False,
            "ready": False,
            "summary": f"Live armability probe unreachable: {exc.__class__.__name__}",
            "details": None,
            "category": CommandResultCategory.OFFLINE.value,
        }
    except Exception as exc:
        return {
            "drone_id": drone_id,
            "success": False,
            "ready": False,
            "summary": f"Live armability probe failed: {str(exc)[:120]}",
            "details": None,
            "category": CommandResultCategory.ERROR.value,
        }


def probe_live_armability_for_drones(
    drones: List[Dict[str, Any]],
    *,
    require_global_position: bool = True,
    timeout: float | None = None,
) -> Dict[str, Any]:
    """Run a bounded live armability probe across target drones."""
    if not drones:
        return {
            "all_ready": True,
            "blocked_ids": [],
            "unavailable_ids": [],
            "results": {},
        }

    results: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(len(drones), 10))) as executor:
        future_to_drone = {
            executor.submit(
                probe_live_armability_for_drone,
                drone,
                require_global_position=require_global_position,
                timeout=timeout,
            ): drone
            for drone in drones
        }

        for future in as_completed(future_to_drone):
            result = future.result()
            results[result["drone_id"]] = result

    blocked_ids = sorted(
        drone_id for drone_id, result in results.items()
        if result.get("category") == "blocked"
    )
    unavailable_ids = sorted(
        drone_id for drone_id, result in results.items()
        if result.get("category") in {CommandResultCategory.OFFLINE.value, CommandResultCategory.ERROR.value}
    )

    return {
        "all_ready": not blocked_ids and not unavailable_ids,
        "blocked_ids": blocked_ids,
        "unavailable_ids": unavailable_ids,
        "results": results,
    }

def send_commands_to_all(drones: List[Dict[str, str]], command_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send a command to all drones concurrently with comprehensive result tracking.
    
    Returns:
        Dict with success/failure counts and details
    """
    if not drones:
        _log_command_event("No drones provided for command execution", "WARNING")
        return {
            'success': 0, 'offline': 0, 'rejected': 0, 'errors': 0,
            'failed': 0, 'total': 0, 'result_summary': 'no drones', 'results': {}
        }
    
    _, command_type, _ = normalize_mission_type(command_data.get('missionType', 'UNKNOWN'))
    
    # Log command initiation for swarm operations
    _log_command_event(
        f"Sending '{command_type}' command to {len(drones)} drones",
        "INFO"
    )
    
    start_time = time.time()
    candidate_drones, preclassified_offline, heartbeat_short_circuit = _partition_recently_online_drones(drones)
    results = dict(preclassified_offline)
    success_count = 0
    offline_count = len(preclassified_offline)
    rejected_count = 0
    error_count = 0

    if heartbeat_short_circuit and preclassified_offline:
        skipped_ids = ", ".join(sorted(preclassified_offline))
        _log_command_event(
            f"Skipping offline targets for '{command_type}' based on recent heartbeat status: {skipped_ids}",
            "INFO",
        )

    # Execute commands concurrently
    with ThreadPoolExecutor(max_workers=max(1, min(len(candidate_drones), 20))) as executor:
        # Submit all commands
        future_to_drone = {
            executor.submit(send_command_to_drone, drone, command_data): drone
            for drone in candidate_drones
        }
        
        # Collect results as they complete
        for future in as_completed(future_to_drone):
            drone = future_to_drone[future]
            drone_id = normalize_drone_id(drone['hw_id'])

            try:
                success, error, category = future.result()
                results[drone_id] = {
                    'success': success,
                    'category': category,
                    'error': error if error else None,
                    'drone_ip': drone['ip']
                }

                if success:
                    success_count += 1
                elif category == CommandResultCategory.OFFLINE.value:
                    offline_count += 1
                elif category == CommandResultCategory.REJECTED.value:
                    rejected_count += 1
                else:
                    error_count += 1

            except Exception as e:
                # Thread execution error
                error_msg = f"Thread execution failed: {str(e)}"
                results[drone_id] = {
                    'success': False,
                    'category': CommandResultCategory.ERROR.value,
                    'error': error_msg,
                    'drone_ip': drone['ip']
                }
                error_count += 1
                _log_drone_command_result(drone_id, command_type, False, error_msg)
    
    # Calculate submission/dispatch time
    execution_time = time.time() - start_time
    # failed_count only includes actual failures (rejected/errors), not offline
    failed_count = rejected_count + error_count
    unavailable_count = offline_count  # Separate tracking for unreachable drones

    # Log comprehensive summary with categorization
    success_rate = (success_count / len(drones)) * 100 if drones else 0
    reachable_count = success_count + rejected_count + error_count  # Drones that responded

    # Build result summary string
    parts = []
    if success_count > 0:
        parts.append(f"{success_count} accepted")
    if offline_count > 0:
        parts.append(f"{offline_count} offline")
    if rejected_count > 0:
        parts.append(f"{rejected_count} rejected")
    if error_count > 0:
        parts.append(f"{error_count} errors")
    result_summary = ", ".join(parts) if parts else "no results"

    if success_count == len(drones):
        # Perfect success
        _log_command_event(
            f"Command '{command_type}' dispatch summary: {result_summary} in {execution_time:.2f}s",
            "INFO"
        )
    elif offline_count == len(drones):
        # All drones offline - informational, not an error
        _log_command_event(
            f"Command '{command_type}' dispatch summary: {result_summary} (no reachable drones) in {execution_time:.2f}s",
            "INFO"
        )
    elif success_count > 0 and error_count == 0 and rejected_count == 0:
        # Some accepted, rest offline - informational
        _log_command_event(
            f"Command '{command_type}' dispatch summary: {result_summary} in {execution_time:.2f}s",
            "INFO"
        )
    elif error_count > 0 or rejected_count > 0:
        # Actual errors or rejections - warning/error level
        log_level = "ERROR" if success_count == 0 else "WARNING"
        _log_command_event(
            f"Command '{command_type}' dispatch summary: {result_summary} in {execution_time:.2f}s",
            log_level
        )
    else:
        # Fallback
        _log_command_event(
            f"Command '{command_type}' dispatch summary: {result_summary} in {execution_time:.2f}s",
            "INFO"
        )
    
    # Log details of failures by category
    if rejected_count > 0 or error_count > 0:
        # Only log rejected/error drones (not offline - that's expected)
        problem_categories = (CommandResultCategory.REJECTED.value, CommandResultCategory.ERROR.value)
        problem_drones = [
            normalize_drone_id(drone_id) for drone_id, result in results.items()
            if result.get('category') in problem_categories
        ]

        # Group by category and error type for cleaner reporting
        category_groups = {}
        for drone_id in problem_drones:
            result = results[drone_id]
            category = result.get('category', CommandResultCategory.ERROR.value)
            error = result['error'] or "Unknown error"
            key = f"{category}:{error.split(':')[0]}"
            if key not in category_groups:
                category_groups[key] = []
            category_groups[key].append(drone_id)

        for key, drone_list in category_groups.items():
            category, error_type = key.split(':', 1)
            log_level = "ERROR" if category == CommandResultCategory.ERROR.value else "WARNING"
            _log_command_event(
                f"Command '{command_type}' {category} ({error_type}) on drones: {', '.join(drone_list[:10])}{'...' if len(drone_list) > 10 else ''}",
                log_level
            )
    
    return {
        'success': success_count,
        'offline': offline_count,
        'rejected': rejected_count,
        'errors': error_count,
        'failed': failed_count,  # Only rejected + errors (actual failures)
        'unavailable': unavailable_count,  # Offline drones (not a failure)
        'total': len(drones),
        'success_rate': success_rate,
        'execution_time': execution_time,
        'result_summary': result_summary,  # Human-readable summary
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
    # Normalize drone IDs to strings (frontend may send integers)
    target_drone_ids = normalize_drone_ids(target_drone_ids) if target_drone_ids else []

    if not target_drone_ids:
        _log_command_event("No target drones specified for selective command", "WARNING")
        return {
            'success': 0, 'offline': 0, 'rejected': 0, 'errors': 0,
            'failed': 0, 'total': 0, 'result_summary': 'no targets', 'results': {}
        }
    
    # Filter drones to only target ones
    target_drones = [
        drone for drone in drones 
        if normalize_drone_id(drone.get('hw_id')) in target_drone_ids
    ]
    
    if len(target_drones) != len(target_drone_ids):
        found_ids = normalize_drone_ids(drone.get('hw_id') for drone in target_drones)
        missing_ids = set(target_drone_ids) - set(found_ids)
        
        _log_command_event(
            f"Some target drones not found in configuration: {', '.join(missing_ids)}",
            "WARNING"
        )
    
    if not target_drones:
        _log_command_event("No valid target drones found for selective command", "ERROR")
        return {
            'success': 0, 'offline': 0, 'rejected': 0, 'errors': 0,
            'failed': 0, 'total': 0, 'result_summary': 'no valid targets', 'results': {}
        }
    
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

    if resolve_mission_type(mission_type) is None:
        return False, "missionType must be a valid mission code or supported mission name"
    
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
    # Validate command data
    is_valid, error_msg = validate_command_data(command_data)
    if not is_valid:
        _log_command_event(f"Invalid command data: {error_msg}", "ERROR")
        return {
            'status': 'error',
            'message': f"Invalid command data: {error_msg}",
            'results': {}
        }
    
    # Validate drone list
    if not drones:
        _log_command_event("No drones available for command execution", "ERROR")
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
        _log_command_event(error_msg, "ERROR")
        return {
            'status': 'error',
            'message': error_msg,
            'results': {}
        }

# Standalone test mode
if __name__ == "__main__":
    import argparse
    from mds_logging.server import init_server_logging
    from mds_logging.cli import add_log_arguments, apply_log_args
    from config import load_config

    parser = argparse.ArgumentParser(description='Test drone command system')
    add_log_arguments(parser)
    parser.add_argument(
        '--command',
        required=True,
        help='Command to send (for example 10, LAND, TAKEOFF, RTL, HOLD)',
    )
    parser.add_argument('--drones', nargs='*', help='Specific drone IDs to target')
    args = parser.parse_args()

    # Initialize logging
    apply_log_args(args)
    init_server_logging()
    
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
