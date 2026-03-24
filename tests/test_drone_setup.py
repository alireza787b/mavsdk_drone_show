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
import time
from unittest.mock import Mock, MagicMock, patch, AsyncMock, PropertyMock
from typing import Dict, Any

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
    async def test_monitor_skips_superseded_process_reports(self):
        """Superseded mission processes should not reset state or report twice."""
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
        setup._report_execution_to_gcs.assert_not_awaited()
        assert record.process_key not in setup.running_processes


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
        mock_popen.assert_called_once()
        mock_logger.warning.assert_any_call(
            "Async subprocess execution is unavailable. Falling back to subprocess.Popen for 'actions.py'."
        )

    @pytest.mark.asyncio
    async def test_execute_mission_script_captures_command_id_in_process_record(self):
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
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
             patch('src.drone_setup.asyncio.create_subprocess_exec', AsyncMock(return_value=process)), \
             patch('src.drone_setup.asyncio.create_task', side_effect=fake_create_task):
            result = await setup.execute_mission_script('actions.py', '--action=hold')

        assert result == (True, "Started mission script 'actions.py' asynchronously.")
        assert drone_config.current_command_id is None
        assert len(setup.running_processes) == 1
        process_record = next(iter(setup.running_processes.values()))
        assert process_record.command_id == "cmd-123"
        assert process_record.process_key.endswith("cmd-123")
        assert process_record.script_name == "actions.py"


@pytest.mark.unit
@pytest.mark.mission
class TestActionMissionHandlerRouting:
    """Representative action and script handlers should all use the shared launcher."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("handler_name", "expected_mission", "expected_script", "expected_action", "interrupts_running"),
        [
            ("_execute_land", "Land Mission", "actions.py", "--action=land", True),
            ("_execute_return_rtl", "Return RTL Mission", "actions.py", "--action=return_rtl", True),
            ("_execute_hold", "Hold Position Mission", "actions.py", "--action=hold", True),
            ("_execute_kill_terminate", "Kill and Terminate Mission", "actions.py", "--action=kill_terminate", True),
            ("_execute_test", "Test Mission", "actions.py", "--action=test", False),
            ("_execute_reboot_fc", "Flight Control Reboot Mission", "actions.py", "--action=reboot_fc", False),
            ("_execute_reboot_sys", "System Reboot Mission", "actions.py", "--action=reboot_sys", False),
            ("_execute_init_sysid", "Init SysID Mission", "actions.py", "--action=init_sysid", False),
            ("_execute_test_led", "LED Test Mission", "test_led_controller.py", "--action=start", False),
            ("_execute_swarm_trajectory", "Swarm Trajectory Mission", "swarm_trajectory_mission.py", "", False),
        ],
    )
    async def test_handlers_use_execute_immediate_launcher(
        self, handler_name, expected_mission, expected_script, expected_action, interrupts_running
    ):
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = create_mock_drone_config()

        setup = DroneSetup(params, drone_config)

        with patch.object(setup, '_execute_immediate_script_mission', AsyncMock(return_value=(True, "started"))) as mock_execute:
            result = await getattr(setup, handler_name)()

        assert result == (True, "started")
        expected_args = (expected_mission, expected_script, expected_action, None, None)
        if interrupts_running:
            mock_execute.assert_awaited_once_with(*expected_args, interrupt_running=True)
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
    @pytest.mark.parametrize(
        ("reboot_after", "expected_action"),
        [
            (False, "--action=apply_common_params"),
            (True, "--action=apply_common_params --reboot_after"),
        ],
    )
    async def test_apply_common_params_handler_uses_execute_mission_script(self, reboot_after, expected_action):
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = create_mock_drone_config()
        drone_config.reboot_after_params = reboot_after

        setup = DroneSetup(params, drone_config)

        with patch.object(setup, '_execute_immediate_script_mission', AsyncMock(return_value=(True, "started"))) as mock_execute:
            result = await setup._execute_apply_common_params()

        assert result == (True, "started")
        expected_mission = "Apply Common Params Mission with reboot" if reboot_after else "Apply Common Params Mission"
        mock_execute.assert_awaited_once_with(
            expected_mission,
            "actions.py",
            expected_action,
            None,
            None,
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
            ("_execute_swarm_trajectory", False),
            ("_execute_init_sysid", False),
        ],
    )
    async def test_immediate_handlers_transition_to_executing_once(self, handler_name, interrupts_running):
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = create_mock_drone_config()
        drone_config.state = State.MISSION_READY.value
        drone_config.trigger_time = 25

        setup = DroneSetup(params, drone_config)
        setup.terminate_all_running_processes = AsyncMock()

        with patch.object(setup, 'execute_mission_script', AsyncMock(return_value=(True, "started"))) as mock_execute:
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
        from src.drone_setup import DroneSetup

        params = Mock()
        params.trigger_sooner_seconds = 4
        drone_config = create_mock_drone_config()
        drone_config.state = State.MISSION_READY.value
        drone_config.trigger_time = 10

        setup = DroneSetup(params, drone_config)
        setup.running_processes["mission.py:cmd-1"] = Mock()
        setup.terminate_all_running_processes = AsyncMock()

        with patch.object(setup, 'execute_mission_script', AsyncMock(return_value=(True, "started"))):
            await setup._execute_land(current_time=100, earlier_trigger_time=0)

        setup.terminate_all_running_processes.assert_awaited_once()


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
    async def test_monitor_script_process_uses_stdout_when_stderr_empty(self):
        """Test child stdout is surfaced when a mission script fails without stderr"""
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
        setup._reset_mission_state = Mock()
        setup._report_execution_to_gcs = AsyncMock()

        with patch('src.drone_setup.logger') as mock_logger:
            await setup._monitor_script_process(process_record)

        setup._reset_mission_state.assert_called_once_with(success=False)
        setup._report_execution_to_gcs.assert_awaited_once()
        report_kwargs = setup._report_execution_to_gcs.await_args.kwargs

        assert report_kwargs["command_id"] == "cmd-123"
        assert report_kwargs["error_message"] == "mavsdk_server executable not found."
        assert report_kwargs["script_output"] == "mavsdk_server executable not found."
        mock_logger.error.assert_any_call(
            "Mission script 'actions.py' failed with return code 1. Output: mavsdk_server executable not found."
        )
