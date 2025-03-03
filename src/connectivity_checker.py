# src/connectivity_checker.py

import logging
import threading
import subprocess
from src.params import Params

logger = logging.getLogger(__name__)

class ConnectivityChecker:
    """
    ConnectivityChecker periodically pings a specified IP address to check internet connectivity.
    It updates the LED color based on the connectivity status: blue for connected, red for disconnected.
    """

    def __init__(self, params, led_controller):
        """
        Initializes the ConnectivityChecker.

        Args:
            params: Parameters object containing configuration settings.
            led_controller: Instance of LEDController to control the drone's LEDs.
        """
        self.params = params
        self.led_controller = led_controller
        self.thread = None
        self.stop_event = threading.Event()
        self.is_running = False  # Flag to prevent multiple threads

    def start(self):
        """
        Starts the connectivity checking thread if it's not already running.
        """
        if not self.is_running:
            self.stop_event.clear()
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()
            self.is_running = True
            logger.info("ConnectivityChecker started.")
        else:
            logger.debug("ConnectivityChecker is already running.")

    def stop(self):
        """
        Stops the connectivity checking thread if it's running.
        """
        if self.is_running:
            self.stop_event.set()
            self.thread.join()
            self.is_running = False
            logger.info("ConnectivityChecker stopped.")
        else:
            logger.debug("ConnectivityChecker is not running.")

    def run(self):
        """
        Thread target function that performs the connectivity check at specified intervals.
        """
        ip = self.params.connectivity_check_ip
        interval = self.params.connectivity_check_interval
        while not self.stop_event.is_set():
            try:
                result = self.check_connectivity(ip)
                if result:
                    # Ping successful, set LED to green
                    self.led_controller.set_color(0, 255, 0)  # Green
                    logger.debug("Connectivity check successful. LED set to green.")
                else:
                    # Ping failed, set LED to purple
                    self.led_controller.set_color(255, 0, 255)  # Purple
                    logger.warning("Connectivity check failed. LED set to red.")
            except Exception as e:
                logger.error(f"Error in connectivity check: {e}")
            # Wait for the interval or until stop_event is set
            self.stop_event.wait(interval)

    @staticmethod
    def check_connectivity(ip):
        """
        Checks connectivity by pinging the specified IP address.

        Args:
            ip (str): IP address to ping.

        Returns:
            bool: True if ping is successful, False otherwise.
        """
        try:
            # Use the 'ping' command to check connectivity
            if Params.sim_mode:
                return True
            else:
                output = subprocess.check_output(['ping', '-c', '1', '-W', '1', ip], stderr=subprocess.STDOUT)
                return True
        except subprocess.CalledProcessError:
            return False
        except Exception as e:
            logger.error(f"Exception in check_connectivity: {e}")
            return False
