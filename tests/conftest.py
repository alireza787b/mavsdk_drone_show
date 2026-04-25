# tests/conftest.py
"""
Pytest Configuration and Shared Fixtures
=========================================
Provides reusable test fixtures for all test modules.

This module includes:
- Basic mock fixtures for unit tests
- Multi-drone configurations for swarm tests (5, 10, 50+ drones)
- MAVLink simulation fixtures
- Command and telemetry sample fixtures
- Coordinator and drone setup fixtures
"""

import pytest
from src.settings.deployment_profile import reset_deployment_profile_cache
from src.settings.runtime import reset_preloaded_local_env_state
import asyncio
import httpx
import tempfile
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from typing import Dict, List, Any
from fastapi.testclient import TestClient as FastAPITestClient

# Configure Python path for all test modules
# This is the SINGLE source of truth for path configuration in tests
import sys
import os

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_GCS_SERVER = os.path.join(_PROJECT_ROOT, 'gcs-server')
_SRC_DIR = os.path.join(_PROJECT_ROOT, 'src')

# Keep matplotlib test imports from warning on root-owned environments.
os.environ.setdefault('MPLCONFIGDIR', tempfile.mkdtemp(prefix='mds-mplconfig-'))

# Add paths in order of priority
for _path in [_PROJECT_ROOT, _GCS_SERVER, _SRC_DIR]:
    if _path not in sys.path:
        sys.path.insert(0, _path)

# Some lean local environments used for focused API validation do not have the
# full MAVSDK gRPC dependency chain installed. Tests stub it at import time so
# route/contract coverage can still run without a flight runtime.
try:
    import aiogrpc  # type: ignore  # noqa: F401
except ModuleNotFoundError:
    sys.modules["aiogrpc"] = MagicMock(name="aiogrpc")

from src.drone_api_server import DroneAPIServer
from src.params import Params
from src.drone_config import DroneConfig

# Import test fixtures
from tests.fixtures.drone_configs import (
    DroneConfigData,
    ZURICH_ORIGIN,
    single_drone_sitl,
    single_drone_real,
    single_drone_armed,
    single_drone_flying,
    single_drone_low_battery,
    single_drone_no_gps,
    generate_drone_configs,
    five_drone_swarm,
    ten_drone_line,
    fifty_drone_grid,
    hundred_drone_grid,
    drone_with_timeout,
    drone_disconnected,
    drones_to_config_json,
    drones_to_swarm_json,
    drones_to_telemetry_response,
)

from tests.fixtures.command_samples import (
    MissionType,
    cmd_takeoff,
    cmd_land,
    cmd_hold,
    cmd_rtl,
    cmd_kill_terminate,
    cmd_drone_show,
    cmd_smart_swarm,
    cmd_hover_test,
    all_valid_commands,
    all_invalid_commands,
)

from tests.fixtures.telemetry_samples import (
    PX4FlightMode,
    MAVState,
    drone_state_idle,
    drone_state_armed,
    drone_state_flying_mission,
    multi_drone_telemetry,
    fifty_drone_telemetry,
    heartbeat_response,
)

from tests.fixtures.mission_samples import (
    Mission,
    MissionState,
    MissionConfig,
    sample_trajectory_csv,
    origin_zurich,
    swarm_config_single_leader,
)

from tests.mocks.mavlink_simulator import (
    MockMAVLinkConnection,
    MockMAVSDKSystem,
    MockMAVLinkRouter,
    create_mock_mavsdk_system,
    create_mock_mavlink_connection,
    create_mock_mavlink_router,
)


# ============================================================================
# Basic Mock Fixtures (Original)
# ============================================================================


class SyncASGITestClient:
    """
    Sync wrapper over httpx.AsyncClient for ASGI app tests.

    Starlette TestClient deadlocks in this environment, even for trivial apps.
    """

    def __init__(self, app):
        self.app = app
        self.base_url = "http://testserver"

    async def _request(self, method: str, url: str, **kwargs):
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(transport=transport, base_url=self.base_url) as client:
            return await client.request(method, url, **kwargs)

    def request(self, method: str, url: str, **kwargs):
        return asyncio.run(self._request(method, url, **kwargs))

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.request("POST", url, **kwargs)

    def websocket_connect(self, url: str, **kwargs):
        """
        Provide websocket support via FastAPI's sync TestClient.

        HTTP requests use httpx.ASGITransport because Starlette's TestClient
        can deadlock in this environment for normal request/response traffic.
        WebSocket tests still need the TestClient websocket session helper, so
        we use a short-lived dedicated client only for that context.
        """
        return _WebSocketConnectContext(self.app, url, **kwargs)


