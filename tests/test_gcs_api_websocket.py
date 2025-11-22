# tests/test_gcs_api_websocket.py
"""
GCS API WebSocket Tests
=======================
Comprehensive test suite for GCS Server FastAPI WebSocket endpoints.

Tests real-time streaming for:
- Telemetry data (WS /ws/telemetry)
- Git status (WS /ws/git-status)
- Heartbeats (WS /ws/heartbeats)

Author: MAVSDK Drone Show Test Team
Last Updated: 2025-11-22
"""

import pytest
import json
import asyncio
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient

# Import paths
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../gcs-server'))


@pytest.fixture
def mock_telemetry_data():
    """Mock telemetry data"""
    return {
        '1': {
            'pos_id': 0,
            'hw_id': '1',
            'battery_voltage': 12.6,
            'Position_Lat': 35.123456,
            'Position_Long': -120.654321,
            'armed': False
        }
    }


@pytest.fixture
def mock_git_status_data():
    """Mock git status data"""
    return {
        '1': {
            'pos_id': 0,
            'hw_id': '1',
            'status': 'synced',
            'branch': 'main',
            'latest_commit': 'abc123'
        }
    }


@pytest.fixture
def test_client(mock_telemetry_data, mock_git_status_data):
    """Create FastAPI test client with mocked dependencies"""
    with patch('gcs-server.app_fastapi.load_config', return_value=[]):
        with patch('gcs-server.app_fastapi.telemetry_data_all_drones', mock_telemetry_data):
            with patch('gcs-server.app_fastapi.git_status_data_all_drones', mock_git_status_data):
                from app_fastapi import app
                client = TestClient(app)
                yield client


# ============================================================================
# Telemetry WebSocket Tests
# ============================================================================

class TestTelemetryWebSocket:
    """Test WebSocket telemetry streaming"""

    def test_websocket_telemetry_connection(self, test_client):
        """Test WebSocket connection to /ws/telemetry"""
        with test_client.websocket_connect("/ws/telemetry") as websocket:
            # Receive first message
            data = websocket.receive_json()

            assert 'type' in data
            assert data['type'] == 'telemetry'
            assert 'timestamp' in data
            assert 'data' in data

    def test_websocket_telemetry_data_format(self, test_client, mock_telemetry_data):
        """Test telemetry WebSocket data format"""
        with test_client.websocket_connect("/ws/telemetry") as websocket:
            data = websocket.receive_json()

            assert data['type'] == 'telemetry'
            assert isinstance(data['data'], dict)
            assert '1' in data['data']
            assert data['data']['1']['battery_voltage'] == 12.6

    def test_websocket_telemetry_multiple_messages(self, test_client):
        """Test receiving multiple telemetry messages"""
        with test_client.websocket_connect("/ws/telemetry") as websocket:
            # Receive multiple messages
            for i in range(3):
                data = websocket.receive_json()
                assert 'type' in data
                assert data['type'] == 'telemetry'


# ============================================================================
# Git Status WebSocket Tests
# ============================================================================

class TestGitStatusWebSocket:
    """Test WebSocket git status streaming"""

    def test_websocket_git_status_connection(self, test_client):
        """Test WebSocket connection to /ws/git-status"""
        with test_client.websocket_connect("/ws/git-status") as websocket:
            data = websocket.receive_json()

            assert 'type' in data
            assert data['type'] == 'git_status'
            assert 'timestamp' in data
            assert 'data' in data

    def test_websocket_git_status_data_format(self, test_client, mock_git_status_data):
        """Test git status WebSocket data format"""
        with test_client.websocket_connect("/ws/git-status") as websocket:
            data = websocket.receive_json()

            assert data['type'] == 'git_status'
            assert isinstance(data['data'], dict)
            assert '1' in data['data']
            assert data['data']['1']['status'] == 'synced'


# ============================================================================
# Heartbeat WebSocket Tests
# ============================================================================

class TestHeartbeatWebSocket:
    """Test WebSocket heartbeat streaming"""

    @patch('gcs-server.app_fastapi.get_all_heartbeats')
    def test_websocket_heartbeat_connection(self, mock_heartbeats, test_client):
        """Test WebSocket connection to /ws/heartbeats"""
        mock_heartbeats.return_value = [
            {'pos_id': 0, 'hw_id': '1', 'online': True}
        ]

        with test_client.websocket_connect("/ws/heartbeats") as websocket:
            data = websocket.receive_json()

            assert 'type' in data
            assert data['type'] == 'heartbeat'
            assert 'timestamp' in data
            assert 'data' in data

    @patch('gcs-server.app_fastapi.get_all_heartbeats')
    def test_websocket_heartbeat_data_format(self, mock_heartbeats, test_client):
        """Test heartbeat WebSocket data format"""
        mock_heartbeats.return_value = [
            {'pos_id': 0, 'hw_id': '1', 'online': True},
            {'pos_id': 1, 'hw_id': '2', 'online': False}
        ]

        with test_client.websocket_connect("/ws/heartbeats") as websocket:
            data = websocket.receive_json()

            assert data['type'] == 'heartbeat'
            assert isinstance(data['data'], list)
            assert len(data['data']) == 2
            assert data['data'][0]['online'] == True


# ============================================================================
# WebSocket Error Handling Tests
# ============================================================================

class TestWebSocketErrorHandling:
    """Test WebSocket error handling"""

    def test_websocket_invalid_endpoint(self, test_client):
        """Test connection to non-existent WebSocket endpoint"""
        with pytest.raises(Exception):
            with test_client.websocket_connect("/ws/nonexistent"):
                pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
