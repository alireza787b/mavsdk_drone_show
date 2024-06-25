# src/telemetry_subscription_manager.py
import threading
import time
import requests
import logging
from src.params import Params

class TelemetrySubscriptionManager:
    def __init__(self, drones):
        self.drones = drones
        self.subscriptions = {}  # Dictionary to hold subscription info
        self.polling_threads = {}  # Dictionary to hold polling threads
        self.stop_flag = threading.Event()
        self.default_polling_rate = Params.polling_interval  # Default polling rate from Params

    def add_subscription(self, hw_id, rate=None):
        if rate is None:
            rate = self.default_polling_rate

        if hw_id in self.subscriptions:
            logging.info(f"Updating subscription for drone {hw_id} with new rate {rate}")
        else:
            logging.info(f"Adding subscription for drone {hw_id} with rate {rate}")

        self.subscriptions[hw_id] = rate
        self._start_polling_thread(hw_id, rate)

    def remove_subscription(self, hw_id):
        if hw_id in self.subscriptions:
            logging.info(f"Removing subscription for drone {hw_id}")
            self.subscriptions.pop(hw_id)
            self._stop_polling_thread(hw_id)

    def _start_polling_thread(self, hw_id, rate):
        if hw_id in self.polling_threads:
            self._stop_polling_thread(hw_id)  # Stop existing thread if it exists

        polling_thread = threading.Thread(target=self._poll_drone_state, args=(hw_id, rate))
        self.polling_threads[hw_id] = polling_thread
        polling_thread.start()

    def _stop_polling_thread(self, hw_id):
        if hw_id in self.polling_threads:
            logging.info(f"Stopping polling thread for drone {hw_id}")
            self.polling_threads[hw_id].join()  # Wait for the thread to finish
            del self.polling_threads[hw_id]

    def _poll_drone_state(self, hw_id, rate):
        while not self.stop_flag.is_set() and hw_id in self.subscriptions:
            drone = self.drones.get(hw_id)
            if drone:
                try:
                    response = requests.get(f"http://{drone['ip']}:{Params.drones_flask_port}/{Params.get_drone_state_URI}", timeout=Params.HTTP_REQUEST_TIMEOUT)
                    if response.status_code == 200:
                        telemetry_data = response.json()
                        logging.info(f"Received telemetry data for drone {hw_id}: {telemetry_data}")
                        # Process and update the drone state here
                        drone.update(telemetry_data)
                        logging.info(f"Successfully polled telemetry from new drone {hw_id}")
                    else:
                        logging.warning(f"Failed to get telemetry data from drone {hw_id}: {response.text}")
                except requests.RequestException as e:
                    logging.error(f"Error polling telemetry from drone {hw_id}: {e}")
            time.sleep(rate)


    def stop_all(self):
        self.stop_flag.set()
        for hw_id in list(self.polling_threads.keys()):
            self._stop_polling_thread(hw_id)
    def subscribe_to_all(self, rate=None):
        logging.info("Subscribing to all drones")
        for hw_id in self.drones.keys():
            self.add_subscription(hw_id, rate)

    def unsubscribe_from_all(self):
        logging.info("Unsubscribing from all drones")
        for hw_id in list(self.subscriptions.keys()):
            self.remove_subscription(hw_id)