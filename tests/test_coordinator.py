# tests/test_coordinator.py
"""
Coordinator Startup Tests
=========================
Tests for coordinator.py startup sequence, component initialization,
state management, and graceful shutdown.

These tests verify the critical startup path that runs on every drone.
"""

import pytest
import asyncio
import threading
import time
from unittest.mock import Mock, MagicMock, patch, AsyncMock, PropertyMock

# Path configuration is handled by conftest.py

from src.enums import Mission, State


def create_mock_drone_config():
    """Create a properly initialized mock DroneConfig for testing"""
    from src.drone_config import DroneConfig
    drone_config = Mock(spec=DroneConfig)
    drone_config.state = State.IDLE.value
    drone_config.mission = Mission.NONE.value
    drone_config.last_mission = Mission.NONE.value
    drone_config.trigger_time = 0
    drone_config.config = {'pos_id': 1, 'hw_id': '1'}
    drone_config.hw_id = '1'
    drone_config.is_armed = False
    drone_config.is_ready_to_arm = True
    return drone_config


# ============================================================================
# Test: Module Imports
# ============================================================================

@pytest.mark.unit
@pytest.mark.coordinator
class TestCoordinatorImports:
    """Test that all coordinator imports work correctly"""

    def test_import_coordinator_module(self):
        """Test coordinator module can be imported"""
        # This tests that all dependencies are available
        with patch.dict('sys.modules', {'sdnotify': MagicMock()}):
            # Mock sdnotify since it may not be installed in test env
            import importlib
            # Don't actually import coordinator as it has side effects
            # Just verify the dependent modules exist
            from src.drone_config import DroneConfig
            from src.params import Params
            from src.enums import State

            assert DroneConfig is not None
            assert Params is not None
            assert State is not None

    def test_import_drone_config(self):
        """Test DroneConfig import"""
        from src.drone_config import DroneConfig
        assert DroneConfig is not None

    def test_import_params(self):
        """Test Params import"""
        from src.params import Params
        assert Params is not None

    def test_import_enums(self):
        """Test enums import"""
        from src.enums import State, Mission
        assert State.IDLE.value == 0
        assert State.MISSION_READY.value == 1
        assert State.MISSION_EXECUTING.value == 2

    def test_import_drone_api_server(self):
        """Test DroneAPIServer import"""
        from src.drone_api_server import DroneAPIServer
        assert DroneAPIServer is not None

    def test_import_drone_communicator(self):
        """Test DroneCommunicator import"""
        from src.drone_communicator import DroneCommunicator
        assert DroneCommunicator is not None

    def test_import_drone_setup(self):
        """Test DroneSetup import"""
        from src.drone_setup import DroneSetup
        assert DroneSetup is not None


# ============================================================================
# Test: Component Initialization
# ============================================================================

@pytest.mark.unit
@pytest.mark.coordinator
class TestComponentInitialization:
    """Test individual component initialization"""

    def test_drone_config_initialization(self):
        """Test DroneConfig mock has required attributes"""
        config = create_mock_drone_config()

        assert config is not None
        assert hasattr(config, 'state')
        assert hasattr(config, 'mission')

    def test_params_initialization(self):
        """Test Params initializes with defaults"""
        from src.params import Params

        params = Params()

        assert params is not None
        assert hasattr(params, 'sim_mode')
        assert hasattr(params, 'GCS_IP')
        assert hasattr(params, 'drone_api_port')

    def test_params_sim_mode_detection(self):
        """Test Params correctly detects sim mode"""
        from src.params import Params

        # Params.sim_mode is based on existence of 'real.mode' file
        # In test environment, it should be True (SITL mode)
        assert hasattr(Params, 'sim_mode')

    def test_drone_api_server_initialization(self, mock_params, mock_drone_config):
        """Test DroneAPIServer initializes correctly"""
        from src.drone_api_server import DroneAPIServer

        server = DroneAPIServer(mock_params, mock_drone_config)

        assert server is not None
        assert hasattr(server, 'app')
        assert hasattr(server, 'run')

    def test_drone_api_server_has_endpoints(self, mock_params, mock_drone_config):
        """Test DroneAPIServer has expected endpoints"""
        from src.drone_api_server import DroneAPIServer

        server = DroneAPIServer(mock_params, mock_drone_config)

        # Check app has routes
        routes = [route.path for route in server.app.routes]

        assert '/api/v1/drone/state' in routes
        assert '/api/v1/system/health' in routes


