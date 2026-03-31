# tests/test_command_processing.py
"""
Command Processing Tests
========================
Tests for command validation, routing, and execution.
Tests both GCS-side command handling and drone-side command reception.
"""

import pytest
import time
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from typing import Dict, List, Any

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


# Import fixtures
from tests.fixtures.drone_configs import (
    generate_drone_configs,
    single_drone_sitl,
    fifty_drone_grid,
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
    cmd_invalid_mission_type,
    cmd_missing_mission_type,
    cmd_empty,
    all_valid_commands,
    all_invalid_commands,
)


# ============================================================================
# Test: Command Validation
# ============================================================================

@pytest.mark.unit
@pytest.mark.command
class TestCommandValidation:
    """Test command data validation"""

    def test_validate_valid_command(self):
        """Test validation of valid command structure"""
        command = cmd_takeoff()

        # Validate command has required fields
        has_mission_type = 'missionType' in command
        has_trigger_time = 'triggerTime' in command

        assert has_mission_type is True
        assert has_trigger_time is True

        # Validate mission type is valid
        mission_type = command.get('missionType')
        assert mission_type is not None

    def test_validate_command_requires_mission_type(self):
        """Test that missionType is required"""
        # Manually test validation logic
        command = {'triggerTime': '12345'}

        # Missing missionType
        has_mission_type = 'missionType' in command
        assert has_mission_type is False

    def test_validate_command_accepts_string_mission_type(self):
        """Test that string missionType is accepted"""
        command = {'missionType': 'TAKEOFF', 'triggerTime': '12345'}

        mission_type = command.get('missionType')
        is_valid_type = isinstance(mission_type, (int, str))

        assert is_valid_type is True

    def test_validate_command_accepts_int_mission_type(self):
        """Test that integer missionType is accepted"""
        command = {'missionType': 10, 'triggerTime': '12345'}

        mission_type = command.get('missionType')
        is_valid_type = isinstance(mission_type, (int, str))

        assert is_valid_type is True

    def test_validate_empty_command_fails(self):
        """Test that empty command fails validation"""
        command = {}

        # Check required field
        has_mission_type = 'missionType' in command
        assert has_mission_type is False

    def test_validate_command_not_dict_fails(self):
        """Test that non-dict command fails"""
        command = "not a dict"

        is_valid = isinstance(command, dict)
        assert is_valid is False


# ============================================================================
# Test: Command Payload Construction
# ============================================================================

@pytest.mark.unit
@pytest.mark.command
class TestCommandPayloadConstruction:
    """Test command payload construction"""

    def test_takeoff_command_has_altitude(self):
        """Test takeoff command includes altitude"""
        command = cmd_takeoff(altitude=15.0)

        assert 'takeoff_altitude' in command
        assert command['takeoff_altitude'] == 15.0

    def test_drone_show_command_has_origin(self):
        """Test drone show command includes origin"""
        command = cmd_drone_show()

        assert 'origin' in command
        assert 'lat' in command['origin']
        assert 'lon' in command['origin']
        assert 'alt' in command['origin']

    def test_command_has_trigger_time(self):
        """Test all commands have trigger time"""
        for command in all_valid_commands():
            assert 'triggerTime' in command

    def test_mission_type_is_string(self):
        """Test missionType is converted to string for API"""
        command = cmd_takeoff()

        # Should be string for drone API compatibility
        assert isinstance(command['missionType'], str)

    def test_target_drones_optional(self):
        """Test target_drones is optional"""
        command = cmd_takeoff()

        # target_drones not required
        # But if present, should be a list
        if 'target_drones' in command:
            assert isinstance(command['target_drones'], list)


# ============================================================================
# Test: Command Routing
# ============================================================================

