# tests/test_drone_api_websocket.py
"""
WebSocket Endpoint Tests
========================
Tests for WebSocket real-time streaming endpoint.
"""

import pytest
import json
import asyncio
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


class TestWebSocketConnection:
    """Test WebSocket connection lifecycle"""

    def test_websocket_connect(self, test_client):
        """Test WebSocket connection establishment"""
        with test_client.websocket_connect("/ws/drone-state") as websocket:
            # Connection should be established
            assert websocket is not None

    def test_websocket_receive_data(self, test_client, mock_drone_communicator):
        """Test receiving drone state via WebSocket"""
        with test_client.websocket_connect("/ws/drone-state") as websocket:
            # Receive first message
            data = websocket.receive_json()

            # Verify data structure
            assert 'pos_id' in data
            assert 'position_lat' in data
            assert 'battery_voltage' in data
            assert 'timestamp' in data

            # Verify values match mock
            assert data['pos_id'] == 1
            assert data['battery_voltage'] == 12.6

    def test_websocket_multiple_messages(self, test_client, mock_drone_communicator):
        """Test receiving multiple consecutive messages"""
        with test_client.websocket_connect("/ws/drone-state") as websocket:
            # Receive multiple messages
            for i in range(3):
                data = websocket.receive_json()
                assert 'pos_id' in data
                assert 'timestamp' in data


class TestWebSocketDataStreaming:
    """Test WebSocket data streaming"""

    def test_websocket_state_updates(self, test_client, mock_drone_communicator):
        """Test that state updates are streamed"""
        # Change mock data between messages
        states = [
            {'pos_id': 1, 'battery_voltage': 12.6, 'position_alt': 0.0},
            {'pos_id': 1, 'battery_voltage': 12.5, 'position_alt': 5.0},
            {'pos_id': 1, 'battery_voltage': 12.4, 'position_alt': 10.0}
        ]

        # Iterator for mock states
        state_iter = iter(states)

        def get_next_state():
            try:
                base_state = next(state_iter)
                # Merge with default state
                full_state = mock_drone_communicator.get_drone_state.return_value.copy()
                full_state.update(base_state)
                return full_state
            except StopIteration:
                return mock_drone_communicator.get_drone_state.return_value

        mock_drone_communicator.get_drone_state.side_effect = get_next_state

        with test_client.websocket_connect("/ws/drone-state") as websocket:
            # Verify state changes are reflected
            data1 = websocket.receive_json()
            assert data1['battery_voltage'] == 12.6
            assert data1['position_alt'] == 0.0


class TestWebSocketErrorHandling:
    """Test WebSocket error handling"""

    def test_websocket_no_data_available(self, test_client, mock_drone_communicator):
        """Test WebSocket when drone state is unavailable"""
        # Mock returns None (no data)
        mock_drone_communicator.get_drone_state.return_value = None

        with test_client.websocket_connect("/ws/drone-state") as websocket:
            data = websocket.receive_json()

            # Should receive error message
            assert 'error' in data
            assert data['error'] == 'Drone state not available'
            assert 'timestamp' in data


class TestWebSocketConcurrency:
    """Test multiple concurrent WebSocket connections"""

    def test_multiple_clients(self, test_client, mock_drone_communicator):
        """Test multiple clients can connect simultaneously"""
        # Note: TestClient doesn't support true concurrent connections
        # This test verifies the connection can be established multiple times

        # First connection
        with test_client.websocket_connect("/ws/drone-state") as ws1:
            data1 = ws1.receive_json()
            assert 'pos_id' in data1

        # Second connection (after first closes)
        with test_client.websocket_connect("/ws/drone-state") as ws2:
            data2 = ws2.receive_json()
            assert 'pos_id' in data2


class TestWebSocketDataFormat:
    """Test WebSocket data format compliance"""

    def test_data_is_valid_json(self, test_client):
        """Test that WebSocket sends valid JSON"""
        with test_client.websocket_connect("/ws/drone-state") as websocket:
            # Receive raw data
            raw_data = websocket.receive_text()

            # Should be valid JSON
            parsed = json.loads(raw_data)
            assert isinstance(parsed, dict)

    def test_timestamp_format(self, test_client):
        """Test that timestamp is in milliseconds"""
        with test_client.websocket_connect("/ws/drone-state") as websocket:
            data = websocket.receive_json()

            # Timestamp should be in milliseconds (13 digits)
            assert 'timestamp' in data
            assert len(str(data['timestamp'])) == 13

    def test_data_schema_matches_http(self, test_client, mock_drone_communicator):
        """Test WebSocket data matches HTTP endpoint schema"""
        # Get HTTP response
        http_response = test_client.get("/get_drone_state")
        http_data = http_response.json()

        # Get WebSocket data
        with test_client.websocket_connect("/ws/drone-state") as websocket:
            ws_data = websocket.receive_json()

        # Both should have same keys (except timestamp which is added dynamically)
        http_keys = set(http_data.keys()) - {'timestamp'}
        ws_keys = set(ws_data.keys()) - {'timestamp'}

        assert http_keys == ws_keys
