# tests/test_command_system.py
"""
Command System Tests - Enterprise-Grade Validation
===================================================
Comprehensive test suite for the command tracking and validation system.

Tests cover:
- CommandErrorCode enum
- Command validation in drone_api_server
- CommandTracker lifecycle management
- GCS command endpoints
- Schemas validation

Author: MAVSDK Drone Show Test Team
Last Updated: 2026-01-05
"""

import pytest
import asyncio
import time
import json
from unittest.mock import Mock, patch, AsyncMock
from typing import Dict, Any

# Path configuration is handled by conftest.py
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'gcs-server'))


# ============================================================================
# CommandErrorCode Tests
# ============================================================================

class TestCommandErrorCode:
    """Test CommandErrorCode enum and descriptions"""

    def test_error_code_values(self):
        """Test that error codes have expected values"""
        from src.enums import CommandErrorCode

        # Validation errors (E1xx)
        assert CommandErrorCode.MISSING_MISSION_TYPE.value == "E100"
        assert CommandErrorCode.INVALID_MISSION_TYPE.value == "E101"
        assert CommandErrorCode.MISSING_TRIGGER_TIME.value == "E102"
        assert CommandErrorCode.INVALID_TRIGGER_TIME.value == "E103"
        assert CommandErrorCode.INVALID_ALTITUDE.value == "E104"

        # State errors (E2xx)
        assert CommandErrorCode.INVALID_STATE.value == "E200"
        assert CommandErrorCode.ALREADY_EXECUTING.value == "E203"
        assert CommandErrorCode.NOT_READY_TO_ARM.value == "E202"

        # Communication errors (E3xx)
        assert CommandErrorCode.TIMEOUT.value == "E300"
        assert CommandErrorCode.HTTP_ERROR.value == "E303"

        # Execution errors (E4xx)
        assert CommandErrorCode.MAVSDK_ERROR.value == "E400"

        # System errors (E5xx)
        assert CommandErrorCode.INTERNAL_ERROR.value == "E500"

    def test_error_descriptions(self):
        """Test that error codes have human-readable descriptions"""
        from src.enums import CommandErrorCode

        desc = CommandErrorCode.get_description("E100")
        assert "missionType" in desc.lower() or "mission" in desc.lower()

        desc = CommandErrorCode.get_description("E200")
        assert "state" in desc.lower()

        desc = CommandErrorCode.get_description("E300")
        assert "timed out" in desc.lower() or "timeout" in desc.lower()

        # Unknown code
        desc = CommandErrorCode.get_description("UNKNOWN")
        assert "unknown" in desc.lower()


class TestGcsLoggingImports:
    """Ensure GCS modules resolve the server-side logging implementation."""

    def test_command_module_uses_server_logging_wrapper(self):
        from command import get_logger

        assert get_logger.__module__ == 'mds_logging.server'

    def test_launch_missions_require_live_armability_probe(self):
        from command import mission_requires_launch_armability_probe
        from src.enums import Mission

        assert mission_requires_launch_armability_probe(Mission.TAKE_OFF) is True
        assert mission_requires_launch_armability_probe(Mission.SWARM_TRAJECTORY) is True
        assert mission_requires_launch_armability_probe(Mission.SMART_SWARM) is False


# ============================================================================
# CommandTracker Tests
# ============================================================================

