# src/heartbeat_sender.py
import threading
import time
import logging
import requests
import socket
import netifaces

from src.params import Params
from src.drone_config import DroneConfig

class HeartbeatSender:
    """
    Periodically sends a POST request (heartbeat) to GCS with
    timestamp, hw_id, pos_id, and discovered Netbird IP.
    """

    def __init__(self, drone_config: DroneConfig):
        self.drone_config = drone_config
        self.interval = Params.heartbeat_interval
        self.gcs_ip = self.drone_config.config.get('gcs_ip', None)
        self.gcs_port = Params.flask_telem_socket_port  # or a separate param if you prefer
        self.running = False
        self.thread = None

    def start(self):
        """
        Start the heartbeat thread.
        """
        if not self.gcs_ip:
            logging.warning("GCS IP not found in drone config. Heartbeat will not start.")
            return

        if self.running:
            logging.warning("HeartbeatSender is already running.")
            return

        self.running = True
        self.thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self.thread.start()
        logging.info("HeartbeatSender started.")

    def stop(self):
        """
        Stop the heartbeat thread.
        """
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)
        logging.info("HeartbeatSender stopped.")

    def _heartbeat_loop(self):
        """
        Main loop that sends heartbeats every `self.interval` seconds.
        """
        while self.running:
            try:
                self.send_heartbeat()
            except Exception as e:
                logging.error(f"HeartbeatSender encountered an error: {e}", exc_info=True)
            time.sleep(self.interval)

    def send_heartbeat(self):
        """
        Sends a single HTTP POST request with minimal data:
        - hw_id
        - pos_id
        - current Netbird IP (or fallback to CSV ip)
        - timestamp
        """
        hw_id = self.drone_config.hw_id
        pos_id = self.drone_config.pos_id
        detected_pos_id = self.drone_config.detected_pos_id

        # Attempt to discover the Netbird IP that starts with "100."
        netbird_ip = self._get_netbird_ip()
        if not netbird_ip:
            # Fallback to the IP from config.csv if no netbird IP found
            netbird_ip = self.drone_config.config.get('ip', 'unknown')

        data = {
            "hw_id": hw_id,
            "pos_id": pos_id,
            "detected_pos_id":detected_pos_id,
            "ip": netbird_ip,
            "timestamp": int(time.time() * 1000),  # ms precision
        }

        url = f"http://{self.gcs_ip}:{self.gcs_port}{Params.gcs_heartbeat_endpoint}"
        logging.debug(f"Sending heartbeat to {url} with data={data}")
        
        try:
            resp = requests.post(url, json=data, timeout=3)
            if resp.status_code == 200:
                logging.info(f"Heartbeat OK: hw_id={hw_id}, ip={netbird_ip}")
            else:
                logging.warning(f"Heartbeat failed with status {resp.status_code}: {resp.text}")
        except requests.RequestException as e:
            logging.error(f"Heartbeat request exception: {e}")

    def _get_netbird_ip(self):
        """
        Inspects all network interfaces, searching for an IPv4 address
        that starts with the netbird prefix (e.g. 100.xxx).
        Returns None if no matching IP is found.
        """
        netbird_prefix = Params.netbird_ip_prefix  # e.g. "100."
        try:
            interfaces = netifaces.interfaces()
            for iface in interfaces:
                addrs = netifaces.ifaddresses(iface).get(netifaces.AF_INET, [])
                for addr_info in addrs:
                    ip_addr = addr_info.get('addr', '')
                    if ip_addr.startswith(netbird_prefix):
                        return ip_addr
            return None
        except Exception as e:
            logging.error(f"Failed to retrieve Netbird IP: {e}", exc_info=True)
            return None
