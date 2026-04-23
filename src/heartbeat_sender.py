# src/heartbeat_sender.py
import threading
import time
import requests
import socket
import netifaces
import subprocess

from mds_logging import get_logger
from src.params import Params
from src.drone_config import DroneConfig

logger = get_logger("heartbeat")

class HeartbeatSender:
    """
    Periodically sends a POST request (heartbeat) to GCS with
    timestamp, hw_id, pos_id,detected_pos_id, and discovered Netbird IP.
    """
    # Class-level flags to prevent log spam for expected SITL failures
    _network_info_error_logged = False
    _netbird_error_logged = False
    _gcs_connection_error_logged = False
    _gcs_connected = False

    def __init__(self, drone_config: DroneConfig):
        self.drone_config = drone_config
        self.interval = Params.heartbeat_interval
        self.gcs_ip = Params.GCS_IP  # Use centralized GCS IP from Params
        self.gcs_port = Params.gcs_api_port
        self.running = False
        self.thread = None

    def start(self):
        """
        Start the heartbeat thread.
        """
        if not self.gcs_ip:
            logger.warning("GCS IP not configured in Params. Heartbeat will not start.")
            return

        if self.running:
            logger.warning("HeartbeatSender is already running.")
            return

        self.running = True
        self.thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self.thread.start()
        logger.info("HeartbeatSender started.")

    def stop(self):
        """
        Stop the heartbeat thread.
        """
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)
        logger.info("HeartbeatSender stopped.")

    def _heartbeat_loop(self):
        """
        Main loop that sends heartbeats every `self.interval` seconds.
        """
        while self.running:
            try:
                self.send_heartbeat()
            except Exception as e:
                logger.error(f"HeartbeatSender encountered an error: {e}", exc_info=True)
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
        # API payloads use string IDs for backward compatibility across mixed
        # drone/GCS versions, even though local config stores hw_id as int.
        hw_id = str(self.drone_config.hw_id)
        pos_id = self.drone_config.pos_id
        detected_pos_id = self.drone_config.detected_pos_id

        # Attempt to discover the Netbird IP that starts with "100."
        netbird_ip = self._get_netbird_ip()
        if not netbird_ip:
            # Fallback to the IP from config if no netbird IP found
            netbird_ip = self.drone_config.config.get('ip', 'unknown')

        # Get comprehensive network info for heartbeat
        network_info = self._get_network_info()

        data = {
            "hw_id": hw_id,
            "pos_id": pos_id,
            "detected_pos_id": detected_pos_id,
            "ip": netbird_ip,
            "timestamp": int(time.time() * 1000),  # ms precision
            "network_info": network_info,  # Include network details
            "runtime_mode": Params.runtime_mode,
        }

        url = f"http://{self.gcs_ip}:{self.gcs_port}{Params.gcs_heartbeat_endpoint}"
        logger.debug(f"Sending heartbeat to {url} with data={data}")
        
        try:
            resp = requests.post(url, json=data, timeout=3)
            if resp.status_code == 200:
                if not HeartbeatSender._gcs_connected:
                    HeartbeatSender._gcs_connected = True
                    HeartbeatSender._gcs_connection_error_logged = False
                    logger.info(f"Heartbeat connected to GCS: hw_id={hw_id}, ip={netbird_ip}")
                else:
                    logger.debug(f"Heartbeat OK: hw_id={hw_id}, ip={netbird_ip}")
            else:
                logger.warning(f"Heartbeat failed with status {resp.status_code}: {resp.text}")
        except requests.RequestException as e:
            HeartbeatSender._gcs_connected = False
            if not HeartbeatSender._gcs_connection_error_logged:
                HeartbeatSender._gcs_connection_error_logged = True
                logger.warning(f"GCS unreachable (will retry silently): {e}")
            else:
                logger.debug(f"Heartbeat request exception: {e}")

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
            # No netbird IP found - this is expected in SITL/Docker
            return None
        except Exception as e:
            # Log once to avoid spam, use appropriate level for SITL
            if not HeartbeatSender._netbird_error_logged:
                HeartbeatSender._netbird_error_logged = True
                if Params.sim_mode:
                    logger.debug(f"Netbird IP not available (expected in SITL): {e}")
                else:
                    logger.warning(f"Failed to retrieve Netbird IP: {e}")
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

        except (subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
            # nmcli not available - expected in SITL/Docker environments
            # Log once to avoid spam
            if not HeartbeatSender._network_info_error_logged:
                HeartbeatSender._network_info_error_logged = True
                if Params.sim_mode:
                    logger.debug(f"nmcli not available (expected in SITL): {e}")
                else:
                    logger.warning(f"Network info unavailable: {e}")
            return {
                "wifi": None,
                "ethernet": None,
                "timestamp": int(time.time() * 1000)
            }
        except Exception as e:
            # Unexpected errors still logged, but only once
            if not HeartbeatSender._network_info_error_logged:
                HeartbeatSender._network_info_error_logged = True
                logger.warning(f"Unexpected error getting network info: {e}")
            return {
                "wifi": None,
                "ethernet": None,
                "timestamp": int(time.time() * 1000)
            }