class TestCommandTracker:
    """Test CommandTracker lifecycle management"""

    @pytest.fixture
    def tracker(self):
        """Create a fresh CommandTracker for each test"""
        from command_tracker import CommandTracker
        return CommandTracker(max_commands=100)

    @pytest.mark.asyncio
    async def test_create_command(self, tracker):
        """Test command creation"""
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=['1', '2', '3'],
            params={'takeoff_altitude': 10}
        )

        assert command_id is not None
        assert len(command_id) == 36  # UUID format

        status = await tracker.get_status(command_id)
        assert status is not None
        assert status['mission_type'] == 10
        assert status['mission_name'] == 'TAKE_OFF'
        assert status['target_drones'] == ['1', '2', '3']
        assert status['status'] == 'created'
        assert status['phase'] == 'awaiting_ack'
        assert status['outcome'] is None
        assert status['acks']['expected'] == 3

    @pytest.mark.asyncio
    async def test_record_ack_accepted(self, tracker):
        """Test recording accepted acknowledgments"""
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=['1', '2']
        )

        # Record ACK from drone 1
        success = await tracker.record_ack(
            command_id, hw_id='1', category='accepted', message='OK'
        )
        assert success

        status = await tracker.get_status(command_id)
        assert status['acks']['received'] == 1
        assert status['acks']['accepted'] == 1
        assert '1' in status['acks']['details']

        # Record ACK from drone 2
        await tracker.record_ack(
            command_id, hw_id='2', category='accepted'
        )

        status = await tracker.get_status(command_id)
        assert status['acks']['received'] == 2
        assert status['acks']['accepted'] == 2
        assert status['status'] == 'executing'  # All ACKs received
        assert status['phase'] == 'pending_execution'

    @pytest.mark.asyncio
    async def test_record_ack_rejected(self, tracker):
        """Test recording rejected acknowledgments"""
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=['1', '2']
        )

        # Both drones reject
        await tracker.record_ack(
            command_id, hw_id='1',
            category='rejected',
            error_code='E202', message='Not ready to arm'
        )
        await tracker.record_ack(
            command_id, hw_id='2',
            category='rejected',
            error_code='E202'
        )

        status = await tracker.get_status(command_id)
        assert status['acks']['rejected'] == 2
        assert status['status'] == 'failed'
        assert status['phase'] == 'terminal'
        assert status['outcome'] == 'failed'
        assert 'E202' in status['acks']['details']['1']['error_code']

    @pytest.mark.asyncio
    async def test_record_execution(self, tracker):
        """Test recording execution results"""
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=['1']
        )

        # ACK first
        await tracker.record_ack(command_id, hw_id='1', category='accepted')

        # Record execution
        success = await tracker.record_execution(
            command_id, hw_id='1', success=True,
            duration_ms=5000
        )
        assert success

        status = await tracker.get_status(command_id)
        assert status['executions']['started'] == 1
        assert status['executions']['succeeded'] == 1
        assert status['status'] == 'completed'
        assert status['phase'] == 'terminal'
        assert status['outcome'] == 'completed'
        assert status['progress']['stage'] == 'completed'

    @pytest.mark.asyncio
    async def test_progress_stage_marks_future_trigger_as_scheduled(self, tracker):
        """Pending execution with a future trigger should report a scheduled stage."""
        future_trigger = int(time.time()) + 120
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=['1', '2'],
            params={'triggerTime': future_trigger},
        )

        await tracker.record_ack(command_id, hw_id='1', category='accepted')
        await tracker.record_ack(command_id, hw_id='2', category='accepted')

        status = await tracker.get_status(command_id)
        assert status['phase'] == 'pending_execution'
        assert status['progress']['stage'] == 'scheduled'
        assert status['progress']['scheduled_trigger_time'] == future_trigger * 1000

    @pytest.mark.asyncio
    async def test_progress_stage_marks_finishing_when_some_drones_complete(self, tracker):
        """In-progress commands should surface a finishing stage once some drones complete."""
        command_id = await tracker.create_command(
            mission_type=4,
            target_drones=['1', '2'],
        )

        await tracker.record_ack(command_id, hw_id='1', category='accepted')
        await tracker.record_ack(command_id, hw_id='2', category='accepted')
        await tracker.record_execution_start(command_id, hw_id='1')
        await tracker.record_execution_start(command_id, hw_id='2')
        await tracker.record_execution(command_id, hw_id='1', success=True, duration_ms=5000)

        status = await tracker.get_status(command_id)
        assert status['phase'] == 'in_progress'
        assert status['progress']['stage'] == 'finishing'
        assert status['progress']['completed'] == 1
        assert status['progress']['remaining'] == 1

    @pytest.mark.asyncio
    async def test_execution_start_promotes_missing_ack_to_accepted(self, tracker):
        """Execution-start should count as acceptance proof if the HTTP ACK was lost."""
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=['1'],
        )

        await tracker.record_execution_start(command_id, hw_id='1')

        status = await tracker.get_status(command_id)
        assert status['acks']['received'] == 1
        assert status['acks']['accepted'] == 1
        assert status['acks']['details']['1']['category'] == 'accepted'
        assert 'execution-start' in status['acks']['details']['1']['message']
        assert status['phase'] == 'in_progress'
        assert status['progress']['active'] == 1

    @pytest.mark.asyncio
    async def test_execution_result_upgrades_offline_ack_to_accepted(self, tracker):
        """Execution-result must override an earlier offline ACK classification."""
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=['1'],
        )

        await tracker.record_ack(command_id, hw_id='1', category='offline', message='Timed out')
        await tracker.record_execution(command_id, hw_id='1', success=True, duration_ms=5000)

        status = await tracker.get_status(command_id)
        assert status['acks']['offline'] == 0
        assert status['acks']['accepted'] == 1
        assert status['acks']['details']['1']['category'] == 'accepted'
        assert 'execution-result' in status['acks']['details']['1']['message']
        assert status['status'] == 'completed'
        assert status['phase'] == 'terminal'
        assert status['outcome'] == 'completed'

    @pytest.mark.asyncio
    async def test_partial_success(self, tracker):
        """Test partial success scenario"""
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=['1', '2', '3']
        )

        # All accept
        for hw_id in ['1', '2', '3']:
            await tracker.record_ack(command_id, hw_id=hw_id, category='accepted')

        # 2 succeed, 1 fails
        await tracker.record_execution(command_id, hw_id='1', success=True)
        await tracker.record_execution(command_id, hw_id='2', success=True)
        await tracker.record_execution(
            command_id, hw_id='3', success=False,
            error_message='Script crashed'
        )

        status = await tracker.get_status(command_id)
        assert status['executions']['succeeded'] == 2
        assert status['executions']['failed'] == 1
        assert status['status'] == 'partial'
        assert status['phase'] == 'terminal'
        assert status['outcome'] == 'partial'

    @pytest.mark.asyncio
    async def test_partial_success_when_some_targets_never_accept(self, tracker):
        """Commands that only reach part of the target set should not count as full success."""
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=['1', '2', '3', '4']
        )

        await tracker.record_ack(command_id, hw_id='1', category='accepted')
        await tracker.record_ack(command_id, hw_id='2', category='accepted')
        await tracker.record_ack(command_id, hw_id='3', category='offline')
        await tracker.record_ack(command_id, hw_id='4', category='offline')

        await tracker.record_execution(command_id, hw_id='1', success=True)
        await tracker.record_execution(command_id, hw_id='2', success=True)

        status = await tracker.get_status(command_id)
        assert status['status'] == 'partial'
        assert status['phase'] == 'terminal'
        assert status['outcome'] == 'partial'
        assert 'Only 2/4 targets accepted' in status['error_summary']

    @pytest.mark.asyncio
    async def test_superseded_execution_results_surface_superseded_outcome(self, tracker):
        """A fully superseded running mission should not look like a generic execution failure."""
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=['1', '2']
        )

        for hw_id in ['1', '2']:
            await tracker.record_ack(command_id, hw_id=hw_id, category='accepted')

        for hw_id in ['1', '2']:
            await tracker.record_execution(
                command_id,
                hw_id=hw_id,
                success=False,
                error_message='Superseded by a newer command before completion',
            )

        status = await tracker.get_status(command_id)
        assert status['status'] == 'cancelled'
        assert status['phase'] == 'terminal'
        assert status['outcome'] == 'superseded'
        assert status['error_summary'] == 'Superseded by newer command on all 2 drones'

    @pytest.mark.asyncio
    async def test_cancel_command(self, tracker):
        """Test command cancellation"""
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=['1']
        )

        success = await tracker.cancel_command(command_id, "Test cancel")
        assert success

        status = await tracker.get_status(command_id)
        assert status['status'] == 'cancelled'
        assert status['phase'] == 'terminal'
        assert status['outcome'] == 'cancelled'

    @pytest.mark.asyncio
    async def test_get_recent_commands(self, tracker):
        """Test retrieving recent commands"""
        # Create multiple commands with explicit pauses for timestamp ordering
        created_ids = []
        for i in range(5):
            cmd_id = await tracker.create_command(
                mission_type=10 + i,
                target_drones=['1']
            )
            created_ids.append(cmd_id)

        commands = await tracker.get_recent(limit=3)
        assert len(commands) == 3

        # Verify we got 3 commands (order may vary with same timestamps)
        command_ids = [c['command_id'] for c in commands]
        assert len(set(command_ids)) == 3  # All unique

    @pytest.mark.asyncio
    async def test_statistics(self, tracker):
        """Test command statistics"""
        # Create and complete a command
        cmd1 = await tracker.create_command(mission_type=10, target_drones=['1'])
        await tracker.record_ack(cmd1, '1', category='accepted')
        await tracker.record_execution(cmd1, '1', True)

        # Create a failed command
        cmd2 = await tracker.create_command(mission_type=10, target_drones=['2'])
        await tracker.record_ack(cmd2, '2', category='rejected', error_code='E200')

        stats = await tracker.get_statistics()
        assert stats['total_commands'] == 2
        assert stats['successful_commands'] == 1
        assert stats['failed_commands'] == 1

    @pytest.mark.asyncio
    async def test_statistics_count_partial_target_shortfall(self, tracker):
        """ACK shortfalls should contribute to partial command stats, not full success."""
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=['1', '2', '3']
        )
        await tracker.record_ack(command_id, '1', category='accepted')
        await tracker.record_ack(command_id, '2', category='accepted')
        await tracker.record_ack(command_id, '3', category='offline')
        await tracker.record_execution(command_id, '1', True)
        await tracker.record_execution(command_id, '2', True)

        stats = await tracker.get_statistics()
        assert stats['partial_commands'] == 1
        assert stats['successful_commands'] == 0
        assert stats['success_rate'] == 0.0

    @pytest.mark.asyncio
    async def test_command_eviction(self):
        """Test that old commands are evicted when limit reached"""
        from command_tracker import CommandTracker
        tracker = CommandTracker(max_commands=3)

        # Create 4 commands
        ids = []
        for i in range(4):
            cmd_id = await tracker.create_command(
                mission_type=10,
                target_drones=['1']
            )
            ids.append(cmd_id)

        # First command should be evicted
        status = await tracker.get_status(ids[0])
        assert status is None

        # Last 3 should still exist
        for cmd_id in ids[1:]:
            status = await tracker.get_status(cmd_id)
            assert status is not None


