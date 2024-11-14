# src/drone_setup.py

import threading
import datetime
import logging
import subprocess
import time
import os
from enum import Enum
from src.enums import Mission, State  # Ensure this import contains the necessary Mission and State enums

class DroneSetup:
    """
    The DroneSetup class manages the execution of various drone missions by handling mission scripts.
    It ensures that only one mission script runs at a time by terminating any existing scripts
    before initiating a new mission. This class also handles time synchronization and monitors
    the status of running processes.
    """

    def __init__(self, params, drone_config):
        """
        Initializes the DroneSetup with configuration parameters and controllers.

        Args:
            params: Configuration parameters. Must include 'trigger_sooner_seconds'.
            drone_config: Drone configuration object containing mission details.
        """
        self.params = params
        self.drone_config = drone_config
        self.last_logged_mission = None
        self.last_logged_state = None
        self.running_processes = {}  # Dictionary to store running mission scripts
        self.process_lock = threading.Lock()  # Threading lock to prevent race conditions

        # Validate configuration objects
        self._validate_params()
        self._validate_drone_config()

        # Mapping of mission codes to their handler functions
        self.mission_handlers = {
            Mission.NONE.value: self._handle_no_mission,
            Mission.DRONE_SHOW_FROM_CSV.value: self._execute_standard_drone_show,
            Mission.CUSTOM_CSV_DRONE_SHOW.value: self._execute_custom_drone_show,
            Mission.SMART_SWARM.value: self._execute_smart_swarm,
            Mission.TAKE_OFF.value: self._execute_takeoff,
            Mission.LAND.value: self._execute_land,
            Mission.HOLD.value: self._execute_hold,
            Mission.TEST.value: self._execute_test,
            Mission.REBOOT_FC.value: self._execute_reboot_fc,
            Mission.REBOOT_SYS.value: self._execute_reboot_sys,
            Mission.TEST_LED.value: self._execute_test_led,
            Mission.UPDATE_CODE.value: self._execute_update_code,
        }

    def _validate_params(self):
        """
        Validates that the 'params' object contains necessary attributes with correct types.
        Converts string representations of numbers to their respective numeric types.
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
                    converted_value = float(attr_value) if '.' in attr_value else int(attr_value)
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
        Converts string representations of numbers to their respective numeric types.
        """
        required_attrs = {
            'trigger_time': (int, float, str)
            # Add other required attributes here if necessary
        }

        # Additional validation for UPDATE_CODE mission
        if self.drone_config.mission == Mission.UPDATE_CODE.value:
            required_attrs['update_branch'] = (str,)

        for attr, expected_types in required_attrs.items():
            if not hasattr(self.drone_config, attr):
                logging.error(f"Missing required attribute '{attr}' in drone_config.")
                raise AttributeError(f"drone_config object must have '{attr}' attribute.")

            attr_value = getattr(self.drone_config, attr)

            if isinstance(attr_value, str) and expected_types != (str,):
                try:
                    # Attempt to convert to float or int
                    converted_value = float(attr_value) if '.' in attr_value else int(attr_value)
                    setattr(self.drone_config, attr, converted_value)
                    logging.info(f"Converted 'drone_config.{attr}' from str to {type(converted_value).__name__}.")
                except ValueError:
                    logging.error(f"Attribute '{attr}' must be a number, got string '{attr_value}'.")
                    raise TypeError(f"'{attr}' must be a number, got string '{attr_value}'.")
            elif not isinstance(attr_value, expected_types):
                logging.error(f"Attribute '{attr}' must be of type {expected_types}, got {type(attr_value).__name__}.")
                raise TypeError(f"'{attr}' must be of type {expected_types}, got {type(attr_value).__name__}.")

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

    def terminate_all_running_processes(self):
        """
        Terminates all currently running mission scripts gracefully.
        If a process does not terminate within the timeout, it is forcefully killed.
        """
        with self.process_lock:
            for script_name, process in list(self.running_processes.items()):
                if process.poll() is None:  # Process is still running
                    logging.info(f"Terminating existing mission script: {script_name} (PID: {process.pid})")
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                        logging.info(f"Process '{script_name}' terminated gracefully.")
                    except subprocess.TimeoutExpired:
                        logging.warning(f"Process '{script_name}' did not terminate gracefully. Killing it.")
                        process.kill()
                        process.wait()
                        logging.info(f"Process '{script_name}' killed forcefully.")
                else:
                    logging.debug(f"Process '{script_name}' has already terminated.")
            self.running_processes.clear()

    def execute_mission_script(self, script_name: str, action: str) -> tuple:
        """
        Executes the specified mission script synchronously without waiting for it to complete.
        Ensures that no other mission scripts are running by terminating them before starting the new mission.

        Args:
            script_name (str): Name of the mission script to execute.
            action (str): Action parameter to pass to the script.

        Returns:
            tuple: (status (bool), message (str))
        """
        with self.process_lock:
            # Terminate any existing running processes
            if self.running_processes:
                logging.info("New mission command received. Terminating existing mission scripts.")
                self.terminate_all_running_processes()

            python_exec_path = self._get_python_exec_path()
            script_path = self._get_script_path(script_name)
            command = [python_exec_path, script_path] + action.split()
            logging.debug(f"Executing command: {' '.join(command)}")

            try:
                # Start the mission script as a subprocess without waiting for it to complete
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                self.running_processes[script_name] = process
                logging.info(f"Mission script '{script_name}' started with PID {process.pid}.")

                # Optionally, start a thread to monitor the process
                monitoring_thread = threading.Thread(target=self._monitor_process, args=(process, script_name))
                monitoring_thread.start()

                # Return immediately to keep scheduler responsive
                return True, "Mission script started successfully."

            except Exception as e:
                logging.error(f"Exception in execute_mission_script: {e}", exc_info=True)
                return False, f"Exception: {str(e)}"

    def _monitor_process(self, process, script_name):
        """
        Monitors the subprocess execution, handles its completion, and logs output.

        Args:
            process: The subprocess to monitor.
            script_name (str): Name of the script being executed.
        """
        try:
            stdout, stderr = process.communicate()
            returncode = process.returncode

            # Process has completed; handle the output
            if returncode == 0:
                logging.info(
                    f"Mission script '{script_name}' completed successfully. Output: {stdout.strip()}"
                )
            else:
                logging.error(
                    f"Mission script '{script_name}' encountered an error. Stderr: {stderr.strip()}"
                )

            # Remove the process from the tracking dictionary
            with self.process_lock:
                if script_name in self.running_processes:
                    del self.running_processes[script_name]

        except Exception as e:
            logging.error(f"Exception in _monitor_process for '{script_name}': {e}", exc_info=True)

    def check_running_processes(self):
        """
        Checks the status of all running mission scripts. Logs and removes any scripts that have finished.
        """
        with self.process_lock:
            for script_name, process in list(self.running_processes.items()):
                if process.poll() is not None:  # Process has finished
                    logging.warning(
                        f"Process for '{script_name}' has finished unexpectedly with return code {process.returncode}."
                    )
                    del self.running_processes[script_name]
                else:
                    logging.debug(f"Process for '{script_name}' is still running.")

    def synchronize_time(self):
        """
        Executes the time synchronization script.
        Logs the output and continues execution regardless of success or failure.
        """
        script_path = self._get_script_path('tools/sync_time_linux.sh')
        try:
            # Run the synchronization script
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

    def schedule_mission(self):
        """
        Schedules and executes various drone missions based on the current mission code and state.
        Ensures proper handling and logging of mission execution results.
        """
        current_time = int(time.time())
        success = False
        message = ""

        try:
            # Parse trigger_time and trigger_sooner_seconds to integers
            trigger_time = int(self.drone_config.trigger_time)
            trigger_sooner = int(self.params.trigger_sooner_seconds)
            earlier_trigger_time = trigger_time - trigger_sooner
        except (AttributeError, ValueError, TypeError) as e:
            logging.error(f"Error calculating trigger time: {e}")
            return

        logging.info(
            f"Scheduling mission at {datetime.datetime.fromtimestamp(current_time)}. "
            f"Current mission: {Mission(self.drone_config.mission).name}, State: {State(self.drone_config.state).name}"
        )

        try:
            # Check the status of running processes before scheduling a new mission
            self.check_running_processes()

            # Retrieve the handler based on the current mission
            handler = self.mission_handlers.get(self.drone_config.mission, self._handle_unknown_mission)

            # Execute the mission handler
            handler(current_time, earlier_trigger_time)

            # self._reset_mission_if_needed(success)

        except Exception as e:
            logging.error(f"Exception in schedule_mission: {e}", exc_info=True)

    def _handle_no_mission(self, current_time: int, earlier_trigger_time: int) -> tuple:
        """
        Handles the scenario where no mission is planned.

        Args:
            current_time (int): The current Unix timestamp.
            earlier_trigger_time (int): The adjusted trigger time.

        Returns:
            tuple: (status (bool), message (str))
        """
        logging.debug("No Mission is Planned yet!")
        return False, "No mission to execute."

    def _handle_unknown_mission(self, current_time: int, earlier_trigger_time: int) -> tuple:
        """
        Handles unknown or undefined mission types.

        Args:
            current_time (int): The current Unix timestamp.
            earlier_trigger_time (int): The adjusted trigger time.

        Returns:
            tuple: (status (bool), message (str))
        """
        logging.error(f"Unknown mission code: {self.drone_config.mission}")
        return False, "Unknown mission code."

    def _execute_standard_drone_show(self, current_time: int, earlier_trigger_time: int) -> tuple:
        """
        Executes the Standard Drone Show mission based on the trigger time and state.

        Args:
            current_time (int): The current Unix timestamp.
            earlier_trigger_time (int): The adjusted trigger time.

        Returns:
            tuple: (status (bool), message (str))
        """
        if self.drone_config.state == State.ARMED.value and current_time >= earlier_trigger_time:
            self.drone_config.state = State.TRIGGERED.value  # Move to the active mission state
            real_trigger_time = self.drone_config.trigger_time
            self.drone_config.trigger_time = 0  # Reset the trigger time
            main_offboard_executer = getattr(self.params, 'main_offboard_executer', None)

            logging.info(f"Starting Standard Drone Show from CSV using file {main_offboard_executer}")

            return self.execute_mission_script(
                main_offboard_executer,
                f"--start_time={real_trigger_time}"
            )

        logging.info("Conditions not met for triggering Standard Drone Show")
        return False, "Conditions not met for Standard Drone Show"

    def _execute_custom_drone_show(self, current_time: int, earlier_trigger_time: int) -> tuple:
        # Similar to _execute_standard_drone_show, implement accordingly
        return False, "Not implemented"

    def _execute_smart_swarm(self, current_time: int, earlier_trigger_time: int) -> tuple:
        # Implement the smart swarm mission logic here
        return False, "Not implemented"

    def _execute_takeoff(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """
        Executes the Takeoff mission by running the takeoff action script.

        Args:
            current_time (int, optional): The current Unix timestamp.
            earlier_trigger_time (int, optional): The adjusted trigger time.

        Returns:
            tuple: (status (bool), message (str))
        """
        try:
            altitude = float(self.drone_config.takeoff_altitude)
        except (AttributeError, ValueError, TypeError) as e:
            logging.error(f"Invalid or missing takeoff altitude: {e}")
            return False, f"Invalid takeoff altitude: {e}"

        logging.info(f"Starting Takeoff to {altitude}m")
        return self.execute_mission_script(
            "actions.py",
            f"--action=takeoff --altitude={altitude}"
        )

    def _execute_land(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        # Implement the landing mission logic here
        logging.info("Starting Land Mission")
        return self.execute_mission_script(
            "actions.py",
            "--action=land"
        )

    def _execute_hold(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        # Implement the hold mission logic here
        logging.info("Starting Hold Position Mission")
        return self.execute_mission_script(
            "actions.py",
            "--action=hold"
        )

    def _execute_test(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        # Implement the test mission logic here
        logging.info("Starting Test Mission")
        return self.execute_mission_script(
            "actions.py",
            "--action=test"
        )

    def _execute_reboot_fc(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        # Implement the reboot flight controller logic here
        logging.info("Starting Flight Control Reboot Mission")
        return self.execute_mission_script(
            "actions.py",
            "--action=reboot_fc"
        )

    def _execute_reboot_sys(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        # Implement the system reboot logic here
        logging.info("Starting System Reboot Mission")
        return self.execute_mission_script(
            "actions.py",
            "--action=reboot_sys"
        )

    def _execute_test_led(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        # Implement the test LED logic here
        logging.info("Starting LED Test Mission")
        return self.execute_mission_script(
            "test_led_controller.py",
            "--action=start"
        )

    def _execute_update_code(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        # Implement the update code logic here
        branch_name = getattr(self.drone_config, 'update_branch', None)
        if not branch_name:
            logging.error("Branch name is not specified in drone_config.update_branch")
            return False, "Branch name is not specified"

        logging.info(f"Starting Update Code Mission with branch '{branch_name}'")

        # Construct the action command
        action_command = f"--action=update_code --branch={branch_name}"

        return self.execute_mission_script(
            "actions.py",
            action_command
        )


