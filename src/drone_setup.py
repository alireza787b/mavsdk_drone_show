import asyncio
import datetime
import logging
import time
from enum import Enum
from src.enums import *
from actions import perform_action_with_retries

class DroneSetup:
    def __init__(self, params, drone_config, offboard_controller):
        self.params = params
        self.drone_config = drone_config
        self.offboard_controller = offboard_controller
        self.last_logged_mission = None
        self.last_logged_state = None

    async def run_mission_script(self, command, retries=3, retry_interval=5):
        """
        Runs the given mission script asynchronously with retry mechanism.
        Returns a tuple (status, message).
        """
        logging.info(f"Executing command: {command}")
        try:
            for attempt in range(retries):
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0:
                    logging.info(f"Mission script completed successfully. Output: {stdout.decode().strip()}")
                    return True, "Mission script completed successfully."
                else:
                    logging.error(f"Mission script encountered an error. Stderr: {stderr.decode().strip()}")
                    if attempt < retries - 1:
                        logging.info(f"Retrying mission script after {retry_interval} seconds...")
                        await asyncio.sleep(retry_interval)
                    else:
                        return False, f"Mission script error: {stderr.decode().strip()}"
        except Exception as e:
            logging.error(f"Exception in run_mission_script: {e}")
            return False, f"Exception: {str(e)}"

    async def schedule_mission(self):
        """
        Schedule and execute various drone missions based on the current mission code and state.
        """
        current_time = int(time.time())
        success = False
        message = ""

        if self.drone_config.mission != Mission.NONE.value:
            logging.info(f"Scheduling mission at {datetime.datetime.fromtimestamp(current_time)}. "
                         f"Current mission: {Mission(self.drone_config.mission).name}, State: {self.drone_config.state}")

        try:
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

            self._log_mission_result(success, message)
            await self._reset_mission_if_needed(success)  # double check later in what condition should we retry

        except Exception as e:
            logging.error(f"Exception in schedule_mission: {e}")

    async def _handle_show_or_swarm(self, current_time):
        if self.drone_config.state == 1 and current_time >= self.drone_config.trigger_time:
            self.drone_config.state = 2
            self.drone_config.trigger_time = 0

            if self.drone_config
