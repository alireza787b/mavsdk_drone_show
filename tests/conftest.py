# tests/conftest.py
"""
Pytest Configuration and Shared Fixtures
=========================================
Provides reusable test fixtures for all test modules.
"""

import pytest
import asyncio
from unittest.mock import Mock, MagicMock
from fastapi.testclient import TestClient

# Import the drone API server
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.drone_api_server import DroneAPIServer
from src.params import Params
from src.drone_config import DroneConfig


# ============================================================================
# Mock Fixtures
# ============================================================================

@pytest.fixture
def mock_params():
    """Mock Params object with test configuration"""
    params = Mock(spec=Params)
    params.drones_flask_port = 7070
    params.env_mode = 'development'
    params.acceptable_deviation = 3.0
    params.sim_mode = True
    params.GCS_IP = "172.18.0.1"
    params.GCS_FLASK_PORT = 5000
    params.config_csv_name = "config_sitl.csv"
    params.swarm_csv_name = "swarm_sitl.csv"
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

    return config


@pytest.fixture
def mock_drone_communicator():
    """Mock DroneCommunicator with test drone state"""
    communicator = Mock()

    # Mock drone state
    communicator.get_drone_state.return_value = {
        'pos_id': 1,
        'detected_pos_id': 1,
        'state': 0,
        'mission': 'IDLE',
        'last_mission': 'IDLE',
        'position_lat': 47.397742,
        'position_long': 8.545594,
        'position_alt': 488.5,
        'velocity_north': 0.0,
        'velocity_east': 0.0,
        'velocity_down': 0.0,
        'yaw': 180.5,
        'battery_voltage': 12.6,
        'follow_mode': 'LEADER',
        'update_time': '2025-11-22 10:30:45',
        'flight_mode': 4,
        'base_mode': 81,
        'system_status': 4,
        'is_armed': False,
        'is_ready_to_arm': True,
        'hdop': 0.8,
        'vdop': 1.2,
        'gps_fix_type': 3,
        'satellites_visible': 12,
        'ip': '192.168.1.100'
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
    return TestClient(api_server.app)


@pytest.fixture
def sample_command():
    """Sample command data for testing"""
    return {
        "missionType": "ARM",
        "triggerTime": "1732270300"
    }


# ============================================================================
# Async Test Fixtures
# ============================================================================

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
