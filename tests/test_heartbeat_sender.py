# tests/test_heartbeat_sender.py
"""
HeartbeatSender Tests
=====================
Tests for the drone heartbeat sending functionality.
"""

import pytest
import time
from unittest.mock import Mock, MagicMock, patch

# Path configuration is handled by conftest.py

from src.heartbeat_sender import HeartbeatSender


class TestHeartbeatSenderInit:
    """Test HeartbeatSender initialization"""

    def test_init_with_drone_config(self):
        """Test initialization with a mock drone config"""
        mock_config = Mock()
        mock_config.hw_id = '1'
        mock_config.pos_id = 1
        mock_config.detected_pos_id = 0

        with patch('src.heartbeat_sender.Params') as mock_params:
            mock_params.heartbeat_interval = 10
            mock_params.GCS_IP = '192.168.1.1'
            mock_params.gcs_api_port = 5030

            sender = HeartbeatSender(mock_config)

            assert sender.drone_config == mock_config
            assert sender.interval == 10
            assert sender.gcs_ip == '192.168.1.1'
            assert sender.gcs_port == 5030
            assert sender.running is False
            assert sender.thread is None

    def test_init_with_missing_gcs_ip(self):
        """Test initialization when GCS IP is not set"""
        mock_config = Mock()

        with patch('src.heartbeat_sender.Params') as mock_params:
            mock_params.heartbeat_interval = 10
            mock_params.GCS_IP = None
            mock_params.gcs_api_port = 5030

            sender = HeartbeatSender(mock_config)

            assert sender.gcs_ip is None


class TestHeartbeatSenderStartStop:
    """Test HeartbeatSender start/stop functionality"""

    def test_start_without_gcs_ip(self):
        """Test that start() does nothing if GCS IP is not configured"""
        mock_config = Mock()

        with patch('src.heartbeat_sender.Params') as mock_params:
            mock_params.heartbeat_interval = 10
            mock_params.GCS_IP = None
            mock_params.gcs_api_port = 5030

            sender = HeartbeatSender(mock_config)
            sender.start()

            assert sender.running is False
            assert sender.thread is None

    def test_start_creates_thread(self):
        """Test that start() creates and starts a daemon thread"""
        mock_config = Mock()

        with patch('src.heartbeat_sender.Params') as mock_params:
            mock_params.heartbeat_interval = 10
            mock_params.GCS_IP = '192.168.1.1'
            mock_params.gcs_api_port = 5030

            sender = HeartbeatSender(mock_config)

            # Mock the thread to not actually run
            with patch('threading.Thread') as mock_thread:
                mock_thread_instance = Mock()
                mock_thread.return_value = mock_thread_instance

                sender.start()

                assert sender.running is True
                mock_thread.assert_called_once()
                mock_thread_instance.start.assert_called_once()

    def test_start_when_already_running(self):
        """Test that start() does nothing if already running"""
        mock_config = Mock()

        with patch('src.heartbeat_sender.Params') as mock_params:
            mock_params.heartbeat_interval = 10
            mock_params.GCS_IP = '192.168.1.1'
            mock_params.gcs_api_port = 5030

            sender = HeartbeatSender(mock_config)
            sender.running = True  # Already running

            with patch('threading.Thread') as mock_thread:
                sender.start()
                mock_thread.assert_not_called()

    def test_stop_sets_running_false(self):
        """Test that stop() sets running to False"""
        mock_config = Mock()

        with patch('src.heartbeat_sender.Params') as mock_params:
            mock_params.heartbeat_interval = 10
            mock_params.GCS_IP = '192.168.1.1'
            mock_params.gcs_api_port = 5030

            sender = HeartbeatSender(mock_config)
            sender.running = True

            mock_thread = Mock()
            mock_thread.is_alive.return_value = True
            sender.thread = mock_thread

            sender.stop()

            assert sender.running is False
            mock_thread.join.assert_called_once_with(timeout=2)


