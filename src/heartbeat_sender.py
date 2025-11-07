# src/heartbeat_sender.py
import threading
import time
import logging
import requests
import socket
import netifaces
import subprocess

from src.params import Params
from src.drone_config import DroneConfig

class HeartbeatSender:
    """
    Periodically sends a POST request (heartbeat) to GCS with
    timestamp, hw_id, pos_id,detected_pos_id, and discovered Netbird IP.
    """

    def __init__(self, drone_config: DroneConfig):
        self.drone_config = drone_config
        self.interval = Params.heartbeat_interval
        self.gcs_ip = Params.GCS_IP  # Use centralized GCS IP from Params
        self.gcs_port = Params.GCS_FLASK_PORT
        self.running = False
        self.thread = None

    def start(self):
        """
        Start the heartbeat thread.
        """
        if not self.gcs_ip:
            logging.warning("GCS IP not configured in Params. Heartbeat will not start.")
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
        - detected_pos_id
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

        # Get comprehensive network info for heartbeat
        network_info = self._get_network_info()

        data = {
            "hw_id": hw_id,
            "pos_id": pos_id,
            "detected_pos_id": detected_pos_id,
            "ip": netbird_ip,
            "timestamp": int(time.time() * 1000),  # ms precision
            "network_info": network_info  # Include network details
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

    def _get_network_info(self):
        """
        Fetch comprehensive network information for heartbeat.
        Returns Wi-Fi and Ethernet details with current status.
        """
        try:
            # Gather Wi-Fi information with active status, SSID, and signal strength
            wifi_info = subprocess.check_output(
                ["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL", "dev", "wifi"],
                universal_newlines=True
            )

            # Gather Wired LAN information
            eth_connection = subprocess.check_output(
                ["nmcli", "-t", "-f", "device,state,connection", "device", "status"],
                universal_newlines=True
            )

            # Initialize network info structure
            network_info = {
                "wifi": None,
                "ethernet": None,
                "timestamp": int(time.time() * 1000)
            }

            # Extract Wi-Fi details
            active_wifi_ssid = None
            active_wifi_signal = None
            for line in wifi_info.splitlines():
                parts = line.split(':')
                if len(parts) >= 3 and parts[0].lower() == 'yes':
                    active_wifi_ssid = parts[1]
                    active_wifi_signal = parts[2]
                    break

            # If Wi-Fi is connected, add it to network info
            if active_wifi_ssid:
                signal_strength = int(active_wifi_signal) if active_wifi_signal.isdigit() else 0
                network_info["wifi"] = {
                    "ssid": active_wifi_ssid,
                    "signal_strength_percent": signal_strength
                }

            # Extract Ethernet details
            active_eth_connection = None
            active_eth_device = None
            for line in eth_connection.splitlines():
                parts = line.split(':')
                if len(parts) >= 3 and parts[1].lower() == 'connected' and 'eth' in parts[0].lower():
                    active_eth_device = parts[0]
                    active_eth_connection = parts[2]
                    break

            # If Ethernet is connected, add it to network info
            if active_eth_device and active_eth_connection:
                network_info["ethernet"] = {
                    "interface": active_eth_device,
                    "connection_name": active_eth_connection
                }

            return network_info

        except subprocess.CalledProcessError as e:
            logging.warning(f"Failed to get network info for heartbeat: {e}")
            return {
                "wifi": None,
                "ethernet": None,
                "timestamp": int(time.time() * 1000),
                "error": f"Command failed: {e}"
            }
        except Exception as e:
            logging.error(f"Unexpected error getting network info for heartbeat: {e}")
            return {
                "wifi": None,
                "ethernet": None,
                "timestamp": int(time.time() * 1000),
                "error": f"Unexpected error: {e}"
            }
