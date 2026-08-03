# tests/test_drone_setup.py
"""
DroneSetup and Mission Execution Tests
======================================
Tests for mission scheduling, execution, and state management.
These are critical tests for the drone's mission control system.
"""

import os
import pytest
import asyncio
import threading
import time
from unittest.mock import AsyncMock, Mock, patch

# Path configuration is handled by conftest.py

from src.enums import Mission, State
from src.drone_config import DroneConfig


# ============================================================================
# Test: DroneSetup Initialization
# ============================================================================

@pytest.mark.unit
@pytest.mark.mission
class TestDroneSetupInitialization:
    """Test DroneSetup initialization"""

    def test_drone_setup_import(self):
        """Test DroneSetup can be imported"""
        from src.drone_setup import DroneSetup
        assert DroneSetup is not None

    def test_drone_setup_requires_params(self):
        """Test DroneSetup requires params argument"""
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = Mock()
        drone_config.trigger_time = 0
        drone_config.mission = 0

        # Should initialize without error
        setup = DroneSetup(params, drone_config)
        assert setup is not None

    def test_drone_setup_validates_trigger_sooner_seconds(self):
        """Test DroneSetup validates trigger_sooner_seconds"""
        from src.drone_setup import DroneSetup

        params = Mock()
        del params.trigger_sooner_seconds  # Remove the attribute

        drone_config = Mock()
        drone_config.trigger_time = 0
        drone_config.mission = 0

        with pytest.raises(AttributeError):
            DroneSetup(params, drone_config)

    def test_drone_setup_has_mission_handlers(self):
        """Test DroneSetup has mission handlers dict"""
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = Mock()
        drone_config.trigger_time = 0
        drone_config.mission = 0

        setup = DroneSetup(params, drone_config)

        assert hasattr(setup, 'mission_handlers')
        assert isinstance(setup.mission_handlers, dict)

    def test_mission_handlers_cover_all_missions(self):
        """Test all mission types have handlers"""
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = Mock()
        drone_config.trigger_time = 0
        drone_config.mission = 0

        setup = DroneSetup(params, drone_config)

        # Check key mission types are handled
        assert Mission.NONE.value in setup.mission_handlers
        assert Mission.DRONE_SHOW_FROM_CSV.value in setup.mission_handlers
        assert Mission.TAKE_OFF.value in setup.mission_handlers
        assert Mission.LAND.value in setup.mission_handlers
        assert Mission.RETURN_RTL.value in setup.mission_handlers
        assert Mission.KILL_TERMINATE.value in setup.mission_handlers
        assert Mission.SMART_SWARM.value in setup.mission_handlers
        assert Mission.PRECISION_MOVE.value in setup.mission_handlers


# ============================================================================
# Test: Mission State Machine
# ============================================================================

def create_mock_drone_config():
    """Create a properly initialized mock DroneConfig"""
    drone_config = Mock(spec=DroneConfig)
    drone_config.state = State.IDLE.value
    drone_config.mission = Mission.NONE.value
    drone_config.last_mission = Mission.NONE.value
    drone_config.trigger_time = 0
    drone_config.config = {'pos_id': 1, 'hw_id': '1'}
    drone_config.hw_id = '1'
    drone_config.is_armed = False
    drone_config.is_ready_to_arm = True
    drone_config.current_command_id = None
    drone_config.ground_test_request_file = None
    drone_config.auto_global_origin = None
    drone_config.use_global_setpoints = None
    return drone_config


@pytest.mark.unit
@pytest.mark.mission
class TestMissionStateMachine:
    """Test mission state transitions"""

    def test_initial_state_is_idle(self):
        """Test initial state is IDLE"""
        drone_config = create_mock_drone_config()

        assert drone_config.state == State.IDLE.value

    def test_state_transitions_to_ready(self):
        """Test state can transition to MISSION_READY"""
        drone_config = create_mock_drone_config()

        drone_config.state = State.MISSION_READY.value

        assert drone_config.state == State.MISSION_READY.value

    def test_state_transitions_to_executing(self):
        """Test state can transition to MISSION_EXECUTING"""
        drone_config = create_mock_drone_config()

        drone_config.state = State.MISSION_EXECUTING.value

        assert drone_config.state == State.MISSION_EXECUTING.value

    def test_state_transitions_back_to_idle(self):
        """Test state transitions back to IDLE after mission"""
        drone_config = create_mock_drone_config()

        # Mission complete
        drone_config.state = State.MISSION_EXECUTING.value
        drone_config.state = State.IDLE.value

        assert drone_config.state == State.IDLE.value

    def test_mission_value_tracking(self):
        """Test mission value is tracked correctly"""
        drone_config = create_mock_drone_config()

        drone_config.mission = Mission.TAKE_OFF.value

        assert drone_config.mission == Mission.TAKE_OFF.value


# ============================================================================
# Test: Schedule Mission
# ============================================================================

