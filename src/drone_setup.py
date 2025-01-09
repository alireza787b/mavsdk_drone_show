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
    DroneSetup manages the execution of drone missions (like drone shows, takeoff, landing, etc.) by handling mission scripts.
    - Ensures only one mission runs at a time (can terminate existing if needed).
    - Waits for mission scripts to fully complete before resetting mission/state.
    - Logs success/failure with detailed info.
    - Checks for the existence of executer scripts and handles missing parameters gracefully.
    """

    def __init__(self, params, drone_config):
        """
        Initializes DroneSetup with given parameters and drone_config.

        Args:
            params: Configuration parameters (must include 'trigger_sooner_seconds', etc.).
            drone_config: Object holding current mission, state, and related config.
        """
        self.params = params
        self.drone_config = drone_config
        self.last_logged_mission = None
        self.last_logged_state = None
        self.running_processes = {}  # {script_name: process}
        self.process_lock = asyncio.Lock()

        self._validate_params()
        self._validate_drone_config()

        # Mapping mission codes to their handler functions
        self.mission_handlers = {
            Mission.NONE.value: self._handle_no_mission,
            Mission.DRONE_SHOW_FROM_CSV.value: self._execute_standard_drone_show,
            Mission.CUSTOM_CSV_DRONE_SHOW.value: self._execute_custom_drone_show,
            Mission.SMART_SWARM.value: self._execute_smart_swarm,
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
                    logger.info(f"Converted 'params.{attr}' from str to {type(converted_value).__name__}.")
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
                    logger.info(f"Converted 'drone_config.{attr}' from str to {type(converted_value).__name__}.")
                except ValueError:
                    logger.error(f"Attribute '{attr}' must be numeric, got '{attr_value}'.")
                    raise TypeError(f"'{attr}' must be numeric.")
            elif not isinstance(attr_value, expected_types):
                logger.error(f"'{attr}' must be of type {expected_types}, got {type(attr_value).__name__}.")
                raise TypeError(f"'{attr}' must be {expected_types}.")

    def _get_python_exec_path(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'venv', 'bin', 'python')

    def _get_script_path(self, script_name: str) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', script_name)

    async def terminate_all_running_processes(self):
        async with self.process_lock:
            for script_name, process in list(self.running_processes.items()):
                if process.returncode is None:
                    logger.info(f"Terminating mission script: {script_name} (PID: {process.pid})")
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=5)
                        logger.info(f"Process '{script_name}' terminated gracefully.")
                    except asyncio.TimeoutError:
                        logger.warning(f"Process '{script_name}' did not terminate in time. Killing it.")
                        process.kill()
                        await process.wait()
                        logger.info(f"Process '{script_name}' killed forcefully.")
                else:
                    logger.debug(f"Process '{script_name}' already ended.")
            self.running_processes.clear()

    async def execute_mission_script(self, script_name: str, action: str) -> tuple:
        async with self.process_lock:
            python_exec_path = self._get_python_exec_path()
            script_path = self._get_script_path(script_name)

            # Check if script file exists
            if not os.path.isfile(script_path):
                logger.error(f"Mission script '{script_name}' not found at '{script_path}'.")
                self._reset_mission_state(success=False)
                return False, f"Script '{script_name}' not found."

            command = [python_exec_path, script_path] + action.split()
            logger.info(f"Executing mission script: {' '.join(command)}")

            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                self.running_processes[script_name] = process

                stdout, stderr = await process.communicate()
                del self.running_processes[script_name]

                return_code = process.returncode
                stdout_str = stdout.decode().strip() if stdout else ""
                stderr_str = stderr.decode().strip() if stderr else ""

                if return_code == 0:
                    logger.info(f"Mission script '{script_name}' completed successfully. Output: {stdout_str}")
                    self._reset_mission_state(success=True)
                    return True, "Mission script completed successfully."
                else:
                    logger.error(
                        f"Mission script '{script_name}' failed with return code {return_code}. "
                        f"Stderr: {stderr_str}"
                    )
                    self._reset_mission_state(success=False)
                    return False, f"Mission script error: {stderr_str if stderr_str else 'Unknown error'}"
            except Exception as e:
                logger.error(f"Exception running '{script_name}': {e}", exc_info=True)
                self._reset_mission_state(success=False)
                return False, f"Exception: {str(e)}"

    def _reset_mission_state(self, success: bool):
        """
        Reset the mission and state after script completion. For now, both success and failure 
        lead to setting mission=NONE and state=IDLE. This ensures the system is stable for the next mission.
        """
        logger.info(f"Resetting mission state after script completion. Success={success}")
        self.drone_config.mission = Mission.NONE.value
        self.drone_config.state = State.IDLE.value
        self._log_mission_result(success, "Mission finished." if success else "Mission failed.")

    def check_running_processes(self):
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
        current_time = int(time.time())
        try:
            trigger_time = int(self.drone_config.trigger_time)
            trigger_sooner = int(self.params.trigger_sooner_seconds)
            earlier_trigger_time = trigger_time - trigger_sooner
        except (AttributeError, ValueError, TypeError) as e:
            logger.error(f"Error calculating trigger time: {e}")
            return

        logger.info(
            f"Scheduling mission at {datetime.datetime.fromtimestamp(current_time)}. "
            f"Mission: {Mission(self.drone_config.mission).name}, State: {State(self.drone_config.state).name}"
        )

        try:
            handler = self.mission_handlers.get(self.drone_config.mission, self._handle_unknown_mission)
            success, message = await handler(current_time, earlier_trigger_time)
            logger.info(f"Mission Execution Result: success={success}, message={message}")
        except Exception as e:
            logger.error(f"Exception in schedule_mission: {e}", exc_info=True)

    async def _handle_no_mission(self, current_time: int, earlier_trigger_time: int) -> tuple:
        logger.debug("No mission planned.")
        return False, "No mission to execute."

    async def _handle_unknown_mission(self, current_time: int, earlier_trigger_time: int) -> tuple:
        logger.error(f"Unknown mission code: {self.drone_config.mission}")
        return False, "Unknown mission code."

    async def _execute_standard_drone_show(self, current_time: int, earlier_trigger_time: int) -> tuple:
        # Check conditions and parameters
        if self.drone_config.state == 1 and current_time >= earlier_trigger_time:
            self.drone_config.state = 2
            real_trigger_time = self.drone_config.trigger_time
            self.drone_config.trigger_time = 0
            main_offboard_executer = getattr(self.params, 'main_offboard_executer', None)

            if not main_offboard_executer:
                logger.error("No main_offboard_executer specified for standard drone show.")
                self._reset_mission_state(success=False)
                return False, "No executer script specified."

            logger.info(f"Starting Standard Drone Show using {main_offboard_executer}")
            return await self.execute_mission_script(main_offboard_executer, f"--start_time={real_trigger_time}")

        logger.info("Conditions not met for triggering Standard Drone Show.")
        return False, "Conditions not met for Standard Drone Show."

    async def _execute_custom_drone_show(self, current_time: int, earlier_trigger_time: int) -> tuple:
        if self.drone_config.state == 1 and current_time >= earlier_trigger_time:
            self.drone_config.state = 2
            real_trigger_time = self.drone_config.trigger_time
            self.drone_config.trigger_time = 0

            main_offboard_executer = getattr(self.params, 'main_offboard_executer', None)
            custom_csv_file_name = getattr(self.params, 'custom_csv_file_name', None)

            if not main_offboard_executer:
                logger.error("No main_offboard_executer specified for custom drone show.")
                self._reset_mission_state(False)
                return False, "No executer script specified."

            if not custom_csv_file_name:
                logger.error("No custom CSV file specified for Custom Drone Show.")
                self._reset_mission_state(False)
                return False, "No custom CSV file specified."

            logger.info(f"Starting Custom Drone Show with {custom_csv_file_name} using {main_offboard_executer}")
            action = f"--start_time={real_trigger_time} --custom_csv={custom_csv_file_name}"
            return await self.execute_mission_script(main_offboard_executer, action)

        logger.info("Conditions not met for triggering Custom CSV Drone Show.")
        return False, "Conditions not met for Custom CSV Drone Show."

    async def _execute_smart_swarm(self, current_time: int, earlier_trigger_time: int) -> tuple:
        if self.drone_config.state == 1 and current_time >= earlier_trigger_time:
            self.drone_config.state = 2
            self.drone_config.trigger_time = 0
            smart_swarm_executer = getattr(self.params, 'smart_swarm_executer', None)

            if not smart_swarm_executer:
                logger.error("No smart_swarm_executer specified for smart swarm mission.")
                self._reset_mission_state(False)
                return False, "No executer script specified."

            logger.info("Starting Smart Swarm Mission")
            follow_mode = int(self.drone_config.swarm.get('follow', 0))
            if follow_mode != 0:
                return await self.execute_mission_script(smart_swarm_executer, "")
            # If no follow mode, assume success but no action
            self._reset_mission_state(True)
            return True, "Smart Swarm Mission initiated."

        logger.info("Conditions not met for triggering Smart Swarm.")
        return False, "Conditions not met for Smart Swarm."

    async def _execute_takeoff(self, current_time: int = 0, earlier_trigger_time: int = 0) -> tuple:
        if current_time == 0:
            current_time = int(time.time())

        if self.drone_config.state == 1 and current_time >= earlier_trigger_time:
            try:
                altitude = float(self.drone_config.takeoff_altitude)
            except (AttributeError, ValueError, TypeError) as e:
                logger.error(f"Invalid takeoff altitude: {e}")
                self._reset_mission_state(False)
                return False, f"Invalid takeoff altitude: {e}"

            logger.info(f"Starting Takeoff to {altitude}m")
            self.drone_config.state = 2
            self.drone_config.trigger_time = 0
            return await self.execute_mission_script("actions.py", f"--action=takeoff --altitude={altitude}")

        logger.info("Conditions not met for Takeoff.")
        return False, "Conditions not met for Takeoff."

    async def _execute_land(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        logger.info("Starting Land Mission")
        return await self.execute_mission_script("actions.py", "--action=land")

    async def _execute_return_rtl(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        logger.info("Starting Return RTL Mission")
        return await self.execute_mission_script("actions.py", "--action=return_rtl")

    async def _execute_kill_terminate(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        logger.info("Starting Kill and Terminate Mission")
        return await self.execute_mission_script("actions.py", "--action=kill_terminate")

    async def _execute_hold(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        logger.info("Starting Hold Position Mission")
        return await self.execute_mission_script("actions.py", "--action=hold")

    async def _execute_test(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        logger.info("Starting Test Mission")
        return await self.execute_mission_script("actions.py", "--action=test")

    async def _execute_reboot_fc(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        logger.info("Starting Flight Control Reboot Mission")
        return await self.execute_mission_script("actions.py", "--action=reboot_fc")

    async def _execute_reboot_sys(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        logger.info("Starting System Reboot Mission")
        return await self.execute_mission_script("actions.py", "--action=reboot_sys")

    async def _execute_test_led(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        logger.info("Starting LED Test Mission")
        return await self.execute_mission_script("test_led_controller.py", "--action=start")

    async def _execute_update_code(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        branch_name = getattr(self.drone_config, 'update_branch', None)
        if not branch_name:
            logger.error("Branch name not specified for UPDATE_CODE mission.")
            self._reset_mission_state(False)
            return False, "Branch name not specified."

        logger.info(f"Starting Update Code Mission with branch '{branch_name}'")
        action_command = f"--action=update_code --branch={branch_name}"
        return await self.execute_mission_script("actions.py", action_command)
    
    async def _execute_init_sysid(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """
        Starts the mission to initialize system ID based on .hwID file
        and reboot the FC using --action=init_sysid in actions.py.
        """
        logger.info("Starting Init SysID Mission")

        # If desired, check if we're in the correct state/time:
        # if self.drone_config.state == 1 and (current_time or time.time()) >= (earlier_trigger_time or 0):
        #     self.drone_config.state = 2

        return await self.execute_mission_script("actions.py", "--action=init_sysid")

    async def _execute_apply_common_params(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """
        Starts the mission to apply the common_params.csv from actions.py.
        Optionally reboots the flight controller if a flag is set.
        """
        logger.info("Starting Apply Common Params Mission")

        reboot_after = getattr(self.drone_config, "reboot_after_params", False)
        action_args = "--action=apply_common_params"
        if reboot_after:
            action_args += " --reboot_after"

        return await self.execute_mission_script("actions.py", action_args)

    def _log_mission_result(self, success: bool, message: str):
        # Only log if mission or state changed
        if (self.last_logged_mission != self.drone_config.mission) or (self.last_logged_state != self.drone_config.state):
            if message:
                if success:
                    logger.info(f"Mission result: Success - {message}")
                else:
                    logger.error(f"Mission result: Failure - {message}")

            self.last_logged_mission = self.drone_config.mission
            self.last_logged_state = self.drone_config.state
