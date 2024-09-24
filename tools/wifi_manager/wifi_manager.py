#!/usr/bin/env python3

import subprocess
import json
import time
import os

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'known_networks.json')
SCAN_INTERVAL = 15  # Time between scans in seconds
INTERFACE = 'wlan0'  # Wi-Fi interface name

def load_known_networks():
    with open(CONFIG_FILE, 'r') as f:
        networks = json.load(f)
    return networks

def scan_wifi_networks():
    result = subprocess.run(['sudo', 'iwlist', INTERFACE, 'scanning'], capture_output=True, text=True)
    output = result.stdout
    networks = {}
    ssid = None
    for line in output.splitlines():
        line = line.strip()
        if "ESSID" in line:
            ssid = line.split('"')[1]
        elif "Signal level" in line and ssid:
            signal_level = int(line.split('=')[-1].split('/')[0])
            networks[ssid] = signal_level
            ssid = None
    return networks

def connect_to_network(ssid, password):
    print(f"Connecting to {ssid}")
    # Generate wpa_supplicant configuration
    wpa_conf = f"""ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=US

network={{
    ssid="{ssid}"
    psk="{password}"
    key_mgmt=WPA-PSK
}}
"""
    with open('/etc/wpa_supplicant/wpa_supplicant.conf', 'w') as f:
        f.write(wpa_conf)
    # Restart the wpa_supplicant service
    subprocess.run(['sudo', 'wpa_cli', '-i', INTERFACE, 'reconfigure'])
    time.sleep(10)  # Wait for connection to establish

def get_current_ssid():
    result = subprocess.run(['iwgetid', '-r'], capture_output=True, text=True)
    return result.stdout.strip()

def main():
    known_networks = load_known_networks()
    while True:
        available_networks = scan_wifi_networks()
        best_network = None
        best_signal = -100  # Start with a very low signal level
        for network in known_networks:
            ssid = network['ssid']
            password = network['password']
            if ssid in available_networks:
                signal_level = available_networks[ssid]
                if signal_level > best_signal:
                    best_signal = signal_level
                    best_network = network
        if best_network:
            current_ssid = get_current_ssid()
            if current_ssid != best_network['ssid']:
                connect_to_network(best_network['ssid'], best_network['password'])
        else:
            print("No known networks available.")
        time.sleep(SCAN_INTERVAL)

if __name__ == '__main__':
    main()