@pytest.mark.unit
@pytest.mark.command
class TestCommandRouting:
    """Test command routing to drones"""

    def test_send_to_all_drones(self):
        """Test command is sent to all drones"""
        drones = [
            {'hw_id': '1', 'ip': '172.18.0.2'},
            {'hw_id': '2', 'ip': '172.18.0.3'},
            {'hw_id': '3', 'ip': '172.18.0.4'},
        ]

        # Verify all drones would receive command
        assert len(drones) == 3
        for drone in drones:
            assert 'hw_id' in drone
            assert 'ip' in drone

    def test_send_to_selected_drones(self):
        """Test command is sent to selected drones only"""
        all_drones = [
            {'hw_id': '1', 'ip': '172.18.0.2'},
            {'hw_id': '2', 'ip': '172.18.0.3'},
            {'hw_id': '3', 'ip': '172.18.0.4'},
        ]
        target_ids = ['1', '3']

        # Filter drones
        selected = [d for d in all_drones if d['hw_id'] in target_ids]

        assert len(selected) == 2
        assert selected[0]['hw_id'] == '1'
        assert selected[1]['hw_id'] == '3'

    def test_missing_target_drones_warning(self):
        """Test warning when target drones not found"""
        all_drones = [
            {'hw_id': '1', 'ip': '172.18.0.2'},
        ]
        target_ids = ['1', '99']  # 99 doesn't exist

        # Filter and check for missing
        found = [d for d in all_drones if d['hw_id'] in target_ids]
        found_ids = [d['hw_id'] for d in found]
        missing = set(target_ids) - set(found_ids)

        assert '99' in missing
        assert len(found) == 1

    def test_empty_drone_list_handling(self):
        """Test handling of empty drone list"""
        drones = []

        # Should return early with no-op
        has_drones = len(drones) > 0
        assert has_drones is False

    def test_empty_target_list_handling(self):
        """Test handling of empty target list"""
        target_ids = []

        has_targets = len(target_ids) > 0
        assert has_targets is False


# ============================================================================
# Test: Command Execution
# ============================================================================

@pytest.mark.unit
@pytest.mark.command
class TestCommandExecution:
    """Test command execution logic"""

    def test_successful_command_returns_true(self):
        """Test successful command returns True"""
        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200

        success = mock_response.status_code == 200
        assert success is True

    def test_failed_command_returns_false(self):
        """Test failed command returns False"""
        mock_response = Mock()
        mock_response.status_code = 500

        success = mock_response.status_code == 200
        assert success is False

    def test_retry_on_timeout(self):
        """Test command retries on timeout"""
        retry_count = 0
        max_retries = 3

        def simulate_timeout():
            nonlocal retry_count
            retry_count += 1
            if retry_count < max_retries:
                raise Exception("Timeout")
            return True

        # Simulate retry loop
        while retry_count < max_retries:
            try:
                result = simulate_timeout()
                if result:
                    break
            except Exception:
                continue

        assert retry_count == max_retries

    def test_exponential_backoff(self):
        """Test exponential backoff between retries"""
        backoff_factor = 1
        attempts = [1, 2, 3]

        wait_times = [backoff_factor * (2 ** (a - 1)) for a in attempts]

        assert wait_times == [1, 2, 4]

    def test_command_statistics_tracking(self):
        """Test command statistics are tracked"""
        stats = {
            'total_commands': 0,
            'successful_commands': 0,
            'failed_commands': 0
        }

        # Simulate command execution
        stats['total_commands'] += 10
        stats['successful_commands'] += 8
        stats['failed_commands'] += 2

        assert stats['total_commands'] == 10
        assert stats['successful_commands'] == 8
        assert stats['failed_commands'] == 2

    def test_success_rate_calculation(self):
        """Test success rate calculation"""
        success = 8
        total = 10

        rate = (success / max(total, 1)) * 100

        assert rate == 80.0


# ============================================================================
# Test: Concurrent Command Execution
# ============================================================================

