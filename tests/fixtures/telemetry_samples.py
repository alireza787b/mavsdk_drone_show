# tests/fixtures/telemetry_samples.py
"""
Telemetry Sample Fixtures
=========================
Pre-built telemetry data including MAVLink messages, drone states,
and various flight scenarios.
"""

from typing import Dict, List, Any
import struct
import time


# ============================================================================
# MAVLink Message Types (subset commonly used)
# ============================================================================

class MAVLinkMsgId:
    """MAVLink message ID constants"""
    HEARTBEAT = 0
    SYS_STATUS = 1
    GPS_RAW_INT = 24
    ATTITUDE = 30
    GLOBAL_POSITION_INT = 33
    LOCAL_POSITION_NED = 32
    GPS_GLOBAL_ORIGIN = 49
    HOME_POSITION = 242
    BATTERY_STATUS = 147


# ============================================================================
# Flight Mode Constants
# ============================================================================

class PX4FlightMode:
    """PX4 flight mode constants"""
    MANUAL = 0
    ALTCTL = 1
    POSCTL = 2
    AUTO_MISSION = 3
    AUTO_LOITER = 4
    AUTO_RTL = 5
    ACRO = 6
    OFFBOARD = 14
    STABILIZED = 7
    RATTITUDE = 8
    AUTO_TAKEOFF = 10
    AUTO_LAND = 11
    AUTO_FOLLOW = 12
    AUTO_PRECLAND = 13


# ============================================================================
# System Status Constants
# ============================================================================

class MAVState:
    """MAVLink system state"""
    UNINIT = 0
    BOOT = 1
    CALIBRATING = 2
    STANDBY = 3
    ACTIVE = 4
    CRITICAL = 5
    EMERGENCY = 6
    POWEROFF = 7
    FLIGHT_TERMINATION = 8


# ============================================================================
# Telemetry State Builders
# ============================================================================

def drone_state_idle(hw_id: str = '1', pos_id: int = 1) -> Dict[str, Any]:
    """Drone in idle state on ground"""
    return {
        'hw_id': hw_id,
        'pos_id': pos_id,
        'detected_pos_id': pos_id,
        'state': 0,  # IDLE
        'mission': 0,  # NONE
        'last_mission': 0,
        'position_lat': 47.397742,
        'position_long': 8.545594,
        'position_alt': 488.5,
        'velocity_north': 0.0,
        'velocity_east': 0.0,
        'velocity_down': 0.0,
        'yaw': 0.0,
        'battery_voltage': 12.6,
        'flight_mode': PX4FlightMode.AUTO_LOITER,
        'base_mode': 81,  # Disarmed
        'system_status': MAVState.STANDBY,
        'is_armed': False,
        'is_ready_to_arm': True,
        'home_position_set': True,
        'global_position_valid': True,
        'global_position_timestamp_ms': int(time.time() * 1000),
        'global_position_age_ms': 0,
        'gps_raw_valid': True,
        'gps_raw_timestamp_ms': int(time.time() * 1000),
        'gps_raw_age_ms': 0,
        'position_source': 'global_position_int',
        'position_unavailable_reason': None,
        'readiness_status': 'ready',
        'readiness_summary': 'Ready to fly',
        'readiness_checks': [],
        'preflight_blockers': [],
        'preflight_warnings': [],
        'status_messages': [],
        'preflight_last_update': int(time.time() * 1000),
        'hdop': 0.8,
        'vdop': 1.2,
        'gps_fix_type': 3,
        'satellites_visible': 12,
        'ip': '172.18.0.2',
        'timestamp': int(time.time() * 1000)
    }


def drone_state_armed(hw_id: str = '1', pos_id: int = 1) -> Dict[str, Any]:
    """Drone armed and ready for takeoff"""
    state = drone_state_idle(hw_id, pos_id)
    state.update({
        'is_armed': True,
        'base_mode': 209,  # Armed
        'system_status': MAVState.ACTIVE
    })
    return state