class _WebSocketConnectContext:
    """Context manager that keeps a FastAPI TestClient alive for one WS session."""

    def __init__(self, app, url: str, **kwargs):
        self._app = app
        self._url = url
        self._kwargs = kwargs
        self._client = None
        self._ws_context = None
        self._websocket = None

    def __enter__(self):
        self._client = FastAPITestClient(self._app)
        self._client.__enter__()
        self._ws_context = self._client.websocket_connect(self._url, **self._kwargs)
        self._websocket = self._ws_context.__enter__()
        return self._websocket

    def __exit__(self, exc_type, exc, tb):
        suppressed = False
        if self._ws_context is not None:
            suppressed = self._ws_context.__exit__(exc_type, exc, tb)
        if self._client is not None:
            self._client.__exit__(exc_type, exc, tb)
        return suppressed

@pytest.fixture
def mock_params():
    """Mock Params object with test configuration"""
    params = Mock(spec=Params)
    params.drone_api_port = 7070
    params.env_mode = 'development'
    params.acceptable_deviation = 3.0
    params.sim_mode = True
    params.GCS_IP = "172.18.0.1"
    params.gcs_api_port = 5030
    params.config_file_name = "config_sitl.json"
    params.swarm_file_name = "swarm_sitl.json"
    # serial_mavlink and sitl_port REMOVED - MAVLink routing is now external
    params.mavsdk_port = 14540
    params.trigger_sooner_seconds = 4
    params.schedule_mission_frequency = 2
    params.default_takeoff_alt = 10
    params.max_takeoff_alt = 100
    params.heartbeat_interval = 10
    params.SMART_SWARM_STATE_STREAM_RATE_HZ = 15
    return params


@pytest.fixture
def mock_drone_config():
    """Mock DroneConfig object with test data"""
    config = Mock(spec=DroneConfig)

    # Position data
    config.position = {
        'lat': 47.397742,
        'long': 8.545594,
        'alt': 488.5
    }

    # Home position
    config.home_position = {
        'lat': 47.397742,
        'long': 8.545594,
        'alt': 488.0
    }

    # GPS global origin
    config.gps_global_origin = {
        'lat': 47.397742,
        'lon': 8.545594,
        'alt': 488.0,
        'time_usec': 1732270245000000
    }

    # Local NED position
    config.local_position_ned = {
        'time_boot_ms': 12345678,
        'x': 0.5,
        'y': -0.3,
        'z': -5.2,
        'vx': 0.0,
        'vy': 0.0,
        'vz': 0.0
    }

    # Config data
    config.config = {
        'pos_id': 1,
        'hw_id': '1'
    }

    config.hw_id = '1'
    config.pos_id = 0  # Add explicit pos_id for validation
    config.state = MissionState.IDLE
    config.mission = Mission.NONE
    config.last_mission = Mission.NONE
    config.trigger_time = 0
    config.is_armed = False
    config.is_ready_to_arm = True
    config.current_command_id = None  # For command tracking
    config.telemetry_timestamp_ms = 1732270245000
    config.telemetry_sequence = 7
    config.yaw_rate_deg_s = 0.0

    return config


@pytest.fixture
def mock_drone_communicator():
    """Mock DroneCommunicator with test drone state"""
    communicator = Mock()

    # Mock drone state
    communicator.get_drone_state.return_value = drone_state_idle('1', 1)
    communicator.get_swarm_state.return_value = {
        "hw_id": 1,
        "pos_id": 1,
        "follow_mode": 0,
        "position_lat": 47.397742,
        "position_long": 8.545594,
        "position_alt": 488.5,
        "velocity_north": 0.0,
        "velocity_east": 0.0,
        "velocity_down": 0.0,
        "yaw": 0.0,
        "yaw_deg": 0.0,
        "yaw_rate_deg_s": 0.0,
        "telemetry_timestamp_ms": 1732270245000,
        "stream_seq": 7,
        "source_frame": "local_ned",
        "source_time_boot_ms": 12345678,
        "local_position_north": 0.5,
        "local_position_east": -0.3,
        "local_position_down": -5.2,
        "local_velocity_north": 0.0,
        "local_velocity_east": 0.0,
        "local_velocity_down": 0.0,
        "emitted_at_ms": 1732270245123,
    }

    # Mock command processing
    communicator.process_command = Mock()

    return communicator


@pytest.fixture
def api_server(mock_params, mock_drone_config, mock_drone_communicator):
    """Create DroneAPIServer instance with mocked dependencies"""
    server = DroneAPIServer(mock_params, mock_drone_config)
    server.set_drone_communicator(mock_drone_communicator)
    return server


@pytest.fixture
def test_client(api_server):
    """Create TestClient for HTTP requests"""
    return SyncASGITestClient(api_server.app)