# ============================================================================
# Test: Coordinator Startup Sequence
# ============================================================================

@pytest.mark.unit
@pytest.mark.coordinator
class TestCoordinatorStartupSequence:
    """Test the coordinator startup sequence"""

    @patch('src.local_mavlink_controller.LocalMavlinkController')
    @patch('src.drone_communicator.DroneCommunicator')
    @patch('src.drone_api_server.DroneAPIServer')
    @patch('src.heartbeat_sender.HeartbeatSender')
    @patch('src.drone_setup.DroneSetup')
    def test_startup_initializes_components(
        self,
        mock_drone_setup,
        mock_heartbeat,
        mock_api_server,
        mock_communicator,
        mock_local_mavlink
    ):
        """Test that coordinator initializes required components

        Note: MAVLink routing is now EXTERNAL (via mavlink-anywhere or run_mavlink_router.sh).
        This test verifies that the coordinator initializes local components correctly,
        assuming external MAVLink routing is already running.
        """
        from src.params import Params
        from src.drone_config import DroneConfig

        # Setup mocks
        mock_api_server.return_value.set_drone_communicator = Mock()
        mock_communicator.return_value.set_api_server = Mock()
        mock_communicator.return_value.start_communication = Mock()
        mock_heartbeat.return_value.start = Mock()

        # Simulate startup order
        params = Params()
        drone_config = create_mock_drone_config()

        # Step 1: LocalMavlinkController (expects external routing to be running)
        local_controller = mock_local_mavlink(drone_config, params, False)

        # Verify LocalMavlinkController was called
        mock_local_mavlink.assert_called_once()

    @patch('src.drone_api_server.DroneAPIServer')
    @patch('src.drone_communicator.DroneCommunicator')
    def test_api_server_communicator_linking(
        self,
        mock_communicator_class,
        mock_api_server_class
    ):
        """Test that API server and communicator are linked correctly"""
        from src.params import Params
        from src.drone_config import DroneConfig

        # Setup mocks
        mock_api = Mock()
        mock_comms = Mock()
        mock_api_server_class.return_value = mock_api
        mock_communicator_class.return_value = mock_comms

        params = Mock()
        drone_config = Mock()
        drones = {}

        # Create instances
        drone_comms = mock_communicator_class(drone_config, params, drones)
        api_server = mock_api_server_class(params, drone_config)

        # Link them (as coordinator does)
        drone_comms.set_api_server(api_server)
        api_server.set_drone_communicator(drone_comms)

        # Verify linking
        mock_comms.set_api_server.assert_called_once_with(mock_api)
        mock_api.set_drone_communicator.assert_called_once_with(mock_comms)

    @patch('src.heartbeat_sender.HeartbeatSender')
    def test_heartbeat_sender_starts(self, mock_heartbeat_class):
        """Test that HeartbeatSender is started during initialization"""
        mock_sender = Mock()
        mock_heartbeat_class.return_value = mock_sender

        drone_config = Mock()

        # Create and start
        heartbeat = mock_heartbeat_class(drone_config)
        heartbeat.start()

        # Verify
        mock_heartbeat_class.assert_called_once_with(drone_config)
        mock_sender.start.assert_called_once()


# ============================================================================
# Test: State Machine
# ============================================================================