def drone_state_taking_off(hw_id: str = '1', pos_id: int = 1) -> Dict[str, Any]:
    """Drone in takeoff"""
    state = drone_state_armed(hw_id, pos_id)
    state.update({
        'state': 2,  # MISSION_EXECUTING
        'mission': 10,  # TAKE_OFF
        'flight_mode': PX4FlightMode.AUTO_TAKEOFF,
        'position_alt': 492.0,  # Climbing
        'velocity_down': -2.0  # Going up
    })
    return state


def drone_state_hovering(hw_id: str = '1', pos_id: int = 1) -> Dict[str, Any]:
    """Drone hovering in position"""
    state = drone_state_armed(hw_id, pos_id)
    state.update({
        'state': 2,  # MISSION_EXECUTING
        'mission': 102,  # HOLD
        'flight_mode': PX4FlightMode.AUTO_LOITER,
        'position_alt': 498.5,  # 10m above ground
        'velocity_down': 0.0
    })
    return state


def drone_state_flying_mission(hw_id: str = '1', pos_id: int = 1) -> Dict[str, Any]:
    """Drone executing mission"""
    state = drone_state_armed(hw_id, pos_id)
    state.update({
        'state': 2,  # MISSION_EXECUTING
        'mission': 1,  # DRONE_SHOW_FROM_CSV
        'flight_mode': PX4FlightMode.OFFBOARD,
        'position_alt': 500.0,
        'velocity_north': 1.5,
        'velocity_east': 0.5,
        'velocity_down': 0.0
    })
    return state


def drone_state_returning(hw_id: str = '1', pos_id: int = 1) -> Dict[str, Any]:
    """Drone returning to launch"""
    state = drone_state_armed(hw_id, pos_id)
    state.update({
        'state': 2,  # MISSION_EXECUTING
        'mission': 104,  # RETURN_RTL
        'flight_mode': PX4FlightMode.AUTO_RTL,
        'position_alt': 495.0,
        'velocity_north': -1.0,
        'velocity_east': -0.5,
        'velocity_down': 0.5  # Descending
    })
    return state


def drone_state_landing(hw_id: str = '1', pos_id: int = 1) -> Dict[str, Any]:
    """Drone landing"""
    state = drone_state_armed(hw_id, pos_id)
    state.update({
        'state': 2,  # MISSION_EXECUTING
        'mission': 101,  # LAND
        'flight_mode': PX4FlightMode.AUTO_LAND,
        'position_alt': 490.0,
        'velocity_down': 0.8  # Descending
    })
    return state


def drone_state_low_battery(hw_id: str = '1', pos_id: int = 1) -> Dict[str, Any]:
    """Drone with low battery"""
    state = drone_state_idle(hw_id, pos_id)
    state.update({
        'battery_voltage': 10.2,
        'is_ready_to_arm': False,
        'readiness_status': 'blocked',
        'readiness_summary': 'Battery voltage is too low for safe flight preparation.',
        'preflight_blockers': [{
            'source': 'telemetry',
            'severity': 'error',
            'message': 'Battery voltage is too low for safe flight preparation.',
            'timestamp': int(time.time() * 1000),
        }],
    })
    return state


def drone_state_no_gps(hw_id: str = '1', pos_id: int = 1) -> Dict[str, Any]:
    """Drone with no GPS fix"""
    state = drone_state_idle(hw_id, pos_id)
    state.update({
        'gps_fix_type': 0,
        'satellites_visible': 0,
        'hdop': 99.99,
        'vdop': 99.99,
        'is_ready_to_arm': False,
        'readiness_status': 'blocked',
        'readiness_summary': 'GPS fix is below 3D while the current flight mode requires GPS.',
        'preflight_blockers': [{
            'source': 'telemetry',
            'severity': 'error',
            'message': 'GPS fix is below 3D while the current flight mode requires GPS.',
            'timestamp': int(time.time() * 1000),
        }],
    })
    return state


def drone_state_emergency(hw_id: str = '1', pos_id: int = 1) -> Dict[str, Any]:
    """Drone in emergency state"""
    state = drone_state_armed(hw_id, pos_id)
    state.update({
        'system_status': MAVState.EMERGENCY,
        'flight_mode': PX4FlightMode.AUTO_LAND,
        'mission': 105,  # KILL_TERMINATE
        'state': 2
    })
    return state