@pytest.fixture
def sample_command():
    """Sample command data for testing"""
    return cmd_takeoff()


# ============================================================================
# Async Test Fixtures
# ============================================================================

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ============================================================================
# Multi-Drone Configuration Fixtures
# ============================================================================

@pytest.fixture
def single_drone():
    """Single drone in SITL mode"""
    return single_drone_sitl()


@pytest.fixture
def single_drone_config_armed():
    """Single armed drone"""
    return single_drone_armed()


@pytest.fixture
def single_drone_config_flying():
    """Single flying drone"""
    return single_drone_flying()


@pytest.fixture
def five_drones():
    """5 drones in swarm formation"""
    return five_drone_swarm()


@pytest.fixture
def ten_drones():
    """10 drones in line formation"""
    return ten_drone_line()


@pytest.fixture
def fifty_drones():
    """50 drones for load testing"""
    return fifty_drone_grid()


@pytest.fixture
def hundred_drones():
    """100 drones for extreme load testing"""
    return hundred_drone_grid()


# ============================================================================
# Telemetry Fixtures
# ============================================================================

@pytest.fixture
def telemetry_single_idle():
    """Telemetry for single idle drone"""
    return drone_state_idle('1', 1)


@pytest.fixture
def telemetry_single_armed():
    """Telemetry for single armed drone"""
    return drone_state_armed('1', 1)


@pytest.fixture
def telemetry_single_flying():
    """Telemetry for single flying drone"""
    return drone_state_flying_mission('1', 1)


@pytest.fixture
def telemetry_five_drones():
    """Telemetry for 5 drones"""
    return multi_drone_telemetry(5)


@pytest.fixture
def telemetry_fifty_drones():
    """Telemetry for 50 drones"""
    return fifty_drone_telemetry()


@pytest.fixture
def heartbeat_five_drones():
    """Heartbeat response for 5 drones"""
    return heartbeat_response(5)


# ============================================================================
# Command Fixtures
# ============================================================================

@pytest.fixture
def cmd_takeoff_10m():
    """Takeoff command to 10m"""
    return cmd_takeoff(altitude=10.0)


@pytest.fixture
def cmd_drone_show_zurich():
    """Drone show command with Zurich origin"""
    return cmd_drone_show(auto_origin=True, origin=ZURICH_ORIGIN)


@pytest.fixture
def valid_commands():
    """All valid command samples"""
    return all_valid_commands()


@pytest.fixture
def invalid_commands():
    """All invalid command samples"""
    return all_invalid_commands()


# ============================================================================
# Mission Fixtures
# ============================================================================

@pytest.fixture
def mission_config_takeoff():
    """Mission config for takeoff"""
    return MissionConfig(
        mission_type=Mission.TAKE_OFF,
        trigger_time=0,  # Immediate
        takeoff_altitude=10.0
    )


@pytest.fixture
def mission_config_drone_show():
    """Mission config for drone show"""
    return MissionConfig(
        mission_type=Mission.DRONE_SHOW_FROM_CSV,
        trigger_time=0,
        auto_global_origin=True,
        origin={'lat': 47.397742, 'lon': 8.545594, 'alt': 488.0}
    )


@pytest.fixture
def trajectory_csv():
    """Sample trajectory CSV data"""
    return sample_trajectory_csv()


@pytest.fixture
def swarm_config():
    """Sample swarm configuration"""
    return swarm_config_single_leader()


@pytest.fixture
def origin_data():
    """Sample origin data"""
    return origin_zurich()


# ============================================================================
# MAVLink Mock Fixtures
# ============================================================================

@pytest.fixture
def mock_mavlink_connection():
    """Mock MAVLink connection"""
    conn = create_mock_mavlink_connection()
    yield conn
    conn.disconnect()


@pytest.fixture
def mock_mavlink_connection_armed():
    """Mock MAVLink connection with armed drone"""
    conn = create_mock_mavlink_connection(armed=True)
    yield conn
    conn.disconnect()


@pytest.fixture
def mock_mavsdk_system():
    """Mock MAVSDK system"""
    return create_mock_mavsdk_system()


@pytest.fixture
def mock_mavlink_router():
    """Mock MAVLink router"""
    return create_mock_mavlink_router()


# ============================================================================
# Coordinator Mock Fixtures
# ============================================================================

# mock_mavlink_manager REMOVED - MAVLink routing is now external
# See docs/guides/mavlink-routing-setup.md

@pytest.fixture
def mock_local_mavlink_controller():
    """Mock LocalMavlinkController"""
    controller = Mock()
    controller.start = Mock()
    controller.stop = Mock()
    controller.is_running = True
    controller.get_telemetry = Mock(return_value=drone_state_idle('1', 1))
    return controller