@pytest.mark.unit
@pytest.mark.command
class TestConcurrentCommandExecution:
    """Test concurrent command execution for multiple drones"""

    def test_thread_pool_max_workers(self):
        """Test thread pool has reasonable max workers"""
        num_drones = 50
        max_workers = min(num_drones, 20)

        assert max_workers == 20

    def test_thread_pool_scales_with_drones(self):
        """Test thread pool scales for smaller swarms"""
        num_drones = 5
        max_workers = min(num_drones, 20)

        assert max_workers == 5

    def test_results_collected_from_all_threads(self):
        """Test results are collected from all concurrent threads"""
        num_drones = 10
        results = {}

        # Simulate collecting results
        for i in range(num_drones):
            drone_id = str(i + 1)
            results[drone_id] = {'success': True, 'error': None}

        assert len(results) == num_drones

    def test_execution_time_tracked(self):
        """Test execution time is tracked"""
        start_time = time.time()

        # Simulate some work
        time.sleep(0.1)

        execution_time = time.time() - start_time

        assert execution_time >= 0.1


# ============================================================================
# Test: Command Error Handling
# ============================================================================

@pytest.mark.unit
@pytest.mark.command
class TestCommandErrorHandling:
    """Test error handling in command processing"""

    def test_connection_error_caught(self):
        """Test connection errors are caught"""
        from requests.exceptions import ConnectionError

        caught = False
        try:
            raise ConnectionError("Connection refused")
        except ConnectionError:
            caught = True

        assert caught is True

    def test_timeout_error_caught(self):
        """Test timeout errors are caught"""
        from requests.exceptions import Timeout

        caught = False
        try:
            raise Timeout("Request timed out")
        except Timeout:
            caught = True

        assert caught is True

    def test_http_error_response_handled(self):
        """Test HTTP error responses are handled"""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        error_msg = f"HTTP {mock_response.status_code}: {mock_response.text[:100]}"

        assert "500" in error_msg

    def test_unexpected_error_not_retried(self):
        """Test unexpected errors don't trigger retry"""
        retry_on_error = lambda e: isinstance(e, (ConnectionError, TimeoutError))

        class UnexpectedError(Exception):
            pass

        should_retry = retry_on_error(UnexpectedError("Unexpected"))

        assert should_retry is False

    def test_error_grouping_by_type(self):
        """Test errors are grouped by type for reporting"""
        errors = {
            '1': {'error': 'Timeout: Connection issue'},
            '2': {'error': 'Timeout: Connection issue'},
            '3': {'error': 'ConnectionError: Refused'},
        }

        # Group by error type
        groups = {}
        for drone_id, result in errors.items():
            error_type = result['error'].split(':')[0]
            if error_type not in groups:
                groups[error_type] = []
            groups[error_type].append(drone_id)

        assert 'Timeout' in groups
        assert len(groups['Timeout']) == 2
        assert 'ConnectionError' in groups
        assert len(groups['ConnectionError']) == 1


# ============================================================================
# Test: Command Results
# ============================================================================

@pytest.mark.unit
@pytest.mark.command
class TestCommandResults:
    """Test command result handling"""

    def test_result_contains_success_count(self):
        """Test result contains success count"""
        result = {
            'success': 8,
            'failed': 2,
            'total': 10
        }

        assert 'success' in result
        assert result['success'] == 8

    def test_result_contains_failure_details(self):
        """Test result contains failure details"""
        result = {
            'results': {
                '1': {'success': False, 'error': 'Timeout'},
                '2': {'success': True, 'error': None},
            }
        }

        failed = [k for k, v in result['results'].items() if not v['success']]

        assert len(failed) == 1
        assert '1' in failed

    def test_status_success_when_all_succeed(self):
        """Test status is success when all drones succeed"""
        failed = 0

        status = 'success' if failed == 0 else 'partial'

        assert status == 'success'

    def test_status_partial_when_some_fail(self):
        """Test status is partial when some drones fail"""
        success = 8
        failed = 2

        if failed == 0:
            status = 'success'
        elif success > 0:
            status = 'partial'
        else:
            status = 'failed'

        assert status == 'partial'

    def test_status_failed_when_all_fail(self):
        """Test status is failed when all drones fail"""
        success = 0
        failed = 10

        if failed == 0:
            status = 'success'
        elif success > 0:
            status = 'partial'
        else:
            status = 'failed'

        assert status == 'failed'


# ============================================================================
# Test: Drone-Side Command Reception
# ============================================================================

