import logging
import socket
import threading
from src.params import Params

logger = logging.getLogger(__name__)

class ConnectivityChecker:
    """
    ConnectivityChecker periodically verifies connectivity to a specified IP address by attempting
    a TCP connection. It updates the LED color based on the connectivity status: green for connected,
    red for disconnected.
    """
    # Class variable for the default connectivity check port (default is 80)
    DEFAULT_PORT = 80

    def __init__(self, params, led_controller):
        """
        Initializes the ConnectivityChecker.

        Args:
            params (Params): Parameters object containing configuration settings.
            led_controller: Instance of LEDController to control the drone's LEDs.
        """
        self.params = params
        self.led_controller = led_controller
        self.thread = None
        self.stop_event = threading.Event()
        self.is_running = False  # Flag to prevent multiple threads
        # Set the port either from params (if defined) or use the default port.
        self.port = getattr(params, 'connectivity_check_port', ConnectivityChecker.DEFAULT_PORT)

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
                    # Connection successful, set LED to green.
                    self.led_controller.set_color(0, 255, 0)  # Green
                    logger.debug("Connectivity check successful. LED set to green.")
                else:
                    # Connection failed, set LED to red.
                    self.led_controller.set_color(255, 0, 0)  # Red
                    logger.warning("Connectivity check failed. LED set to red.")
            except Exception as e:
                logger.error(f"Error in connectivity check: {e}")
            # Wait for the specified interval or until stop_event is set.
            self.stop_event.wait(interval)

    def check_connectivity(self, ip):
        """
        Checks connectivity by attempting a TCP connection to the specified IP address.
        Uses the port from params if available; otherwise, the default port is used.
        A 1-second timeout is applied.

        Args:
            ip (str): IP address to check connectivity with.

        Returns:
            bool: True if the connection is successful, False otherwise.
        """
        try:
            if self.params.sim_mode:
                return True

            logger.debug(f"Attempting TCP connection to {ip}:{self.port}")
            # Attempt a TCP connection with a 1-second timeout.
            with socket.create_connection((ip, self.port), timeout=1):
                logger.debug("TCP connection successful.")
                return True
        except Exception as e:
            logger.error(f"Exception in check_connectivity: {e}")
            return False