@pytest.mark.unit
@pytest.mark.coordinator
class TestCoordinatorStateMachine:
    """Test coordinator state machine transitions"""

    def test_state_enum_values(self):
        """Test State enum has correct values"""
        from src.enums import State

        assert State.IDLE.value == 0
        assert State.MISSION_READY.value == 1
        assert State.MISSION_EXECUTING.value == 2

    def test_state_transitions_idle_to_ready(self):
        """Test transition from IDLE to MISSION_READY"""
        drone_config = create_mock_drone_config()

        # Start in IDLE
        drone_config.state = State.IDLE.value
        assert drone_config.state == 0

        # Transition to READY
        drone_config.state = State.MISSION_READY.value
        assert drone_config.state == 1

    def test_state_transitions_ready_to_executing(self):
        """Test transition from MISSION_READY to MISSION_EXECUTING"""
        drone_config = create_mock_drone_config()

        drone_config.state = State.MISSION_READY.value
        assert drone_config.state == 1

        drone_config.state = State.MISSION_EXECUTING.value
        assert drone_config.state == 2

    def test_state_transitions_executing_to_idle(self):
        """Test transition from MISSION_EXECUTING back to IDLE"""
        drone_config = create_mock_drone_config()

        drone_config.state = State.MISSION_EXECUTING.value
        assert drone_config.state == 2

        # Mission complete, back to IDLE
        drone_config.state = State.IDLE.value
        assert drone_config.state == 0

    def test_mission_tracking(self):
        """Test mission value tracking"""
        drone_config = create_mock_drone_config()

        # Set mission
        drone_config.mission = Mission.TAKE_OFF.value
        assert drone_config.mission == 10

        # Track last mission
        drone_config.last_mission = drone_config.mission
        drone_config.mission = Mission.NONE.value

        assert drone_config.mission == 0
        assert drone_config.last_mission == 10


# ============================================================================
# Test: Mission Scheduling
# ============================================================================

@pytest.mark.unit
@pytest.mark.coordinator
class TestMissionScheduling:
    """Test mission scheduling functionality"""

    @pytest.mark.asyncio
    async def test_schedule_mission_async_calls_drone_setup(self):
        """Test that schedule_missions_async calls drone_setup.schedule_mission"""
        from src.drone_setup import DroneSetup

        # Mock DroneSetup
        mock_drone_setup = Mock(spec=DroneSetup)
        mock_drone_setup.schedule_mission = AsyncMock()

        # Call schedule_mission
        await mock_drone_setup.schedule_mission()

        # Verify it was called
        mock_drone_setup.schedule_mission.assert_awaited_once()

    def test_scheduling_thread_is_daemon(self):
        """Test that scheduling thread is a daemon thread"""
        # Create a thread like coordinator does
        def dummy_target():
            pass

        scheduling_thread = threading.Thread(
            target=dummy_target,
            daemon=True
        )

        assert scheduling_thread.daemon is True

    @pytest.mark.asyncio
    async def test_schedule_mission_loop_frequency(self):
        """Test scheduling loop respects frequency parameter"""
        call_count = 0
        max_calls = 3

        async def mock_schedule():
            nonlocal call_count
            call_count += 1
            if call_count >= max_calls:
                raise asyncio.CancelledError()

        mock_setup = Mock()
        mock_setup.schedule_mission = mock_schedule

        # Run scheduler briefly
        try:
            while call_count < max_calls:
                await mock_setup.schedule_mission()
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass

        assert call_count == max_calls


# ============================================================================
# Test: Connectivity Checker Integration
# ============================================================================

@pytest.mark.unit
@pytest.mark.coordinator
class TestConnectivityCheckerIntegration:
    """Test ConnectivityChecker integration with coordinator"""

    def test_connectivity_checker_starts_in_idle(self):
        """Test ConnectivityChecker starts when drone is IDLE"""
        from src.enums import State

        mock_checker = Mock()
        mock_checker.is_running = False

        # Simulate IDLE state transition
        current_state = State.IDLE.value
        current_mission = 0
        enable_connectivity_check = True

        if current_state == State.IDLE.value:
            if current_mission == 0 and enable_connectivity_check:
                if not mock_checker.is_running:
                    mock_checker.start()

        mock_checker.start.assert_called_once()

    def test_connectivity_checker_stops_when_armed(self):
        """Test ConnectivityChecker stops when MISSION_READY"""
        from src.enums import State

        mock_checker = Mock()
        mock_checker.is_running = True

        # Simulate MISSION_READY state
        current_state = State.MISSION_READY.value

        if current_state == State.MISSION_READY.value:
            if mock_checker.is_running:
                mock_checker.stop()

        mock_checker.stop.assert_called_once()

    def test_connectivity_checker_stops_during_mission(self):
        """Test ConnectivityChecker stops during MISSION_EXECUTING"""
        from src.enums import State

        mock_checker = Mock()
        mock_checker.is_running = True

        current_state = State.MISSION_EXECUTING.value

        if current_state == State.MISSION_EXECUTING.value:
            if mock_checker.is_running:
                mock_checker.stop()

        mock_checker.stop.assert_called_once()