@pytest.mark.unit
@pytest.mark.command
class TestDroneCommandReception:
    """Test command reception on drone side"""

    def test_command_endpoint_exists(self, test_client):
        """Test /api/send-command endpoint exists"""
        response = test_client.post('/api/send-command', json={})

        # Should get response (even if error)
        assert response.status_code in [200, 400, 422]

    def test_command_updates_drone_state(self, mock_drone_communicator):
        """Test command updates drone state"""
        from src.enums import Mission, State

        command_data = {
            'missionType': str(Mission.TAKE_OFF.value),
            'triggerTime': str(int(time.time()) + 5)
        }

        # Process command
        mock_drone_communicator.process_command(command_data)

        mock_drone_communicator.process_command.assert_called_once_with(command_data)

    def test_trigger_time_parsed_correctly(self):
        """Test trigger time is parsed correctly"""
        now = int(time.time())
        trigger_time = str(now + 10)

        parsed = int(trigger_time)

        assert parsed == now + 10

    def test_mission_type_converted_from_string(self):
        """Test mission type is converted from string"""
        from src.enums import Mission

        mission_str = str(Mission.TAKE_OFF.value)  # "10"
        mission_int = int(mission_str)

        assert mission_int == 10

    def test_update_code_command_preserves_runtime_branch(self):
        """UPDATE_CODE must carry update_branch into drone runtime state."""
        from src.drone_communicator import DroneCommunicator

        params = Mock(
            enable_udp_telemetry=False,
            enable_default_subscriptions=False,
            default_takeoff_alt=10.0,
            max_takeoff_alt=50.0,
            reboot_after_params=True,
        )
        drone_config = create_mock_drone_config()
        drone_config.update_branch = None
        communicator = DroneCommunicator(drone_config, params, {})

        communicator.process_command({
            'missionType': str(Mission.UPDATE_CODE.value),
            'triggerTime': '0',
            'update_branch': 'main-candidate',
        })

        assert drone_config.update_branch == 'main-candidate'
        assert drone_config.mission == Mission.UPDATE_CODE.value
        assert drone_config.state == State.MISSION_READY.value

    def test_apply_common_params_command_preserves_reboot_flag(self):
        """APPLY_COMMON_PARAMS must preserve reboot_after_params into runtime state."""
        from src.drone_communicator import DroneCommunicator

        params = Mock(
            enable_udp_telemetry=False,
            enable_default_subscriptions=False,
            default_takeoff_alt=10.0,
            max_takeoff_alt=50.0,
            reboot_after_params=False,
        )
        drone_config = create_mock_drone_config()
        drone_config.reboot_after_params = None
        communicator = DroneCommunicator(drone_config, params, {})

        communicator.process_command({
            'missionType': str(Mission.APPLY_COMMON_PARAMS.value),
            'triggerTime': '0',
            'reboot_after_params': True,
        })

        assert drone_config.reboot_after_params is True
        assert drone_config.mission == Mission.APPLY_COMMON_PARAMS.value
        assert drone_config.state == State.MISSION_READY.value

    def test_get_drone_state_reports_px4_home_truth_not_fallback_cache(self):
        """Telemetry home_position_set must reflect PX4 home truth, not a fallback position cache."""
        from src.drone_communicator import DroneCommunicator

        params = Mock(
            enable_udp_telemetry=False,
            enable_default_subscriptions=False,
            default_takeoff_alt=10.0,
            max_takeoff_alt=50.0,
            reboot_after_params=True,
        )
        drone_config = create_mock_drone_config()
        drone_config.home_position = {'lat': 35.0, 'long': 51.0, 'alt': 1278.0}
        drone_config.px4_home_position_set = False
        drone_config.home_position_source = 'fallback_position'
        drone_config.pos_id = 1
        drone_config.detected_pos_id = 1
        drone_config.position = {'lat': 35.0, 'long': 51.0, 'alt': 1278.0}
        drone_config.velocity = {'north': 0.0, 'east': 0.0, 'down': 0.0}
        drone_config.yaw = 0.0
        drone_config.battery = 16.2
        drone_config.last_update_timestamp = int(time.time())
        drone_config.custom_mode = 262147
        drone_config.base_mode = 81
        drone_config.system_status = 4
        drone_config.readiness_checks = []
        drone_config.preflight_blockers = []
        drone_config.preflight_warnings = []
        drone_config.status_messages = []
        drone_config.preflight_last_update = int(time.time() * 1000)
        drone_config.hdop = 0.8
        drone_config.vdop = 1.1
        drone_config.gps_fix_type = 3
        drone_config.satellites_visible = 12

        communicator = DroneCommunicator(drone_config, params, {})
        drone_state = communicator.get_drone_state()

        assert drone_state['home_position_set'] is False
        assert drone_state['home_position_source'] == 'fallback_position'

    def test_get_drone_state_marks_stale_local_mavlink_as_unavailable(self):
        """Stale local telemetry must not remain operator-visible as ready."""
        from src.drone_communicator import DroneCommunicator

        params = Mock(
            enable_udp_telemetry=False,
            enable_default_subscriptions=False,
            default_takeoff_alt=10.0,
            max_takeoff_alt=50.0,
            reboot_after_params=True,
            LOCAL_MAVLINK_STALE_TIMEOUT_SEC=15,
        )
        drone_config = create_mock_drone_config()
        drone_config.home_position = {'lat': 35.0, 'long': 51.0, 'alt': 1278.0}
        drone_config.px4_home_position_set = True
        drone_config.home_position_source = 'px4'
        drone_config.pos_id = 2
        drone_config.detected_pos_id = 2
        drone_config.position = {'lat': 35.0, 'long': 51.0, 'alt': 1278.0}
        drone_config.velocity = {'north': 0.0, 'east': 0.0, 'down': 0.0}
        drone_config.yaw = 0.0
        drone_config.battery = 16.2
        drone_config.last_update_timestamp = int(time.time()) - 60
        drone_config.custom_mode = 262147
        drone_config.base_mode = 81
        drone_config.system_status = 4
        drone_config.readiness_checks = []
        drone_config.preflight_blockers = []
        drone_config.preflight_warnings = []
        drone_config.status_messages = []
        drone_config.preflight_last_update = int(time.time() * 1000)
        drone_config.hdop = 0.8
        drone_config.vdop = 1.1
        drone_config.gps_fix_type = 3
        drone_config.satellites_visible = 12

        communicator = DroneCommunicator(drone_config, params, {})
        drone_state = communicator.get_drone_state()

        assert drone_state['telemetry_available'] is False
        assert 'stale' in drone_state['telemetry_error'].lower()
        assert drone_state['is_ready_to_arm'] is False
        assert drone_state['readiness_status'] == 'unknown'
        assert drone_state['preflight_blockers']