def drone_state_disconnected(hw_id: str = '1', pos_id: int = 1) -> Dict[str, Any]:
    """Simulated disconnected drone (stale data)"""
    state = drone_state_idle(hw_id, pos_id)
    state.update({
        'timestamp': int(time.time() * 1000) - 30000,  # 30 seconds ago
        'system_status': MAVState.UNINIT,
        'battery_voltage': 0.0
    })
    return state


# ============================================================================
# Multi-Drone Telemetry
# ============================================================================

def multi_drone_telemetry(count: int = 5) -> Dict[str, Dict[str, Any]]:
    """Generate telemetry for multiple drones"""
    telemetry = {}
    for i in range(count):
        hw_id = str(i + 1)
        telemetry[hw_id] = drone_state_idle(hw_id, i + 1)
        telemetry[hw_id]['ip'] = f'172.18.0.{i + 2}'
    return telemetry


def swarm_telemetry_flying(count: int = 5) -> Dict[str, Dict[str, Any]]:
    """Generate telemetry for flying swarm"""
    telemetry = {}
    for i in range(count):
        hw_id = str(i + 1)
        telemetry[hw_id] = drone_state_flying_mission(hw_id, i + 1)
        telemetry[hw_id]['ip'] = f'172.18.0.{i + 2}'
        # Offset positions slightly
        telemetry[hw_id]['position_lat'] += i * 0.00005
        telemetry[hw_id]['position_long'] += i * 0.00005
    return telemetry


def fifty_drone_telemetry() -> Dict[str, Dict[str, Any]]:
    """Generate telemetry for 50 drones (load testing)"""
    return multi_drone_telemetry(50)


# ============================================================================
# MAVLink Message Builders
# ============================================================================

def mavlink_heartbeat(
    custom_mode: int = PX4FlightMode.AUTO_LOITER,
    base_mode: int = 81,
    system_status: int = MAVState.STANDBY
) -> bytes:
    """Build a MAVLink heartbeat message"""
    # MAVLink heartbeat structure (simplified)
    # custom_mode (4 bytes), type (1), autopilot (1), base_mode (1), system_status (1), mavlink_version (1)
    return struct.pack('<IBBBBB',
        custom_mode,
        2,  # MAV_TYPE_QUADROTOR
        12,  # MAV_AUTOPILOT_PX4
        base_mode,
        system_status,
        3  # MAVLink version 2
    )


def mavlink_global_position_int(
    lat: float = 47.397742,
    lon: float = 8.545594,
    alt: int = 488500,  # mm
    relative_alt: int = 500,  # mm
    vx: int = 0,  # cm/s
    vy: int = 0,
    vz: int = 0,
    hdg: int = 0  # cdeg
) -> bytes:
    """Build MAVLink GLOBAL_POSITION_INT message"""
    lat_int = int(lat * 1e7)
    lon_int = int(lon * 1e7)
    return struct.pack('<IiiiihhHH',
        int(time.time() * 1000) % (2**32),  # time_boot_ms
        lat_int, lon_int,
        alt, relative_alt,
        vx, vy, vz, hdg
    )


def mavlink_battery_status(
    voltage: float = 12.6,
    current: float = 5.0,
    remaining: int = 80
) -> bytes:
    """Build MAVLink BATTERY_STATUS message"""
    voltages = [int(voltage * 1000)] + [65535] * 9  # Only first cell used
    return struct.pack('<BbhhhHhB' + 'H' * 10,
        0,  # id
        0,  # battery_function
        0,  # type
        int(voltage * 100),  # temperature (placeholder)
        voltages[0], voltages[1], voltages[2], voltages[3], voltages[4],
        int(current * 100),  # current_battery
        0,  # current_consumed
        0,  # energy_consumed
        remaining,  # battery_remaining
        *voltages
    )