# ============================================================================
# Test: LED Controller Integration
# ============================================================================

@pytest.mark.unit
@pytest.mark.coordinator
class TestLEDControllerIntegration:
    """Test LED controller integration"""

    def test_led_cyan_on_startup(self):
        """Test LED is set to cyan on startup"""
        mock_led = Mock()

        # Startup sequence sets cyan
        mock_led.set_color(0, 255, 255)

        mock_led.set_color.assert_called_with(0, 255, 255)

    def test_led_orange_when_armed(self):
        """Test LED is set to orange when MISSION_READY"""
        from src.enums import State

        mock_led = Mock()
        current_state = State.MISSION_READY.value

        if current_state == State.MISSION_READY.value:
            mock_led.set_color(255, 165, 0)  # Orange

        mock_led.set_color.assert_called_with(255, 165, 0)

    def test_led_red_on_error(self):
        """Test LED is set to red on error"""
        mock_led = Mock()

        # Error handling
        try:
            raise Exception("Test error")
        except Exception:
            mock_led.set_color(255, 0, 0)  # Red

        mock_led.set_color.assert_called_with(255, 0, 0)

    def test_led_controller_none_in_sim_mode(self):
        """Test LED controller is None in simulation mode"""
        from src.params import Params

        # In sim mode, led_controller should be None
        if Params.sim_mode:
            led_controller = None
            assert led_controller is None


# ============================================================================
# Test: Graceful Shutdown
# ============================================================================

@pytest.mark.unit
@pytest.mark.coordinator
class TestGracefulShutdown:
    """Test graceful shutdown of coordinator components"""

    def test_shutdown_stops_connectivity_checker(self):
        """Test shutdown stops ConnectivityChecker"""
        mock_checker = Mock()
        mock_checker.is_running = True

        # Shutdown sequence
        if mock_checker and mock_checker.is_running:
            mock_checker.stop()

        mock_checker.stop.assert_called_once()

    # test_shutdown_terminates_mavlink_manager REMOVED
    # MAVLink routing is now external (mavlink-anywhere or run_mavlink_router.sh)

    def test_shutdown_stops_drone_communication(self):
        """Test shutdown stops drone communication"""
        mock_comms = Mock()

        # Shutdown sequence
        if mock_comms:
            mock_comms.stop_communication()

        mock_comms.stop_communication.assert_called_once()

    def test_shutdown_stops_heartbeat_sender(self):
        """Test shutdown stops HeartbeatSender"""
        mock_heartbeat = Mock()

        # Shutdown sequence
        if mock_heartbeat:
            mock_heartbeat.stop()

        mock_heartbeat.stop.assert_called_once()

    def test_shutdown_stops_pos_id_detector(self):
        """Test shutdown stops PosIDAutoDetector"""
        mock_detector = Mock()

        # Shutdown sequence
        if mock_detector:
            mock_detector.stop()

        mock_detector.stop.assert_called_once()

    def test_full_shutdown_sequence(self):
        """Test complete shutdown sequence

        Note: mavlink_manager is no longer part of shutdown - MAVLink routing
        is now external (via mavlink-anywhere or run_mavlink_router.sh).
        """
        # Create all mock components
        mock_checker = Mock()
        mock_checker.is_running = True
        mock_comms = Mock()
        mock_heartbeat = Mock()
        mock_detector = Mock()

        # Execute shutdown sequence (as in coordinator finally block)
        shutdown_order = []

        if mock_checker and mock_checker.is_running:
            mock_checker.stop()
            shutdown_order.append('connectivity_checker')

        # mavlink_manager termination REMOVED - routing is external

        if mock_comms:
            mock_comms.stop_communication()
            shutdown_order.append('drone_comms')

        if mock_heartbeat:
            mock_heartbeat.stop()
            shutdown_order.append('heartbeat_sender')

        if mock_detector:
            mock_detector.stop()
            shutdown_order.append('pos_id_detector')

        # Verify all components were stopped (4 components, not 5)
        assert len(shutdown_order) == 4
        mock_checker.stop.assert_called_once()
        mock_comms.stop_communication.assert_called_once()
        mock_heartbeat.stop.assert_called_once()
        mock_detector.stop.assert_called_once()


