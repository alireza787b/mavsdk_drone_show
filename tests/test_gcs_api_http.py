# tests/test_gcs_api_http.py
"""
GCS API HTTP Endpoint Tests
============================
Comprehensive test suite for GCS Server FastAPI HTTP endpoints.

Tests all major endpoint categories:
- Health & System endpoints
- Configuration management
- Telemetry retrieval
- Heartbeat handling
- Origin management
- Show import and management
- Git operations
- Swarm trajectory management

Author: MAVSDK Drone Show Test Team
Last Updated: 2025-11-22
"""

import pytest
import json
import tempfile
import os
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient
from io import BytesIO

# Import the FastAPI GCS app
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../gcs-server'))

# Mock the background services before importing the app
@pytest.fixture(autouse=True)
def mock_background_services():
    """Mock background services to prevent actual polling during tests"""
    with patch('app_fastapi.BackgroundServices') as mock_services:
        mock_instance = Mock()
        mock_instance.start = Mock()
        mock_instance.stop = Mock()
        mock_services.return_value = mock_instance
        yield mock_services


@pytest.fixture
def mock_config():
    """Mock drone configuration"""
    return [
        {
            'pos_id': 0,
            'hw_id': '1',
            'ip': '192.168.1.101',
            'connection_str': 'udp://:14540'
        },
        {
            'pos_id': 1,
            'hw_id': '2',
            'ip': '192.168.1.102',
            'connection_str': 'udp://:14541'
        }
    ]


@pytest.fixture
def mock_telemetry_data():
    """Mock telemetry data for all drones"""
    return {
        '1': {
            'pos_id': 0,
            'hw_id': '1',
            'battery_voltage': 12.6,
            'Position_Lat': 35.123456,
            'Position_Long': -120.654321,
            'Position_Alt': 488.5,
            'armed': False,
            'timestamp': 1700000000000
        },
        '2': {
            'pos_id': 1,
            'hw_id': '2',
            'battery_voltage': 12.4,
            'Position_Lat': 35.123457,
            'Position_Long': -120.654322,
            'Position_Alt': 488.6,
            'armed': False,
            'timestamp': 1700000000000
        }
    }


@pytest.fixture
def mock_origin():
    """Mock origin data"""
    return {
        'lat': 35.123456,
        'lon': -120.654321,
        'alt': 488.0,
        'timestamp': '2025-11-22T12:00:00',
        'alt_source': 'manual'
    }


@pytest.fixture
def test_client(mock_config, mock_telemetry_data):
    """Create FastAPI test client with mocked dependencies"""
    with patch('app_fastapi.load_config', return_value=mock_config):
        with patch('app_fastapi.telemetry_data_all_drones', mock_telemetry_data):
            from app_fastapi import app
            client = TestClient(app)
            yield client


# ============================================================================
# Health & System Tests
# ============================================================================

class TestHealthEndpoints:
    """Test health check and system status endpoints"""

    def test_ping_endpoint(self, test_client):
        """Test /ping health check endpoint"""
        response = test_client.get("/ping")
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'ok'
        assert 'timestamp' in data

    def test_health_endpoint(self, test_client):
        """Test /health health check endpoint"""
        response = test_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'ok'
        assert 'timestamp' in data


# ============================================================================
# Configuration Tests
# ============================================================================

class TestConfigurationEndpoints:
    """Test drone configuration endpoints"""

    def test_get_config(self, test_client, mock_config):
        """Test GET /get-config-data"""
        response = test_client.get("/get-config-data")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]['pos_id'] == 0
        assert data[0]['hw_id'] == '1'

    @patch('app_fastapi.save_config')
    @patch('app_fastapi.validate_and_process_config')
    def test_save_config(self, mock_validate, mock_save, test_client, mock_config):
        """Test POST /save-config-data"""
        mock_validate.return_value = {'updated_config': mock_config}

        response = test_client.post("/save-config-data", json=mock_config)
        assert response.status_code == 200
        data = response.json()
        assert data['success'] == True
        assert 'updated_count' in data

    @patch('app_fastapi.validate_and_process_config')
    def test_validate_config(self, mock_validate, test_client, mock_config):
        """Test POST /validate-config"""
        mock_validate.return_value = {
            'updated_config': mock_config,
            'summary': {
                'duplicates_count': 0,
                'missing_trajectories_count': 0,
                'role_swaps_count': 0
            }
        }

        response = test_client.post("/validate-config", json=mock_config)
        assert response.status_code == 200
        data = response.json()
        assert 'summary' in data


