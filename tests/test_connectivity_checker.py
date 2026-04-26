# tests/test_connectivity_checker.py
"""
Connectivity Checker Tests
==========================
Tests for the ConnectivityChecker class that monitors GCS connectivity.
"""

import pytest
import threading
import time
from unittest.mock import Mock, patch, MagicMock

from src.connectivity_checker import ConnectivityChecker


class TestConnectivityCheckerInit:
    """Test ConnectivityChecker initialization"""

    def test_init_with_default_endpoint(self):
        """Test initialization with default endpoint"""
        params = Mock()
        params.gcs_api_port = 5030
        del params.connectivity_check_endpoint  # Ensure attribute doesn't exist

        led_controller = Mock()

        checker = ConnectivityChecker(params, led_controller)

        assert checker.params == params
        assert checker.led_controller == led_controller
        assert checker.endpoint == "/ping"
        assert checker.port == 5030
        assert checker.is_running is False

    def test_init_with_custom_endpoint(self):
        """Test initialization with custom endpoint"""
        params = Mock()
        params.connectivity_check_endpoint = "/health"
        params.gcs_api_port = 8080

        led_controller = Mock()

        checker = ConnectivityChecker(params, led_controller)

        assert checker.endpoint == "/health"
        assert checker.port == 8080

    def test_init_default_port(self):
        """Test initialization with default port when not specified"""
        params = Mock(spec=[])  # Empty spec means no attributes
        led_controller = Mock()

        checker = ConnectivityChecker(params, led_controller)

        assert checker.port == 5030  # Default fallback


class TestConnectivityCheckerStartStop:
    """Test start/stop functionality"""

    def test_start_creates_thread(self):
        """Test that start creates a daemon thread"""
        params = Mock()
        params.connectivity_check_ip = "192.168.1.1"
        params.connectivity_check_interval = 5
        params.sim_mode = True
        led_controller = Mock()

        checker = ConnectivityChecker(params, led_controller)

        with patch.object(checker, 'run'):
            checker.start()

            assert checker.is_running is True
            assert checker.thread is not None
            assert checker.thread.daemon is True

            # Stop to clean up
            checker.stop()

    def test_start_when_already_running(self):
        """Test that start does nothing when already running"""
        params = Mock()
        params.connectivity_check_ip = "192.168.1.1"
        params.connectivity_check_interval = 5
        params.sim_mode = True
        led_controller = Mock()

        checker = ConnectivityChecker(params, led_controller)
        checker.is_running = True

        original_thread = checker.thread
        checker.start()

        # Thread should not be replaced
        assert checker.thread == original_thread

    def test_stop_when_running(self):
        """Test stop when checker is running"""
        params = Mock()
        params.connectivity_check_ip = "192.168.1.1"
        params.connectivity_check_interval = 0.1
        params.sim_mode = True
        led_controller = Mock()

        checker = ConnectivityChecker(params, led_controller)
        checker.start()

        # Wait briefly for thread to start
        time.sleep(0.05)

        checker.stop()

        assert checker.is_running is False
        assert checker.stop_event.is_set()

    def test_stop_when_not_running(self):
        """Test stop when checker is not running"""
        params = Mock()
        led_controller = Mock()

        checker = ConnectivityChecker(params, led_controller)
        assert checker.is_running is False

        # Should not raise
        checker.stop()

        assert checker.is_running is False


class TestConnectivityCheck:
    """Test connectivity check logic"""

    def test_check_connectivity_sim_mode(self):
        """Test that sim_mode always returns True"""
        params = Mock()
        params.sim_mode = True
        led_controller = Mock()

        checker = ConnectivityChecker(params, led_controller)

        result = checker.check_connectivity("192.168.1.1")

        assert result is True

    def test_check_connectivity_success(self):
        """Test successful connectivity check"""
        params = Mock()
        params.sim_mode = False
        params.gcs_api_port = 5030
        led_controller = Mock()

        checker = ConnectivityChecker(params, led_controller)

        with patch('src.connectivity_checker.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response

            result = checker.check_connectivity("192.168.1.1")

            assert result is True
            mock_get.assert_called_once()

    def test_check_connectivity_failure_status(self):
        """Test connectivity check with non-200 status"""
        params = Mock()
        params.sim_mode = False
        params.gcs_api_port = 5030
        led_controller = Mock()

        checker = ConnectivityChecker(params, led_controller)

        with patch('src.connectivity_checker.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 500
            mock_get.return_value = mock_response

            result = checker.check_connectivity("192.168.1.1")

            assert result is False

    def test_check_connectivity_exception(self):
        """Test connectivity check with exception"""
        params = Mock()
        params.sim_mode = False
        params.gcs_api_port = 5030
        led_controller = Mock()

        checker = ConnectivityChecker(params, led_controller)

        with patch('src.connectivity_checker.requests.get') as mock_get:
            mock_get.side_effect = Exception("Connection refused")

            result = checker.check_connectivity("192.168.1.1")

            assert result is False

    def test_check_connectivity_timeout(self):
        """Test connectivity check with timeout"""
        params = Mock()
        params.sim_mode = False
        params.gcs_api_port = 5030
        led_controller = Mock()

        checker = ConnectivityChecker(params, led_controller)

        with patch('src.connectivity_checker.requests.get') as mock_get:
            import requests
            mock_get.side_effect = requests.exceptions.Timeout()

            result = checker.check_connectivity("192.168.1.1")

            assert result is False


class TestConnectivityCheckerRun:
    """Test the run loop"""

    def test_run_sets_green_on_success(self):
        """Test that LED is set to green on successful connectivity"""
        params = Mock()
        params.connectivity_check_ip = "192.168.1.1"
        params.connectivity_check_interval = 0.01
        params.sim_mode = True
        led_controller = Mock()

        checker = ConnectivityChecker(params, led_controller)

        # Start and stop quickly
        checker.start()
        time.sleep(0.05)
        checker.stop()

        # LED should have been set to green (0, 255, 0)
        led_controller.set_color.assert_called_with(0, 255, 0)

    def test_run_sets_purple_on_failure(self):
        """Test that LED is set to purple on failed connectivity"""
        params = Mock()
        params.connectivity_check_ip = "192.168.1.1"
        params.connectivity_check_interval = 0.01
        params.sim_mode = False
        params.gcs_api_port = 5030
        led_controller = Mock()

        checker = ConnectivityChecker(params, led_controller)

        with patch('src.connectivity_checker.requests.get') as mock_get:
            mock_get.side_effect = Exception("Connection refused")

            checker.start()
            time.sleep(0.05)
            checker.stop()

        # LED should have been set to dim purple (128, 0, 128) for disconnected state
        led_controller.set_color.assert_called_with(128, 0, 128)


class TestConnectivityCheckerIntegration:
    """Integration tests for ConnectivityChecker"""

    def test_full_lifecycle(self):
        """Test complete start-run-stop lifecycle"""
        params = Mock()
        params.connectivity_check_ip = "127.0.0.1"
        params.connectivity_check_interval = 0.01
        params.sim_mode = True
        params.gcs_api_port = 5030
        led_controller = Mock()

        checker = ConnectivityChecker(params, led_controller)

        # Start
        checker.start()
        assert checker.is_running is True

        # Let it run for a bit
        time.sleep(0.05)

        # Stop
        checker.stop()
        assert checker.is_running is False

        # Verify LED was updated
        assert led_controller.set_color.called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
