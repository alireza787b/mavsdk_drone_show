# src/pos_id_auto_detector.py
import threading
import time
import logging
import math

import numpy as np
from src.params import Params
from src.flask_handler import FlaskHandler  # Assuming FlaskHandler has _get_origin_from_gcs method
import navpy

class PosIDAutoDetector:
    """
    Handles the automatic detection of pos_id based on the drone's current position.
    """
    def __init__(self, drone_config, params, flask_handler):
        self.drone_config = drone_config
        self.params = params
        self.flask_handler = flask_handler
        self.running = False
        self.thread = None
        self.logger = logging.getLogger(self.__class__.__name__)

    def start(self):
        """
        Start the auto-detection thread.
        """
        if not self.params.auto_detection_enabled:
            self.logger.info("PosIDAutoDetector is disabled via parameters.")
            return

        if self.running:
            self.logger.warning("PosIDAutoDetector is already running.")
            return

        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.logger.info("PosIDAutoDetector started.")

    def stop(self):
        """
        Stop the auto-detection thread.
        """
        if not self.running:
            self.logger.warning("PosIDAutoDetector is not running.")
            return

        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)
        self.logger.info("PosIDAutoDetector stopped.")

    def _run(self):
        """
        Main loop for auto-detection.
        """
        self.logger.debug("PosIDAutoDetector thread running.")
        while self.running:
            try:
                self.detect_pos_id()
            except Exception as e:
                self.logger.error(f"Error in PosIDAutoDetector: {e}", exc_info=True)
            time.sleep(self.params.auto_detection_interval)

    def detect_pos_id(self):
        """
        Perform the pos_id detection logic.
        """
        self.logger.debug("Starting pos_id detection process.")

        # Fetch origin from GCS
        origin = self.flask_handler._get_origin_from_gcs()
        if not origin:
            self.logger.warning("Origin data unavailable. Skipping pos_id detection.")
            return

        origin_lat = origin['lat']
        origin_lon = origin['lon']
        origin_alt = self.drone_config.position.get('alt', 0)

        # Get drone's current position
        drone_lat = self.drone_config.position.get('lat', 0)
        drone_lon = self.drone_config.position.get('long', 0)
        drone_alt = self.drone_config.position.get('alt', 0)

        if drone_lat == 0 and drone_lon == 0:
            self.logger.warning("Drone's GPS data unavailable. Skipping pos_id detection.")
            return

        # Convert global coordinates to local NED
        try:
            # Using navpy to compute ENU coordinates
            e, n, u = navpy.enu(
                np.array([drone_lat]),
                np.array([drone_lon]),
                np.array([drone_alt]),
                origin_lat,
                origin_lon,
                origin_alt,
                ell=None
            )
            # Convert ENU to NED
            x = n[0]  # North
            y = e[0]  # East
            self.logger.debug(f"Computed local NED offsets: x={x:.2f}, y={y:.2f}")
        except Exception as e:
            self.logger.error(f"Error converting coordinates: {e}", exc_info=True)
            return

        # Find the closest (x, y) in all_configs
        min_distance = float('inf')
        best_pos_id = 0  # Default to 0 indicating failure
        for pos_id, coords in self.drone_config.all_configs.items():
            dx = x - coords['x']
            dy = y - coords['y']
            distance = math.sqrt(dx**2 + dy**2)
            self.logger.debug(f"Comparing with pos_id={pos_id}: distance={distance:.2f}")
            if distance < min_distance:
                min_distance = distance
                best_pos_id = pos_id

        self.logger.info(f"Closest pos_id detected: {best_pos_id} with distance {min_distance:.2f} meters.")

        # Check if the distance is within the maximum allowed deviation
        if min_distance > self.params.max_deviation:
            best_pos_id = 0  # Indicate failure
            self.logger.warning(f"Minimum distance {min_distance:.2f} exceeds max_deviation {self.params.max_deviation}. Setting detected_pos_id to 0.")

        # Update detected_pos_id
        previous_detected_pos_id = self.drone_config.detected_pos_id
        self.drone_config.detected_pos_id = best_pos_id
        self.logger.debug(f"Updated detected_pos_id from {previous_detected_pos_id} to {best_pos_id}.")

        # Compare with actual pos_id and warn if different
        if best_pos_id != self.drone_config.pos_id:
            self.logger.warning(f"Detected pos_id ({best_pos_id}) does not match configured pos_id ({self.drone_config.pos_id}).")
            # Optionally, notify the operator via UI or other mechanisms here

