#!/bin/bash

# Wi-Fi Manager Script for Raspberry Pi
# Manages Wi-Fi connections based on signal strength and known networks.

# Exit immediately if a command exits with a non-zero status
# Removed 'set -e' to prevent the script from exiting unexpectedly on non-critical errors

# Variables
CONFIG_FILE="$(dirname "$0")/known_networks.conf"
LOG_FILE="/var/log/wifi_manager.log"
SCAN_INTERVAL=15          # Time between scans in seconds
SIGNAL_THRESHOLD=10       # dBm difference to switch networks
MAX_LOG_SIZE=5242880      # 5 MB
BACKUP_COUNT=3
COUNTRY_CODE="US"         # Modify as needed (e.g., 'US', 'GB', etc.)

# Ensure the script runs as root
if [ "$EUID" -ne 0 ]; then
  echo "ERROR - Please run as root."
  exit 1
fi

# Setup logging with timestamps
exec >> >(while read line; do echo "$(date '+%Y-%m-%d %H:%M:%S') - $line"; done | tee -a "$LOG_FILE") 2>&1

# Function to rotate logs
rotate_logs() {
  if [ -f "$LOG_FILE" ]; then
    LOG_SIZE=$(stat -c%s "$LOG_FILE")
    if [ "$LOG_SIZE" -ge "$MAX_LOG_SIZE" ]; then
      for ((i=BACKUP_COUNT; i>=1; i--)); do
        if [ -f "$LOG_FILE.$i" ]; then
          if [ "$i" -eq "$BACKUP_COUNT" ]; then
            rm -f "$LOG_FILE.$i"
          else
            mv "$LOG_FILE.$i" "$LOG_FILE.$((i+1))"
          fi
        fi
      done
      mv "$LOG_FILE" "$LOG_FILE.1"
      touch "$LOG_FILE"
    fi
  else
    touch "$LOG_FILE"
  fi
}

# Load known networks from configuration file
load_known_networks() {
  if [ ! -f "$CONFIG_FILE" ]; then
    echo "ERROR - Configuration file $CONFIG_FILE not found."
    exit 1
  fi

  declare -gA KNOWN_NETWORKS
  ssid=""
  password=""
  while IFS='=' read -r key value || [ -n "$key" ]; do
    if [[ "$key" =~ ^ssid$ ]]; then
      ssid="$value"
    elif [[ "$key" =~ ^password$ ]]; then
      password="$value"
      if [ -n "$ssid" ] && [ -n "$password" ]; then
        KNOWN_NETWORKS["$ssid"]="$password"
      fi
      ssid=""
      password=""
    fi
  done < "$CONFIG_FILE"
}

# Get Wi-Fi interface (e.g., wlan0)
get_wifi_interface() {
  interfaces=$(ls /sys/class/net/)
  for iface in $interfaces; do
    if [[ "$iface" == wlan* ]] || [[ "$iface" == wifi* ]]; then
      echo "$iface"
      return
    fi
  done
  echo "wlan0"
}

INTERFACE=$(get_wifi_interface)
echo "INFO - Using wireless interface: $INTERFACE"

# Scan Wi-Fi networks and collect available SSIDs and signal levels
scan_wifi_networks() {
  available_networks=()
  scan_output=$(iwlist "$INTERFACE" scanning 2>/dev/null)

  if [ -z "$scan_output" ]; then
    echo "WARNING - No Wi-Fi networks found during scan."
    return
  fi

  ssid=""
  signal=""
  while IFS= read -r line; do
    line=$(echo "$line" | sed 's/^[ \t]*//')
    if [[ "$line" == "Cell "* ]]; then
      ssid=""
      signal=""
    elif [[ "$line" == "ESSID:"* ]]; then
      ssid=$(echo "$line" | sed 's/ESSID:"\(.*\)"/\1/')
    elif [[ "$line" == *"Signal level="* ]]; then
      signal=$(echo "$line" | sed 's/.*Signal level=\([-0-9]*\).*/\1/')
    fi

    if [ -n "$ssid" ] && [ -n "$signal" ]; then
      available_networks+=("$ssid;$signal")
      ssid=""
      signal=""
    fi
  done <<< "$scan_output"
}

# Get current connection SSID and signal level
get_current_connection_info() {
  current_ssid=$(iwgetid -r)
  if [ -n "$current_ssid" ]; then
    current_signal=$(iwconfig "$INTERFACE" | grep -i --color=never 'signal level' | awk -F'=' '{print $3}' | awk '{print $1}')
    if [ -z "$current_signal" ]; then
      current_signal="-100"  # Assume very weak signal if unable to get signal level
    fi
  else
    current_ssid=""
    current_signal="-100"
  fi
}

# Connect to a specified network
connect_to_network() {
  ssid="$1"
  password="$2"

  wpa_conf="/etc/wpa_supplicant/wpa_supplicant.conf"

  # Generate wpa_supplicant configuration
  cat <<EOF > "$wpa_conf"
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=$COUNTRY_CODE

network={
    ssid="$ssid"
    psk="$password"
    key_mgmt=WPA-PSK
}
EOF

  # Restart wpa_supplicant service
  echo "INFO - Attempting to connect to network '$ssid'..."
  wpa_cli -i "$INTERFACE" reconfigure >/dev/null 2>&1
  sleep 10  # Wait for the connection to establish
}

# Main loop to manage Wi-Fi connections
main_loop() {
  while true; do
    rotate_logs
    load_known_networks
    get_current_connection_info
    scan_wifi_networks

    best_ssid=""
    best_signal=-100

    # Find the best known network based on signal strength
    for entry in "${available_networks[@]}"; do
      ssid=$(echo "$entry" | cut -d';' -f1)
      signal=$(echo "$entry" | cut -d';' -f2)

      if [[ -n "${KNOWN_NETWORKS[$ssid]}" ]]; then
        if [ "$signal" -gt "$best_signal" ]; then
          best_signal="$signal"
          best_ssid="$ssid"
          best_password="${KNOWN_NETWORKS[$ssid]}"
        fi
      fi
    done

    if [ -n "$best_ssid" ]; then
      signal_diff=$((best_signal - current_signal))
      if [ "$current_ssid" != "$best_ssid" ]; then
        if [ "$current_ssid" == "" ]; then
          echo "INFO - Not connected. Connecting to '$best_ssid' ($best_signal dBm)."
          connect_to_network "$best_ssid" "$best_password"
        elif [ "$signal_diff" -ge "$SIGNAL_THRESHOLD" ]; then
          echo "INFO - Switching from '$current_ssid' ($current_signal dBm) to better network '$best_ssid' ($best_signal dBm)."
          connect_to_network "$best_ssid" "$best_password"
        else
          echo "INFO - Current network '$current_ssid' ($current_signal dBm) is sufficient. No switch needed."
        fi
      else
        echo "INFO - Already connected to the best network '$current_ssid' ($current_signal dBm)."
      fi
    else
      echo "WARNING - No known networks available."
    fi

    sleep "$SCAN_INTERVAL"
  done
}

# Start the main loop
main_loop