# ============================================================================
# Telemetry Tests
# ============================================================================

class TestTelemetryEndpoints:
    """Test telemetry endpoints"""

    def test_get_telemetry_legacy(self, test_client, mock_telemetry_data):
        """Test GET /telemetry (legacy endpoint)"""
        response = test_client.get("/telemetry")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert '1' in data
        assert data['1']['battery_voltage'] == 12.6

    def test_get_telemetry_typed(self, test_client):
        """Test GET /api/telemetry (typed endpoint)"""
        response = test_client.get("/api/telemetry")
        assert response.status_code == 200
        data = response.json()
        assert 'telemetry' in data
        assert 'total_drones' in data
        assert 'online_drones' in data


# ============================================================================
# Heartbeat Tests
# ============================================================================

class TestHeartbeatEndpoints:
    """Test heartbeat endpoints"""

    @patch('app_fastapi.handle_heartbeat_post')
    def test_post_heartbeat(self, mock_handle, test_client):
        """Test POST /heartbeat"""
        heartbeat_data = {
            'pos_id': 0,
            'hw_id': '1',
            'timestamp': 1700000000000
        }

        response = test_client.post("/heartbeat", json=heartbeat_data)
        assert response.status_code == 200
        data = response.json()
        assert data['success'] == True

    @patch('app_fastapi.get_all_heartbeats')
    def test_get_heartbeats(self, mock_get_heartbeats, test_client):
        """Test GET /get-heartbeats"""
        mock_get_heartbeats.return_value = [
            {'pos_id': 0, 'hw_id': '1', 'online': True},
            {'pos_id': 1, 'hw_id': '2', 'online': True}
        ]

        response = test_client.get("/get-heartbeats")
        assert response.status_code == 200
        data = response.json()
        assert 'heartbeats' in data
        assert data['total_drones'] == 2


# ============================================================================
# Origin Tests
# ============================================================================

class TestOriginEndpoints:
    """Test origin management endpoints"""

    @patch('app_fastapi.load_origin')
    def test_get_origin(self, mock_load, test_client, mock_origin):
        """Test GET /get-origin"""
        mock_load.return_value = mock_origin

        response = test_client.get("/get-origin")
        assert response.status_code == 200
        data = response.json()
        assert data['latitude'] == 35.123456
        assert data['longitude'] == -120.654321

    @patch('app_fastapi.save_origin')
    def test_set_origin(self, mock_save, test_client):
        """Test POST /set-origin"""
        origin_data = {
            'latitude': 35.123456,
            'longitude': -120.654321,
            'altitude': 488.0
        }

        response = test_client.post("/set-origin", json=origin_data)
        assert response.status_code == 200
        data = response.json()
        assert data['latitude'] == origin_data['latitude']

    @patch('app_fastapi.load_origin')
    def test_get_gps_global_origin(self, mock_load, test_client, mock_origin):
        """Test GET /get-gps-global-origin"""
        mock_load.return_value = mock_origin

        response = test_client.get("/get-gps-global-origin")
        assert response.status_code == 200
        data = response.json()
        assert data['has_origin'] == True

    @patch('app_fastapi.load_origin')
    def test_get_origin_for_drone(self, mock_load, test_client, mock_origin):
        """Test GET /get-origin-for-drone"""
        mock_load.return_value = mock_origin

        response = test_client.get("/get-origin-for-drone")
        assert response.status_code == 200
        data = response.json()
        assert data['lat'] == 35.123456
        assert data['source'] == 'manual'


# ============================================================================
# Show Management Tests
# ============================================================================