@pytest.fixture
def mock_heartbeat_sender():
    """Mock HeartbeatSender"""
    sender = Mock()
    sender.start = Mock()
    sender.stop = Mock()
    sender.is_running = False
    return sender


@pytest.fixture
def mock_connectivity_checker():
    """Mock ConnectivityChecker"""
    checker = Mock()
    checker.start = Mock()
    checker.stop = Mock()
    checker.is_connected = True
    return checker


@pytest.fixture
def mock_led_controller():
    """Mock LEDController"""
    led = Mock()
    led.set_color = Mock()
    led.clear = Mock()
    return led


@pytest.fixture
def mock_drone_setup():
    """Mock DroneSetup for mission scheduling"""
    setup = Mock()
    setup.schedule_mission = AsyncMock()
    setup.cancel_mission = Mock()
    setup.get_current_mission = Mock(return_value=Mission.NONE)
    setup.get_state = Mock(return_value=MissionState.IDLE)
    return setup


# ============================================================================
# GCS Server Mock Fixtures
# ============================================================================

@pytest.fixture
def mock_gcs_telemetry_data(fifty_drones):
    """Mock GCS telemetry data for 50 drones"""
    return drones_to_telemetry_response(fifty_drones)


@pytest.fixture
def mock_gcs_config_json(fifty_drones):
    """Mock config.json content for 50 drones"""
    return drones_to_config_json(fifty_drones)


@pytest.fixture
def mock_gcs_swarm_json(fifty_drones):
    """Mock swarm.json content for 50 drones"""
    return drones_to_swarm_json(fifty_drones)


# ============================================================================
# Integration Test Fixtures
# ============================================================================

@pytest.fixture
def integration_timeout():
    """Timeout for integration tests (longer than unit tests)"""
    return 30  # seconds


@pytest.fixture
def sitl_docker_image():
    """Docker image for SITL testing"""
    return "alireza787/mavsdk-drone-show:px4-sitl-latest"


# ============================================================================
# Test Helpers as Fixtures
# ============================================================================

@pytest.fixture
def assert_drone_state():
    """Helper to assert drone state"""
    def _assert(state: Dict, expected_mission: int = None, expected_armed: bool = None):
        assert 'hw_id' in state
        assert 'pos_id' in state
        assert 'position_lat' in state
        assert 'position_long' in state
        assert 'battery_voltage' in state

        if expected_mission is not None:
            assert state.get('mission') == expected_mission

        if expected_armed is not None:
            assert state.get('is_armed') == expected_armed

    return _assert


@pytest.fixture
def assert_command_success():
    """Helper to assert command was successful"""
    def _assert(response):
        assert response.status_code == 200
        data = response.json()
        assert data.get('status') in ['success', 'accepted', 'ok']
    return _assert


# ============================================================================
# Cleanup Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def disable_git_operations():
    """Prevent tests from creating real git commits via git_operations()"""
    try:
        with patch('utils.git_operations', return_value={'success': True, 'message': 'mocked'}):
            yield
    except (ModuleNotFoundError, AttributeError):
        # utils module not importable outside gcs-server context
        yield


@pytest.fixture(autouse=True)
def cleanup_async_tasks():
    """Clean up any pending async tasks after each test"""
    yield
    # Get all tasks and cancel pending ones
    try:
        loop = asyncio.get_event_loop()
        pending = asyncio.all_tasks(loop)
        for task in pending:
            if not task.done():
                task.cancel()
    except RuntimeError:
        pass  # No event loop


@pytest.fixture(autouse=True)
def reset_runtime_env_preload_state():
    """Keep runtime-env preload state isolated across tests."""
    reset_deployment_profile_cache()
    reset_preloaded_local_env_state()
    yield
    reset_preloaded_local_env_state()
    reset_deployment_profile_cache()


# ============================================================================
# Markers
# ============================================================================

def pytest_configure(config):
    """Configure custom markers"""
    config.addinivalue_line("markers", "unit: Unit tests (fast, no external deps)")
    config.addinivalue_line("markers", "integration: Integration tests (may use SITL)")
    config.addinivalue_line("markers", "slow: Slow running tests")
    config.addinivalue_line("markers", "swarm: Swarm coordination tests")
    config.addinivalue_line("markers", "load: Load/performance tests")
    config.addinivalue_line("markers", "coordinator: Coordinator startup tests")
    config.addinivalue_line("markers", "mission: Mission execution tests")
    config.addinivalue_line("markers", "command: Command processing tests")
    config.addinivalue_line("markers", "telemetry: Telemetry handling tests")
