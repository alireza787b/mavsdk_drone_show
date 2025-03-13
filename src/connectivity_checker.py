import logging
import threading
import requests  # Make sure requests is installed
from src.params import Params

logger = logging.getLogger(__name__)

class ConnectivityChecker:
    """
    ConnectivityChecker periodically verifies connectivity by making an HTTP GET
    request to a specified endpoint on the GCS server. It updates the LED color based on
    the connectivity status: green for connected, red for disconnected.
    """
    # Class variable for the default HTTP endpoint path (e.g., '/ping')
    DEFAULT_ENDPOINT = "/ping"

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
        # Optionally, you can add a connectivity_check_endpoint in your Params; otherwise use default.
        self.endpoint = getattr(params, 'connectivity_check_endpoint', ConnectivityChecker.DEFAULT_ENDPOINT)
        # Use a port from params if available, else fall back to flask_telem_socket_port (or a default value)
        self.port = getattr(params, 'flask_telem_socket_port', 5000)

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
        # Use the connectivity_check_ip from params (should be set to your GCS server IP)
        ip = self.params.connectivity_check_ip
        interval = self.params.connectivity_check_interval
        while not self.stop_event.is_set():
            try:
                result = self.check_connectivity(ip)
                if result:
                    # Connection successful, set LED to green
                    self.led_controller.set_color(0, 255, 0)  # Green
                    logger.debug("Connectivity check successful. LED set to green.")
                else:
                    # Connection failed, set LED to purple
                    self.led_controller.set_color(255, 0, 255)  # purple
                    logger.warning("Connectivity check failed. LED set to purple.")
            except Exception as e:
                logger.error(f"Error in connectivity check: {e}")
            # Wait for the specified interval or until stop_event is set
            self.stop_event.wait(interval)

    def check_connectivity(self, ip):
        """
        Checks connectivity by making an HTTP GET request to the GCS server's ping endpoint.
        A 1-second timeout is applied.

        Args:
            ip (str): IP address of the GCS server.

        Returns:
            bool: True if the HTTP request is successful (status code 200), False otherwise.
        """
        try:
            if self.params.sim_mode:
                return True

            # Build the URL: e.g., http://<ip>:<port>/ping
            url = f"http://{ip}:{self.port}{self.endpoint}"
            logger.debug(f"Attempting HTTP GET to {url}")
            response = requests.get(url, timeout=1)
            if response.status_code == 200:
                logger.debug("HTTP GET successful, connectivity confirmed.")
                return True
            else:
                logger.error(f"HTTP GET returned status code {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Exception in check_connectivity: {e}")
            return False
