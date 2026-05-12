# tests/fixtures/drone_configs.py
"""
Drone Configuration Fixtures
============================
Pre-built drone configurations for different test scenarios.
Supports single drone, multi-drone (5, 10, 50+), and swarm configurations.
"""

from typing import Dict, List, Any
from dataclasses import dataclass, field
from copy import deepcopy
import random


# ============================================================================
# Base Configuration Templates
# ============================================================================

# Zurich test location (default for SITL)
ZURICH_ORIGIN = {
    'lat': 47.397742,
    'lon': 8.545594,
    'alt': 488.0
}

# San Francisco test location
SF_ORIGIN = {
    'lat': 37.7749,
    'lon': -122.4194,
    'alt': 10.0
}

# Dubai test location (for high altitude tests)
DUBAI_ORIGIN = {
    'lat': 25.2048,
    'lon': 55.2708,
    'alt': 5.0
}


@dataclass
class DroneConfigData:
    """Complete drone configuration for testing"""
    hw_id: str
    pos_id: int
    ip: str
    mavlink_port: int
    serial_port: str = "/dev/ttyS0"
    baudrate: int = 57600

    # Position data
    position_lat: float = 47.397742
    position_lon: float = 8.545594
    position_alt: float = 488.5

    # Velocity
    velocity_north: float = 0.0
    velocity_east: float = 0.0
    velocity_down: float = 0.0

    # Flight status
    yaw: float = 0.0
    battery_voltage: float = 12.6
    flight_mode: int = 4  # HOLD
    base_mode: int = 81
    system_status: int = 4  # STANDBY
    is_armed: bool = False
    is_ready_to_arm: bool = True

    # GPS
    hdop: float = 0.8
    vdop: float = 1.2
    gps_fix_type: int = 3  # 3D fix
    satellites_visible: int = 12

    # State
    state: int = 0  # IDLE
    mission: int = 0  # NONE
    last_mission: int = 0

    # Swarm config
    follow: int = 0  # 0 = leader
    offset_x: float = 0.0
    offset_y: float = 0.0
    offset_z: float = 0.0
    frame: str = "ned"

    def to_config_row(self) -> Dict[str, Any]:
        """Convert to config JSON entry"""
        return {
            'hw_id': self.hw_id,
            'pos_id': self.pos_id,
            'ip': self.ip,
            'mavlink_port': self.mavlink_port,
            'serial_port': self.serial_port,
            'baudrate': self.baudrate
        }

    def to_swarm_row(self) -> Dict[str, Any]:
        """Convert to swarm assignment format"""
        return {
            'hw_id': self.hw_id,
            'follow': self.follow,
            'offset_x': self.offset_x,
            'offset_y': self.offset_y,
            'offset_z': self.offset_z,
            'frame': self.frame,
        }

    def to_drone_state(self) -> Dict[str, Any]:
        """Convert to drone state response format"""
        return {
            'hw_id': self.hw_id,
            'pos_id': self.pos_id,
            'detected_pos_id': self.pos_id,
            'state': self.state,
            'mission': self.mission,
            'last_mission': self.last_mission,
            'position_lat': self.position_lat,
            'position_long': self.position_lon,
            'position_alt': self.position_alt,
            'velocity_north': self.velocity_north,
            'velocity_east': self.velocity_east,
            'velocity_down': self.velocity_down,
            'yaw': self.yaw,
            'battery_voltage': self.battery_voltage,
            'flight_mode': self.flight_mode,
            'base_mode': self.base_mode,
            'system_status': self.system_status,
            'is_armed': self.is_armed,
            'is_ready_to_arm': self.is_ready_to_arm,
            'home_position_set': True,
            'readiness_status': 'ready' if self.is_ready_to_arm else 'blocked',
            'readiness_summary': 'Ready to fly' if self.is_ready_to_arm else 'Preflight checks are not complete.',
            'readiness_checks': [],
            'preflight_blockers': [],
            'preflight_warnings': [],
            'status_messages': [],
            'preflight_last_update': 1703084400000,
            'hdop': self.hdop,
            'vdop': self.vdop,
            'gps_fix_type': self.gps_fix_type,
            'satellites_visible': self.satellites_visible,
            'ip': self.ip,
            'timestamp': 1703084400000
        }


# ============================================================================
# Single Drone Configurations
# ============================================================================

