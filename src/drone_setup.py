import asyncio
import datetime
import logging
import subprocess
import time
import psutil  # For process handling
import os
from enum import Enum
from src.enums import *  # Ensure this import is correct and contains the necessary Mission enums


class DroneSetup:
    """
    DroneSetup class manages the execution of various drone missions by handling mission scripts.
    It ensures that only one mission script runs at a time by terminating any existing scripts
    before initiating a new mission. This class also handles time synchronization and monitors
    the status of running processes.
    """

    def __init__(self, params, drone_config, offboard_controller):
        """
        Initializes the DroneSetup with configuration parameters and controllers.

        Args:
            params: Configuration parameters. Must include 'trigger_sooner_seconds'.
            drone_config: Drone configuration object containing mission details.
            offboard_controller: Controller for offboard operations.
        """
        self.params = params
        self.drone_config = drone_config
        self.offboard_controller = offboard_controller
        self.last_logged_mission = None
        self.last_logged_state = None
        self.running_processes = {}  # Dictionary to store running mission scripts
        self.process_lock = asyncio.Lock()  # Async lock to prevent race conditions

        # Validate configuration objects
        self._validate_params()
        self._validate_drone_config()

    def _validate_params(self):
        """
        Validates that the 'params' object contains necessary attributes with correct types.
        Attempts to convert them if they are strings.
        """
        required_attrs = {
            'trigger_sooner_seconds': (int, float, str)
            # Add other required attributes here if necessary
        }

        for attr, expected_types in required_attrs.items():
            if not hasattr(self.params, attr):
                logging.error(f"Missing required attribute '{attr}' in params.")
                raise AttributeError(f"params object must have '{attr}' attribute.")

            attr_value = getattr(self.params, attr)

            if isinstance(attr_value, str):
                try:
                    # Attempt to convert to float or int
                    if '.' in attr_value:
                        converted_value = float(attr_value)
                    else:
                        converted_value = int(attr_value)
                    setattr(self.params, attr, converted_value)
                    logging.info(f"Converted 'params.{attr}' from str to {type(converted_value).__name__}.")
                except ValueError:
                    logging.error(f"Attribute '{attr}' must be a number, got string '{attr_value}'.")
                    raise TypeError(f"'{attr}' must be a number, got string '{attr_value}'.")
            elif not isinstance(attr_value, expected_types[:-1]):  # Exclude str from expected types for validation
                logging.error(f"Attribute '{attr}' must be of type int or float, got {type(attr_value).__name__}.")
                raise TypeError(f"'{attr}' must be of type int or float, got {type(attr_value).__name__}.")

    def _validate_drone_config(self):
        """
        Validates that the 'drone_config' object contains necessary attributes with correct types.
        Attempts to convert them if they are strings.
        """
        required_attrs = {
            'trigger_time': (int, float, str)
            # Add other required attributes here if necessary
        }

        for attr, expected_types in required_attrs.items():
            if not hasattr(self.drone_config, attr):
                logging.error(f"Missing required attribute '{attr}' in drone_config.")
                raise AttributeError(f"drone_config object must have '{attr}' attribute.")

            attr_value = getattr(self.drone_config, attr)

            if isinstance(attr_value, str):
                try:
                    # Attempt to convert to float or int
                    if '.' in attr_value:
                        converted_value = float(attr_value)
                    else:
                        converted_value = int(attr_value)
                    setattr(self.drone_config, attr, converted_value)
                    logging.info(f"Converted 'drone_config.{attr}' from str to {type(converted_value).__name__}.")
                except ValueError:
                    logging.error(f"Attribute '{attr}' must be a number, got string '{attr_value}'.")
                    raise TypeError(f"'{attr}' must be a number, got string '{attr_value}'.")
            elif not isinstance(attr_value, expected_types[:-1]):  # Exclude str from expected types for validation
                logging.error(f"Attribute '{attr}' must be of type int or float, got {type(attr_value).__name__}.")
                raise TypeError(f"'{attr}' must be of type int or float, got {type(attr_value).__name__}.")

    def _get_python_exec_path(self) -> str:
        """
        Retrieves the absolute path to the Python executable within the virtual environment.

        Returns:
            str: Path to the Python executable.
        """
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'venv', 'bin', 'python')

    def _get_script_path(self, script_name: str) -> str:
        """
        Constructs the absolute path to a given script.

        Args:
            script_name (str): Name of the script.

        Returns:
            str: Absolute path to the script.
        """
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', script_name)

    async def terminate_all_running_processes(self):
        """
        Terminates all currently running mission scripts gracefully.
        If a process does not terminate within the timeout, it is forcefully killed.
        """
        async with self.process_lock:
            for script_name, process in list(self.running_processes.items()):
                if process.returncode is None:  # Process is still running
                    logging.info(f"Terminating existing mission script: {script_name} (PID: {process.pid})")
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=5)
                        logging.info(f"Process '{script_name}' terminated gracefully.")
                    except asyncio.TimeoutError:
                        logging.warning(f"Process '{script_name}' did not terminate gracefully. Killing it.")
                        process.kill()
                        await process.wait()
                        logging.info(f"Process '{script_name}' killed forcefully.")
                else:
                    logging.debug(f"Process '{script_name}' has already terminated.")
            self.running_processes.clear()

    async def run_mission_script(self, script_name: str, action: str) -> tuple:
        """
        Runs the specified mission script asynchronously. Ensures that no other mission scripts
        are running by terminating them before starting the new one.

        Args:
            script_name (str): Name of the mission script to execute.
            action (str): Action parameter to pass to the script.

        Returns:
            tuple: (status (bool), message (str))
        """
        async with self.process_lock:
            # Terminate any existing running processes
            if self.running_processes:
                logging.info("New mission command received. Terminating existing mission scripts.")
                await self.terminate_all_running_processes()

            python_exec_path = self._get_python_exec_path()
            script_path = self._get_script_path(script_name)
            command = f"{python_exec_path} {script_path} {action}"
            logging.debug(f"Executing command: {command}")

            try:
                # Start the mission script as a subprocess
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                self.running_processes[script_name] = process

                # Wait for the process to complete and capture output
                stdout, stderr = await process.communicate()

                if process.returncode == 0:
                    logging.info(
                        f"Mission script '{script_name}' completed successfully. Output: {stdout.decode().strip()}"
                    )
                    status = True
                    message = "Mission script completed successfully."
                else:
                    logging.error(
                        f"Mission script '{script_name}' encountered an error. Stderr: {stderr.decode().strip()}"
                    )
                    status = False
                    message = f"Mission script error: {stderr.decode().strip()}"

                # Remove the process from the tracking dictionary
                del self.running_processes[script_name]
                return status, message

            except Exception as e:
                logging.error(f"Exception in run_mission_script: {e}")
                if script_name in self.running_processes:
                    del self.running_processes[script_name]
                return False, f"Exception: {str(e)}"

    def check_running_processes(self):
        """
        Checks the status of all running mission scripts. Logs and removes any scripts that have finished.
        """
        for script_name, process in list(self.running_processes.items()):
            if process.returncode is not None:  # Process has finished
                logging.warning(
                    f"Process for '{script_name}' has finished unexpectedly with return code {process.returncode}."
                )
                del self.running_processes[script_name]
            else:
                logging.debug(f"Process for '{script_name}' is still running.")

    def synchronize_time(self):
        """
        Executes the time synchronization script with sudo privileges.
        Logs the output and continues execution regardless of success or failure.
        """
        script_path = self._get_script_path('tools/sync_time_linux.sh')
        try:
            # Run the synchronization script with sudo
            result = subprocess.run(
                [script_path],
                capture_output=True,
                text=True,
                check=False
            )

            if result.returncode == 0:
                logging.info(f"Time synchronization successful: {result.stdout.strip()}")
                print("Time synchronization successful.")
            else:
                logging.error(f"Time synchronization failed: {result.stderr.strip()}")
                print("Time synchronization failed, continuing without adjustment.")

        except Exception as e:
            logging.error(f"Error executing time synchronization script: {e}")
            print(f"Error during time synchronization, but continuing: {str(e)}")

    async def schedule_mission(self):
        """
        Schedules and executes various drone missions based on the current mission code and state.
        Ensures proper handling and logging of mission execution results.
        """
        current_time = int(time.time())
        success = False
        message = ""

        # Defensive programming: Ensure attributes exist and are of correct type
        try:
            # Parse trigger_time and trigger_sooner_seconds to integers
            trigger_time = int(self.drone_config.trigger_time)
            trigger_sooner = int(self.params.trigger_sooner_seconds)
            earlier_trigger_time = trigger_time - trigger_sooner
        except AttributeError as e:
            logging.error(f"Missing attribute during trigger time calculation: {e}")
            return
        except ValueError as e:
            logging.error(f"Invalid numeric value during trigger time calculation: {e}")
            return
        except TypeError as e:
            logging.error(f"Invalid type during trigger time calculation: {e}")
            return

        logging.info(
            f"Scheduling mission at {datetime.datetime.fromtimestamp(current_time)}. "
            f"Current mission: {Mission(self.drone_config.mission).name}, State: {self.drone_config.state}"
        )

        try:
            self.check_running_processes()  # Check the status of running processes before scheduling a new mission

            # Determine which mission handler to invoke based on the mission code
            if self.drone_config.mission == Mission.NONE.value:
                logging.debug("No Mission is Planned yet!")
            elif self.drone_config.mission == Mission.DRONE_SHOW_FROM_CSV.value:
                success, message = await self._handle_drone_show(current_time, earlier_trigger_time)
            elif self.drone_config.mission == Mission.SMART_SWARM.value:
                success, message = await self._handle_smart_swarm(current_time, earlier_trigger_time)
            elif self.drone_config.mission == Mission.TAKE_OFF.value:
                success, message = await self._handle_takeoff()
            elif self.drone_config.mission == Mission.LAND.value:
                success, message = await self._handle_land()
            elif self.drone_config.mission == Mission.HOLD.value:
                success, message = await self._handle_hold()
            elif self.drone_config.mission == Mission.TEST.value:
                success, message = await self._handle_test()
            elif self.drone_config.mission == Mission.REBOOT_FC.value:
                success, message = await self._handle_reboot_fc()
            elif self.drone_config.mission == Mission.REBOOT_SYS.value:
                success, message = await self._handle_reboot_sys()
            elif self.drone_config.mission == Mission.CUSTOM_CSV_DRONE_SHOW.value:
                success, message = await self._handle_custom_csv_drone_show(current_time, earlier_trigger_time)
            elif self.drone_config.mission == Mission.TEST_LED.value:
                success, message = await self._handle_test_led()
            else:
                logging.error(f"Unknown mission code: {self.drone_config.mission}")
                success = False
                message = "Unknown mission code."

            # Log the result of the mission execution
            self._log_mission_result(success, message)
            await self._reset_mission_if_needed(success)

        except Exception as e:
            logging.error(f"Exception in schedule_mission: {e}")


    async def _handle_drone_show(self, current_time: int, earlier_trigger_time: int) -> tuple:
        """
        Handles the Drone Show mission progression based on the trigger time and state.

        Args:
            current_time (int): The current Unix timestamp.
            earlier_trigger_time (int): The adjusted trigger time.

        Returns:
            tuple: (status (bool), message (str))
        """
        if self.drone_config.state == 1 and current_time >= earlier_trigger_time:
            self.drone_config.state = 2  # Move to the active mission state
            real_trigger_time = self.drone_config.trigger_time
            self.drone_config.trigger_time = 0  # Reset the trigger time

            logging.info("Starting Drone Show from CSV")
            return await self.run_mission_script("offboard_multiple_from_csv.py", f"--start_time={real_trigger_time}")

        logging.info("Conditions not met for triggering Drone Show")
        return False, "Conditions not met for Drone Show"

    async def _handle_smart_swarm(self, current_time: int, earlier_trigger_time: int) -> tuple:
        """
        Handles the Smart Swarm mission progression based on the trigger time and state.

        Args:
            current_time (int): The current Unix timestamp.
            earlier_trigger_time (int): The adjusted trigger time.

        Returns:
            tuple: (status (bool), message (str))
        """
        if self.drone_config.state == 1 and current_time >= earlier_trigger_time:
            self.drone_config.state = 2  # Move to the active mission state
            self.drone_config.trigger_time = 0  # Reset the trigger time

            logging.info("Starting Smart Swarm Mission")
            if int(self.drone_config.swarm.get('follow', 0)) != 0:
                if self.offboard_controller:
                    await self.offboard_controller.start_swarm()
                    await self.offboard_controller.start_offboard_follow()
                else:
                    logging.error("Offboard controller is not initialized.")
                    return False, "Offboard controller not available."
            return True, "Swarm Mission initiated"

        logging.info("Conditions not met for triggering Smart Swarm")
        return False, "Conditions not met for Smart Swarm"

    async def _handle_takeoff(self) -> tuple:
        """
        Handles the Takeoff mission by executing the 'takeoff' action script.

        Returns:
            tuple: (status (bool), message (str))
        """
        try:
            altitude = float(self.drone_config.takeoff_altitude)
        except (AttributeError, ValueError, TypeError) as e:
            logging.error(f"Invalid or missing takeoff altitude: {e}")
            return False, f"Invalid takeoff altitude: {e}"

        logging.info(f"Starting Takeoff to {altitude}m")
        return await self.run_mission_script("actions.py", f"--action=takeoff --altitude={altitude}")

    async def _handle_land(self) -> tuple:
        """
        Handles the Land mission by executing the 'land' action script.
        Stops offboard mode if necessary before landing.

        Returns:
            tuple: (status (bool), message (str))
        """
        logging.info("Starting Land")
        try:
            if int(self.drone_config.swarm.get('follow', 0)) != 0 and self.offboard_controller:
                if self.offboard_controller.is_offboard:
                    logging.info("Is in Offboard mode. Attempting to stop offboard.")
                    await self.offboard_controller.stop_offboard()
                    await asyncio.sleep(1)
        except AttributeError as e:
            logging.error(f"Error accessing offboard controller attributes: {e}")
            return False, f"Offboard controller error: {e}"

        return await self.run_mission_script("actions.py", "--action=land")

    async def _handle_hold(self) -> tuple:
        """
        Handles the Hold Position mission by executing the 'hold' action script.

        Returns:
            tuple: (status (bool), message (str))
        """
        logging.info("Starting Hold Position")
        return await self.run_mission_script("actions.py", "--action=hold")

    async def _handle_test(self) -> tuple:
        """
        Handles the Test mission by executing the 'test' action script.

        Returns:
            tuple: (status (bool), message (str))
        """
        logging.info("Starting Test")
        return await self.run_mission_script("actions.py", "--action=test")

    async def _handle_reboot_fc(self) -> tuple:
        """
        Handles the Flight Control Reboot mission by executing the 'reboot_fc' action script.

        Returns:
            tuple: (status (bool), message (str))
        """
        logging.info("Starting Flight Control Reboot")
        return await self.run_mission_script("actions.py", "--action=reboot_fc")
    
    async def _handle_reboot_sys(self) -> tuple:
        """
        Handles the Reboot system mission by executing the 'reboot_sys' action script.

        Returns:
            tuple: (status (bool), message (str))
        """
        logging.info("Starting system reboot")

        try:
            # Perform the reboot using subprocess.run for better control
            subprocess.run(['systemctl', 'reboot', '--force'], check=True)
        except subprocess.CalledProcessError as e:
            logging.error(f"Reboot command failed: {e}")
            return False, "System reboot failed"

        return await self.run_mission_script("actions.py", "--action=reboot_sys")

    async def _handle_custom_csv_drone_show(self, current_time: int, earlier_trigger_time: int) -> tuple:
        """
        Handles the Custom CSV Drone Show mission progression based on the trigger time and state.

        Args:
            current_time (int): The current Unix timestamp.
            earlier_trigger_time (int): The adjusted trigger time.

        Returns:
            tuple: (status (bool), message (str))
        """
        if self.drone_config.state == 1 and current_time >= earlier_trigger_time:
            self.drone_config.state = 2  # Move to the active mission state
            real_trigger_time = self.drone_config.trigger_time
            self.drone_config.trigger_time = 0  # Reset the trigger time

            logging.info("Starting Custom CSV Drone Show")
            return await self.run_mission_script("offboard_from_csv.py", f"--start_time={real_trigger_time}")

        logging.info("Conditions not met for triggering Custom CSV Drone Show")
        return False, "Conditions not met for Custom CSV Drone Show"

    async def _handle_test_led(self) -> tuple:
        """
        Handles the LED Test mission by executing the 'test_led_controller.py' script.

        Returns:
            tuple: (status (bool), message (str))
        """
        logging.info("Starting LED Test Script")
        return await self.run_mission_script("test_led_controller.py", "--action=start")

    def _log_mission_result(self, success: bool, message: str):
        """
        Logs the result of the mission execution if there's a change in mission or state.

        Args:
            success (bool): Indicates if the mission was successful.
            message (str): Additional information about the mission result.
        """
        if (self.last_logged_mission != self.drone_config.mission) or (self.last_logged_state != self.drone_config.state):
            if message:
                log_func = logging.info if success else logging.error
                log_func(f"Mission result: {'Success' if success else 'Error'} - {message}")
            self.last_logged_mission = self.drone_config.mission
            self.last_logged_state = self.drone_config.state

    async def _reset_mission_if_needed(self, success: bool):
        """
        Resets the mission code and state if the mission was successful and not a Smart Swarm mission.

        Args:
            success (bool): Indicates if the mission was successful.
        """
        if success and self.drone_config.mission != Mission.SMART_SWARM.value:
            logging.info("Resetting mission code and state.")
            self.drone_config.mission = Mission.NONE.value
            self.drone_config.state = 0