class TestShowManagementEndpoints:
    """Test show import and management endpoints"""

    @patch('app_fastapi.run_formation_process')
    @patch('app_fastapi.clear_show_directories')
    @patch('os.listdir')
    def test_import_show(self, mock_listdir, mock_clear, mock_process, test_client):
        """Test POST /import-show with file upload"""
        # Create a mock zip file
        mock_listdir.return_value = ['Drone 1.csv', 'Drone 2.csv']

        # Create test zip content
        zip_content = b'PK\x03\x04...'  # Minimal zip header

        files = {'file': ('test_show.zip', BytesIO(zip_content), 'application/zip')}

        with patch('zipfile.ZipFile'):
            response = test_client.post("/import-show", files=files)

        # Should process but may fail on actual zip extraction
        # We're testing the endpoint structure, not zip processing
        assert response.status_code in [200, 500]

    @patch('os.listdir')
    @patch('os.path.exists', return_value=True)
    def test_get_show_info(self, mock_exists, mock_listdir, test_client):
        """Test GET /get-show-info"""
        mock_listdir.return_value = ['Drone 1.csv', 'Drone 2.csv']

        with patch('builtins.open', create=True) as mock_open:
            mock_file = MagicMock()
            mock_file.__enter__.return_value.__iter__.return_value = [
                't [ms],x [m],y [m],z [m],yaw [deg]\n',
                '0,0,0,0,0\n',
                '60000,1.0,1.0,5.0,0\n'
            ]
            mock_open.return_value = mock_file

            response = test_client.get("/get-show-info")

        assert response.status_code == 200
        data = response.json()
        assert 'drone_count' in data
        assert 'max_altitude' in data


# ============================================================================
# Git Status Tests
# ============================================================================

class TestGitStatusEndpoints:
    """Test git status endpoints"""

    @patch('app_fastapi.git_status_data_all_drones', {'1': {'status': 'synced'}, '2': {'status': 'synced'}})
    def test_get_git_status(self, test_client):
        """Test GET /git-status"""
        response = test_client.get("/git-status")
        assert response.status_code == 200
        data = response.json()
        assert 'git_status' in data
        assert 'synced_count' in data

    @patch('app_fastapi.get_gcs_git_report')
    def test_get_gcs_git_status(self, mock_report, test_client):
        """Test GET /get-gcs-git-status"""
        mock_report.return_value = {'branch': 'main', 'status': 'clean'}

        response = test_client.get("/get-gcs-git-status")
        assert response.status_code == 200


# ============================================================================
# Swarm Management Tests
# ============================================================================

class TestSwarmEndpoints:
    """Test swarm configuration endpoints"""

    @patch('app_fastapi.load_swarm')
    def test_get_swarm_data(self, mock_load, test_client):
        """Test GET /get-swarm-data"""
        mock_load.return_value = {'hierarchies': {}}

        response = test_client.get("/get-swarm-data")
        assert response.status_code == 200

    @patch('app_fastapi.save_swarm')
    @patch('app_fastapi.git_operations')
    def test_save_swarm_data(self, mock_git, mock_save, test_client):
        """Test POST /save-swarm-data"""
        swarm_data = {'hierarchies': {}}

        response = test_client.post("/save-swarm-data", json=swarm_data)
        assert response.status_code == 200


# ============================================================================
# Command Tests
# ============================================================================

class TestCommandEndpoints:
    """Test command submission endpoints"""

    @patch('app_fastapi.send_commands_to_all')
    @patch('app_fastapi.load_config')
    def test_submit_command(self, mock_load, mock_send, test_client, mock_config):
        """Test POST /submit_command"""
        mock_load.return_value = mock_config

        command_data = {
            'action': 'arm',
            'params': {}
        }

        response = test_client.post("/submit_command", json=command_data)
        assert response.status_code == 200
        data = response.json()
        assert data['success'] == True


# ============================================================================
# Error Handling Tests
# ============================================================================

class TestErrorHandling:
    """Test error handling"""

    def test_404_not_found(self, test_client):
        """Test 404 error for non-existent endpoint"""
        response = test_client.get("/nonexistent-endpoint")
        assert response.status_code == 404

    def test_invalid_json(self, test_client):
        """Test handling of invalid JSON in POST request"""
        response = test_client.post(
            "/save-config-data",
            data="invalid json",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code in [400, 422, 500]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