def mavlink_gps_raw_int(
    lat: float = 47.397742,
    lon: float = 8.545594,
    alt: int = 488500,
    fix_type: int = 3,
    satellites: int = 12,
    hdop: int = 80,  # cm
    vdop: int = 120  # cm
) -> bytes:
    """Build MAVLink GPS_RAW_INT message"""
    lat_int = int(lat * 1e7)
    lon_int = int(lon * 1e7)
    return struct.pack('<QiiiHHHHBB',
        int(time.time() * 1e6),  # time_usec
        lat_int, lon_int, alt,
        hdop, vdop,
        0,  # vel (cm/s)
        0,  # cog (cdeg)
        fix_type,
        satellites
    )


# ============================================================================
# Telemetry Response Builders
# ============================================================================

def telemetry_response_success(drone_states: Dict[str, Dict]) -> Dict[str, Any]:
    """Build successful telemetry response"""
    return drone_states


def telemetry_response_partial(
    available: List[str],
    unavailable: List[str]
) -> Dict[str, Any]:
    """Build partial telemetry response (some drones offline)"""
    result = {}
    for hw_id in available:
        result[hw_id] = drone_state_idle(hw_id, int(hw_id))
    # Unavailable drones are simply not in the response
    return result


def telemetry_response_empty() -> Dict[str, Any]:
    """Empty telemetry response (no drones connected)"""
    return {}


# ============================================================================
# Heartbeat Response Builders
# ============================================================================

def heartbeat_data(
    hw_id: str = '1',
    pos_id: int = 1,
    ip: str = '172.18.0.2',
    online: bool = True
) -> Dict[str, Any]:
    """Build single heartbeat data"""
    timestamp = int(time.time() * 1000)
    if not online:
        timestamp -= 30000  # 30 seconds ago
    return {
        'hw_id': hw_id,
        'pos_id': pos_id,
        'ip': ip,
        'last_heartbeat': timestamp,
        'online': online,
        'heartbeat_age_sec': 0.0 if online else 30.0
    }


def heartbeat_response(count: int = 5) -> Dict[str, Any]:
    """Build heartbeat response for multiple drones"""
    heartbeats = []
    for i in range(count):
        heartbeats.append(heartbeat_data(
            hw_id=str(i + 1),
            pos_id=i + 1,
            ip=f'172.18.0.{i + 2}'
        ))

    return {
        'heartbeats': heartbeats,
        'total_drones': count,
        'online_count': count,
        'timestamp': int(time.time() * 1000)
    }


def heartbeat_response_partial_offline(
    total: int = 5,
    offline_ids: List[int] = None
) -> Dict[str, Any]:
    """Build heartbeat response with some drones offline"""
    if offline_ids is None:
        offline_ids = [3, 5]

    heartbeats = []
    online_count = 0
    for i in range(total):
        hw_id = i + 1
        online = hw_id not in offline_ids
        if online:
            online_count += 1
        heartbeats.append(heartbeat_data(
            hw_id=str(hw_id),
            pos_id=hw_id,
            ip=f'172.18.0.{hw_id + 1}',
            online=online
        ))

    return {
        'heartbeats': heartbeats,
        'total_drones': total,
        'online_count': online_count,
        'timestamp': int(time.time() * 1000)
    }


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    'MAVLinkMsgId',
    'PX4FlightMode',
    'MAVState',
    'drone_state_idle',
    'drone_state_armed',
    'drone_state_taking_off',
    'drone_state_hovering',
    'drone_state_flying_mission',
    'drone_state_returning',
    'drone_state_landing',
    'drone_state_low_battery',
    'drone_state_no_gps',
    'drone_state_emergency',
    'drone_state_disconnected',
    'multi_drone_telemetry',
    'swarm_telemetry_flying',
    'fifty_drone_telemetry',
    'mavlink_heartbeat',
    'mavlink_global_position_int',
    'mavlink_battery_status',
    'mavlink_gps_raw_int',
    'telemetry_response_success',
    'telemetry_response_partial',
    'telemetry_response_empty',
    'heartbeat_data',
    'heartbeat_response',
    'heartbeat_response_partial_offline',
]
