import asyncio
import datetime
import logging
import time
import psutil  # Add this import for process handling
import os
from enum import Enum
from src.enums import *

class DroneSetup:
    def __init__(self, params, drone_config, offboard_controller):
        self.params = params
        self.drone_config = drone_config
        self.offboard_controller = offboard_controller
        self.last_logged_mission = None
        self.last_logged_state = None
        self.running_processes = {}  # Store running processes

    def _get_python_exec_path(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)),'..', 'venv', 'bin', 'python')

    def _get_script_path(self, script_name):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), script_name)

    async def run_mission_script(self, script_name, action):
        """
        Runs the given mission script asynchronously using full command paths.
        Returns a tuple (status, message).
        """
        python_exec_path = self._get_python_exec_path()
        script_path = self._get_script_path(script_name)
        command = f"{python_exec_path} {script_path} --action={action}"
        logging.debug(f"Executing command: {command}")
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            self.running_processes[script_name] = process
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                logging.info(f"Mission script completed successfully. Output: {stdout.decode().strip()}")
                del self.running_processes[script_name]
                return True, "Mission script completed successfully."
            else:
                logging.error(f"Mission script encountered an error. Stderr: {stderr.decode().strip()}")
                del self.running_processes[script_name]
                return False, f"Mission script error: {stderr.decode().strip()}"
        except Exception as e:
            logging.error(f"Exception in run_mission_script: {e}")
            del self.running_processes[script_name]
            return False, f"Exception: {str(e)}"

    def check_running_processes(self):
        """
        Check the status of running processes.
        """
        for script_name, process in list(self.running_processes.items()):
            if process.returncode is not None:  # Process has finished
                logging.warning(f"Process for {script_name} has finished unexpectedly with return code {process.returncode}.")
                del self.running_processes[script_name]
            else:
                logging.debug(f"Process for {script_name} is still running.")

    async def schedule_mission(self):
        """
        Schedule and execute various drone missions based on the current mission code and state.
        """
        current_time = int(time.time())
        success = False
        message = ""

        logging.info(f"Scheduling mission at {datetime.datetime.fromtimestamp(current_time)}. "
                     f"Current mission: {Mission(self.drone_config.mission).name}, State: {self.drone_config.state}")

        try:
            self.check_running_processes()  # Check the status of running processes before scheduling a new mission

            if self.drone_config.mission in [Mission.DRONE_SHOW_FROM_CSV.value, Mission.SMART_SWARM.value]:
                success, message = await self._handle_show_or_swarm(current_time)
            elif self.drone_config.mission == Mission.TAKE_OFF.value:
                success, message = await self._handle_takeoff()
            elif self.drone_config.mission == Mission.LAND.value:
                success, message = await self._handle_land()
            elif self.drone_config.mission == Mission.HOLD.value:
                success, message = await self._handle_hold()
            elif self.drone_config.mission == Mission.TEST.value:
                success, message = await self._handle_test()
            elif self.drone_config.mission == Mission.REBOOT.value:
                success, message = await self._handle_reboot()

            self._log_mission_result(success, message)
            await self._reset_mission_if_needed(success)  # double check later in what condition should we retry

        except Exception as e:
            logging.error(f"Exception in schedule_mission: {e}")

    async def _handle_show_or_swarm(self, current_time):
        """
        Handles the progression of states for show or swarm missions based on the trigger time.

        Args:
            current_time (int): The current system time to compare with the trigger time.

        Returns:
            Tuple[bool, str]: Status of the mission initiation and a message describing the outcome.
        """
        # Check if the mission is ready to be triggered
        if self.drone_config.state == 1 and current_time >= self.drone_config.trigger_time:
            self.drone_config.state = 2  # Move to the active mission state
            self.drone_config.trigger_time = 0  # Reset the trigger time

            if self.drone_config.mission == Mission.DRONE_SHOW_FROM_CSV.value:
                logging.info("Starting Drone Show from CSV")
                return await self.run_mission_script("offboard_multiple_from_csv.py", "start")
            elif self.drone_config.mission == Mission.SMART_SWARM.value:
                logging.info("Starting Smart Swarm Mission")
                if int(self.drone_config.swarm.get('follow', 0)) != 0:
                    self.offboard_controller.start_swarm()
                    await self.offboard_controller.start_offboard_follow()
                return True, "Swarm Mission initiated"

        # Log when conditions are not met to trigger the mission
        logging.info("Conditions not met for triggering show or swarm")
        return False, "Conditions not met for show or swarm"

    async def _handle_takeoff(self):
        altitude = float(self.drone_config.takeoff_altitude)
        logging.info(f"Starting Takeoff to {altitude}m")
        return await self.run_mission_script("actions.py", f"takeoff --altitude={altitude}")

    async def _handle_land(self):
        logging.info("Starting Land")
        if int(self.drone_config.swarm.get('follow', 0)) != 0 and self.offboard_controller:
            if self.offboard_controller.is_offboard:
                logging.info("Is in Offboard mode. Attempting to stop offboard.")
                await self.offboard_controller.stop_offboard()
                await asyncio.sleep(1)
        return await self.run_mission_script("actions.py", "land")

    async def _handle_hold(self):
        logging.info("Starting Hold Position")
        return await self.run_mission_script("actions.py", "hold")

    async def _handle_test(self):
        logging.info("Starting Test")
        return await self.run_mission_script("actions.py", "test")
    
    async def _handle_reboot(self):
        logging.info("Starting Reboot")
        return await self.run_mission_script("actions.py", "reboot")

    def _log_mission_result(self, success, message):
        if (self.last_logged_mission != self.drone_config.mission) or (self.last_logged_state != self.drone_config.state):
            if message:
                log_func = logging.info if success else logging.error
                log_func(f"Mission result: {'Success' if success else 'Error'} - {message}")
            self.last_logged_mission = self.drone_config.mission
            self.last_logged_state = self.drone_config.state

    async def _reset_mission_if_needed(self, success):
        if success and self.drone_config.mission != Mission.SMART_SWARM.value:
            logging.info("Resetting mission code and state.")
            self.drone_config.mission = Mission.NONE.value
            self.drone_config.state = 0
