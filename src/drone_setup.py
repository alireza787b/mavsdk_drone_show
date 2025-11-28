#!/usr/bin/env python3
# src/drone_setup.py

import asyncio
import datetime
import logging
import subprocess
import time
import os
from enum import Enum

from src.enums import Mission, State  # Ensure this import contains the necessary Mission and State enums

logger = logging.getLogger(__name__)

class DroneSetup:
    """
    DroneSetup manages execution of drone missions (drone shows, takeoff, landing, etc.) via mission scripts.
    - Only one mission runs at a time.
    - Can override/interrupt an existing mission if needed.
    - Logs success/failure with detailed info.
    """

    def __init__(self, params, drone_config):
        """
        Args:
            params: Configuration parameters (must include 'trigger_sooner_seconds', etc.).
            drone_config: Object holding current mission, state, and related config.
        """
        self.params = params
        self.drone_config = drone_config

        # For preventing repeated logs about the same mission/state changes:
        self.last_logged_mission = None
        self.last_logged_state = None

        # Track currently running processes {script_name: process}
        self.running_processes = {}
        self.process_lock = asyncio.Lock()  # Ensures concurrency safety around process operations

        self._validate_params()
        self._validate_drone_config()

        # Map mission codes to handler functions
        self.mission_handlers = {
            Mission.NONE.value: self._handle_no_mission,
            Mission.DRONE_SHOW_FROM_CSV.value: self._execute_standard_drone_show,
            Mission.CUSTOM_CSV_DRONE_SHOW.value: self._execute_custom_drone_show,
            Mission.HOVER_TEST.value: self._execute_hover_test,
            Mission.SMART_SWARM.value: self._execute_smart_swarm,
            Mission.SWARM_TRAJECTORY.value: self._execute_swarm_trajectory,
            Mission.TAKE_OFF.value: self._execute_takeoff,
            Mission.LAND.value: self._execute_land,
            Mission.RETURN_RTL.value: self._execute_return_rtl,
            Mission.KILL_TERMINATE.value: self._execute_kill_terminate,
            Mission.HOLD.value: self._execute_hold,
            Mission.TEST.value: self._execute_test,
            Mission.REBOOT_FC.value: self._execute_reboot_fc,
            Mission.REBOOT_SYS.value: self._execute_reboot_sys,
            Mission.TEST_LED.value: self._execute_test_led,
            Mission.UPDATE_CODE.value: self._execute_update_code,
            Mission.INIT_SYSID.value: self._execute_init_sysid,
            Mission.APPLY_COMMON_PARAMS.value: self._execute_apply_common_params,
        }

    def _validate_params(self):
        required_attrs = {
            'trigger_sooner_seconds': (int, float, str)
        }

        for attr, expected_types in required_attrs.items():
            if not hasattr(self.params, attr):
                logger.error(f"Missing required attribute '{attr}' in params.")
                raise AttributeError(f"params object must have '{attr}'")

            attr_value = getattr(self.params, attr)

            if isinstance(attr_value, str):
                try:
                    converted_value = float(attr_value) if '.' in attr_value else int(attr_value)
                    setattr(self.params, attr, converted_value)
                    logger.info(f"Converted params.{attr} from str to {type(converted_value).__name__}.")
                except ValueError:
                    logger.error(f"Attribute '{attr}' must be numeric, got '{attr_value}'.")
                    raise TypeError(f"'{attr}' must be numeric.")
            elif not isinstance(attr_value, expected_types[:-1]):
                logger.error(f"'{attr}' must be int or float, got {type(attr_value).__name__}.")
                raise TypeError(f"'{attr}' must be int or float.")

    def _validate_drone_config(self):
        required_attrs = {
            'trigger_time': (int, float, str)
        }

        # Additional validation for UPDATE_CODE mission
        if self.drone_config.mission == Mission.UPDATE_CODE.value:
            required_attrs['update_branch'] = (str,)

        for attr, expected_types in required_attrs.items():
            if not hasattr(self.drone_config, attr):
                logger.error(f"Missing required attribute '{attr}' in drone_config.")
                raise AttributeError(f"drone_config must have '{attr}'")

            attr_value = getattr(self.drone_config, attr)

            if isinstance(attr_value, str) and expected_types != (str,):
                try:
                    converted_value = float(attr_value) if '.' in attr_value else int(attr_value)
                    setattr(self.drone_config, attr, converted_value)
                    logger.info(f"Converted drone_config.{attr} from str to {type(converted_value).__name__}.")
                except ValueError:
                    logger.error(f"Attribute '{attr}' must be numeric, got '{attr_value}'.")
                    raise TypeError(f"'{attr}' must be numeric.")
            elif not isinstance(attr_value, expected_types):
                logger.error(f"'{attr}' must be of type {expected_types}, got {type(attr_value).__name__}.")
                raise TypeError(f"'{attr}' must be {expected_types}.")

    def _get_python_exec_path(self) -> str:
        # Adjust to your project’s Python environment path if needed
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'venv', 'bin', 'python')

    def _get_script_path(self, script_name: str) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', script_name)

    async def terminate_all_running_processes(self):
        """
        Forcibly stops all currently running mission scripts.
        Useful for emergency overrides (e.g., new land command).
        """
        async with self.process_lock:
            for script_name, process in list(self.running_processes.items()):
                if process.returncode is None:
                    logger.warning(f"Terminating mission script: {script_name} (PID: {process.pid})")
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=5)
                        logger.info(f"Process '{script_name}' terminated gracefully.")
                    except asyncio.TimeoutError:
                        logger.warning(f"Process '{script_name}' did not terminate in time. Killing it.")
                        process.kill()
                        await process.wait()
                        logger.info(f"Process '{script_name}' killed forcefully.")

                    # Mark mission as failed to place the system in a safe state
                    self._reset_mission_state(success=False)
                else:
                    logger.debug(f"Process '{script_name}' already ended.")
            self.running_processes.clear()

    async def execute_mission_script(self, script_name: str, action: str) -> tuple:
        """
        Launches a mission script asynchronously (so it won't block new commands).
        A background task `_monitor_script_process` will watch its completion.
        """
        async with self.process_lock:
            python_exec_path = self._get_python_exec_path()
            script_path = self._get_script_path(script_name)

            if not os.path.isfile(script_path):
                logger.error(f"Mission script '{script_name}' not found at '{script_path}'.")
                self._reset_mission_state(success=False)
                return (False, f"Script '{script_name}' not found.")

            command = [python_exec_path, script_path] + action.split()
            logger.info(f"Executing mission script asynchronously: {' '.join(command)}")

            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                self.running_processes[script_name] = process

                # Create a background task that monitors this script's completion
                asyncio.create_task(self._monitor_script_process(script_name, process))

                # Return immediately - do NOT block on process.communicate()
                return (True, f"Started mission script '{script_name}' asynchronously.")
            except Exception as e:
                logger.error(f"Exception running '{script_name}': {e}", exc_info=True)
                self._reset_mission_state(success=False)
                return (False, f"Exception: {str(e)}")

    async def _monitor_script_process(self, script_name: str, process: asyncio.subprocess.Process):
        """
        Monitors the lifetime of the subprocess for a given script.
        Cleans up upon completion, sets mission state accordingly.
        """
        try:
            stdout, stderr = await process.communicate()
            return_code = process.returncode
            stdout_str = stdout.decode().strip() if stdout else ""
            stderr_str = stderr.decode().strip() if stderr else ""

            async with self.process_lock:
                if script_name in self.running_processes:
                    del self.running_processes[script_name]

            if return_code == 0:
                logger.info(f"Mission script '{script_name}' completed successfully. Output: {stdout_str}")
                self._reset_mission_state(success=True)
            else:
                logger.error(
                    f"Mission script '{script_name}' failed with return code {return_code}. "
                    f"Stderr: {stderr_str}"
                )
                self._reset_mission_state(success=False)

        except Exception as e:
            logger.error(f"Exception in _monitor_script_process for '{script_name}': {e}", exc_info=True)
            self._reset_mission_state(success=False)
            async with self.process_lock:
                if script_name in self.running_processes:
                    del self.running_processes[script_name]

    def _reset_mission_state(self, success: bool):
        """
        Reset the mission and state after script completion or forced kill.
        Both success and failure lead to mission=NONE and state=IDLE.
        """
        logger.info(f"Resetting mission state. Success={success}")
        self.drone_config.mission = Mission.NONE.value
        self.drone_config.state = State.IDLE.value
        self._log_mission_result(success, "Mission finished." if success else "Mission failed.")

    def check_running_processes(self):
        """
        Debug helper to see if any processes ended unexpectedly.
        If a process ended, remove it from the dictionary.
        """
        for script_name, process in list(self.running_processes.items()):
            if process.returncode is not None:
                logger.warning(f"Process '{script_name}' ended unexpectedly with code {process.returncode}.")
                del self.running_processes[script_name]
            else:
                logger.debug(f"Process '{script_name}' still running.")

    def synchronize_time(self):
        script_path = self._get_script_path('tools/sync_time_linux.sh')
        if not os.path.isfile(script_path):
            logger.warning("Time sync script not found, skipping time synchronization.")
            return

        try:
            result = subprocess.run([script_path], capture_output=True, text=True, check=False)
            if result.returncode == 0:
                logger.info(f"Time synchronization successful: {result.stdout.strip()}")
            else:
                logger.error(f"Time synchronization failed: {result.stderr.strip()}")
        except Exception as e:
            logger.error(f"Error during time synchronization: {e}")

    async def schedule_mission(self):
        """
        Periodically called (e.g., by the coordinator) to see if we should start or handle a mission.
        """
        # Guard: if already triggered, skip to avoid double triggers
        if self.drone_config.state == State.MISSION_EXECUTING.value:
            logger.debug("schedule_mission: Drone is already in TRIGGERED state, skipping.")
            return

        current_time = int(time.time())
        try:
            trigger_time = int(self.drone_config.trigger_time)
            trigger_sooner = int(self.params.trigger_sooner_seconds)
            earlier_trigger_time = trigger_time - trigger_sooner
        except (AttributeError, ValueError, TypeError) as e:
            logger.error(f"Error calculating trigger time: {e}")
            return

        logger.info(
            f"Checking Scheduler: "
            f"Mission Code: {self.drone_config.mission}, "
            f"State: {self.drone_config.state}, "
            f"Trigger Time: {trigger_time}, "
            f"Current Time: {current_time}"
        )

        try:
            handler = self.mission_handlers.get(self.drone_config.mission, self._handle_unknown_mission)
            success, message = await handler(current_time, earlier_trigger_time)
            logger.info(f"Mission Execution Result: success={success}, message='{message}'")
        except Exception as e:
            logger.error(f"Exception in schedule_mission: {e}", exc_info=True)

    # --------------------- MISSION HANDLERS ---------------------

    async def _handle_no_mission(self, current_time: int, earlier_trigger_time: int) -> tuple:
        logger.debug("No mission scheduled (Mission.NONE).")
        return (False, "No mission to execute.")

    async def _handle_unknown_mission(self, current_time: int, earlier_trigger_time: int) -> tuple:
        logger.error(f"Unknown mission code: {self.drone_config.mission}")
        return (False, "Unknown mission code.")

    async def _execute_standard_drone_show(self, current_time: int, earlier_trigger_time: int) -> tuple:
        """Handler for Mission.DRONE_SHOW_FROM_CSV."""
        if (
            self.drone_config.state == State.MISSION_READY.value
            and current_time >= earlier_trigger_time
        ):
            logger.info("🚀 Executing Standard Drone Show - conditions met, transitioning to MISSION_EXECUTING")
            self.drone_config.state = State.MISSION_EXECUTING.value
            real_trigger_time = self.drone_config.trigger_time
            self.drone_config.trigger_time = 0

            main_offboard_executer = getattr(self.params, 'main_offboard_executer', None)
            if not main_offboard_executer:
                logger.error("No 'main_offboard_executer' specified for standard drone show.")
                self._reset_mission_state(False)
                return (False, "No executer script specified.")

            # Phase 2: Build CLI flags (use command values if provided, else Params defaults)
            auto_global_origin = self.drone_config.auto_global_origin
            if auto_global_origin is None:
                auto_global_origin = getattr(self.params, 'AUTO_GLOBAL_ORIGIN_MODE', True)

            use_global_setpoints = self.drone_config.use_global_setpoints
            if use_global_setpoints is None:
                use_global_setpoints = getattr(self.params, 'USE_GLOBAL_SETPOINTS', True)

            # Build action string with all flags
            action = f"--start_time={real_trigger_time}"
            action += f" --auto_global_origin {auto_global_origin}"
            action += f" --use_global_setpoints {use_global_setpoints}"
            action += " --mission_type 1"  # DRONE_SHOW_FROM_CSV

            logger.info(f"Starting Standard Drone Show using '{main_offboard_executer}'.")
            logger.info(f"Phase 2 flags: auto_global_origin={auto_global_origin}, "
                       f"use_global_setpoints={use_global_setpoints}")
            return await self.execute_mission_script(main_offboard_executer, action)

        logger.debug("Conditions NOT met for Standard Drone Show.")
        return (False, "Conditions not met for Standard Drone Show.")

    async def _execute_custom_drone_show(self, current_time: int, earlier_trigger_time: int) -> tuple:
        """Handler for Mission.CUSTOM_CSV_DRONE_SHOW."""
        if (
            self.drone_config.state == State.MISSION_READY.value
            and current_time >= earlier_trigger_time
        ):
            logger.debug("Conditions met for Custom Drone Show; transitioning to TRIGGERED.")
            self.drone_config.state = State.MISSION_EXECUTING.value
            real_trigger_time = self.drone_config.trigger_time
            self.drone_config.trigger_time = 0

            main_offboard_executer = getattr(self.params, 'main_offboard_executer', None)
            custom_csv_file_name = getattr(self.params, 'custom_csv_file_name', None)

            if not main_offboard_executer:
                logger.error("No 'main_offboard_executer' specified for custom drone show.")
                self._reset_mission_state(False)
                return (False, "No executer script specified.")

            if not custom_csv_file_name:
                logger.error("No custom CSV file specified for Custom Drone Show.")
                self._reset_mission_state(False)
                return (False, "No custom CSV file specified.")

            # Phase 2: Build CLI flags (use command values if provided, else Params defaults)
            auto_global_origin = self.drone_config.auto_global_origin
            if auto_global_origin is None:
                auto_global_origin = getattr(self.params, 'AUTO_GLOBAL_ORIGIN_MODE', True)

            use_global_setpoints = self.drone_config.use_global_setpoints
            if use_global_setpoints is None:
                use_global_setpoints = getattr(self.params, 'USE_GLOBAL_SETPOINTS', True)

            # Build action string with all flags
            action = f"--start_time={real_trigger_time} --custom_csv={custom_csv_file_name}"
            action += f" --auto_global_origin {auto_global_origin}"
            action += f" --use_global_setpoints {use_global_setpoints}"
            action += " --mission_type 3"  # CUSTOM_CSV

            logger.info(f"Starting Custom Drone Show with '{custom_csv_file_name}' using '{main_offboard_executer}'.")
            logger.info(f"Phase 2 flags: auto_global_origin={auto_global_origin}, "
                       f"use_global_setpoints={use_global_setpoints}")
            return await self.execute_mission_script(main_offboard_executer, action)

        logger.debug("Conditions NOT met for Custom CSV Drone Show.")
        return (False, "Conditions not met for Custom CSV Drone Show.")

    async def _execute_hover_test(self, current_time: int, earlier_trigger_time: int) -> tuple:
        """Handler for Mission.HOVER_TEST."""
        if (
            self.drone_config.state == State.MISSION_READY.value
            and current_time >= earlier_trigger_time
        ):
            logger.debug("Conditions met for Hover Test; transitioning to TRIGGERED.")
            self.drone_config.state = State.MISSION_EXECUTING.value
            real_trigger_time = self.drone_config.trigger_time
            self.drone_config.trigger_time = 0

            main_offboard_executer = getattr(self.params, 'main_offboard_executer', None)
            hover_test_csv_file_name = getattr(self.params, 'hover_test_csv_file_name', None)

            if not main_offboard_executer:
                logger.error("No 'main_offboard_executer' specified for hover test.")
                self._reset_mission_state(False)
                return (False, "No executer script specified.")

            if not hover_test_csv_file_name:
                logger.error("No hover test CSV file specified for Hover Test Drone Show.")
                self._reset_mission_state(False)
                return (False, "No hover test CSV file specified.")

            # Phase 2: Build CLI flags (use command values if provided, else Params defaults)
            auto_global_origin = self.drone_config.auto_global_origin
            if auto_global_origin is None:
                auto_global_origin = getattr(self.params, 'AUTO_GLOBAL_ORIGIN_MODE', True)

            use_global_setpoints = self.drone_config.use_global_setpoints
            if use_global_setpoints is None:
                use_global_setpoints = getattr(self.params, 'USE_GLOBAL_SETPOINTS', True)

            # Build action string with all flags
            action = f"--start_time={real_trigger_time} --custom_csv={hover_test_csv_file_name}"
            action += f" --auto_global_origin {auto_global_origin}"
            action += f" --use_global_setpoints {use_global_setpoints}"
            action += " --mission_type 106"  # HOVER_TEST

            logger.info(f"Starting Hover Test with '{hover_test_csv_file_name}' using '{main_offboard_executer}'.")
            logger.info(f"Phase 2 flags: auto_global_origin={auto_global_origin}, "
                       f"use_global_setpoints={use_global_setpoints}")
            return await self.execute_mission_script(main_offboard_executer, action)

        logger.debug("Conditions NOT met for Hover Test CSV Drone Show.")
        return (False, "Conditions not met for Hover Test CSV Drone Show.")

    async def _execute_smart_swarm(self, current_time: int, earlier_trigger_time: int) -> tuple:
        """Handler for Mission.SMART_SWARM."""
        if (
            self.drone_config.state == State.MISSION_READY.value
            and current_time >= earlier_trigger_time
        ):
            logger.debug("Conditions met for Smart Swarm; transitioning to TRIGGERED.")
            self.drone_config.state = State.MISSION_EXECUTING.value
            self.drone_config.trigger_time = 0

            smart_swarm_executer = getattr(self.params, 'smart_swarm_executer', None)
            if not smart_swarm_executer:
                logger.error("No 'smart_swarm_executer' specified for smart swarm mission.")
                self._reset_mission_state(False)
                return (False, "No executer script specified.")

            follow_mode = int(self.drone_config.swarm.get('follow', 0))
            if follow_mode != 0:
                logger.info("Starting Smart Swarm mission in follow mode.")
                return await self.execute_mission_script(smart_swarm_executer, "")

            # If no follow mode, treat as success but no action
            logger.info("Smart Swarm mission did not require follow mode; marking success.")
            self._reset_mission_state(True)
            return (True, "Smart Swarm Mission initiated (no follow mode).")

        logger.debug("Conditions NOT met for Smart Swarm.")
        return (False, "Conditions not met for Smart Swarm.")

    async def _execute_swarm_trajectory(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.SWARM_TRAJECTORY."""
        logger.info("Starting Swarm Trajectory Mission")
        return await self.execute_mission_script("swarm_trajectory_mission.py", "")

    async def _execute_takeoff(self, current_time: int = 0, earlier_trigger_time: int = 0) -> tuple:
        """Handler for Mission.TAKE_OFF."""
        if current_time == 0:
            current_time = int(time.time())

        if (
            self.drone_config.state == State.MISSION_READY.value
            and current_time >= earlier_trigger_time
        ):
            logger.info("🛫 Executing Takeoff - conditions met, transitioning to MISSION_EXECUTING")
            try:
                altitude = float(self.drone_config.takeoff_altitude)
            except (AttributeError, ValueError, TypeError) as e:
                logger.error(f"Invalid takeoff altitude: {e}")
                self._reset_mission_state(False)
                return (False, f"Invalid takeoff altitude: {e}")

            logger.info(f"📊 Takeoff altitude: {altitude}m")
            self.drone_config.state = State.MISSION_EXECUTING.value
            self.drone_config.trigger_time = 0
            return await self.execute_mission_script("actions.py", f"--action=takeoff --altitude={altitude}")

        logger.debug("Conditions NOT met for Takeoff.")
        return (False, "Conditions not met for Takeoff.")

    async def _execute_land(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.LAND."""
        logger.info("Starting Land Mission")
        return await self.execute_mission_script("actions.py", "--action=land")

    async def _execute_return_rtl(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.RETURN_RTL."""
        logger.info("Starting Return RTL Mission")
        return await self.execute_mission_script("actions.py", "--action=return_rtl")

    async def _execute_kill_terminate(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.KILL_TERMINATE."""
        logger.warning("Starting Kill and Terminate Mission (Emergency Stop).")
        return await self.execute_mission_script("actions.py", "--action=kill_terminate")

    async def _execute_hold(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.HOLD."""
        logger.info("Starting Hold Position Mission")
        return await self.execute_mission_script("actions.py", "--action=hold")

    async def _execute_test(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.TEST."""
        logger.info("Starting Test Mission")
        return await self.execute_mission_script("actions.py", "--action=test")

    async def _execute_reboot_fc(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.REBOOT_FC."""
        logger.warning("Starting Flight Control Reboot Mission")
        return await self.execute_mission_script("actions.py", "--action=reboot_fc")

    async def _execute_reboot_sys(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.REBOOT_SYS."""
        logger.warning("Starting System Reboot Mission")
        return await self.execute_mission_script("actions.py", "--action=reboot_sys")

    async def _execute_test_led(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.TEST_LED."""
        logger.info("Starting LED Test Mission")
        return await self.execute_mission_script("test_led_controller.py", "--action=start")

    async def _execute_update_code(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.UPDATE_CODE."""
        branch_name = getattr(self.drone_config, 'update_branch', None)
        if not branch_name:
            logger.error("Branch name not specified for UPDATE_CODE mission.")
            self._reset_mission_state(False)
            return (False, "Branch name not specified.")

        logger.info(f"Starting Update Code Mission with branch '{branch_name}'")
        action_command = f"--action=update_code --branch={branch_name}"
        return await self.execute_mission_script("actions.py", action_command)

    async def _execute_init_sysid(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.INIT_SYSID."""
        logger.info("Starting Init SysID Mission")
        return await self.execute_mission_script("actions.py", "--action=init_sysid")

    async def _execute_apply_common_params(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.APPLY_COMMON_PARAMS."""
        logger.info("Starting Apply Common Params Mission")

        reboot_after = getattr(self.drone_config, "reboot_after_params", False)
        action_args = "--action=apply_common_params"
        if reboot_after:
            action_args += " --reboot_after"

        return await self.execute_mission_script("actions.py", action_args)

    # --------------------- LOGGING HELPERS ----------------------
    def _log_mission_result(self, success: bool, message: str):
        """
        Avoid spamming logs with repeated mission/state changes.
        Only log if mission or state differs from the last time we logged.
        """
        current_mission = self.drone_config.mission
        current_state = self.drone_config.state

        if (self.last_logged_mission != current_mission) or (self.last_logged_state != current_state):
            if message:
                if success:
                    logger.info(f"Mission result: Success - {message}")
                else:
                    logger.error(f"Mission result: Failure - {message}")

            self.last_logged_mission = current_mission
            self.last_logged_state = current_state
