#!/usr/bin/env python3

import subprocess
import json
import time
import os
import logging
from logging.handlers import RotatingFileHandler
import sys

# Configuration Constants
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'known_networks.json')
SCAN_INTERVAL = int(os.getenv('SCAN_INTERVAL', '15'))  # Time between scans in seconds
SIGNAL_THRESHOLD = int(os.getenv('SIGNAL_THRESHOLD', '10'))  # dBm difference to switch networks
LOG_FILE = '/var/log/wifi_manager.log'
MAX_LOG_SIZE = 5 * 1024 * 1024  # 5 MB
BACKUP_COUNT = 3  # Number of backup log files

# Setup logging with rotation
logger = logging.getLogger()
logger.setLevel(logging.INFO)

handler = RotatingFileHandler(LOG_FILE, maxBytes=MAX_LOG_SIZE, backupCount=BACKUP_COUNT)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)

logger.addHandler(handler)

def load_known_networks():
    """
    Loads known Wi-Fi networks from a JSON configuration file.

    Returns:
        list: A list of dictionaries containing 'ssid' and 'password' keys.
    """
    if not os.path.exists(CONFIG_FILE):
        logger.error(f"Configuration file {CONFIG_FILE} not found.")
        return []
    try:
        with open(CONFIG_FILE, 'r') as f:
            networks = json.load(f)
        if not isinstance(networks, list):
            logger.error(f"Configuration file {CONFIG_FILE} is not a list of networks.")
            return []
        # Validate each network entry
        for network in networks:
            if 'ssid' not in network or 'password' not in network:
                logger.error("Each network must have 'ssid' and 'password' fields.")
                return []
        return networks
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing {CONFIG_FILE}: {e}")
        return []
    except Exception as e:
        logger.exception(f"Unexpected error while loading known networks: {e}")
        return []

def get_wifi_interface():
    """
    Dynamically detects the wireless interface.

    Returns:
        str: The name of the wireless interface, e.g., 'wlan0'.
    """
    try:
        interfaces = os.listdir('/sys/class/net/')
        for iface in interfaces:
            if iface.startswith('wlan') or iface.startswith('wifi'):
                logger.info(f"Detected wireless interface: {iface}")
                return iface
        logger.warning("No wireless interface detected. Defaulting to 'wlan0'.")
        return 'wlan0'
    except Exception as e:
        logger.exception(f"Error detecting wireless interface: {e}")
        return 'wlan0'

INTERFACE = get_wifi_interface()

def scan_wifi_networks():
    """
    Scans for available Wi-Fi networks and retrieves their signal strengths.

    Returns:
        dict: A dictionary mapping SSIDs to their signal strengths in dBm.
    """
    try:
        result = subprocess.run(['sudo', 'iwlist', INTERFACE, 'scanning'],
                                capture_output=True, text=True, check=True)
        output = result.stdout
    except subprocess.CalledProcessError as e:
        logger.error(f"Error scanning Wi-Fi networks: {e}")
        return {}
    except Exception as e:
        logger.exception(f"Unexpected error during Wi-Fi scan: {e}")
        return {}

    networks = {}
    ssid = None
    for line in output.splitlines():
        line = line.strip()
        if "ESSID" in line:
            # Extract SSID
            parts = line.split('ESSID:')
            if len(parts) > 1:
                ssid = parts[1].strip().strip('"')
            else:
                ssid = None
        elif "Signal level" in line and ssid:
            try:
                # Extract signal level (dBm)
                if "dBm" in line:
                    signal_part = line.split("Signal level=")[1].split(" dBm")[0]
                else:
                    signal_part = line.split("Signal level=")[1].split(' ')[0]
                signal_level = int(signal_part)
                networks[ssid] = signal_level
            except (IndexError, ValueError) as e:
                logger.warning(f"Failed to parse signal level for SSID '{ssid}': {e}")
            ssid = None  # Reset SSID for the next entry
    logger.debug(f"Available networks: {networks}")
    return networks