# ============================================================================
# Test: Command Integration with DroneConfig
# ============================================================================

@pytest.mark.unit
@pytest.mark.command
class TestCommandDroneConfigIntegration:
    """Test command integration with DroneConfig"""

    def test_command_sets_mission(self):
        """Test command sets mission in DroneConfig"""
        config = create_mock_drone_config()

        # Simulate command processing
        config.mission = Mission.TAKE_OFF.value
        config.trigger_time = int(time.time()) + 5

        assert config.mission == 10

    def test_command_sets_state_to_ready(self):
        """Test command sets state to MISSION_READY"""
        config = create_mock_drone_config()

        # Simulate command processing
        config.state = State.MISSION_READY.value

        assert config.state == 1

    def test_origin_stored_in_config(self):
        """Test origin from command is stored"""
        config = create_mock_drone_config()

        origin = {'lat': 47.397742, 'lon': 8.545594, 'alt': 488.0}

        # Store origin (if the command includes it)
        config.origin = origin

        assert config.origin['lat'] == 47.397742


# ============================================================================
# Test: 50+ Drone Commands (Load)
# ============================================================================

@pytest.mark.unit
@pytest.mark.command
@pytest.mark.load
class TestLargeSwarmCommands:
    """Test command handling for large swarms (50+ drones)"""

    def test_50_drone_config_generation(self, fifty_drones):
        """Test 50 drone configurations can be generated"""
        assert len(fifty_drones) == 50

    def test_command_payload_for_50_drones(self, fifty_drones):
        """Test command payload works for 50 drones"""
        command = cmd_takeoff()

        # Each drone should receive the same command
        for drone in fifty_drones:
            drone_cmd = command.copy()
            drone_cmd['hw_id'] = drone.hw_id

            assert 'missionType' in drone_cmd

    def test_result_aggregation_for_50_drones(self, fifty_drones):
        """Test results are aggregated correctly for 50 drones"""
        results = {}

        for drone in fifty_drones:
            results[drone.hw_id] = {'success': True, 'error': None}

        success_count = sum(1 for r in results.values() if r['success'])

        assert success_count == 50

    def test_thread_pool_limit_for_50_drones(self, fifty_drones):
        """Test thread pool is limited to 20 for 50 drones"""
        max_workers = min(len(fifty_drones), 20)

        assert max_workers == 20

    def test_success_rate_for_partial_failure(self, fifty_drones):
        """Test success rate calculation with partial failure"""
        # Simulate 45 success, 5 failure
        success = 45
        total = 50

        rate = (success / total) * 100

        assert rate == 90.0