# ============================================================================
# GCS Command Distribution Tests
# ============================================================================

class TestGcsCommandDistribution:
    """Test GCS command fan-out behavior with mixed ID types and ACK payloads."""

    def test_validate_command_data_accepts_supported_legacy_mission_names(self):
        """Legacy CLI-style mission names should normalize cleanly."""
        from command import validate_command_data

        is_valid, error = validate_command_data({'missionType': 'LAND', 'triggerTime': '0'})

        assert is_valid is True
        assert error == ""

    def test_send_command_to_drone_respects_rejected_ack_body(self):
        """HTTP 200 with status=rejected must not be treated as accepted."""
        from command import send_command_to_drone

        drone = {'hw_id': 1, 'ip': '172.18.0.2'}
        command_data = {'missionType': '10', 'triggerTime': '0'}

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'status': 'rejected',
            'message': 'Drone failed pre-arm checks',
            'error_code': 'E202',
        }

        with patch('command.requests.post', return_value=mock_response):
            success, error, category = send_command_to_drone(drone, command_data, retries=1)

        assert success is False
        assert category == 'rejected'
        assert 'E202' in error

    def test_send_command_to_drone_normalizes_legacy_mission_names_to_numeric_payload(self):
        """Drone API payloads must use numeric mission codes even for legacy aliases."""
        from command import send_command_to_drone
        from src.enums import Mission

        drone = {'hw_id': 1, 'ip': '172.18.0.2'}
        command_data = {'missionType': 'RTL', 'triggerTime': 0}

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'status': 'accepted'}

        with patch('command.requests.post', return_value=mock_response) as mock_post:
            success, error, category = send_command_to_drone(drone, command_data, retries=1)

        assert success is True
        assert error == ""
        assert category == 'accepted'
        assert mock_post.call_args.kwargs['json']['missionType'] == str(Mission.RETURN_RTL.value)
        assert mock_post.call_args.kwargs['json']['triggerTime'] == '0'

    def test_send_command_to_drone_aborts_after_sync_dispatch_window_expires(self):
        """Synchronized missions should not be retried once the safe queue window has passed."""
        from command import send_command_to_drone
        from src.enums import Mission

        drone = {'hw_id': 1, 'ip': '172.18.0.2'}
        command_data = {
            'missionType': str(Mission.SWARM_TRAJECTORY.value),
            'triggerTime': '205',
        }

        with patch('command.time.time', return_value=201.0):
            with patch('command.requests.post') as mock_post:
                success, error, category = send_command_to_drone(drone, command_data, timeout=5, retries=3)

        assert success is False
        assert category == 'error'
        assert 'Missed synchronized dispatch window' in error
        mock_post.assert_not_called()

    def test_send_command_to_drone_caps_timeout_to_remaining_sync_window(self):
        """Last-chance synchronized dispatch attempts should not wait longer than the remaining safe window."""
        from command import send_command_to_drone
        from src.enums import Mission

        drone = {'hw_id': 1, 'ip': '172.18.0.2'}
        command_data = {
            'missionType': str(Mission.SWARM_TRAJECTORY.value),
            'triggerTime': '204',
        }

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'status': 'accepted'}

        with patch('command.time.time', return_value=198.5):
            with patch('command.requests.post', return_value=mock_response) as mock_post:
                success, error, category = send_command_to_drone(drone, command_data, timeout=5, retries=1)

        assert success is True
        assert error == ""
        assert category == 'accepted'
        assert mock_post.call_args.kwargs['timeout'] == pytest.approx(0.5, abs=1e-6)

    def test_send_commands_to_all_normalizes_rejected_drone_ids(self):
        """Rejected/error logging should not crash when config uses integer hw_id values."""
        from command import send_commands_to_all

        drones = [{'hw_id': 1, 'ip': '172.18.0.2'}]
        command_data = {'missionType': '10', 'triggerTime': '0'}

        with patch('command.send_command_to_drone', return_value=(False, 'E202: Not ready to arm', 'rejected')):
            results = send_commands_to_all(drones, command_data)

        assert results['success'] == 0
        assert results['rejected'] == 1
        assert '1' in results['results']
        assert results['results']['1']['category'] == 'rejected'

    def test_send_commands_to_selected_matches_string_targets_to_integer_hwids(self):
        """Selective command targeting should work with frontend string drone IDs."""
        from command import send_commands_to_selected

        drones = [
            {'hw_id': 1, 'ip': '172.18.0.2'},
            {'hw_id': 2, 'ip': '172.18.0.3'},
        ]
        command_data = {'missionType': '10', 'triggerTime': '0'}

        with patch('command.send_command_to_drone', return_value=(True, '', 'accepted')):
            results = send_commands_to_selected(drones, command_data, ['1'])

        assert results['total'] == 1
        assert results['success'] == 1
        assert '1' in results['results']

    def test_send_commands_to_all_short_circuits_targets_without_recent_heartbeat(self):
        """Offline targets should not delay dispatch when recent heartbeat data exists."""
        from command import send_commands_to_all

        now_ms = int(time.time() * 1000)
        drones = [
            {'hw_id': 1, 'ip': '172.18.0.2'},
            {'hw_id': 2, 'ip': '172.18.0.3'},
        ]
        command_data = {'missionType': '10', 'triggerTime': '0'}

        with patch('command.get_all_heartbeats', return_value={
            '1': {'timestamp': now_ms},
        }):
            with patch('command.send_command_to_drone', return_value=(True, '', 'accepted')) as mock_send:
                results = send_commands_to_all(drones, command_data)

        assert results['success'] == 1
        assert results['offline'] == 1
        assert results['total'] == 2
        assert mock_send.call_count == 1
        assert mock_send.call_args.args[0]['hw_id'] == 1
        assert results['results']['2']['category'] == 'offline'

    def test_send_commands_to_all_keeps_targets_when_no_recent_heartbeat_baseline_exists(self):
        """Do not short-circuit if the heartbeat layer has no current presence signal at all."""
        from command import send_commands_to_all

        now_ms = int(time.time() * 1000)
        stale_ms = now_ms - 60_000
        drones = [
            {'hw_id': 1, 'ip': '172.18.0.2'},
            {'hw_id': 2, 'ip': '172.18.0.3'},
        ]
        command_data = {'missionType': '10', 'triggerTime': '0'}

        with patch('command.get_all_heartbeats', return_value={
            '1': {'timestamp': stale_ms},
            '2': {'timestamp': stale_ms},
        }):
            with patch('command.send_command_to_drone', return_value=(True, '', 'accepted')) as mock_send:
                results = send_commands_to_all(drones, command_data)

        assert results['success'] == 2
        assert results['offline'] == 0
        assert mock_send.call_count == 2

    def test_probe_live_armability_for_drones_collects_blocked_and_unavailable(self):
        from command import probe_live_armability_for_drones

        drones = [
            {'hw_id': 1, 'ip': '172.18.0.2'},
            {'hw_id': 2, 'ip': '172.18.0.3'},
            {'hw_id': 3, 'ip': '172.18.0.4'},
        ]

        with patch('command.probe_live_armability_for_drone', side_effect=[
            {'drone_id': '1', 'category': 'ready', 'ready': True, 'summary': 'ok'},
            {'drone_id': '2', 'category': 'blocked', 'ready': False, 'summary': 'waiting for PX4 armability'},
            {'drone_id': '3', 'category': 'offline', 'ready': False, 'summary': 'probe unreachable'},
        ]):
            result = probe_live_armability_for_drones(drones)

        assert result['all_ready'] is False
        assert result['blocked_ids'] == ['2']
        assert result['unavailable_ids'] == ['3']

    def test_probe_live_armability_for_drone_uses_total_request_budget(self):
        from command import probe_live_armability_for_drone
        from src.mission_startup import calculate_live_armability_request_timeout

        drone = {'hw_id': 3, 'ip': '172.18.0.4'}
        response = Mock()
        response.raise_for_status = Mock()
        response.json.return_value = {
            'success': True,
            'ready': True,
            'summary': 'ready for mission startup',
        }

        params = Mock()
        params.LIVE_ARMABILITY_PROBE_CONNECT_TIMEOUT_SEC = 5.0
        params.LIVE_ARMABILITY_PROBE_TIMEOUT_SEC = 6.0
        params.LIVE_ARMABILITY_PROBE_HTTP_BUFFER_SEC = 2.0

        with patch('command.requests.get', return_value=response) as mock_get:
            with patch('command.Params', params):
                result = probe_live_armability_for_drone(drone)

        expected_timeout = calculate_live_armability_request_timeout(params=params)
        assert result['ready'] is True
        assert mock_get.call_args.kwargs['timeout'] == pytest.approx(expected_timeout)


