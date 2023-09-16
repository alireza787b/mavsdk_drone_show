import datetime
import requests
import os
import subprocess
import logging
import time
import asyncio
class DroneSetup:
    
    
    def __init__(self, params,drone_config, offboard_controller):
        self.drone_config = drone_config
        self.offboard_controller = offboard_controller
        self.params = params
        self.last_logged_mission = None  # Add this line
        self.last_logged_state = None  # Add this line

    def synchronize_time(self):
        if self.params.online_sync_time:
            logging.info(f"Current system time before synchronization: {datetime.datetime.now()}")
            logging.info("Attempting to synchronize time with a reliable internet source...")
            
            try:
                response = requests.get("http://worldtimeapi.org/api/ip")
                
                if response.status_code == 200:
                    server_used = response.json()["client_ip"]
                    current_time = response.json()["datetime"]
                    logging.info(f"Time server used: {server_used}")
                    logging.info(f"Time reported by server: {current_time}")
                    
                    logging.info("Setting system time...")
                    os.system(f"sudo date -s '{current_time}'")
                    
                    logging.info(f"Current system time after synchronization: {datetime.datetime.now()}")
                else:
                    logging.error("Failed to sync time with an internet source.")
            except Exception as e:
                logging.error(f"An error occurred while synchronizing time: {e}")
        else:
            logging.info(f"Using Current System Time without online synchronization: {datetime.datetime.now()}")


    def run_mission_script(self,command, subprocess_module=subprocess):
        """
        Runs the given mission script and returns a tuple (status, message).
        Status is a boolean indicating success (True) or failure (False).
        Message is a string describing the outcome or error.
        """
        try:
            subprocess_module.run(command.split(), check=True)
            logging.info("Mission script completed successfully.")
            return True, "Mission script completed successfully."
        except subprocess_module.CalledProcessError as e:
            logging.error(f"Mission script encountered an error: {e}")
            return False, f"Mission script encountered an error: {e}"
        
        
        
    def schedule_mission(self):
        """
        Schedule and execute various drone missions based on the current mission code and state.
        """
        # Get the current time
        current_time = int(time.time())
        
        # Initialize success flag and message
        success = False
        message = ""
        
        # If the mission is 1 (Drone Show) or 2 (Swarm Mission)
        if self.drone_config.mission in [1, 2]:
            if self.drone_config.state == 1 and current_time >= self.drone_config.trigger_time:
                # Update state and reset trigger time
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
        
        # If the mission is to take off to a certain altitude
        elif 10 <= self.drone_config.mission < 100:
            altitude = float(self.drone_config.mission) - 10
            altitude = min(altitude, 50)  # Limit altitude to 50m
            logging.info(f"Starting Takeoff to {altitude}m")
            success, message = self.run_mission_script(f"python3 actions.py --action=takeoff --altitude={altitude}")
        
        # If the mission is to land
        elif self.drone_config.mission == 101:
            logging.info("Starting Land")
            if int(self.drone_config.swarm.get('follow')) != 0 and self.offboard_controller:  # Check if it's a follower
                if self.offboard_controller.is_offboard:  # Check if it's in offboard mode
                    logging.info("Is in Offboard mode. Attempting to stop offboard.")
                    asyncio.run(self.offboard_controller.stop_offboard())
                    asyncio.sleep(1)
            success, message = self.run_mission_script("python3 actions.py --action=land")
        
        # If the mission is to hold the position
        elif self.drone_config.mission == 102:
            logging.info("Starting Hold Position")
            success, message = self.run_mission_script("python3 actions.py --action=hold")
        
        # If the mission is a test
        elif self.drone_config.mission == 100:
            logging.info("Starting Test")
            success, message = self.run_mission_script("python3 actions.py --action=test")
        
        # Log the outcome only once for each mission code or state change
        if (self.last_logged_mission != self.drone_config.mission) or \
           (self.last_logged_state != self.drone_config.state):
            if message:  # Only log if there's a message to display
                if success:
                    logging.info(message)
                else:
                    logging.error(f"Error: {message}")

            # Update the last logged mission and state
            self.last_logged_mission = self.drone_config.mission
            self.last_logged_state = self.drone_config.state

        # Reset mission and state if successful
        if success:
            if self.drone_config.mission != 2:  # Don't reset if it's a Smart Swarm mission
                logging.info("Resetting mission code and state.")
                self.drone_config.mission = 0
                self.drone_config.state = 0