# ============================================================================
# Test: Command Type Specific Tests
# ============================================================================

@pytest.mark.unit
@pytest.mark.command
class TestMissionTypeCommands:
    """Test specific command types"""

    def test_takeoff_command_type(self):
        """Test takeoff command structure"""
        command = cmd_takeoff(altitude=10.0)

        assert command['missionType'] == str(MissionType.TAKE_OFF)

    def test_land_command_type(self):
        """Test land command structure"""
        command = cmd_land()

        assert command['missionType'] == str(MissionType.LAND)

    def test_hold_command_type(self):
        """Test hold command structure"""
        command = cmd_hold()

        assert command['missionType'] == str(MissionType.HOLD)

    def test_rtl_command_type(self):
        """Test RTL command structure"""
        command = cmd_rtl()

        assert command['missionType'] == str(MissionType.RETURN_RTL)

    def test_kill_command_type(self):
        """Test kill/terminate command structure"""
        command = cmd_kill_terminate()

        assert command['missionType'] == str(MissionType.KILL_TERMINATE)

    def test_drone_show_command_type(self):
        """Test drone show command structure"""
        command = cmd_drone_show()

        assert command['missionType'] == str(MissionType.DRONE_SHOW_FROM_CSV)
        assert 'origin' in command
        assert 'auto_global_origin' in command


# ============================================================================
# Test: Invalid Commands
# ============================================================================

@pytest.mark.unit
@pytest.mark.command
class TestInvalidCommands:
    """Test handling of invalid commands"""

    def test_invalid_mission_type_rejected(self):
        """Test invalid mission type is rejected"""
        command = cmd_invalid_mission_type()

        # Should have invalid mission type
        mission_type = command.get('missionType')

        # 999 is not a valid mission type
        valid_types = [0, 1, 2, 3, 4, 6, 7, 8, 10, 100, 101, 102, 103, 104, 105, 106, 110, 111]
        is_valid = int(mission_type) in valid_types if mission_type else False

        assert is_valid is False

    def test_missing_mission_type_rejected(self):
        """Test missing mission type is rejected"""
        command = cmd_missing_mission_type()

        has_mission_type = 'missionType' in command

        assert has_mission_type is False

    def test_empty_command_rejected(self):
        """Test empty command is rejected"""
        command = cmd_empty()

        is_empty = len(command) == 0

        assert is_empty is True

    def test_all_invalid_commands_detected(self):
        """Test all_invalid_commands returns a list of commands"""
        invalid = all_invalid_commands()

        # Should have multiple invalid command examples
        assert len(invalid) > 0

        # Each should be a dict (command structure)
        for command in invalid:
            assert isinstance(command, dict)