class TestHeartbeatSending:
    """Test heartbeat message sending"""

    def test_send_heartbeat_success(self):
        """Test successful heartbeat POST request"""
        mock_config = Mock()
        mock_config.hw_id = 1
        mock_config.pos_id = 1
        mock_config.detected_pos_id = 0
        mock_config.config = {'ip': '10.0.0.1'}

        with patch('src.heartbeat_sender.Params') as mock_params:
            mock_params.heartbeat_interval = 10
            mock_params.GCS_IP = '192.168.1.1'
            mock_params.gcs_api_port = 5030
            mock_params.gcs_heartbeat_endpoint = '/api/v1/fleet/heartbeats'
            mock_params.netbird_ip_prefix = '192.0.2.'

            sender = HeartbeatSender(mock_config)

            with patch.object(sender, '_get_netbird_ip', return_value='192.0.2.1'):
                with patch.object(sender, '_get_network_info', return_value={'wifi': None, 'ethernet': None}):
                    with patch('requests.post') as mock_post:
                        mock_response = Mock()
                        mock_response.status_code = 200
                        mock_post.return_value = mock_response

                        sender.send_heartbeat()

                        mock_post.assert_called_once()
                        call_args = mock_post.call_args
                        assert call_args[0][0] == 'http://192.168.1.1:5030/api/v1/fleet/heartbeats'
                        assert call_args[1]['json']['hw_id'] == '1'
                        assert call_args[1]['json']['pos_id'] == 1
                        assert call_args[1]['json']['ip'] == '192.0.2.1'

    def test_send_heartbeat_failure(self):
        """Test heartbeat POST request failure"""
        mock_config = Mock()
        mock_config.hw_id = '1'
        mock_config.pos_id = 1
        mock_config.detected_pos_id = 0
        mock_config.config = {'ip': '10.0.0.1'}

        with patch('src.heartbeat_sender.Params') as mock_params:
            mock_params.heartbeat_interval = 10
            mock_params.GCS_IP = '192.168.1.1'
            mock_params.gcs_api_port = 5030
            mock_params.gcs_heartbeat_endpoint = '/api/v1/fleet/heartbeats'
            mock_params.netbird_ip_prefix = '192.0.2.'

            sender = HeartbeatSender(mock_config)

            with patch.object(sender, '_get_netbird_ip', return_value=None):
                with patch.object(sender, '_get_network_info', return_value={}):
                    with patch('requests.post') as mock_post:
                        mock_response = Mock()
                        mock_response.status_code = 500
                        mock_response.text = 'Server Error'
                        mock_post.return_value = mock_response

                        # Should not raise, just log warning
                        sender.send_heartbeat()

    def test_send_heartbeat_uses_fallback_ip(self):
        """Test that fallback IP from config is used when no netbird IP"""
        mock_config = Mock()
        mock_config.hw_id = '1'
        mock_config.pos_id = 1
        mock_config.detected_pos_id = 0
        mock_config.config = {'ip': '10.0.0.1'}

        with patch('src.heartbeat_sender.Params') as mock_params:
            mock_params.heartbeat_interval = 10
            mock_params.GCS_IP = '192.168.1.1'
            mock_params.gcs_api_port = 5030
            mock_params.gcs_heartbeat_endpoint = '/api/v1/fleet/heartbeats'
            mock_params.netbird_ip_prefix = '100.'

            sender = HeartbeatSender(mock_config)

            with patch.object(sender, '_get_netbird_ip', return_value=None):
                with patch.object(sender, '_get_network_info', return_value={}):
                    with patch('requests.post') as mock_post:
                        mock_response = Mock()
                        mock_response.status_code = 200
                        mock_post.return_value = mock_response

                        sender.send_heartbeat()

                        call_args = mock_post.call_args
                        assert call_args[1]['json']['ip'] == '10.0.0.1'


class TestNetworkInfoGathering:
    """Test network info gathering methods"""

    def test_get_netbird_ip_found(self):
        """Test finding netbird IP from interfaces"""
        mock_config = Mock()

        with patch('src.heartbeat_sender.Params') as mock_params:
            mock_params.heartbeat_interval = 10
            mock_params.GCS_IP = '192.168.1.1'
            mock_params.gcs_api_port = 5030
            mock_params.netbird_ip_prefix = '192.0.2.'

            sender = HeartbeatSender(mock_config)

            with patch('netifaces.interfaces', return_value=['eth0', 'wt0']):
                with patch('netifaces.ifaddresses') as mock_ifaddr:
                    mock_ifaddr.return_value = {
                        2: [{'addr': '192.0.2.5', 'netmask': '255.255.255.0'}]
                    }
                    with patch('netifaces.AF_INET', 2):
                        result = sender._get_netbird_ip()
                        assert result == '192.0.2.5'

    def test_get_netbird_ip_not_found(self):
        """Test when no netbird IP is found"""
        mock_config = Mock()

        with patch('src.heartbeat_sender.Params') as mock_params:
            mock_params.heartbeat_interval = 10
            mock_params.GCS_IP = '192.168.1.1'
            mock_params.gcs_api_port = 5030
            mock_params.netbird_ip_prefix = '100.'

            sender = HeartbeatSender(mock_config)

            with patch('netifaces.interfaces', return_value=['eth0']):
                with patch('netifaces.ifaddresses') as mock_ifaddr:
                    mock_ifaddr.return_value = {
                        2: [{'addr': '192.168.1.50', 'netmask': '255.255.255.0'}]
                    }
                    with patch('netifaces.AF_INET', 2):
                        result = sender._get_netbird_ip()
                        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