@pytest.mark.unit
@pytest.mark.mission
class TestScheduleMission:
    """Test schedule_mission functionality"""

    @pytest.mark.asyncio
    async def test_schedule_mission_skips_when_executing(self):
        """Test schedule_mission skips when already executing"""
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = Mock()
        drone_config.state = State.MISSION_EXECUTING.value
        drone_config.mission = Mission.TAKE_OFF.value
        drone_config.trigger_time = 0

        setup = DroneSetup(params, drone_config)

        # Should skip without calling handler
        await setup.schedule_mission()

        # State should remain unchanged
        assert drone_config.state == State.MISSION_EXECUTING.value

    @pytest.mark.asyncio
    async def test_schedule_mission_calls_handler(self):
        """Test schedule_mission calls appropriate handler"""
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = Mock()
        drone_config.state = State.MISSION_READY.value
        drone_config.mission = Mission.NONE.value
        drone_config.trigger_time = int(time.time())

        setup = DroneSetup(params, drone_config)

        # Replace handler with mock
        mock_handler = AsyncMock(return_value=(True, "Success"))
        setup.mission_handlers[Mission.NONE.value] = mock_handler

        await setup.schedule_mission()

        mock_handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_schedule_mission_calculates_earlier_trigger(self):
        """Test schedule_mission calculates earlier trigger time"""
        trigger_time = int(time.time()) + 10
        trigger_sooner = 4

        earlier_trigger = trigger_time - trigger_sooner

        assert earlier_trigger == trigger_time - 4

    @pytest.mark.asyncio
    async def test_scheduler_holds_shared_state_transaction_through_handler(self):
        """An HTTP override cannot interleave after handler selection."""
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = create_mock_drone_config()
        drone_config.state = State.MISSION_READY.value
        drone_config.mission = Mission.TAKE_OFF.value
        drone_config.current_command_id = "takeoff-old"
        drone_config.trigger_time = int(time.time())
        setup = DroneSetup(params, drone_config)

        handler_started = asyncio.Event()
        release_handler = asyncio.Event()
        override_attempted = threading.Event()
        override_acquired = threading.Event()

        async def controlled_handler(*_args):
            handler_started.set()
            await release_handler.wait()
            return True, "handler completed"

        def attempt_override():
            override_attempted.set()
            setup.command_state_transaction_lock.acquire()
            try:
                override_acquired.set()
                drone_config.current_command_id = "land-new"
                drone_config.mission = Mission.LAND.value
                drone_config.state = State.MISSION_READY.value
            finally:
                setup.command_state_transaction_lock.release()

        setup.mission_handlers[Mission.TAKE_OFF.value] = controlled_handler
        scheduler_task = asyncio.create_task(setup.schedule_mission())
        await asyncio.wait_for(handler_started.wait(), timeout=1)
        override_task = asyncio.create_task(asyncio.to_thread(attempt_override))
        await asyncio.to_thread(override_attempted.wait, 1)
        await asyncio.sleep(0.02)

        assert not override_acquired.is_set()
        assert drone_config.current_command_id == "takeoff-old"

        release_handler.set()
        await asyncio.wait_for(scheduler_task, timeout=1)
        await asyncio.wait_for(override_task, timeout=1)
        assert override_acquired.is_set()
        assert drone_config.current_command_id == "land-new"

    @pytest.mark.asyncio
    async def test_scheduler_releases_state_lock_before_slow_gcs_start_callback(self):
        """GCS callback latency cannot block a later safety-command transaction."""
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        params.COMMAND_IDEMPOTENCY_HISTORY_SEC = 1800
        params.COMMAND_IDEMPOTENCY_MAX_HISTORY = 256
        drone_config = create_mock_drone_config()
        drone_config.state = State.MISSION_READY.value
        drone_config.mission = Mission.DRONE_SHOW_FROM_CSV.value
        drone_config.current_command_id = "show-old"
        drone_config.trigger_time = int(time.time())
        setup = DroneSetup(params, drone_config)
        process = Mock(pid=8765, returncode=None)
        report_started = asyncio.Event()
        release_report = asyncio.Event()

        async def slow_start_report(**_kwargs):
            report_started.set()
            await release_report.wait()

        async def launch_handler(*_args):
            setup._prepare_mission_start("test show")
            return await setup.execute_mission_script("drone_show.py", "")

        setup._report_execution_start_to_gcs = slow_start_report
        setup._monitor_script_process = AsyncMock(return_value=None)
        setup.mission_handlers[Mission.DRONE_SHOW_FROM_CSV.value] = launch_handler

        with patch("src.drone_setup.os.path.isfile", return_value=True), patch(
            "src.drone_setup.asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ):
            await asyncio.wait_for(setup.schedule_mission(), timeout=1)
            await asyncio.wait_for(report_started.wait(), timeout=1)

            # The callback is still blocked, but command acceptance can take
            # the shared lock immediately.
            assert setup.command_state_transaction_lock.acquire(blocking=False)
            setup.command_state_transaction_lock.release()
            release_report.set()
            await asyncio.sleep(0)


# ============================================================================
# Test: Mission Handlers
# ============================================================================

@pytest.mark.unit
@pytest.mark.mission
class TestMissionHandlers:
    """Test individual mission handlers"""

    @pytest.mark.asyncio
    async def test_no_mission_handler(self):
        """Test _handle_no_mission returns correctly"""
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = Mock()
        drone_config.state = State.IDLE.value
        drone_config.mission = Mission.NONE.value
        drone_config.trigger_time = 0

        setup = DroneSetup(params, drone_config)

        result = await setup._handle_no_mission(int(time.time()), int(time.time()))

        assert result[0] is False
        assert "No mission" in result[1]

    @pytest.mark.asyncio
    async def test_unknown_mission_handler(self):
        """Test _handle_unknown_mission returns correctly"""
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = Mock()
        drone_config.state = State.IDLE.value
        drone_config.mission = 999  # Unknown
        drone_config.trigger_time = 0

        setup = DroneSetup(params, drone_config)

        result = await setup._handle_unknown_mission(int(time.time()), int(time.time()))

        assert result[0] is False
        assert "Unknown" in result[1]

    @pytest.mark.asyncio
    async def test_takeoff_handler_checks_state(self):
        """Test takeoff handler checks state is MISSION_READY"""
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = Mock()
        drone_config.state = State.IDLE.value  # Not ready
        drone_config.mission = Mission.TAKE_OFF.value
        drone_config.trigger_time = int(time.time())

        setup = DroneSetup(params, drone_config)

        # Should not execute because state is not MISSION_READY
        result = await setup._execute_takeoff(int(time.time()), int(time.time()))

        assert result[0] is False

    @pytest.mark.asyncio
    async def test_drone_show_handler_checks_conditions(self):
        """Test drone show handler checks all conditions"""
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = Mock()
        drone_config.state = State.IDLE.value  # Not ready
        drone_config.mission = Mission.DRONE_SHOW_FROM_CSV.value
        drone_config.trigger_time = int(time.time()) + 100  # Future

        setup = DroneSetup(params, drone_config)

        result = await setup._execute_standard_drone_show(int(time.time()), int(time.time()) + 50)

        assert result[0] is False

    def test_custom_csv_action_forces_local_mode(self):
        """Custom CSV missions must not inherit global/origin-corrected flags."""
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        params.AUTO_GLOBAL_ORIGIN_MODE = True
        params.USE_GLOBAL_SETPOINTS = True

        drone_config = create_mock_drone_config()
        drone_config.auto_global_origin = True
        drone_config.use_global_setpoints = True

        setup = DroneSetup(params, drone_config)

        action = setup._build_offboard_action(
            trigger_time=1234567890,
            mission_type=Mission.CUSTOM_CSV_DRONE_SHOW.value,
            custom_csv='active.csv',
        )

        assert '--custom_csv=active.csv' in action
        assert '--mission_type 3' in action
        assert '--auto_global_origin False' in action
        assert '--use_global_setpoints False' in action


# ============================================================================
# Test: Process Management
# ============================================================================

@pytest.mark.unit
@pytest.mark.mission
class TestProcessManagement:
    """Test mission process management"""

    def test_running_processes_initialized(self):
        """Test running_processes dict is initialized"""
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = Mock()
        drone_config.trigger_time = 0
        drone_config.mission = 0

        setup = DroneSetup(params, drone_config)

        assert hasattr(setup, 'running_processes')
        assert isinstance(setup.running_processes, dict)

    def test_process_lock_initialized(self):
        """Test process lock is initialized"""
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = Mock()
        drone_config.trigger_time = 0
        drone_config.mission = 0

        setup = DroneSetup(params, drone_config)

        assert hasattr(setup, 'process_lock')

    @pytest.mark.asyncio
    async def test_terminate_all_clears_processes(self):
        """Test terminate_all clears running processes"""
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = Mock()
        drone_config.trigger_time = 0
        drone_config.mission = 0

        setup = DroneSetup(params, drone_config)

        # Add a mock process
        mock_process = Mock()
        mock_process.returncode = None
        mock_process.pid = 12345
        mock_process.terminate = Mock()
        mock_process.kill = Mock()

        async def mock_wait():
            mock_process.returncode = 0

        mock_process.wait = mock_wait

        setup.running_processes['test_script.py'] = mock_process

        await setup.terminate_all_running_processes()

        assert len(setup.running_processes) == 0

    @pytest.mark.asyncio
    async def test_recovery_preemption_force_stops_stuck_controller_within_budget(self):
        """LAND/RTL/HOLD do not inherit the routine five-second shutdown grace."""
        from src.drone_setup import DroneSetup, ProcessStopMode, RunningMissionProcess

        params = Mock()
        params.trigger_sooner_seconds = 4
        params.RECOVERY_PROCESS_STOP_GRACE_SEC = 0.02
        drone_config = create_mock_drone_config()
        setup = DroneSetup(params, drone_config)

        process = Mock(pid=4321, returncode=None)
        process.terminate = Mock()
        process.kill = Mock()

        async def wait_forever():
            await asyncio.Event().wait()

        process.wait = wait_forever
        record = RunningMissionProcess(
            process_key="show.py:old",
            script_name="show.py",
            process=process,
            command_id="old",
        )
        setup.running_processes[record.process_key] = record
        setup._active_mission_owner_token = record.ownership_token

        started = time.monotonic()
        summary = await setup.terminate_all_running_processes(
            reset_state=False,
            mode=ProcessStopMode.RECOVERY,
        )
        elapsed = time.monotonic() - started

        assert elapsed < 0.2
        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()
        assert summary.killed == 1
        assert summary.unresolved == 0
        assert record.superseded is True
        assert not setup.running_processes

    @pytest.mark.asyncio
    async def test_emergency_preemption_skips_grace_period(self):
        """Emergency Stop signals the old controller immediately."""
        from src.drone_setup import DroneSetup, ProcessStopMode, RunningMissionProcess

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = create_mock_drone_config()
        setup = DroneSetup(params, drone_config)
        process = Mock(pid=4321, returncode=None)
        process.terminate = Mock()
        process.kill = Mock()
        record = RunningMissionProcess(
            process_key="show.py:old",
            script_name="actions.py",
            process=process,
            mission_type=Mission.TAKE_OFF.value,
        )
        setup.running_processes[record.process_key] = record

        summary = await setup.terminate_all_running_processes(
            reset_state=False,
            mode=ProcessStopMode.EMERGENCY,
        )

        process.terminate.assert_not_called()
        process.kill.assert_called_once_with()
        assert summary.killed == 1
        assert summary.unresolved == 0
        assert summary.cleanup_unconfirmed == 1
        assert record.forced_kill_cleanup_unconfirmed is True
        assert record.forced_stop_mode == "emergency"

    def test_takeoff_and_ground_test_receive_canonical_cleanup_grace(self):
        from src.action_safety import ACTION_PROCESS_CLEANUP_GRACE_SEC
        from src.drone_setup import DroneSetup, ProcessStopMode, RunningMissionProcess

        params = Mock()
        params.trigger_sooner_seconds = 4
        params.RECOVERY_PROCESS_STOP_GRACE_SEC = 0.02
        setup = DroneSetup(params, create_mock_drone_config())

        for mission_type in (Mission.TAKE_OFF.value, Mission.TEST.value):
            record = RunningMissionProcess(
                process_key=f"actions.py:{mission_type}",
                script_name="actions.py",
                process=Mock(),
                mission_type=mission_type,
            )
            assert setup._process_stop_grace_seconds(
                ProcessStopMode.RECOVERY,
                record,
            ) == ACTION_PROCESS_CLEANUP_GRACE_SEC
            assert setup._process_stop_grace_seconds(
                ProcessStopMode.EMERGENCY,
                record,
            ) == 0.0

    @pytest.mark.asyncio
    async def test_monitor_reports_superseded_process_without_reset(self):
        """Superseded mission processes should skip state reset but still close the command tracker."""
        from src.command_execution_contract import DroneExecutionOutcome
        from src.drone_setup import DroneSetup, RunningMissionProcess

        class FakeProcess:
            pid = 1234
            returncode = 0

            async def communicate(self):
                return (b'ok', b'')

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = Mock()
        drone_config.trigger_time = 0
        drone_config.mission = 0

        setup = DroneSetup(params, drone_config)
        setup._reset_mission_state = Mock()
        setup._report_execution_to_gcs = AsyncMock()

        record = RunningMissionProcess(
            process_key='drone_show.py:test',
            script_name='drone_show.py',
            process=FakeProcess(),
            command_id='cmd-1',
            superseded=True,
        )
        setup.running_processes[record.process_key] = record

        await setup._monitor_script_process(record)

        setup._reset_mission_state.assert_not_called()
        setup._report_execution_to_gcs.assert_awaited_once()
        report_kwargs = setup._report_execution_to_gcs.await_args.kwargs
        assert report_kwargs["command_id"] == "cmd-1"
        assert report_kwargs["success"] is False
        assert report_kwargs["outcome"] == DroneExecutionOutcome.SUPERSEDED
        assert report_kwargs["error_message"] == "Superseded by a newer command before completion"
        assert report_kwargs["exit_code"] == 0
        assert report_kwargs["script_output"] == "Legacy stdout (diagnostic only): ok"
        assert record.process_key not in setup.running_processes

    @pytest.mark.asyncio
    async def test_monitor_reports_override_that_wins_terminal_retirement_race(self):
        """Supersede classification is decided inside the state transaction."""
        from src.drone_setup import DroneSetup, RunningMissionProcess

        class FakeProcess:
            returncode = 0

            async def communicate(self):
                return b"old process completed", b""

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = create_mock_drone_config()
        drone_config.mission = Mission.HOLD.value
        drone_config.state = State.MISSION_EXECUTING.value
        setup = DroneSetup(params, drone_config)
        record = RunningMissionProcess(
            process_key="actions.py:old-race",
            script_name="actions.py",
            process=FakeProcess(),
            command_id="old-race",
            mission_type=Mission.HOLD.value,
        )
        setup.running_processes[record.process_key] = record
        setup._active_mission_owner_token = record.ownership_token
        setup._reset_mission_state = Mock()
        setup._report_execution_to_gcs = AsyncMock()

        setup.command_state_transaction_lock.acquire()
        try:
            monitor_task = asyncio.create_task(setup._monitor_script_process(record))
            await asyncio.sleep(0.02)
            record.superseded = True
            drone_config.current_command_id = "replacement"
            drone_config.mission = Mission.LAND.value
            drone_config.state = State.MISSION_READY.value
        finally:
            setup.command_state_transaction_lock.release()

        await asyncio.wait_for(monitor_task, timeout=1)

        setup._reset_mission_state.assert_not_called()
        report = setup._report_execution_to_gcs.await_args.kwargs
        assert report["success"] is False
        assert report["error_message"] == "Superseded by a newer command before completion"

    @pytest.mark.asyncio
    async def test_monitor_reports_cleanup_unconfirmed_override_as_failed(self):
        """A force-stopped action must not look like a safely superseded command."""
        from src.command_execution_contract import (
            DroneExecutionOutcome,
            is_legacy_superseded_execution_error,
        )
        from src.drone_setup import DroneSetup, RunningMissionProcess

        process = Mock(returncode=-9)
        process.communicate = AsyncMock(return_value=(b"", b""))
        setup = DroneSetup(Mock(trigger_sooner_seconds=4), create_mock_drone_config())
        record = RunningMissionProcess(
            process_key="actions.py:unsafe-stop",
            script_name="actions.py",
            process=process,
            command_id="unsafe-stop",
            superseded=True,
            forced_kill_cleanup_unconfirmed=True,
        )
        setup.running_processes[record.process_key] = record
        setup._active_mission_owner_token = record.ownership_token
        setup._reset_mission_state = Mock()
        setup._report_execution_to_gcs = AsyncMock()

        await setup._monitor_script_process(record)

        report = setup._report_execution_to_gcs.await_args.kwargs
        assert report["outcome"] == DroneExecutionOutcome.FAILED
        assert "cleanup could be confirmed" in report["error_message"]
        assert is_legacy_superseded_execution_error(report["error_message"]) is False


# ============================================================================
# Test: Mission State Reset
# ============================================================================

@pytest.mark.unit
@pytest.mark.mission
class TestMissionStateReset:
    """Test mission state reset functionality"""

    def test_reset_sets_mission_none(self):
        """Test _reset_mission_state sets mission to NONE"""
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = Mock()
        drone_config.trigger_time = 0
        drone_config.mission = Mission.TAKE_OFF.value
        drone_config.state = State.MISSION_EXECUTING.value

        setup = DroneSetup(params, drone_config)

        setup._reset_mission_state(success=True)

        assert drone_config.mission == Mission.NONE.value

    def test_reset_sets_state_idle(self):
        """Test _reset_mission_state sets state to IDLE"""
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = Mock()
        drone_config.trigger_time = 0
        drone_config.mission = Mission.TAKE_OFF.value
        drone_config.state = State.MISSION_EXECUTING.value

        setup = DroneSetup(params, drone_config)

        setup._reset_mission_state(success=False)

        assert drone_config.state == State.IDLE.value


# ============================================================================
# Test: Script Execution
# ============================================================================

@pytest.mark.unit
@pytest.mark.mission
class TestScriptExecution:
    """Test mission script execution"""

    def test_get_script_path(self):
        """Test _get_script_path returns correct path"""
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = Mock()
        drone_config.trigger_time = 0
        drone_config.mission = 0

        setup = DroneSetup(params, drone_config)

        path = setup._get_script_path('drone_show.py')

        assert 'drone_show.py' in path

    @pytest.mark.asyncio
    async def test_execute_mission_script_checks_file_exists(self):
        """Test execute_mission_script checks file exists"""
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = Mock()
        drone_config.trigger_time = 0
        drone_config.mission = 0

        setup = DroneSetup(params, drone_config)

        # Try to execute non-existent script
        result = await setup.execute_mission_script('nonexistent_script.py', '')

        assert result[0] is False
        assert 'not found' in result[1].lower()

    @pytest.mark.asyncio
    async def test_execute_mission_script_falls_back_to_popen(self):
        """Test execute_mission_script falls back when asyncio subprocess support is unavailable"""
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = Mock()
        drone_config.trigger_time = 0
        drone_config.mission = 0

        setup = DroneSetup(params, drone_config)
        fallback_process = Mock()
        fallback_process.pid = 1234
        fallback_process.returncode = None

        def fake_create_task(coro):
            coro.close()
            return Mock()

        with patch('src.drone_setup.os.path.isfile', return_value=True), \
             patch('src.drone_setup.asyncio.create_subprocess_exec', AsyncMock(side_effect=NotImplementedError)), \
             patch('src.drone_setup.subprocess.Popen', return_value=fallback_process) as mock_popen, \
             patch('src.drone_setup.asyncio.create_task', side_effect=fake_create_task), \
             patch('src.drone_setup.logger') as mock_logger:
            result = await setup.execute_mission_script('actions.py', '--action=takeoff')

        assert result[0] is True
        assert len(setup.running_processes) == 1
        process_record = next(iter(setup.running_processes.values()))
        assert process_record.script_name == 'actions.py'
        assert process_record.process is fallback_process
        assert process_record.process_group_owned is True
        mock_popen.assert_called_once()
        assert mock_popen.call_args.kwargs["start_new_session"] is True
        mock_logger.warning.assert_any_call(
            "Async subprocess execution is unavailable. Falling back to subprocess.Popen for 'actions.py'."
        )

    @pytest.mark.asyncio
    async def test_execute_mission_script_captures_command_id_in_process_record(self):
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        params.COMMAND_IDEMPOTENCY_HISTORY_SEC = 1800
        params.COMMAND_IDEMPOTENCY_MAX_HISTORY = 256
        drone_config = create_mock_drone_config()
        drone_config.current_command_id = "cmd-123"

        setup = DroneSetup(params, drone_config)
        process = Mock()
        process.pid = 4321
        process.returncode = None

        def fake_create_task(coro):
            coro.close()
            return Mock()

        with patch('src.drone_setup.os.path.isfile', return_value=True), \
             patch('src.drone_setup.asyncio.create_subprocess_exec', AsyncMock(return_value=process)) as mock_spawn, \
             patch('src.drone_setup.asyncio.create_task', side_effect=fake_create_task):
            result = await setup.execute_mission_script('actions.py', '--action=hold')

        assert result == (True, "Started mission script 'actions.py' asynchronously.")
        assert drone_config.current_command_id is None
        assert len(setup.running_processes) == 1
        process_record = next(iter(setup.running_processes.values()))
        assert process_record.command_id == "cmd-123"
        assert process_record.process_key.endswith("cmd-123")
        assert process_record.script_name == "actions.py"
        assert process_record.process_group_owned is True
        assert mock_spawn.await_args.kwargs["start_new_session"] is True
        lifecycle = setup.get_recent_command_record("cmd-123")
        assert lifecycle is not None
        assert lifecycle["phase"] == "executing"
        assert lifecycle["state"] == State.MISSION_EXECUTING.value

    @pytest.mark.asyncio
    async def test_execute_reserves_launching_lifecycle_before_subprocess_creation(self):
        """Duplicate lookup sees accepted ownership during the detach/spawn gap."""
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        params.COMMAND_IDEMPOTENCY_HISTORY_SEC = 1800
        params.COMMAND_IDEMPOTENCY_MAX_HISTORY = 256
        drone_config = create_mock_drone_config()
        drone_config.current_command_id = "cmd-launch-gap"
        drone_config.mission = Mission.TAKE_OFF.value
        drone_config.state = State.MISSION_EXECUTING.value
        drone_config.trigger_time = 12345
        setup = DroneSetup(params, drone_config)
        process = Mock(pid=4567, returncode=None)

        async def inspect_lifecycle_before_spawn(*_args, **_kwargs):
            lifecycle = setup.get_recent_command_record("cmd-launch-gap")
            assert lifecycle is not None
            assert lifecycle["phase"] == "launching"
            assert lifecycle["mission_type"] == Mission.TAKE_OFF.value
            assert lifecycle["trigger_time"] == 12345
            return process

        def discard_monitor(coro):
            coro.close()
            return Mock()

        with patch("src.drone_setup.os.path.isfile", return_value=True), patch(
            "src.drone_setup.asyncio.create_subprocess_exec",
            side_effect=inspect_lifecycle_before_spawn,
        ), patch("src.drone_setup.asyncio.create_task", side_effect=discard_monitor):
            result = await setup.execute_mission_script("drone_show.py", "")

        assert result[0] is True

    @pytest.mark.asyncio
    async def test_stale_scheduler_claim_cannot_detach_replacement_command(self):
        """A delayed old handler cannot launch under a newer command identity."""
        from src.drone_setup import AcceptedCommandClaim, DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = create_mock_drone_config()
        drone_config.current_command_id = "land-new"
        drone_config.mission = Mission.LAND.value
        drone_config.state = State.MISSION_READY.value
        setup = DroneSetup(params, drone_config)
        setup._active_scheduler_claim = AcceptedCommandClaim(
            command_id="takeoff-old",
            mission_type=Mission.TAKE_OFF.value,
        )

        with patch("src.drone_setup.asyncio.create_subprocess_exec", AsyncMock()) as spawn:
            success, message = await setup.execute_mission_script(
                "actions.py",
                "--action=takeoff",
            )

        assert success is False
        assert "ownership changed" in message.lower()
        assert drone_config.current_command_id == "land-new"
        assert drone_config.mission == Mission.LAND.value
        assert drone_config.state == State.MISSION_READY.value
        spawn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_execute_mission_script_coerces_list_args_to_strings(self):
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = create_mock_drone_config()

        setup = DroneSetup(params, drone_config)
        process = Mock()
        process.pid = 5678
        process.returncode = None

        def fake_create_task(coro):
            coro.close()
            return Mock()

        with patch('src.drone_setup.os.path.isfile', return_value=True), \
             patch('src.drone_setup.asyncio.create_subprocess_exec', AsyncMock(return_value=process)) as mock_exec, \
             patch('src.drone_setup.asyncio.create_task', side_effect=fake_create_task):
            result = await setup.execute_mission_script(
                'quickscout_mission.py',
                ['--mission-id', 'mission-1', '--hw-id', 1],
            )

        assert result == (True, "Started mission script 'quickscout_mission.py' asynchronously.")
        called_command = list(mock_exec.await_args.args)
        assert called_command[2:] == ['--mission-id', 'mission-1', '--hw-id', '1']


@pytest.mark.unit
@pytest.mark.mission
class TestActionMissionHandlerRouting:
    """Representative action and script handlers should all use the shared launcher."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("handler_name", "expected_mission", "expected_script", "expected_action", "interrupt_mode"),
        [
            ("_execute_land", "Land Mission", "actions.py", "--action=land", "recovery"),
            ("_execute_return_rtl", "Return RTL Mission", "actions.py", "--action=return_rtl", "recovery"),
            ("_execute_hold", "Hold Position Mission", "actions.py", "--action=hold", "recovery"),
            ("_execute_kill_terminate", "Kill and Terminate Mission", "actions.py", "--action=kill_terminate", "emergency"),
            (
                "_execute_test",
                "Arm/Disarm Ground Test",
                "actions.py",
                ["--action=test", "--request-file=/tmp/ground_test_cmd-xyz.json"],
                None,
            ),
            ("_execute_reboot_fc", "Flight Control Reboot Mission", "actions.py", "--action=reboot_fc", None),
            ("_execute_reboot_sys", "System Reboot Mission", "actions.py", "--action=reboot_sys", None),
            ("_execute_precision_move", "Precision Move Mission", "actions.py", "--action=precision_move --request-file=/tmp/precision_move_1_cmd-xyz.json", "recovery"),
            ("_execute_test_led", "LED Test Mission", "test_led_controller.py", "--action=start", None),
            ("_execute_swarm_trajectory", "Swarm Trajectory Mission", "swarm_trajectory_mission.py", "", "normal"),
        ],
    )
    async def test_handlers_use_execute_immediate_launcher(
        self, handler_name, expected_mission, expected_script, expected_action, interrupt_mode
    ):
        from src.drone_setup import DroneSetup, ProcessStopMode

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = create_mock_drone_config()
        if handler_name == "_execute_test":
            drone_config.ground_test_request_file = "/tmp/ground_test_cmd-xyz.json"
        if handler_name == "_execute_precision_move":
            drone_config.precision_move_request_file = "/tmp/precision_move_1_cmd-xyz.json"

        setup = DroneSetup(params, drone_config)

        with (
            patch.object(setup, '_execute_immediate_script_mission', AsyncMock(return_value=(True, "started"))) as mock_execute,
            patch("src.drone_setup.os.path.isfile", return_value=True),
        ):
            result = await getattr(setup, handler_name)()

        assert result == (True, "started")
        expected_args = (expected_mission, expected_script, expected_action, None, None)
        if interrupt_mode:
            mock_execute.assert_awaited_once_with(
                *expected_args,
                interrupt_mode=ProcessStopMode(interrupt_mode),
            )
        else:
            mock_execute.assert_awaited_once_with(*expected_args)

    @pytest.mark.asyncio
    async def test_update_code_handler_uses_execute_mission_script(self):
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = create_mock_drone_config()
        drone_config.update_branch = "main-candidate"

        setup = DroneSetup(params, drone_config)

        with patch.object(setup, '_execute_immediate_script_mission', AsyncMock(return_value=(True, "started"))) as mock_execute:
            result = await setup._execute_update_code()

        assert result == (True, "started")
        mock_execute.assert_awaited_once_with(
            "Update Code Mission with branch 'main-candidate'",
            "actions.py",
            "--action=update_code --branch=main-candidate",
            None,
            None,
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("follow_value", ["0", "2"])
    async def test_smart_swarm_handler_always_launches_runtime(self, follow_value):
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        params.smart_swarm_executer = "smart_swarm.py"
        drone_config = create_mock_drone_config()
        drone_config.state = State.MISSION_READY.value
        drone_config.trigger_time = 25
        drone_config.swarm = {"follow": follow_value}

        setup = DroneSetup(params, drone_config)

        with patch.object(setup, 'execute_mission_script', AsyncMock(return_value=(True, "started"))) as mock_execute:
            result = await setup._execute_smart_swarm(current_time=100, earlier_trigger_time=0)

        assert result == (True, "started")
        assert drone_config.state == State.MISSION_EXECUTING.value
        assert drone_config.trigger_time == 0
        mock_execute.assert_awaited_once_with("smart_swarm.py", "")

    @pytest.mark.asyncio
    async def test_precision_move_handler_requires_payload_file(self):
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = create_mock_drone_config()
        drone_config.precision_move_request_file = None

        setup = DroneSetup(params, drone_config)
        with patch.object(setup, "_fail_pending_command", AsyncMock(return_value=(False, "missing"))) as mock_fail:
            result = await setup._execute_precision_move()

        assert result == (False, "missing")
        mock_fail.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ground_test_handler_requires_bound_safety_payload_file(self):
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = create_mock_drone_config()
        drone_config.current_command_id = "ground-test-missing"
        drone_config.mission = Mission.TEST.value
        drone_config.ground_test_request_file = None

        setup = DroneSetup(params, drone_config)
        with patch.object(
            setup,
            "_fail_pending_command",
            AsyncMock(return_value=(False, "missing")),
        ) as mock_fail:
            result = await setup._execute_test()

        assert result == (False, "missing")
        mock_fail.assert_awaited_once_with(
            "Arm/Disarm Ground Test safety acknowledgement file not found. No arm command was sent."
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("handler_name", "interrupts_running"),
        [
            ("_execute_land", True),
            ("_execute_return_rtl", True),
            ("_execute_hold", True),
            ("_execute_kill_terminate", True),
            ("_execute_test", False),
            ("_execute_reboot_fc", False),
            ("_execute_reboot_sys", False),
            ("_execute_test_led", False),
            ("_execute_swarm_trajectory", True),
        ],
    )
    async def test_immediate_handlers_transition_to_executing_once(self, handler_name, interrupts_running):
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = create_mock_drone_config()
        drone_config.state = State.MISSION_READY.value
        drone_config.trigger_time = 25
        if handler_name == "_execute_test":
            drone_config.ground_test_request_file = "/tmp/ground_test_cmd-xyz.json"

        setup = DroneSetup(params, drone_config)
        setup.terminate_all_running_processes = AsyncMock()

        with patch.object(
            setup,
            'execute_mission_script',
            AsyncMock(return_value=(True, "started")),
        ) as mock_execute, patch("src.drone_setup.os.path.isfile", return_value=True):
            result = await getattr(setup, handler_name)(current_time=100, earlier_trigger_time=0)

        assert result == (True, "started")
        assert drone_config.state == State.MISSION_EXECUTING.value
        assert drone_config.trigger_time == 0
        if interrupts_running:
            setup.terminate_all_running_processes.assert_not_awaited()
        else:
            setup.terminate_all_running_processes.assert_not_awaited()
        mock_execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_override_actions_interrupt_running_processes(self):
        from src.drone_setup import DroneSetup, ProcessStopMode, ProcessStopSummary

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = create_mock_drone_config()
        drone_config.state = State.MISSION_READY.value
        drone_config.trigger_time = 10

        setup = DroneSetup(params, drone_config)
        setup.running_processes["mission.py:cmd-1"] = Mock()
        setup.terminate_all_running_processes = AsyncMock(return_value=ProcessStopSummary())

        with patch.object(setup, 'execute_mission_script', AsyncMock(return_value=(True, "started"))):
            await setup._execute_land(current_time=100, earlier_trigger_time=0)

        setup.terminate_all_running_processes.assert_awaited_once_with(
            reset_state=False,
            mode=ProcessStopMode.RECOVERY,
        )

    @pytest.mark.asyncio
    async def test_recovery_does_not_start_competing_controller_when_preemption_fails(self):
        from src.drone_setup import DroneSetup, ProcessStopSummary

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = create_mock_drone_config()
        drone_config.state = State.MISSION_READY.value
        setup = DroneSetup(params, drone_config)
        setup.running_processes["show.py:old"] = Mock()
        setup.terminate_all_running_processes = AsyncMock(
            return_value=ProcessStopSummary(attempted=1, unresolved=1)
        )
        setup._fail_pending_command = AsyncMock(return_value=(False, "blocked"))
        setup.execute_mission_script = AsyncMock()

        result = await setup._execute_land(current_time=100, earlier_trigger_time=0)

        assert result == (False, "blocked")
        setup.execute_mission_script.assert_not_awaited()
        setup._fail_pending_command.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_emergency_stop_proceeds_when_local_preemption_is_uncertain(self):
        from src.drone_setup import DroneSetup, ProcessStopSummary

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = create_mock_drone_config()
        drone_config.state = State.MISSION_READY.value
        setup = DroneSetup(params, drone_config)
        setup.running_processes["show.py:old"] = Mock()
        setup.terminate_all_running_processes = AsyncMock(
            return_value=ProcessStopSummary(attempted=1, unresolved=1)
        )
        setup.execute_mission_script = AsyncMock(return_value=(True, "started"))

        result = await setup._execute_kill_terminate(current_time=100, earlier_trigger_time=0)

        assert result == (True, "started")
        setup.execute_mission_script.assert_awaited_once_with(
            "actions.py",
            "--action=kill_terminate",
        )

    @pytest.mark.asyncio
    async def test_standard_show_interrupts_smart_swarm_leader_runtime(self):
        from src.drone_setup import DroneSetup
        from src.enums import Mission, State

        params = Mock()
        params.trigger_sooner_seconds = 4
        params.main_offboard_executer = "offboard_executer.py"
        drone_config = create_mock_drone_config()
        drone_config.state = State.MISSION_READY.value
        drone_config.mission = Mission.DRONE_SHOW_FROM_CSV.value
        drone_config.trigger_time = 10

        setup = DroneSetup(params, drone_config)
        setup.running_processes["smart_swarm.py:cmd-1"] = Mock()
        setup.terminate_all_running_processes = AsyncMock()

        with patch.object(setup, 'execute_mission_script', AsyncMock(return_value=(True, "started"))):
            await setup._execute_standard_drone_show(current_time=100, earlier_trigger_time=0)

        setup.terminate_all_running_processes.assert_awaited_once_with(reset_state=False)

    @pytest.mark.asyncio
    async def test_custom_show_interrupts_smart_swarm_leader_runtime(self):
        from src.drone_setup import DroneSetup
        from src.enums import Mission, State

        params = Mock()
        params.trigger_sooner_seconds = 4
        params.main_offboard_executer = "offboard_executer.py"
        params.custom_csv_file_name = "active.csv"
        drone_config = create_mock_drone_config()
        drone_config.state = State.MISSION_READY.value
        drone_config.mission = Mission.CUSTOM_CSV_DRONE_SHOW.value
        drone_config.trigger_time = 10

        setup = DroneSetup(params, drone_config)
        setup.running_processes["smart_swarm.py:cmd-1"] = Mock()
        setup.terminate_all_running_processes = AsyncMock()

        with patch.object(setup, 'execute_mission_script', AsyncMock(return_value=(True, "started"))):
            await setup._execute_custom_drone_show(current_time=100, earlier_trigger_time=0)

        setup.terminate_all_running_processes.assert_awaited_once_with(reset_state=False)

    @pytest.mark.asyncio
    async def test_terminate_all_running_processes_can_preserve_staged_mission(self):
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = create_mock_drone_config()
        drone_config.mission = Mission.SWARM_TRAJECTORY.value
        drone_config.state = State.MISSION_READY.value

        setup = DroneSetup(params, drone_config)

        mock_process = Mock()
        mock_process.returncode = None
        mock_process.pid = 4321
        mock_process.terminate = Mock()
        mock_process.kill = Mock()

        async def mock_wait():
            mock_process.returncode = 0

        mock_process.wait = mock_wait

        process_record = Mock()
        process_record.script_name = "smart_swarm.py"
        process_record.process = mock_process
        process_record.process_key = "smart_swarm.py:cmd-1"
        process_record.superseded = False

        setup.running_processes[process_record.process_key] = process_record

        await setup.terminate_all_running_processes(reset_state=False)

        assert drone_config.mission == Mission.SWARM_TRAJECTORY.value
        assert drone_config.state == State.MISSION_READY.value
        assert process_record.superseded is True
        assert len(setup.running_processes) == 0


# ============================================================================
# Test: Trigger Time Calculation
# ============================================================================

@pytest.mark.unit
@pytest.mark.mission
class TestTriggerTimeCalculation:
    """Test trigger time calculations"""

    def test_trigger_time_from_string(self):
        """Test trigger time can be parsed from string"""
        trigger_str = "1703084400"
        trigger_int = int(trigger_str)

        assert trigger_int == 1703084400

    def test_earlier_trigger_calculation(self):
        """Test earlier trigger time calculation"""
        trigger_time = 1703084400
        trigger_sooner = 4

        earlier = trigger_time - trigger_sooner

        assert earlier == 1703084396

    def test_current_time_vs_earlier_trigger(self):
        """Test current time vs earlier trigger comparison"""
        now = int(time.time())
        trigger_time = now + 10
        trigger_sooner = 4
        earlier_trigger = trigger_time - trigger_sooner

        # 6 seconds from now is past earlier trigger (4 seconds before trigger)
        at_time = now + 6
        should_execute = at_time >= earlier_trigger

        assert should_execute is True

    def test_not_yet_time_to_execute(self):
        """Test when it's not yet time to execute"""
        now = int(time.time())
        trigger_time = now + 100
        trigger_sooner = 4
        earlier_trigger = trigger_time - trigger_sooner

        should_execute = now >= earlier_trigger

        assert should_execute is False


# ============================================================================
# Test: Mission Type Specific Tests
# ============================================================================

@pytest.mark.unit
@pytest.mark.mission
class TestMissionTypeSpecific:
    """Test specific mission type behaviors"""

    def test_mission_enum_values(self):
        """Test Mission enum has correct values"""
        assert Mission.NONE.value == 0
        assert Mission.DRONE_SHOW_FROM_CSV.value == 1
        assert Mission.SMART_SWARM.value == 2
        assert Mission.CUSTOM_CSV_DRONE_SHOW.value == 3
        assert Mission.SWARM_TRAJECTORY.value == 4
        assert Mission.TAKE_OFF.value == 10
        assert Mission.LAND.value == 101
        assert Mission.HOLD.value == 102
        assert Mission.RETURN_RTL.value == 104
        assert Mission.KILL_TERMINATE.value == 105
        assert Mission.HOVER_TEST.value == 106

    def test_state_enum_values(self):
        """Test State enum has correct values"""
        assert State.IDLE.value == 0
        assert State.MISSION_READY.value == 1
        assert State.MISSION_EXECUTING.value == 2


# ============================================================================
# Test: Time Synchronization
# ============================================================================

@pytest.mark.unit
@pytest.mark.mission
class TestTimeSynchronization:
    """Test time synchronization functionality"""

    def test_synchronize_time_method_exists(self):
        """Test synchronize_time method exists"""
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = Mock()
        drone_config.trigger_time = 0
        drone_config.mission = 0

        setup = DroneSetup(params, drone_config)

        assert hasattr(setup, 'synchronize_time')
        assert callable(setup.synchronize_time)

    @patch('src.drone_setup.subprocess.run')
    @patch('src.drone_setup.logger')
    def test_synchronize_time_skips_in_sim_mode(self, mock_logger, mock_run):
        """Test time sync is skipped cleanly in simulation mode"""
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        params.sim_mode = True
        drone_config = Mock()
        drone_config.trigger_time = 0
        drone_config.mission = 0

        setup = DroneSetup(params, drone_config)
        setup.synchronize_time()

        mock_run.assert_not_called()
        mock_logger.info.assert_any_call("Simulation mode active. Skipping time synchronization.")


# ============================================================================
# Test: DroneConfig Integration
# ============================================================================

@pytest.mark.unit
@pytest.mark.mission
class TestDroneConfigIntegration:
    """Test DroneConfig integration with DroneSetup"""

    def test_drone_config_has_required_attributes(self):
        """Test mock DroneConfig has attributes needed by DroneSetup"""
        drone_config = create_mock_drone_config()

        assert hasattr(drone_config, 'state')
        assert hasattr(drone_config, 'mission')
        assert hasattr(drone_config, 'trigger_time')

    def test_drone_config_default_values(self):
        """Test DroneConfig default values in mock"""
        drone_config = create_mock_drone_config()

        assert drone_config.state == State.IDLE.value
        assert drone_config.mission == Mission.NONE.value

    def test_drone_config_tracks_last_mission(self):
        """Test DroneConfig tracks last mission"""
        drone_config = create_mock_drone_config()

        drone_config.mission = Mission.TAKE_OFF.value
        drone_config.last_mission = drone_config.mission
        drone_config.mission = Mission.NONE.value

        assert drone_config.last_mission == Mission.TAKE_OFF.value


# ============================================================================
# Test: Error Handling
# ============================================================================

@pytest.mark.unit
@pytest.mark.mission
class TestMissionErrorHandling:
    """Test error handling in mission execution"""

    def test_drone_setup_validates_trigger_time_on_init(self):
        """Test DroneSetup validates trigger_time type on initialization"""
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = Mock()
        drone_config.state = State.MISSION_READY.value
        drone_config.mission = Mission.TAKE_OFF.value
        drone_config.trigger_time = "invalid"  # Invalid type

        # Should raise TypeError during initialization
        with pytest.raises(TypeError):
            DroneSetup(params, drone_config)

    def test_missing_script_handled(self):
        """Test missing script is handled gracefully"""
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = Mock()
        drone_config.trigger_time = 0
        drone_config.mission = 0

        setup = DroneSetup(params, drone_config)

        # Get path for nonexistent script
        path = setup._get_script_path('nonexistent.py')

        # File should not exist
        assert not os.path.isfile(path)


# ============================================================================
# Test: Logging
# ============================================================================

@pytest.mark.unit
@pytest.mark.mission
class TestMissionLogging:
    """Test mission logging functionality"""

    def test_last_logged_mission_tracking(self):
        """Test last logged mission is tracked"""
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = Mock()
        drone_config.trigger_time = 0
        drone_config.mission = 0

        setup = DroneSetup(params, drone_config)

        assert hasattr(setup, 'last_logged_mission')
        assert setup.last_logged_mission is None

    def test_last_logged_state_tracking(self):
        """Test last logged state is tracked"""
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = Mock()
        drone_config.trigger_time = 0
        drone_config.mission = 0

        setup = DroneSetup(params, drone_config)

        assert hasattr(setup, 'last_logged_state')
        assert setup.last_logged_state is None


@pytest.mark.unit
@pytest.mark.mission
class TestMissionProcessMonitoring:
    """Test mission subprocess monitoring and diagnostics"""

    @pytest.mark.asyncio
    async def test_terminal_callback_waits_for_start_callback_attempt(self):
        """Very short actions still report start before their terminal result."""
        from src.drone_setup import DroneSetup, RunningMissionProcess

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = create_mock_drone_config()
        drone_config.mission = Mission.QUICKSCOUT.value
        drone_config.state = State.MISSION_EXECUTING.value
        setup = DroneSetup(params, drone_config)
        process = Mock(returncode=0)
        process.communicate = AsyncMock(return_value=(b"done\n", b""))
        record = RunningMissionProcess(
            process_key="quickscout.py:ordered",
            script_name="quickscout.py",
            process=process,
            command_id="ordered",
            mission_type=Mission.QUICKSCOUT.value,
        )
        setup.running_processes[record.process_key] = record
        setup._active_mission_owner_token = record.ownership_token
        setup._reset_mission_state = Mock()
        setup._report_execution_to_gcs = AsyncMock()
        allow_start_completion = asyncio.Event()

        async def pending_start_report():
            await allow_start_completion.wait()

        start_task = asyncio.create_task(pending_start_report())
        monitor_task = asyncio.create_task(
            setup._monitor_script_process(
                record,
                execution_start_task=start_task,
            )
        )
        await asyncio.sleep(0.02)
        setup._report_execution_to_gcs.assert_not_awaited()

        allow_start_completion.set()
        await asyncio.wait_for(monitor_task, timeout=1)
        setup._report_execution_to_gcs.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_monitor_script_process_labels_legacy_output_without_inferring_root_cause(self):
        """Legacy stdout remains diagnostic, not an inferred action root cause."""
        from src.drone_setup import DroneSetup, RunningMissionProcess

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = create_mock_drone_config()

        setup = DroneSetup(params, drone_config)
        process = Mock()
        process.communicate = AsyncMock(return_value=(b"mavsdk_server executable not found.\n", b""))
        process.returncode = 1
        process_record = RunningMissionProcess(
            process_key="actions.py:cmd-123",
            script_name="actions.py",
            process=process,
            command_id="cmd-123",
        )
        setup.running_processes[process_record.process_key] = process_record
        setup._active_mission_owner_token = process_record.ownership_token
        setup._reset_mission_state = Mock()
        setup._report_execution_to_gcs = AsyncMock()

        with patch('src.drone_setup.logger') as mock_logger:
            await setup._monitor_script_process(process_record)

        setup._reset_mission_state.assert_called_once_with(success=False)
        setup._report_execution_to_gcs.assert_awaited_once()
        report_kwargs = setup._report_execution_to_gcs.await_args.kwargs

        assert report_kwargs["command_id"] == "cmd-123"
        assert report_kwargs["error_message"] == (
            "Mission script exited with code 1 without a valid structured terminal result."
        )
        assert report_kwargs["script_output"] == (
            "Legacy stdout (diagnostic only): mavsdk_server executable not found."
        )
        assert mock_logger.error.called

    @pytest.mark.asyncio
    async def test_monitor_prefers_structured_action_failure_over_spi_stderr(self):
        """Native LED diagnostics must not mask the PX4 action result."""
        from src.action_result_protocol import encode_terminal_result, make_terminal_result
        from src.drone_setup import DroneSetup, RunningMissionProcess

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = create_mock_drone_config()
        setup = DroneSetup(params, drone_config)
        process = Mock()
        process.communicate = AsyncMock(
            return_value=(
                b"Action test failed with ActionError\n",
                b"Unable to open SPI device /dev/spidev0.0\n",
            )
        )
        process.returncode = 1
        result = make_terminal_result(
            success=False,
            code="PX4_COMMAND_DENIED",
            phase="vehicle_command",
            operator_message=(
                "PX4 rejected the 'test' vehicle command: Resolve system health failures first."
            ),
            retryable=False,
            evidence={"mavsdk_result": "COMMAND_DENIED"},
            final_vehicle_state={"armed": False},
        )
        read_fd, write_fd = os.pipe()
        os.write(write_fd, encode_terminal_result(result))
        os.close(write_fd)
        process_record = RunningMissionProcess(
            process_key="actions.py:cmd-structured",
            script_name="actions.py",
            process=process,
            command_id="cmd-structured",
            action_result_read_fd=read_fd,
        )
        setup.running_processes[process_record.process_key] = process_record
        setup._active_mission_owner_token = process_record.ownership_token
        setup._reset_mission_state = Mock()
        setup._report_execution_to_gcs = AsyncMock()

        await setup._monitor_script_process(process_record)

        report_kwargs = setup._report_execution_to_gcs.await_args.kwargs
        assert report_kwargs["success"] is False
        assert report_kwargs["error_message"] == result.operator_message
        assert "PX4_COMMAND_DENIED" in report_kwargs["script_output"]
        assert "SPI" not in report_kwargs["script_output"]

    @pytest.mark.asyncio
    async def test_monitor_types_superseded_structured_action_independent_of_message(self):
        """Process ownership, not arbitrary child text, classifies supersession."""
        from src.action_result_protocol import encode_terminal_result, make_terminal_result
        from src.command_execution_contract import DroneExecutionOutcome
        from src.drone_setup import DroneSetup, RunningMissionProcess

        setup = DroneSetup(Mock(trigger_sooner_seconds=4), create_mock_drone_config())
        process = Mock(returncode=1)
        process.communicate = AsyncMock(return_value=(b"", b""))
        result = make_terminal_result(
            success=False,
            code="ACTION_INTERRUPTED",
            phase="interrupted",
            operator_message="Precision move stopped after SIGTERM.",
            retryable=False,
            final_vehicle_state={"armed": True},
        )
        read_fd, write_fd = os.pipe()
        os.write(write_fd, encode_terminal_result(result))
        os.close(write_fd)
        record = RunningMissionProcess(
            process_key="actions.py:interrupted",
            script_name="actions.py",
            process=process,
            command_id="interrupted",
            superseded=True,
            action_result_read_fd=read_fd,
        )
        setup.running_processes[record.process_key] = record
        setup._active_mission_owner_token = record.ownership_token
        setup._reset_mission_state = Mock()
        setup._report_execution_to_gcs = AsyncMock()

        await setup._monitor_script_process(record)

        report = setup._report_execution_to_gcs.await_args.kwargs
        assert report["outcome"] == DroneExecutionOutcome.SUPERSEDED
        assert report["error_message"].startswith(
            "Superseded by a newer command before completion."
        )
        assert "Precision move stopped after SIGTERM" in report["error_message"]

    @pytest.mark.asyncio
    async def test_monitor_preserves_legacy_mission_failure_as_operator_reason(self):
        """Non-actions runners keep their concrete bounded failure diagnostics."""
        from src.drone_setup import DroneSetup, RunningMissionProcess

        params = Mock()
        params.trigger_sooner_seconds = 4
        setup = DroneSetup(params, create_mock_drone_config())
        process = Mock()
        process.communicate = AsyncMock(
            return_value=(b"", b"Trajectory file failed integrity validation\n")
        )
        process.returncode = 2
        process_record = RunningMissionProcess(
            process_key="drone_show.py:cmd-show",
            script_name="drone_show.py",
            process=process,
            command_id="cmd-show",
        )
        setup.running_processes[process_record.process_key] = process_record
        setup._active_mission_owner_token = process_record.ownership_token
        setup._reset_mission_state = Mock()
        setup._report_execution_to_gcs = AsyncMock()

        await setup._monitor_script_process(process_record)

        report_kwargs = setup._report_execution_to_gcs.await_args.kwargs
        expected = (
            "Legacy stderr (diagnostic only): "
            "Trajectory file failed integrity validation"
        )
        assert report_kwargs["success"] is False
        assert report_kwargs["error_message"] == expected
        assert report_kwargs["script_output"] == expected
        assert "structured terminal result" not in report_kwargs["error_message"]

    @pytest.mark.asyncio
    async def test_monitor_preserves_newer_staged_command_state(self):
        """An older process completion must not erase a newly accepted safety command."""
        from src.drone_setup import DroneSetup, RunningMissionProcess

        params = Mock()
        params.trigger_sooner_seconds = 4
        params.COMMAND_IDEMPOTENCY_HISTORY_SEC = 1800
        params.COMMAND_IDEMPOTENCY_MAX_HISTORY = 256
        drone_config = create_mock_drone_config()
        drone_config.current_command_id = "hold-cmd"
        drone_config.mission = Mission.HOLD.value
        drone_config.state = State.MISSION_READY.value

        setup = DroneSetup(params, drone_config)
        process = Mock()
        process.communicate = AsyncMock(return_value=(b"quickscout complete\n", b""))
        process.returncode = 0
        process_record = RunningMissionProcess(
            process_key="quickscout_mission.py:quickscout-cmd",
            script_name="quickscout_mission.py",
            process=process,
            command_id="quickscout-cmd",
            mission_type=Mission.QUICKSCOUT.value,
        )
        setup.running_processes[process_record.process_key] = process_record
        setup._reset_mission_state = Mock()
        setup._report_execution_to_gcs = AsyncMock()

        await setup._monitor_script_process(process_record)

        setup._reset_mission_state.assert_not_called()
        assert drone_config.current_command_id == "hold-cmd"
        assert drone_config.mission == Mission.HOLD.value
        assert drone_config.state == State.MISSION_READY.value
        setup._report_execution_to_gcs.assert_awaited_once()
        assert setup._report_execution_to_gcs.await_args.kwargs["success"] is True

    @pytest.mark.asyncio
    async def test_monitor_cas_preserves_newer_pending_same_mission(self):
        """Old completion cannot reset after a same-type replacement is accepted."""
        from src.drone_setup import DroneSetup, RunningMissionProcess

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = create_mock_drone_config()
        drone_config.mission = Mission.TAKE_OFF.value
        drone_config.state = State.MISSION_EXECUTING.value
        setup = DroneSetup(params, drone_config)
        process = Mock(returncode=0)
        process.communicate = AsyncMock(return_value=(b"old takeoff complete\n", b""))
        old_record = RunningMissionProcess(
            process_key="actions.py:old",
            script_name="actions.py",
            process=process,
            command_id="old",
            mission_type=Mission.TAKE_OFF.value,
        )
        setup.running_processes[old_record.process_key] = old_record
        setup._active_mission_owner_token = old_record.ownership_token
        setup._reset_mission_state = Mock()
        setup._report_execution_to_gcs = AsyncMock()

        # Hold the same lock used by command acceptance. The monitor may finish
        # child I/O, but cannot perform a check-then-reset across this update.
        setup.command_state_transaction_lock.acquire()
        try:
            monitor_task = asyncio.create_task(setup._monitor_script_process(old_record))
            await asyncio.sleep(0.02)
            drone_config.current_command_id = "replacement"
            drone_config.mission = Mission.TAKE_OFF.value
            drone_config.state = State.MISSION_READY.value
        finally:
            setup.command_state_transaction_lock.release()

        await asyncio.wait_for(monitor_task, timeout=1)

        setup._reset_mission_state.assert_not_called()
        assert drone_config.current_command_id == "replacement"
        assert drone_config.mission == Mission.TAKE_OFF.value
        assert drone_config.state == State.MISSION_READY.value
        assert old_record.process_key not in setup.running_processes

    @pytest.mark.asyncio
    async def test_old_monitor_cannot_detach_replacement_with_reused_process_key(self):
        """Object identity and owner tokens protect against key reuse."""
        from src.drone_setup import DroneSetup, RunningMissionProcess

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = create_mock_drone_config()
        drone_config.mission = Mission.HOLD.value
        drone_config.state = State.MISSION_EXECUTING.value
        setup = DroneSetup(params, drone_config)

        old_process = Mock(returncode=0)
        old_process.communicate = AsyncMock(return_value=(b"old done\n", b""))
        replacement_process = Mock(returncode=None)
        old_record = RunningMissionProcess(
            process_key="actions.py:reused",
            script_name="actions.py",
            process=old_process,
            command_id="old",
            mission_type=Mission.HOLD.value,
        )
        replacement_record = RunningMissionProcess(
            process_key=old_record.process_key,
            script_name="actions.py",
            process=replacement_process,
            command_id="replacement",
            mission_type=Mission.HOLD.value,
        )
        setup.running_processes[replacement_record.process_key] = replacement_record
        setup._active_mission_owner_token = replacement_record.ownership_token
        setup._reset_mission_state = Mock()
        setup._report_execution_to_gcs = AsyncMock()

        await setup._monitor_script_process(old_record)

        setup._reset_mission_state.assert_not_called()
        assert setup.running_processes[replacement_record.process_key] is replacement_record
        assert setup._active_mission_owner_token == replacement_record.ownership_token
        assert drone_config.state == State.MISSION_EXECUTING.value


@pytest.mark.unit
@pytest.mark.mission
class TestCommandReportRetry:
    """Test deferred retry behavior for drone -> GCS command callbacks."""

    def _build_params(self):
        params = Mock()
        params.trigger_sooner_seconds = 4
        params.GCS_IP = "127.0.0.1"
        params.gcs_api_port = 5030
        params.COMMAND_REPORT_HTTP_TIMEOUT_SEC = 5
        params.COMMAND_REPORT_RETRY_BASE_DELAY_SEC = 2
        params.COMMAND_REPORT_RETRY_MAX_DELAY_SEC = 60
        params.COMMAND_REPORT_RETRY_MAX_AGE_SEC = 1800
        params.COMMAND_REPORT_RETRY_LOOP_INTERVAL_SEC = 1.0
        return params

    @pytest.mark.asyncio
    async def test_report_execution_to_gcs_queues_retry_when_initial_post_fails(self):
        from src.drone_setup import DroneSetup

        setup = DroneSetup(self._build_params(), create_mock_drone_config())
        setup._post_command_report = AsyncMock(return_value=False)
        setup._ensure_command_report_retry_worker = AsyncMock()
        capability = "c" * 43
        setup.register_command_report_capability("cmd-123", capability)

        await setup._report_execution_to_gcs(
            command_id="cmd-123",
            success=True,
            duration_ms=42,
        )

        assert len(setup.pending_command_reports) == 1
        report = setup.pending_command_reports[0]
        assert report.endpoint == "/api/v1/command-reports/execution-result"
        assert report.payload["command_id"] == "cmd-123"
        assert report.payload["success"] is True
        assert report.payload["outcome"] == "completed"
        assert "capability" not in report.payload
        assert report.capability == capability
        assert capability not in repr(report)
        assert report.next_attempt_monotonic >= report.first_queued_monotonic + 2.0
        setup._post_command_report.assert_awaited_once_with(
            "/api/v1/command-reports/execution-result",
            report.payload,
            capability,
        )
        setup._ensure_command_report_retry_worker.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_typed_execution_report_retries_old_strict_schema_once(self, monkeypatch):
        """New nodes downgrade only the optional outcome after an old GCS returns 422."""
        from src.drone_setup import DroneSetup

        posted_payloads = []
        statuses = iter([422, 200])

        class FakeResponse:
            def __init__(self, status):
                self.status = status

            async def json(self, *, content_type=None):
                del content_type
                return {
                    "detail": [
                        {
                            "type": "extra_forbidden",
                            "loc": ["body", "outcome"],
                        }
                    ]
                }

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                return False

        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                return False

            def post(self, url, *, json, headers, timeout):
                del url, headers, timeout
                posted_payloads.append(dict(json))
                return FakeResponse(next(statuses))

        monkeypatch.setattr(
            "src.drone_setup.aiohttp.ClientSession",
            lambda: FakeSession(),
        )
        setup = DroneSetup(self._build_params(), create_mock_drone_config())

        delivered = await setup._post_command_report(
            "/api/v1/command-reports/execution-result",
            {
                "command_id": "cmd-compat",
                "hw_id": "1",
                "success": False,
                "outcome": "superseded",
                "error_message": "Superseded by a newer command before completion",
            },
            capability="c" * 43,
        )

        assert delivered is True
        assert posted_payloads[0]["outcome"] == "superseded"
        assert "outcome" not in posted_payloads[1]
        assert posted_payloads[1]["command_id"] == "cmd-compat"

    def test_long_running_command_keeps_capability_for_terminal_report(self):
        from src.drone_setup import DroneSetup

        params = self._build_params()
        setup = DroneSetup(params, create_mock_drone_config())
        capability = "c" * 43
        setup.register_command_report_capability("cmd-long", capability)
        setup._command_report_capabilities["cmd-long"] = (
            capability,
            time.monotonic() - params.COMMAND_REPORT_RETRY_MAX_AGE_SEC - 1,
        )

        assert setup._get_command_report_capability("cmd-long") == capability
        assert "cmd-long" in setup._command_report_capabilities

    @pytest.mark.asyncio
    async def test_permanent_callback_rejection_is_not_retried(self):
        from src.drone_setup import DroneSetup, PermanentCommandReportRejection

        setup = DroneSetup(self._build_params(), create_mock_drone_config())
        setup._post_command_report = AsyncMock(
            side_effect=PermanentCommandReportRejection(403)
        )
        setup._queue_command_report_retry = AsyncMock()
        setup.register_command_report_capability("cmd-rejected", "c" * 43)

        await setup._report_execution_to_gcs(
            command_id="cmd-rejected",
            success=True,
        )

        setup._queue_command_report_retry.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_retry_worker_drops_permanently_rejected_callback(self):
        from src.drone_setup import (
            DroneSetup,
            PendingCommandReport,
            PermanentCommandReportRejection,
        )

        setup = DroneSetup(self._build_params(), create_mock_drone_config())
        setup.pending_command_reports = [
            PendingCommandReport(
                endpoint="/api/v1/command-reports/execution-result",
                payload={"command_id": "cmd-rejected", "hw_id": "1"},
                capability="c" * 43,
                description="execution-result for command cmd-rejected",
                first_queued_monotonic=10.0,
                next_attempt_monotonic=10.0,
            )
        ]
        setup._post_command_report = AsyncMock(
            side_effect=PermanentCommandReportRejection(403)
        )

        delivered = await setup._retry_pending_command_reports_once(
            now_monotonic=10.0
        )

        assert delivered == 0
        assert setup.pending_command_reports == []

    @pytest.mark.asyncio
    async def test_retry_pending_command_reports_once_clears_successful_report(self):
        from src.drone_setup import DroneSetup, PendingCommandReport

        setup = DroneSetup(self._build_params(), create_mock_drone_config())
        setup.pending_command_reports = [
            PendingCommandReport(
                endpoint="/api/v1/command-reports/execution-result",
                payload={"command_id": "cmd-123"},
                description="execution-result for command cmd-123",
                first_queued_monotonic=10.0,
                next_attempt_monotonic=10.0,
            )
        ]
        setup._post_command_report = AsyncMock(return_value=True)

        delivered = await setup._retry_pending_command_reports_once(now_monotonic=10.0)

        assert delivered == 1
        assert setup.pending_command_reports == []

    @pytest.mark.asyncio
    async def test_retry_pending_command_reports_once_reschedules_failed_report(self):
        from src.drone_setup import DroneSetup, PendingCommandReport

        setup = DroneSetup(self._build_params(), create_mock_drone_config())
        setup.pending_command_reports = [
            PendingCommandReport(
                endpoint="/api/v1/command-reports/execution-start",
                payload={"command_id": "cmd-456"},
                description="execution-start for command cmd-456",
                first_queued_monotonic=100.0,
                next_attempt_monotonic=100.0,
            )
        ]
        setup._post_command_report = AsyncMock(return_value=False)

        delivered = await setup._retry_pending_command_reports_once(now_monotonic=100.0)

        assert delivered == 0
        assert len(setup.pending_command_reports) == 1
        report = setup.pending_command_reports[0]
        assert report.attempt_count == 1
        assert report.next_attempt_monotonic == 102.0

    @pytest.mark.asyncio
    async def test_queue_command_report_retry_coalesces_duplicate_callback(self):
        from src.drone_setup import DroneSetup

        setup = DroneSetup(self._build_params(), create_mock_drone_config())
        setup._ensure_command_report_retry_worker = AsyncMock()

        await setup._queue_command_report_retry(
            "/api/v1/command-reports/execution-result",
            {"command_id": "cmd-789", "hw_id": "1", "success": False},
            "execution-result for command cmd-789",
        )
        first_report = setup.pending_command_reports[0]

        await setup._queue_command_report_retry(
            "/api/v1/command-reports/execution-result",
            {"command_id": "cmd-789", "hw_id": "1", "success": True},
            "execution-result for command cmd-789",
        )

        assert len(setup.pending_command_reports) == 1
        report = setup.pending_command_reports[0]
        assert report is first_report
        assert report.payload["success"] is True
        setup._ensure_command_report_retry_worker.assert_awaited()
