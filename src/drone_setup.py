import datetime
import requests
import os
import subprocess
import logging
import time
import asyncio

from src.params import Params

class DroneSetup:
    def __init__(self, params, drone_config, offboard_controller):
        """
        Initialize the DroneSetup class with the given parameters, drone configuration, and offboard controller.
        """
        self.params = params
        self.drone_config = drone_config
        self.offboard_controller = offboard_controller
        self.last_logged_mission = None
        self.last_logged_state = None

    def synchronize_time(self):
        """
        Synchronize the system time using an external shell script.
        """
        logging.info("Attempting to synchronize time using shell script...")

        try:
            # Execute the shell script and capture the output
            result = subprocess.run(['bash', 'tools/sync_time_linux.sh'], capture_output=True, text=True)

            if result.returncode == 0:
                logging.info("Time synchronization successful.")
                print("Shell script output:")
                print(result.stdout)  # Printing the output from the shell script to the terminal
            else:
                logging.error("Failed to execute time synchronization script.")
                print("Shell script output (stderr):")
                print(result.stderr)  # Printing the error output from the shell script to the terminal

        except Exception as e:
            logging.error(f"An error occurred while running the time synchronization script: {e}")
            print(f"Error running shell script: {e}")

        finally:
            # Always log the final action, whether success or failure
            logging.info("Time synchronization attempt completed.")

    def run_mission_script(self, command, subprocess_module=subprocess):
        """
        Runs the given mission script and returns a tuple (status, message).
        Status is a boolean indicating success (True) or failure (False).
        Message is a string describing the outcome or error.
        """
        logging.info(f"Executing command: {command}")
        try:
            result = subprocess_module.run(command.split(), check=True, capture_output=True, text=True)
            logging.info(f"Mission script completed successfully. Output: {result.stdout}")
            return True, "Mission script completed successfully."
        except subprocess_module.CalledProcessError as e:
            logging.error(f"Mission script encountered an error: {e}. Stderr: {e.stderr}")
            return False, f"Mission script encountered an error: {e}"

    def schedule_mission(self):
        """
        Schedule and execute various drone missions based on the current mission code and state.
        """
        current_time = int(time.time())
        success = False
        message = ""

        logging.info(f"Scheduling mission at {datetime.datetime.fromtimestamp(current_time)}. "
                     f"Current mission: {self.drone_config.mission}, State: {self.drone_config.state}")

        if self.drone_config.mission in [1, 2]:
            if self.drone_config.state == 1 and current_time >= self.drone_config.trigger_time:
                self.drone_config.state = 2
                self.drone_config.trigger_time = 0

                if self.drone_config.mission == 1:
                    logging.info("Starting Drone Show")
                    success, message = self.run_mission_script("python3 offboard_multiple_from_csv.py")
                elif self.drone_config.mission == 2:
                    logging.info("Starting Swarm Mission")
                    if int(self.drone_config.swarm.get('follow')) != 0:
                        self.offboard_controller.start_swarm()
                        asyncio.run(self.offboard_controller.start_offboard_follow())
                    success, message = True, "Assumed success for Swarm Mission."

        elif self.drone_config.mission == 10:  # Constant takeoff command
            altitude = float(self.drone_config.assignedAltitude)
            logging.info(f"Starting Takeoff to {altitude}m")
            success, message = self.run_mission_script(f"python3 actions.py --action=takeoff --altitude={altitude}")
        
        elif self.drone_config.mission == 101:
            logging.info("Starting Land")
            if int(self.drone_config.swarm.get('follow')) != 0 and self.offboard_controller:
                if self.offboard_controller.is_offboard:
                    logging.info("Is in Offboard mode. Attempting to stop offboard.")
                    asyncio.run(self.offboard_controller.stop_offboard())
                    asyncio.sleep(1)
            success, message = self.run_mission_script("python3 actions.py --action=land")

        elif self.drone_config.mission == 102:
            logging.info("Starting Hold Position")
            success, message = self.run_mission_script("python3 actions.py --action=hold")

        elif self.drone_config.mission == 100:
            logging.info("Starting Test")
            success, message = self.run_mission_script("python3 actions.py --action=test")

        if (self.last_logged_mission != self.drone_config.mission) or (self.last_logged_state != self.drone_config.state):
            if message:
                if success:
                    logging.info(message)
                else:
                    logging.error(f"Error: {message}")

            self.last_logged_mission = self.drone_config.mission
            self.last_logged_state = self.drone_config.state

        if success:
            if self.drone_config.mission != 2:
                logging.info("Resetting mission code and state.")
                self.drone_config.mission = 0
                self.drone_config.state = 0