def connect_to_network(ssid, password, country='US'):
    """
    Attempts to connect to a specified Wi-Fi network.

    Args:
        ssid (str): The SSID of the target network.
        password (str): The password for the target network.
        country (str): The country code for regulatory purposes.
    """
    logger.info(f"Attempting to connect to SSID: {ssid}")
    # Generate wpa_supplicant configuration
    wpa_conf = f"""ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country={country}

network={{
    ssid="{ssid}"
    psk="{password}"
    key_mgmt=WPA-PSK
}}
"""
    temp_conf = '/tmp/wpa_supplicant.conf'
    try:
        with open(temp_conf, 'w') as f:
            f.write(wpa_conf)
        # Validate the configuration
        subprocess.run(['wpa_passphrase', ssid, password], check=True, stdout=subprocess.PIPE)
        # Replace the actual config with the temporary one
        subprocess.run(['sudo', 'cp', temp_conf, '/etc/wpa_supplicant/wpa_supplicant.conf'], check=True)
        # Restart the wpa_supplicant service
        subprocess.run(['sudo', 'wpa_cli', '-i', INTERFACE, 'reconfigure'], check=True)
        logger.info(f"Successfully connected to {ssid}")
        time.sleep(10)  # Wait for connection to establish
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to connect to {ssid}: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error while connecting to {ssid}: {e}")
    finally:
        if os.path.exists(temp_conf):
            try:
                os.remove(temp_conf)
                logger.debug(f"Temporary configuration file {temp_conf} removed.")
            except Exception as e:
                logger.warning(f"Failed to remove temporary config file {temp_conf}: {e}")

def get_current_connection_info():
    """
    Retrieves the current connected SSID and its signal strength.

    Returns:
        tuple: (current_ssid (str), signal_level (int)) or (None, None) if not connected or on error.
    """
    try:
        # Get current SSID
        ssid_result = subprocess.run(['iwgetid', '-r'],
                                     capture_output=True, text=True, check=True)
        current_ssid = ssid_result.stdout.strip()

        if not current_ssid:
            logger.info("Not connected to any network.")
            return None, None

        # Get current signal level using iwconfig
        iwconfig_result = subprocess.run(['iwconfig', INTERFACE],
                                         capture_output=True, text=True, check=True)
        for line in iwconfig_result.stdout.splitlines():
            if "Signal level" in line:
                try:
                    # Extract dBm value
                    parts = line.split("Signal level=")
                    if len(parts) > 1:
                        signal_part = parts[1].split(' ')[0]
                        if "dBm" in signal_part:
                            signal_level = int(signal_part.replace("dBm", ""))
                        else:
                            signal_level = int(signal_part)
                        logger.debug(f"Current SSID: {current_ssid}, Signal Level: {signal_level} dBm")
                        return current_ssid, signal_level
                except (IndexError, ValueError) as e:
                    logger.warning(f"Failed to parse signal level for current SSID '{current_ssid}': {e}")
        logger.warning(f"Signal level for SSID '{current_ssid}' not found.")
        return current_ssid, None
    except subprocess.CalledProcessError as e:
        logger.error(f"Error retrieving current connection info: {e}")
        return None, None
    except Exception as e:
        logger.exception(f"Unexpected error while retrieving connection info: {e}")
        return None, None

def main():
    """
    Main loop that continuously scans for available networks and manages connections.
    """
    known_networks = load_known_networks()
    if not known_networks:
        logger.error("No known networks to connect to. Exiting.")
        sys.exit(1)

    while True:
        available_networks = scan_wifi_networks()
        if not available_networks:
            logger.info("No Wi-Fi networks found.")
        else:
            # Identify the best known network available
            best_network = None
            best_signal = -100  # Initialize with a very low signal level
            for network in known_networks:
                ssid = network.get('ssid')
                password = network.get('password')
                if ssid in available_networks:
                    signal_level = available_networks[ssid]
                    if signal_level > best_signal:
                        best_signal = signal_level
                        best_network = network

            if best_network:
                current_ssid, current_signal = get_current_connection_info()

                if current_ssid:
                    # Find the signal level of the current network
                    current_network = next((net for net in known_networks if net['ssid'] == current_ssid), None)
                    if current_network and current_signal is not None:
                        # Compare signal strengths
                        signal_difference = best_signal - current_signal
                        if signal_difference >= SIGNAL_THRESHOLD:
                            logger.info(f"Found a better network '{best_network['ssid']}' ({best_signal} dBm) "
                                        f"compared to current '{current_ssid}' ({current_signal} dBm). "
                                        f"Difference: {signal_difference} dBm. Switching...")
                            connect_to_network(best_network['ssid'], best_network['password'])
                        else:
                            logger.info(f"Best available network '{best_network['ssid']}' ({best_signal} dBm) is "
                                        f"not significantly better than current '{current_ssid}' ({current_signal} dBm). "
                                        f"Difference: {signal_difference} dBm. Not switching.")
                    else:
                        logger.info(f"Current SSID '{current_ssid}' detected, but unable to determine signal strength. "
                                    f"Proceeding to connect to '{best_network['ssid']}'.")
                        connect_to_network(best_network['ssid'], best_network['password'])
                else:
                    logger.info(f"Not connected to any network. Connecting to '{best_network['ssid']}'.")
                    connect_to_network(best_network['ssid'], best_network['password'])
            else:
                logger.info("No known networks available.")
        time.sleep(SCAN_INTERVAL)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Wi-Fi manager script terminated by user.")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        sys.exit(1)