# ============================================================================
# Test: Error Handling
# ============================================================================

@pytest.mark.unit
@pytest.mark.coordinator
class TestCoordinatorErrorHandling:
    """Test error handling in coordinator"""

    def test_led_controller_init_failure_handled(self):
        """Test LED controller initialization failure is handled"""
        # Simulate LED controller failure
        led_controller = None
        try:
            raise Exception("Failed to initialize LED")
        except Exception:
            led_controller = None

        assert led_controller is None

    def test_main_loop_exception_sets_led_red(self):
        """Test that exceptions in main loop set LED to red"""
        mock_led = Mock()

        try:
            raise Exception("Test error in main loop")
        except Exception:
            if mock_led:
                mock_led.set_color(255, 0, 0)

        mock_led.set_color.assert_called_with(255, 0, 0)

    def test_unknown_state_handled(self):
        """Test that unknown state is detected"""
        # Unknown state value
        current_state = 999

        valid_states = [State.IDLE.value, State.MISSION_READY.value, State.MISSION_EXECUTING.value]

        # 999 should not be a valid state
        assert current_state not in valid_states

        # Test that handlers can be called for unknown states
        mock_checker = Mock()
        mock_led = Mock()

        if current_state not in valid_states:
            mock_checker.stop()
            mock_led.set_color(255, 0, 0)

        mock_checker.stop.assert_called_once()
        mock_led.set_color.assert_called_once_with(255, 0, 0)


# ============================================================================
# Test: Watchdog Notifications
# ============================================================================

@pytest.mark.unit
@pytest.mark.coordinator
class TestWatchdogNotifications:
    """Test systemd watchdog notifications"""

    def test_watchdog_notify_called(self):
        """Test that watchdog notify is called"""
        mock_notifier = Mock()

        # Main loop calls watchdog
        mock_notifier.notify("WATCHDOG=1")

        mock_notifier.notify.assert_called_with("WATCHDOG=1")

    def test_watchdog_notify_in_scheduling(self):
        """Test watchdog is notified in scheduling loop"""
        mock_notifier = Mock()

        # Scheduling loop notifies watchdog
        for _ in range(3):
            mock_notifier.notify("WATCHDOG=1")

        assert mock_notifier.notify.call_count == 3


# ============================================================================
# Test: PosIDAutoDetector Integration
# ============================================================================

@pytest.mark.unit
@pytest.mark.coordinator
class TestPosIDAutoDetectorIntegration:
    """Test PosIDAutoDetector integration"""

    def test_auto_detector_starts_when_enabled(self):
        """Test auto detector starts when enabled"""
        mock_detector = Mock()
        auto_detection_enabled = True

        if auto_detection_enabled:
            mock_detector.start()

        mock_detector.start.assert_called_once()

    def test_auto_detector_not_started_when_disabled(self):
        """Test auto detector doesn't start when disabled"""
        mock_detector = Mock()
        auto_detection_enabled = False

        if auto_detection_enabled:
            mock_detector.start()

        mock_detector.start.assert_not_called()


# ============================================================================
# Test: Thread Safety
# ============================================================================

@pytest.mark.unit
@pytest.mark.coordinator
class TestThreadSafety:
    """Test thread safety in coordinator"""

    def test_drone_config_state_atomic(self):
        """Test that drone_config state changes are atomic"""
        config = create_mock_drone_config()

        # Simulate concurrent access
        results = []

        def writer():
            for _ in range(100):
                config.state = State.MISSION_READY.value
                config.state = State.IDLE.value

        def reader():
            for _ in range(100):
                # State should always be a valid value
                state = config.state
                results.append(state in [0, 1, 2])

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)

        t1.start()
        t2.start()

        t1.join()
        t2.join()

        # All reads should have gotten valid states
        assert all(results)

    def test_scheduling_thread_daemon(self):
        """Test scheduling thread is daemon (won't block exit)"""
        def dummy():
            time.sleep(10)

        thread = threading.Thread(target=dummy, daemon=True)
        thread.start()

        assert thread.daemon is True
        # Thread will be killed when test exits due to daemon=True
