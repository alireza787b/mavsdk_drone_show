#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Variables
CONFIG_FILE="$(dirname "$0")/known_networks.conf"
LOG_FILE="/var/log/wifi_manager.log"
SCAN_INTERVAL=15  # Time between scans in seconds
SIGNAL_THRESHOLD=10  # dBm difference to switch networks
MAX_LOG_SIZE=5242880  # 5 MB
BACKUP_COUNT=3

# Ensure the script runs as root
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root."
  exit 1
fi

# Setup logging
exec >> >(tee -a "$LOG_FILE") 2>&1

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

# Load known networks
load_known_networks() {
  if [ ! -f "$CONFIG_FILE" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - ERROR - Configuration file $CONFIG_FILE not found."
    exit 1
  fi

  declare -gA KNOWN_NETWORKS
  while IFS='=' read -r key value; do
    if [[ "$key" =~ ^ssid ]]; then
      ssid="$value"
    elif [[ "$key" =~ ^password ]]; then
      password="$value"
      KNOWN_NETWORKS["$ssid"]="$password"
    fi
  done < "$CONFIG_FILE"
}

# Get Wi-Fi interface
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

# Scan Wi-Fi networks
scan_wifi_networks() {
  available_networks=()
  mapfile -t scan_output < <(iwlist "$INTERFACE" scanning 2>/dev/null)
  for line in "${scan_output[@]}"; do
    line=$(echo "$line" | sed 's/^[ \t]*//')
    if [[ "$line" == ESSID* ]]; then
      ssid=$(echo "$line" | sed 's/ESSID:"\(.*\)"/\1/')
    elif [[ "$line" == *"Signal level="* ]]; then
      signal=$(echo "$line" | sed 's/.*Signal level=\([-0-9]*\) dBm.*/\1/')
      available_networks+=("$ssid;$signal")
    fi
  done
}

# Get current connection info
get_current_connection_info() {
  current_ssid=$(iwgetid -r)
  if [ -z "$current_ssid" ]; then
    current_signal=""
  else
    current_signal=$(iwconfig "$INTERFACE" | grep -i --color=never 'signal level' | awk '{print $4}' | sed 's/level=//g')
  fi
}

# Connect to network
connect_to_network() {
  ssid="$1"
  password="$2"
  country_code="US"  # Modify as needed

  wpa_conf="/etc/wpa_supplicant/wpa_supplicant.conf"

  # Generate wpa_supplicant configuration
  cat <<EOF > "$wpa_conf"
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=$country_code

network={
    ssid="$ssid"
    psk="$password"
    key_mgmt=WPA-PSK
}
EOF

  # Restart networking services
  wpa_cli -i "$INTERFACE" reconfigure >/dev/null 2>&1
  sleep 10  # Wait for the connection to establish
}

# Main loop
main_loop() {
  while true; do
    rotate_logs
    load_known_networks
    get_current_connection_info
    scan_wifi_networks

    best_ssid=""
    best_signal=-100

    for entry in "${available_networks[@]}"; do
      ssid=$(echo "$entry" | cut -d';' -f1)
      signal=$(echo "$entry" | cut -d';' -f2)

      if [[ -v KNOWN_NETWORKS["$ssid"] ]]; then
        if [ "$signal" -gt "$best_signal" ]; then
          best_signal="$signal"
          best_ssid="$ssid"
          best_password="${KNOWN_NETWORKS[$ssid]}"
        fi
      fi
    done

    if [ -n "$best_ssid" ]; then
      if [ "$current_ssid" != "$best_ssid" ]; then
        if [ -z "$current_ssid" ]; then
          echo "$(date '+%Y-%m-%d %H:%M:%S') - INFO - Connecting to '$best_ssid' with signal $best_signal dBm."
          connect_to_network "$best_ssid" "$best_password"
        else
          signal_diff=$((best_signal - current_signal))
          if [ "$signal_diff" -ge "$SIGNAL_THRESHOLD" ]; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') - INFO - Switching from '$current_ssid' ($current_signal dBm) to better network '$best_ssid' ($best_signal dBm)."
            connect_to_network "$best_ssid" "$best_password"
          else
            echo "$(date '+%Y-%m-%d %H:%M:%S') - INFO - Current network '$current_ssid' ($current_signal dBm) is sufficient. No switch needed."
          fi
        fi
      else
        echo "$(date '+%Y-%m-%d %H:%M:%S') - INFO - Already connected to the best network '$current_ssid' ($current_signal dBm)."
      fi
    else
      echo "$(date '+%Y-%m-%d %H:%M:%S') - WARNING - No known networks available."
    fi

    sleep "$SCAN_INTERVAL"
  done
}

main_loop
