# tests/mocks/mavlink_simulator.py
"""
MAVLink Protocol Simulator
==========================
Mock implementation for simulating MAVLink communication without real hardware.
"""

from typing import Dict, List, Any, Optional, Callable
from unittest.mock import Mock, MagicMock, AsyncMock
import asyncio
import struct
import time
import threading


# ============================================================================
# MAVLink Constants
# ============================================================================

class MAVLinkConstants:
    """MAVLink protocol constants"""
    # Message IDs
    HEARTBEAT = 0
    SYS_STATUS = 1
    GPS_RAW_INT = 24
    ATTITUDE = 30
    LOCAL_POSITION_NED = 32
    GLOBAL_POSITION_INT = 33
    GPS_GLOBAL_ORIGIN = 49
    HOME_POSITION = 242
    BATTERY_STATUS = 147
    COMMAND_LONG = 76
    COMMAND_ACK = 77

    # Base modes
    MAV_MODE_FLAG_ARMED = 128
    MAV_MODE_FLAG_GUIDED_ENABLED = 8

    # System status
    MAV_STATE_STANDBY = 3
    MAV_STATE_ACTIVE = 4

    # Results
    MAV_RESULT_ACCEPTED = 0
    MAV_RESULT_DENIED = 4


# ============================================================================
# Mock MAVLink Connection
# ============================================================================

class MockMAVLinkConnection:
    """Mock MAVLink connection for testing"""

    def __init__(
        self,
        connection_string: str = "udp://127.0.0.1:14540",
        system_id: int = 1,
        component_id: int = 1
    ):
        self.connection_string = connection_string
        self.system_id = system_id
        self.component_id = component_id

        # State
        self.is_connected = False
        self.messages: List[Dict[str, Any]] = []
        self.message_handlers: Dict[str, List[Callable]] = {}

        # Simulated drone state
        self._armed = False
        self._flight_mode = 4  # LOITER
        self._position = {'lat': 47.397742, 'lon': 8.545594, 'alt': 488.5}
        self._velocity = {'vn': 0.0, 've': 0.0, 'vd': 0.0}
        self._battery = 12.6
        self._gps_fix = 3
        self._satellites = 12

    def connect(self) -> bool:
        """Simulate connection"""
        self.is_connected = True
        return True

    def disconnect(self):
        """Simulate disconnection"""
        self.is_connected = False

    def recv_msg(self) -> Optional[Dict[str, Any]]:
        """Receive a message (returns None if no messages)"""
        if self.messages:
            return self.messages.pop(0)
        return None

    def send_message(self, msg_type: int, **kwargs):
        """Send a MAVLink message"""
        msg = {
            'type': msg_type,
            'timestamp': time.time(),
            **kwargs
        }
        self.messages.append(msg)

    def add_message_handler(self, msg_type: str, handler: Callable):
        """Add a message handler"""
        if msg_type not in self.message_handlers:
            self.message_handlers[msg_type] = []
        self.message_handlers[msg_type].append(handler)

    # ========================================================================
    # Simulated Telemetry Generation
    # ========================================================================

    def generate_heartbeat(self) -> Dict[str, Any]:
        """Generate a heartbeat message"""
        base_mode = 81
        if self._armed:
            base_mode |= MAVLinkConstants.MAV_MODE_FLAG_ARMED

        return {
            'type': MAVLinkConstants.HEARTBEAT,
            'custom_mode': self._flight_mode,
            'base_mode': base_mode,
            'system_status': MAVLinkConstants.MAV_STATE_ACTIVE if self._armed else MAVLinkConstants.MAV_STATE_STANDBY,
            'autopilot': 12,  # PX4
            'mavlink_version': 3
        }

    def generate_global_position(self) -> Dict[str, Any]:
        """Generate a global position message"""
        return {
            'type': MAVLinkConstants.GLOBAL_POSITION_INT,
            'time_boot_ms': int(time.time() * 1000) % (2**32),
            'lat': int(self._position['lat'] * 1e7),
            'lon': int(self._position['lon'] * 1e7),
            'alt': int(self._position['alt'] * 1000),
            'relative_alt': int((self._position['alt'] - 488.0) * 1000),
            'vx': int(self._velocity['vn'] * 100),
            'vy': int(self._velocity['ve'] * 100),
            'vz': int(self._velocity['vd'] * 100),
            'hdg': 0
        }

    def generate_gps_raw(self) -> Dict[str, Any]:
        """Generate a GPS raw message"""
        return {
            'type': MAVLinkConstants.GPS_RAW_INT,
            'time_usec': int(time.time() * 1e6),
            'fix_type': self._gps_fix,
            'lat': int(self._position['lat'] * 1e7),
            'lon': int(self._position['lon'] * 1e7),
            'alt': int(self._position['alt'] * 1000),
            'satellites_visible': self._satellites,
            'eph': 80,  # HDOP in cm
            'epv': 120  # VDOP in cm
        }

    def generate_battery_status(self) -> Dict[str, Any]:
        """Generate a battery status message"""
        return {
            'type': MAVLinkConstants.BATTERY_STATUS,
            'id': 0,
            'voltages': [int(self._battery * 1000)] + [65535] * 9,
            'current_battery': 500,  # 5A
            'battery_remaining': 80
        }

    def generate_all_telemetry(self) -> List[Dict[str, Any]]:
        """Generate all telemetry messages"""
        return [
            self.generate_heartbeat(),
            self.generate_global_position(),
            self.generate_gps_raw(),
            self.generate_battery_status()
        ]

    # ========================================================================
    # Command Simulation
    # ========================================================================

    def process_command(self, command: int, params: List[float]) -> int:
        """Process a MAVLink command and return result"""
        # ARM/DISARM
        if command == 400:  # MAV_CMD_COMPONENT_ARM_DISARM
            self._armed = params[0] == 1.0
            return MAVLinkConstants.MAV_RESULT_ACCEPTED

        # Takeoff
        if command == 22:  # MAV_CMD_NAV_TAKEOFF
            if not self._armed:
                return MAVLinkConstants.MAV_RESULT_DENIED
            self._position['alt'] += params[6]  # Altitude param
            return MAVLinkConstants.MAV_RESULT_ACCEPTED

        # Land
        if command == 21:  # MAV_CMD_NAV_LAND
            return MAVLinkConstants.MAV_RESULT_ACCEPTED

        # RTL
        if command == 20:  # MAV_CMD_NAV_RETURN_TO_LAUNCH
            self._flight_mode = 5  # AUTO_RTL
            return MAVLinkConstants.MAV_RESULT_ACCEPTED

        return MAVLinkConstants.MAV_RESULT_ACCEPTED