def single_drone_sitl() -> DroneConfigData:
    """Single drone in SITL mode"""
    return DroneConfigData(
        hw_id='1',
        pos_id=1,
        ip='172.18.0.2',
        mavlink_port=14551
    )


def single_drone_real() -> DroneConfigData:
    """Single drone in real mode"""
    return DroneConfigData(
        hw_id='1',
        pos_id=1,
        ip='192.0.2.11',
        mavlink_port=14550,
        serial_port='/dev/ttyS0',
        baudrate=921600
    )


def single_drone_armed() -> DroneConfigData:
    """Single drone that is armed"""
    drone = single_drone_sitl()
    drone.is_armed = True
    drone.base_mode = 209  # Armed + guided
    drone.system_status = 3  # ACTIVE
    return drone


def single_drone_flying() -> DroneConfigData:
    """Single drone in flight"""
    drone = single_drone_armed()
    drone.position_alt = 498.5  # 10m above ground
    drone.velocity_down = 0.0
    drone.flight_mode = 14  # OFFBOARD
    drone.state = 2  # MISSION_EXECUTING
    drone.mission = 1  # DRONE_SHOW_FROM_CSV
    return drone


def single_drone_low_battery() -> DroneConfigData:
    """Single drone with low battery"""
    drone = single_drone_sitl()
    drone.battery_voltage = 10.5
    drone.is_ready_to_arm = False
    return drone


def single_drone_no_gps() -> DroneConfigData:
    """Single drone with no GPS fix"""
    drone = single_drone_sitl()
    drone.gps_fix_type = 0
    drone.satellites_visible = 0
    drone.hdop = 99.99
    drone.vdop = 99.99
    drone.is_ready_to_arm = False
    return drone


# ============================================================================
# Multi-Drone Configurations
# ============================================================================

def generate_drone_configs(
    count: int,
    base_ip: str = "172.18.0",
    base_port: int = 14551,
    origin: Dict[str, float] = None,
    spacing_meters: float = 5.0,
    mode: str = 'sitl'
) -> List[DroneConfigData]:
    """
    Generate configurations for multiple drones.

    Args:
        count: Number of drones
        base_ip: Base IP prefix (drone N gets base_ip.N+1)
        base_port: Starting MAVLink port
        origin: Origin coordinates (lat, lon, alt)
        spacing_meters: Distance between drones in meters
        mode: 'sitl' or 'real'

    Returns:
        List of DroneConfigData
    """
    if origin is None:
        origin = ZURICH_ORIGIN

    drones = []

    # Calculate grid dimensions for drone placement
    grid_size = int(count ** 0.5) + 1

    for i in range(count):
        hw_id = str(i + 1)
        pos_id = i + 1

        # Calculate position offset in grid
        row = i // grid_size
        col = i % grid_size

        # Convert to lat/lon offset (rough approximation)
        # 1 degree lat ~= 111km, 1 degree lon ~= 111km * cos(lat)
        lat_offset = (row * spacing_meters) / 111000.0
        lon_offset = (col * spacing_meters) / (111000.0 * 0.73)  # cos(47) ~= 0.68

        if mode == 'sitl':
            ip = f"{base_ip}.{i + 2}"
            port = base_port + i
            serial = "/dev/ttyS0"
            baudrate = 57600
        else:
            # Real mode uses Netbird IPs
            ip = f"100.96.{240 + i // 256}.{i % 256}"
            port = 14550
            serial = "/dev/ttyS0"
            baudrate = 921600

        drone = DroneConfigData(
            hw_id=hw_id,
            pos_id=pos_id,
            ip=ip,
            mavlink_port=port,
            serial_port=serial,
            baudrate=baudrate,
            position_lat=origin['lat'] + lat_offset,
            position_lon=origin['lon'] + lon_offset,
            position_alt=origin['alt'] + 0.5,
            # Vary battery slightly
            battery_voltage=12.4 + random.random() * 0.4,
            satellites_visible=10 + random.randint(0, 5)
        )
        drones.append(drone)

    return drones


def five_drone_swarm() -> List[DroneConfigData]:
    """5-drone swarm in diamond formation with leader"""
    drones = generate_drone_configs(5)

    # Configure as swarm: drone 1 is leader, others follow
    drones[0].follow = 0  # Leader
    drones[1].follow = 1
    drones[1].offset_x = 5.0
    drones[1].offset_y = 0.0

    drones[2].follow = 1
    drones[2].offset_x = -5.0
    drones[2].offset_y = 0.0

    drones[3].follow = 1
    drones[3].offset_x = 0.0
    drones[3].offset_y = 5.0

    drones[4].follow = 1
    drones[4].offset_x = 0.0
    drones[4].offset_y = -5.0

    return drones