# ============================================================================
# Command Validation Tests
# ============================================================================

class TestCommandValidation:
    """Test command validation in drone_api_server"""

    @pytest.fixture
    def mock_drone_config(self):
        """Create mock drone config"""
        config = Mock()
        config.hw_id = '1'
        config.pos_id = 0
        config.state = 0  # IDLE
        config.mission = 0  # NONE
        config.is_ready_to_arm = True
        config.current_command_id = None
        return config

    @pytest.fixture
    def mock_params(self):
        """Create mock params"""
        params = Mock()
        params.max_takeoff_alt = 50
        params.drone_api_port = 7070
        return params

    @pytest.fixture
    def api_server(self, mock_params, mock_drone_config):
        """Create DroneAPIServer instance"""
        from src.drone_api_server import DroneAPIServer
        server = DroneAPIServer(mock_params, mock_drone_config)
        return server

    def test_validate_missing_mission_type(self, api_server):
        """Test validation fails for missing missionType"""
        result = api_server._validate_command({
            'triggerTime': '0'
        })
        assert not result['valid']
        assert 'E100' in result['error_code']

    def test_validate_missing_trigger_time(self, api_server):
        """Test validation fails for missing triggerTime"""
        result = api_server._validate_command({
            'missionType': '10'
        })
        assert not result['valid']
        assert 'E102' in result['error_code']

    def test_validate_invalid_mission_type(self, api_server):
        """Test validation fails for unknown mission type"""
        result = api_server._validate_command({
            'missionType': '9999',
            'triggerTime': '0'
        })
        assert not result['valid']
        assert 'E101' in result['error_code']

    def test_validate_invalid_mission_type_format(self, api_server):
        """Test validation fails for non-numeric mission type"""
        result = api_server._validate_command({
            'missionType': 'not_a_number',
            'triggerTime': '0'
        })
        assert not result['valid']
        assert 'E107' in result['error_code']

    def test_validate_negative_trigger_time(self, api_server):
        """Test validation fails for negative trigger time"""
        result = api_server._validate_command({
            'missionType': '10',
            'triggerTime': '-1'
        })
        assert not result['valid']
        assert 'E103' in result['error_code']

    def test_validate_invalid_altitude(self, api_server):
        """Test validation fails for invalid takeoff altitude"""
        result = api_server._validate_command({
            'missionType': '10',
            'triggerTime': '0',
            'takeoff_altitude': '-5'
        })
        assert not result['valid']
        assert 'E104' in result['error_code']

    def test_validate_altitude_exceeds_max(self, api_server):
        """Test validation fails for altitude exceeding maximum"""
        result = api_server._validate_command({
            'missionType': '10',
            'triggerTime': '0',
            'takeoff_altitude': '100'  # Exceeds max of 50
        })
        assert not result['valid']
        assert 'E104' in result['error_code']

    def test_validate_success(self, api_server):
        """Test validation succeeds for valid command"""
        result = api_server._validate_command({
            'missionType': '10',
            'triggerTime': '0',
            'takeoff_altitude': '10'
        })
        assert result['valid']

    def test_check_state_executing(self, api_server):
        """Test state check fails during execution"""
        api_server.drone_config.state = 2  # MISSION_EXECUTING

        result = api_server._check_state_preconditions(mission_type=10)  # TAKE_OFF
        assert not result['valid']
        assert 'E203' in result['error_code']

    def test_check_state_emergency_allowed(self, api_server):
        """Test emergency commands allowed during execution"""
        api_server.drone_config.state = 2  # MISSION_EXECUTING

        result = api_server._check_state_preconditions(mission_type=105)  # KILL_TERMINATE
        assert result['valid']

    def test_check_state_not_ready_to_arm(self, api_server):
        """Test state check fails when not ready to arm"""
        api_server.drone_config.is_ready_to_arm = False

        result = api_server._check_state_preconditions(mission_type=10)  # TAKE_OFF
        assert not result['valid']
        assert 'E202' in result['error_code']