# ============================================================================
# Mock MAVSDK System
# ============================================================================

class MockMAVSDKSystem:
    """Mock MAVSDK System for testing"""

    def __init__(self, system_id: int = 1):
        self.system_id = system_id
        self._connection = MockMAVLinkConnection(system_id=system_id)

        # Mock plugins
        self.telemetry = MockTelemetryPlugin(self._connection)
        self.action = MockActionPlugin(self._connection)
        self.offboard = MockOffboardPlugin(self._connection)
        self.param = MockParamPlugin()

    async def connect(self, system_address: str = "udp://:14540"):
        """Connect to the system"""
        await asyncio.sleep(0.1)  # Simulate connection delay
        self._connection.connect()
        return True

    async def disconnect(self):
        """Disconnect from the system"""
        self._connection.disconnect()


class MockTelemetryPlugin:
    """Mock MAVSDK Telemetry plugin"""

    def __init__(self, connection: MockMAVLinkConnection):
        self._conn = connection

    async def position(self):
        """Get current position"""
        return type('Position', (), {
            'latitude_deg': self._conn._position['lat'],
            'longitude_deg': self._conn._position['lon'],
            'absolute_altitude_m': self._conn._position['alt'],
            'relative_altitude_m': self._conn._position['alt'] - 488.0
        })()

    async def armed(self) -> bool:
        """Get armed state"""
        return self._conn._armed

    async def flight_mode(self):
        """Get flight mode"""
        return type('FlightMode', (), {'value': self._conn._flight_mode})()

    async def battery(self):
        """Get battery status"""
        return type('Battery', (), {
            'voltage_v': self._conn._battery,
            'remaining_percent': 80.0
        })()

    async def gps_info(self):
        """Get GPS info"""
        return type('GpsInfo', (), {
            'fix_type': self._conn._gps_fix,
            'num_satellites': self._conn._satellites
        })()


