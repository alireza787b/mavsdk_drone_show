#src/connectivity_checker.py
from asyncio import subprocess

import logging
import threading
logger = logging.getLogger(__name__)


class ConnectivityChecker:
    def __init__(self, params, led_controller):
        self.params = params
        self.led_controller = led_controller
        self.thread = None
        self.stop_event = threading.Event()
        self.is_running = False  # Flag to prevent multiple threads

    def start(self):
        if not self.is_running:
            self.stop_event.clear()
            self.thread = threading.Thread(target=self.run)
            self.thread.start()
            self.is_running = True
            logger.info("ConnectivityChecker started.")
        else:
            logger.debug("ConnectivityChecker is already running.")

    def stop(self):
        if self.is_running:
            self.stop_event.set()
            self.thread.join()
            self.is_running = False
            logger.info("ConnectivityChecker stopped.")
        else:
            logger.debug("ConnectivityChecker is not running.")

    def run(self):
        ip = self.params.connectivity_check_ip
        interval = self.params.connectivity_check_interval
        while not self.stop_event.is_set():
            try:
                result = self.check_connectivity(ip)
                if result:
                    # Ping successful, set LED to green
                    self.led_controller.set_color(0, 255, 0)  # Green
                    logger.debug("Connectivity check successful. LED set to blue.")
                else:
                    # Ping failed, set LED to red
                    self.led_controller.set_color(255, 0, 0)  # Red
                    logger.warning("Connectivity check failed. LED set to red.")
            except Exception as e:
                logger.error(f"Error in connectivity check: {e}")
            # Wait for the interval or until stop_event is set
            self.stop_event.wait(interval)

    @staticmethod
    def check_connectivity(ip):
        try:
            # Use the 'ping' command to check connectivity
            output = subprocess.check_output(['ping', '-c', '1', '-W', '1', ip], stderr=subprocess.STDOUT)
            return True
        except subprocess.CalledProcessError:
            return False
        except Exception as e:
            logger.error(f"Exception in check_connectivity: {e}")
            return False