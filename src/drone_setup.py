#src/drone_setup.py
import asyncio
import datetime
import logging
import time
from enum import Enum
from src.enums import *

class DroneSetup:
    def __init__(self, params, drone_config, offboard_controller):
        self.params = params
        self.drone_config = drone_config
        self.offboard_controller = offboard_controller
        self.last_logged_mission = None
        self.last_logged_state = None

    async def run_mission_script(self, command):
        """
        Runs the given mission script asynchronously.
        Returns a tuple (status, message).
        """
        logging.info(f"Executing command: {command}")
        try:
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

        if True or self.drone_config.mission != Mission.NONE.value:
            logging.info(f"Scheduling mission at {datetime.datetime.fromtimestamp(current_time)}. "
                         f"Current mission: {Mission(self.drone_config.mission).name}, State: {self.drone_config.state}")
        print(self.drone_config.mission.name)
        try:
            if self.drone_config.mission in [Mission.DRONE_SHOW_FROM_CSV.value, Mission.SMART_SWARM.value]:
                print("detected droneshow or swarm")
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

            if self.drone_config.mission == Mission.DRONE_SHOW_FROM_CSV.value:
                logging.info("Starting Drone Show")
                return await self.run_mission_script("python3 offboard_multiple_from_csv.py")
            elif self.drone_config.mission == Mission.SMART_SWARM.value:
                logging.info("Starting Swarm Mission")
                if int(self.drone_config.swarm.get('follow', 0)) != 0:
                    self.offboard_controller.start_swarm()
                    await self.offboard_controller.start_offboard_follow()
                return True, "Swarm Mission initiated"
        return False, "Conditions not met for show or swarm"

    async def _handle_takeoff(self):
        altitude = float(self.drone_config.takeoff_altitude)
        logging.info(f"Starting Takeoff to {altitude}m")
        return await self.run_mission_script(f"python3 actions.py --action=takeoff --altitude={altitude}")

    async def _handle_land(self):
        logging.info("Starting Land")
        if int(self.drone_config.swarm.get('follow', 0)) != 0 and self.offboard_controller:
            if self.offboard_controller.is_offboard:
                logging.info("Is in Offboard mode. Attempting to stop offboard.")
                await self.offboard_controller.stop_offboard()
                await asyncio.sleep(1)
        return await self.run_mission_script("python3 actions.py --action=land")

    async def _handle_hold(self):
        logging.info("Starting Hold Position")
        return await self.run_mission_script("python3 actions.py --action=hold")

    async def _handle_test(self):
        logging.info("Starting Test")
        return await self.run_mission_script("python3 actions.py --action=test")

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