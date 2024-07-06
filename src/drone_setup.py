import asyncio
import datetime
import logging
import time
from src.enums import *

class DroneSetup:
    MAX_RETRIES = 3  # Maximum number of retries for an action
    RETRY_DELAY = 5  # Seconds to wait before retrying an action

    def __init__(self, params, drone_config, offboard_controller):
        self.params = params
        self.drone_config = drone_config
        self.offboard_controller = offboard_controller
        self.last_logged_mission = None
        self.last_logged_state = None

    async def run_mission_script(self, command):
        """Executes drone mission commands asynchronously with retries."""
        attempt = 0
        while attempt < self.MAX_RETRIES:
            try:
                logging.info(f"Executing command: {command}, Attempt: {attempt + 1}")
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                if process.returncode == 0:
                    logging.info(f"Mission script completed successfully: {stdout.decode().strip()}")
                    return True, "Mission completed successfully."
                else:
                    logging.error(f"Mission script failed: {stderr.decode().strip()}")
                    attempt += 1
                    await asyncio.sleep(self.RETRY_DELAY)
            except Exception as e:
                logging.error(f"Exception running mission script: {e}")
                attempt += 1
                await asyncio.sleep(self.RETRY_DELAY)

        return False, "Mission failed after all retries."

    async def schedule_mission(self):
        """Schedules and executes drone missions based on the current state and mission code."""
        current_time = int(time.time())
        if self.drone_config.mission != Mission.NONE.value:
            logging.info(f"Scheduling mission at {datetime.datetime.now()}: Mission {self.drone_config.mission}, State {self.drone_config.state}")
            success, message = await self.handle_mission(current_time)
            self.log_mission_result(success, message)
            await self.reset_mission_if_needed(success)

    async def handle_mission(self, current_time):
        """Handles specific missions based on the mission code."""
        if self.drone_config.mission in [Mission.DRONE_SHOW_FROM_CSV.value, Mission.SMART_SWARM.value]:
            return await self._handle_show_or_swarm(current_time)
        elif self.drone_config.mission == Mission.TAKE_OFF.value:
            return await self._handle_takeoff()
        elif self.drone_config.mission == Mission.LAND.value:
            return await self._handle_land()
        elif self.drone_config.mission == Mission.HOLD.value:
            return await self._handle_hold()
        elif self.drone_config.mission == Mission.TEST.value:
            return await self._handle_test()
        return False, "Unknown mission type."

    async def _handle_show_or_swarm(self, current_time):
        if self.drone_config.state == 1 and current_time >= self.drone_config.trigger_time:
            self.drone_config.state = 2
            self.drone_config.trigger_time = 0
            script = "python3 offboard_multiple_from_csv.py" if self.drone_config.mission == Mission.DRONE_SHOW_FROM_CSV.value else ""
            return await self.run_mission_script(script)
        return False, "Conditions not met for show or swarm."

    async def _handle_takeoff(self):
        return await self.run_mission_script(f"python3 actions.py --action=takeoff --altitude={self.drone_config.takeoff_altitude}")

    async def _handle_land(self):
        return await self.run_mission_script("python3 actions.py --action=land")

    async def _handle_hold(self):
        return await self.run_mission_script("python3 actions.py --action=hold")

    async def _handle_test(self):
        return await self.run_mission_script("python3 actions.py --action=test")

    def log_mission_result(self, success, message):
        """Logs the result of a mission execution."""
        if self.last_logged_mission != self.drone_config.mission or self.last_logged_state != self.drone_config.state:
            log_func = logging.info if success else logging.error
            log_func(f"Mission result: {'Success' if success else 'Error'} - {message}")
            self.last_logged_mission = self.drone_config.mission
            self.last_logged_state = self.drone_config.state

    async def reset_mission_if_needed(self, success):
        """Resets the mission code and state after a successful execution."""
        if success and self.drone_config.mission != Mission.SMART_SWARM.value:
            logging.info("Resetting mission code and state.")
            self.drone_config.mission = Mission.NONE.value
            self.drone_config.state = 0

# Configuration of logging for debugging and tracing
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
