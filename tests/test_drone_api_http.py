# tests/test_drone_api_http.py
"""
HTTP REST Endpoint Tests
=========================
Tests for all HTTP REST endpoints in the Drone API Server.
"""

import pytest
import json
from fastapi.testclient import TestClient


class TestHealthCheck:
    """Test health check endpoint"""

    def test_ping_success(self, test_client):
        """Test /ping endpoint returns ok"""
        response = test_client.get("/ping")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestDroneState:
    """Test drone state endpoint"""

    def test_get_drone_state_success(self, test_client, mock_drone_communicator):
        """Test /get_drone_state returns valid state"""
        response = test_client.get("/get_drone_state")

        assert response.status_code == 200
        data = response.json()

        # Verify key fields
        assert 'pos_id' in data
        assert 'position_lat' in data
        assert 'position_alt' in data
        assert 'battery_voltage' in data
        assert 'is_armed' in data
        assert 'timestamp' in data

        # Verify values
        assert data['pos_id'] == 1
        assert data['battery_voltage'] == 12.6
        assert data['is_armed'] is False

    def test_get_drone_state_no_data(self, test_client, mock_drone_communicator):
        """Test /get_drone_state when no data available"""
        mock_drone_communicator.get_drone_state.return_value = None

        response = test_client.get("/get_drone_state")

        assert response.status_code == 404
        assert 'detail' in response.json()


class TestCommands:
    """Test command endpoint"""

    def test_send_command_success(self, test_client, sample_command, mock_drone_communicator):
        """Test sending command to drone"""
        response = test_client.post("/api/send-command", json=sample_command)

        assert response.status_code == 200
        data = response.json()

        assert data['status'] == 'success'
        assert data['message'] == 'Command received'

        # Verify command was processed
        mock_drone_communicator.process_command.assert_called_once()
        call_args = mock_drone_communicator.process_command.call_args[0][0]
        assert call_args['missionType'] == 'ARM'

    def test_send_command_different_mission_types(self, test_client, mock_drone_communicator):
        """Test different mission types"""
        mission_types = ['ARM', 'DISARM', 'TAKEOFF', 'LAND', 'RTL', 'HOLD']

        for mission_type in mission_types:
            command = {"missionType": mission_type, "triggerTime": "0"}
            response = test_client.post("/api/send-command", json=command)

            assert response.status_code == 200
            assert response.json()['status'] == 'success'


class TestPositionData:
    """Test position-related endpoints"""

    def test_get_home_position(self, test_client, mock_drone_config):
        """Test /get-home-pos endpoint"""
        response = test_client.get("/get-home-pos")

        assert response.status_code == 200
        data = response.json()

        assert 'latitude' in data
        assert 'longitude' in data
        assert 'altitude' in data
        assert 'timestamp' in data

        assert data['latitude'] == 47.397742
        assert data['longitude'] == 8.545594

    def test_get_gps_global_origin(self, test_client, mock_drone_config):
        """Test /get-gps-global-origin endpoint"""
        response = test_client.get("/get-gps-global-origin")

        assert response.status_code == 200
        data = response.json()

        assert 'latitude' in data
        assert 'longitude' in data
        assert 'altitude' in data
        assert 'origin_time_usec' in data
        assert 'timestamp' in data

    def test_get_local_position_ned(self, test_client, mock_drone_config):
        """Test /get-local-position-ned endpoint"""
        response = test_client.get("/get-local-position-ned")

        assert response.status_code == 200
        data = response.json()

        assert 'time_boot_ms' in data
        assert 'x' in data
        assert 'y' in data
        assert 'z' in data
        assert 'vx' in data
        assert 'vy' in data
        assert 'vz' in data
        assert 'timestamp' in data

        # Verify NED coordinates
        assert data['x'] == 0.5
        assert data['y'] == -0.3
        assert data['z'] == -5.2

    def test_get_local_position_ned_no_data(self, test_client, mock_drone_config):
        """Test /get-local-position-ned when no data available"""
        # Set time_boot_ms to 0 (indicates no data)
        mock_drone_config.local_position_ned['time_boot_ms'] = 0

        response = test_client.get("/get-local-position-ned")

        assert response.status_code == 404
        assert 'NED data not available' in response.json()['detail']


class TestGitStatus:
    """Test git status endpoint"""

    def test_get_git_status(self, test_client, monkeypatch):
        """Test /get-git-status endpoint"""
        # Mock git commands
        def mock_execute_git_command(self, command):
            git_responses = {
                ('git', 'rev-parse', '--abbrev-ref', 'HEAD'): 'main-candidate',
                ('git', 'rev-parse', 'HEAD'): 'abc123def456',
                ('git', 'show', '-s', '--format=%an', 'abc123def456'): 'Test User',
                ('git', 'show', '-s', '--format=%ae', 'abc123def456'): 'test@example.com',
                ('git', 'show', '-s', '--format=%cd', '--date=iso-strict', 'abc123def456'): '2025-11-22T10:00:00+00:00',
                ('git', 'show', '-s', '--format=%B', 'abc123def456'): 'test commit',
                ('git', 'config', '--get', 'remote.origin.url'): 'git@github.com:test/repo.git',
                ('git', 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}'): 'origin/main-candidate',
                ('git', 'status', '--porcelain'): ''
            }
            return git_responses.get(tuple(command), '')

        # Monkeypatch the method
        from src.drone_api_server import DroneAPIServer
        monkeypatch.setattr(DroneAPIServer, '_execute_git_command', mock_execute_git_command)

        response = test_client.get("/get-git-status")

        assert response.status_code == 200
        data = response.json()

        assert 'branch' in data
        assert 'commit' in data
        assert 'status' in data
        assert data['status'] == 'clean'


class TestNetworkStatus:
    """Test network status endpoint"""

    def test_get_network_status(self, test_client, monkeypatch):
        """Test /get-network-status endpoint"""
        # Mock network info method
        def mock_get_network_info(self):
            return {
                "wifi": {
                    "ssid": "TestNetwork",
                    "signal_strength_percent": 85
                },
                "ethernet": {
                    "interface": "eth0",
                    "connection_name": "Wired"
                },
                "timestamp": 1732270245000
            }

        from src.drone_api_server import DroneAPIServer
        monkeypatch.setattr(DroneAPIServer, '_get_network_info', mock_get_network_info)

        response = test_client.get("/get-network-status")

        assert response.status_code == 200
        data = response.json()

        assert 'wifi' in data
        assert 'ethernet' in data
        assert 'timestamp' in data
        assert data['wifi']['ssid'] == 'TestNetwork'


class TestErrorHandling:
    """Test error handling"""

    def test_404_not_found(self, test_client):
        """Test non-existent endpoint returns 404"""
        response = test_client.get("/non-existent-endpoint")

        assert response.status_code == 404

    def test_invalid_command_data(self, test_client):
        """Test sending invalid command data"""
        # Send empty dict (missing required fields)
        response = test_client.post("/api/send-command", json={})

        # Should still accept it due to extra="allow" in Pydantic model
        # But we can add validation later if needed
        assert response.status_code in [200, 422]  # Either success or validation error