class MockActionPlugin:
    """Mock MAVSDK Action plugin"""

    def __init__(self, connection: MockMAVLinkConnection):
        self._conn = connection

    async def arm(self):
        """Arm the drone"""
        result = self._conn.process_command(400, [1.0])
        if result != MAVLinkConstants.MAV_RESULT_ACCEPTED:
            raise Exception("Arm failed")

    async def disarm(self):
        """Disarm the drone"""
        result = self._conn.process_command(400, [0.0])
        if result != MAVLinkConstants.MAV_RESULT_ACCEPTED:
            raise Exception("Disarm failed")

    async def takeoff(self):
        """Take off"""
        if not self._conn._armed:
            raise Exception("Cannot takeoff - not armed")
        self._conn._position['alt'] += 10.0

    async def land(self):
        """Land"""
        pass

    async def return_to_launch(self):
        """Return to launch"""
        self._conn._flight_mode = 5

    async def kill(self):
        """Emergency kill"""
        self._conn._armed = False


class MockOffboardPlugin:
    """Mock MAVSDK Offboard plugin"""

    def __init__(self, connection: MockMAVLinkConnection):
        self._conn = connection
        self._is_active = False

    async def start(self):
        """Start offboard mode"""
        self._is_active = True
        self._conn._flight_mode = 14  # OFFBOARD

    async def stop(self):
        """Stop offboard mode"""
        self._is_active = False

    async def set_position_ned(self, position_ned):
        """Set position in NED frame"""
        pass

    async def set_velocity_ned(self, velocity_ned):
        """Set velocity in NED frame"""
        pass


class MockParamPlugin:
    """Mock MAVSDK Param plugin"""

    def __init__(self):
        self._params: Dict[str, Any] = {}

    async def get_param_int(self, name: str) -> int:
        """Get integer parameter"""
        return self._params.get(name, 0)

    async def set_param_int(self, name: str, value: int):
        """Set integer parameter"""
        self._params[name] = value

    async def get_param_float(self, name: str) -> float:
        """Get float parameter"""
        return self._params.get(name, 0.0)

    async def set_param_float(self, name: str, value: float):
        """Set float parameter"""
        self._params[name] = value


# ============================================================================
# Mock MAVLink Router
# ============================================================================

class MockMAVLinkRouter:
    """Mock for mavlink-routerd process"""

    def __init__(self):
        self.is_running = False
        self.endpoints: List[str] = []
        self.pid = 12345

    def start(self, config: Dict[str, Any] = None):
        """Start the router"""
        self.is_running = True

    def stop(self):
        """Stop the router"""
        self.is_running = False

    def add_endpoint(self, endpoint: str):
        """Add routing endpoint"""
        self.endpoints.append(endpoint)


# ============================================================================
# Factory Functions for Tests
# ============================================================================

def create_mock_mavsdk_system(system_id: int = 1) -> MockMAVSDKSystem:
    """Create a mock MAVSDK system for testing"""
    return MockMAVSDKSystem(system_id=system_id)


def create_mock_mavlink_connection(
    system_id: int = 1,
    armed: bool = False,
    position: Dict[str, float] = None
) -> MockMAVLinkConnection:
    """Create a mock MAVLink connection"""
    conn = MockMAVLinkConnection(system_id=system_id)
    conn._armed = armed
    if position:
        conn._position = position
    conn.connect()
    return conn


def create_mock_mavlink_router() -> MockMAVLinkRouter:
    """Create a mock MAVLink router"""
    return MockMAVLinkRouter()


# ============================================================================
# Pytest Fixtures (to be imported into conftest.py)
# ============================================================================

def mock_mavsdk_system_fixture():
    """Pytest fixture for mock MAVSDK system"""
    system = create_mock_mavsdk_system()
    yield system


def mock_mavlink_connection_fixture():
    """Pytest fixture for mock MAVLink connection"""
    conn = create_mock_mavlink_connection()
    yield conn
    conn.disconnect()


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    'MAVLinkConstants',
    'MockMAVLinkConnection',
    'MockMAVSDKSystem',
    'MockTelemetryPlugin',
    'MockActionPlugin',
    'MockOffboardPlugin',
    'MockParamPlugin',
    'MockMAVLinkRouter',
    'create_mock_mavsdk_system',
    'create_mock_mavlink_connection',
    'create_mock_mavlink_router',
]