def ten_drone_line() -> List[DroneConfigData]:
    """10 drones in a line formation"""
    return generate_drone_configs(10, spacing_meters=3.0)


def fifty_drone_grid() -> List[DroneConfigData]:
    """50 drones in a grid formation for load testing"""
    return generate_drone_configs(50, spacing_meters=5.0)


def hundred_drone_grid() -> List[DroneConfigData]:
    """100 drones for extreme load testing"""
    return generate_drone_configs(100, spacing_meters=5.0)


# ============================================================================
# Error Scenario Configurations
# ============================================================================

def drone_with_timeout() -> DroneConfigData:
    """Drone configuration for timeout testing (unreachable IP)"""
    return DroneConfigData(
        hw_id='timeout',
        pos_id=99,
        ip='192.168.255.255',  # Unreachable
        mavlink_port=14550
    )


def drone_with_invalid_data() -> DroneConfigData:
    """Drone with invalid/corrupt data"""
    drone = single_drone_sitl()
    drone.position_lat = 999.0  # Invalid latitude
    drone.position_lon = 999.0  # Invalid longitude
    drone.battery_voltage = -1.0  # Invalid
    return drone


def drone_disconnected() -> DroneConfigData:
    """Drone that appears disconnected"""
    drone = single_drone_sitl()
    drone.gps_fix_type = 0
    drone.satellites_visible = 0
    drone.battery_voltage = 0.0
    drone.system_status = 0  # UNINIT
    return drone


# ============================================================================
# Config Export Functions
# ============================================================================

def drones_to_config_csv(drones: List[DroneConfigData]) -> str:
    """Legacy: Convert drone list to config.csv format (kept for CSV import tests)"""
    header = "hw_id,pos_id,ip,mavlink_port,serial_port,baudrate"
    rows = [header]
    for drone in drones:
        row = f"{drone.hw_id},{drone.pos_id},{drone.ip},{drone.mavlink_port},{drone.serial_port},{drone.baudrate}"
        rows.append(row)
    return "\n".join(rows)


def drones_to_swarm_csv(drones: List[DroneConfigData]) -> str:
    """Legacy: Convert drone list to swarm.csv format (kept for CSV import tests)"""
    header = "hw_id,follow,offset_x,offset_y,offset_z,frame"
    rows = [header]
    for drone in drones:
        row = f"{drone.hw_id},{drone.follow},{drone.offset_x},{drone.offset_y},{drone.offset_z},{drone.frame}"
        rows.append(row)
    return "\n".join(rows)


def drones_to_config_json(drones: List[DroneConfigData]) -> dict:
    """Convert drone list to config.json format"""
    return {
        "version": 1,
        "drones": [d.to_config_row() for d in drones]
    }


def drones_to_swarm_json(drones: List[DroneConfigData]) -> dict:
    """Convert drone list to swarm.json format"""
    return {
        "version": 1,
        "assignments": [d.to_swarm_row() for d in drones]
    }


def drones_to_telemetry_response(drones: List[DroneConfigData]) -> Dict[str, Dict]:
    """Convert drone list to telemetry response format"""
    return {drone.hw_id: drone.to_drone_state() for drone in drones}


# ============================================================================
# Pytest Fixtures
# ============================================================================

# These will be imported into conftest.py
__all__ = [
    'DroneConfigData',
    'ZURICH_ORIGIN',
    'SF_ORIGIN',
    'DUBAI_ORIGIN',
    'single_drone_sitl',
    'single_drone_real',
    'single_drone_armed',
    'single_drone_flying',
    'single_drone_low_battery',
    'single_drone_no_gps',
    'generate_drone_configs',
    'five_drone_swarm',
    'ten_drone_line',
    'fifty_drone_grid',
    'hundred_drone_grid',
    'drone_with_timeout',
    'drone_with_invalid_data',
    'drone_disconnected',
    'drones_to_config_csv',
    'drones_to_swarm_csv',
    'drones_to_config_json',
    'drones_to_swarm_json',
    'drones_to_telemetry_response',
]