# ============================================================================
# Schema Validation Tests
# ============================================================================

class TestSchemas:
    """Test Pydantic schema validation"""

    def test_submit_command_request(self):
        """Test SubmitCommandRequest schema"""
        from schemas import SubmitCommandRequest

        # Valid request
        request = SubmitCommandRequest(
            missionType=10,
            triggerTime=0,
            takeoff_altitude=10.0
        )
        assert request.missionType == 10

        # Invalid altitude (negative)
        with pytest.raises(Exception):
            SubmitCommandRequest(
                missionType=10,
                takeoff_altitude=-5.0
            )

    def test_submit_command_response(self):
        """Test SubmitCommandResponse schema"""
        from schemas import SubmitCommandResponse

        response = SubmitCommandResponse(
            success=True,  # Required field
            command_id="abc-123",
            status="submitted",
            mission_type=10,
            mission_name="TAKE_OFF",
            target_drones=["1", "2"],
            submitted_count=2,
            tracking_timeout_ms=90000,
            message="Command submitted",
            timestamp=int(time.time() * 1000)
        )
        assert response.success == True
        assert response.command_id == "abc-123"
        assert response.submitted_count == 2
        assert response.tracking_timeout_ms == 90000

    def test_command_status_response(self):
        """Test CommandStatusResponse schema"""
        from schemas import (
            AckSummary,
            CommandOutcome,
            CommandPhase,
            CommandProgressSummary,
            CommandStatus,
            CommandStatusResponse,
            ExecutionSummary,
        )

        response = CommandStatusResponse(
            command_id="abc-123",
            mission_type=10,
            mission_name="TAKE_OFF",
            target_drones=["1"],
            status=CommandStatus.COMPLETED,
            phase=CommandPhase.TERMINAL,
            outcome=CommandOutcome.COMPLETED,
            created_at=int(time.time() * 1000),
            updated_at=int(time.time() * 1000),
            acks=AckSummary(
                expected=1, received=1, accepted=1, rejected=0
            ),
            executions=ExecutionSummary(
                expected=1, started=1, active=0, received=1, succeeded=1, failed=0
            ),
            progress=CommandProgressSummary(
                stage="completed",
                label="Completed",
                message="Completed successfully on 1/1 accepted drone.",
                ack_pending=0,
                accepted=1,
                execution_pending=0,
                active=0,
                completed=1,
                remaining=0,
            ),
        )
        assert response.status == CommandStatus.COMPLETED
        assert response.phase == CommandPhase.TERMINAL

    def test_execution_report_request(self):
        """Test ExecutionReportRequest schema"""
        from schemas import ExecutionReportRequest

        report = ExecutionReportRequest(
            command_id="abc-123",
            hw_id="1",
            success=False,
            error_message="Script failed",
            exit_code=1,
            duration_ms=5000
        )
        assert report.success == False
        assert report.exit_code == 1


# ============================================================================
# Integration Tests (require mock server)
# ============================================================================

class TestCommandEndpointIntegration:
    """Integration tests for command endpoints"""

    @pytest.fixture
    def mock_config_data(self):
        """Mock drone configuration"""
        return [
            {'pos_id': 0, 'hw_id': '1', 'ip': '192.168.1.101'},
            {'pos_id': 1, 'hw_id': '2', 'ip': '192.168.1.102'},
        ]

    @pytest.mark.skip(reason="Requires full server setup - run manually")
    @pytest.mark.asyncio
    async def test_submit_and_track_command(self, mock_config_data):
        """Test full command submission and tracking flow"""
        # This would test:
        # 1. POST /submit_command
        # 2. GET /command/{id}
        # 3. Wait for ACKs
        # 4. Verify status progression
        pass


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x"])
