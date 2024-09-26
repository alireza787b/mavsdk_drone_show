#!/bin/bash

# Wi-Fi Manager Script for Raspberry Pi
# This script ensures drones (Raspberry Pi devices) are always connected to the strongest known Wi-Fi network.
# It scans for Wi-Fi networks periodically, compares signal strength, and switches to a stronger network if available.

# =======================
# Configuration Parameters
# =======================

CONFIG_FILE="$(dirname "$0")/known_networks.conf"  # Path to known networks configuration file
LOG_FILE="/var/log/wifi-manager.log"               # Log file to record all activities
SCAN_INTERVAL=15                                   # Time (in seconds) between Wi-Fi scans
SIGNAL_THRESHOLD=10                                # Minimum signal strength improvement to trigger a switch
MAX_LOG_SIZE=5242880                               # Maximum log file size (5 MB)
BACKUP_COUNT=3                                     # Number of rotated log files to keep
LOCK_FILE="/var/run/wifi-manager.lock"             # Lock file to prevent multiple instances

# =======================
# Initial Setup and Checks
# =======================

# Ensure the script runs with root privileges
if [ "$EUID" -ne 0 ]; then
  printf "ERROR - Please run as root.\n" >&2
  exit 1
fi

# Create and acquire a lock to prevent multiple instances of the script from running
exec 200>"$LOCK_FILE"
flock -n 200 || { echo "ERROR - Another instance of the script is running."; exit 1; }

# Ensure the lock file is removed on script exit (graceful or forced)
trap 'rm -f "$LOCK_FILE"; exit' INT TERM HUP QUIT EXIT

# Setup logging: timestamps for all log entries and both stdout/stderr logged
exec >> >(while IFS= read -r line; do printf "%s - %s\n" "$(date '+%Y-%m-%d %H:%M:%S')" "$line"; done | tee -a "$LOG_FILE") 2>&1

# =======================
# Log Rotation Function
# =======================

rotate_logs() {
  if [ -f "$LOG_FILE" ]; then
    local log_size
    log_size=$(stat -c%s "$LOG_FILE")
    if [ "$log_size" -ge "$MAX_LOG_SIZE" ]; then
      # Rotate logs and keep backups
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
      : > "$LOG_FILE"  # Truncate current log file
    fi
  else
    : > "$LOG_FILE"  # Create log file if it doesn't exist
  fi
}

# =======================
# Load Known Networks Function
# =======================

load_known_networks() {
  if [ ! -f "$CONFIG_FILE" ]; then
    printf "ERROR - Configuration file %s not found.\n" "$CONFIG_FILE" >&2
    exit 1
  fi

  declare -gA KNOWN_NETWORKS  # Declare global associative array for SSIDs and passwords
  local ssid=""
  local password=""

  while IFS='=' read -r key value || [ -n "$key" ]; do
    key=$(echo "$key" | xargs)  # Trim leading/trailing whitespace
    value=$(echo "$value" | xargs)

    # Skip empty lines or comments
    if [[ -z "$key" ]] || [[ -z "$value" ]] || [[ "$key" == \#* ]]; then
      continue
    fi

    # Parse SSID and password pairs from the configuration file
    case "$key" in
      ssid)
        ssid="$value"
        ;;
      password)
        password="$value"
        if [ -n "$ssid" ] && [ -n "$password" ]; then
          KNOWN_NETWORKS["$ssid"]="$password"
          ssid=""
          password=""
        fi
        ;;
    esac
  done < "$CONFIG_FILE"

  if [ ${#KNOWN_NETWORKS[@]} -eq 0 ]; then
    printf "ERROR - No known networks loaded from %s.\n" "$CONFIG_FILE" >&2
    exit 1
  fi
}

# =======================
# Get Wi-Fi Interface Function
# =======================

get_wifi_interface() {
  local interfaces
  interfaces=$(nmcli device status | awk '$2 == "wifi" {print $1}' | head -n1)
  printf "%s" "${interfaces:-wlan0}"  # Default to wlan0 if no interface is found
}

# Get the wireless interface for later use
INTERFACE=$(get_wifi_interface)

# =======================
# Scan Wi-Fi Networks Function
# =======================

scan_wifi_networks() {
  available_networks=()
  local scan_output
  scan_output=$(nmcli -f SSID,SIGNAL dev wifi list ifname "$INTERFACE" --rescan yes)

  if [ $? -ne 0 ] || [ -z "$scan_output" ]; then
    printf "WARNING - Failed to scan Wi-Fi networks on interface '%s'.\n" "$INTERFACE"
    return
  fi

  # Parse SSID and signal strength from the scan output
  while IFS= read -r line; do
    signal=$(echo "$line" | awk '{print $NF}')
    ssid=$(echo "$line" | sed "s/$signal\$//" | xargs)
    available_networks+=("$ssid;$signal")
  done <<< "$(echo "$scan_output" | tail -n +2)"  # Skip the header
}

# =======================
# Get Current Connection Info Function
# =======================

get_current_connection_info() {
  current_ssid=$(nmcli -t -f active,ssid dev wifi | grep '^yes:' | cut -d':' -f2-)
  if [ -n "$current_ssid" ]; then
    current_signal=$(nmcli -t -f SIGNAL connection show --active | head -n1 | cut -d':' -f1)
    printf "INFO - Connected to '%s' with signal strength %s%%.\n" "$current_ssid" "$current_signal"
  else
    current_ssid=""
    current_signal=0
    printf "INFO - Not connected to any network.\n"
  fi
}

# =======================
# Connect to Network Function Using nmcli
# =======================

connect_to_network() {
  local ssid="$1"
  local password="$2"
  nmcli_output=$(nmcli dev wifi connect "$ssid" password "$password" ifname "$INTERFACE" 2>&1)
  nmcli_exit_status=$?

  if [ "$nmcli_exit_status" -eq 0 ]; then
    printf "INFO - Successfully connected to '%s'.\n" "$ssid"
    return 0
  else
    printf "ERROR - Failed to connect to '%s'. Output: %s\n" "$ssid" "$nmcli_output" >&2
    return 1
  fi
}

# =======================
# Main Logic Loop
# =======================

main_loop() {
  while true; do
    rotate_logs
    load_known_networks
    scan_wifi_networks
    get_current_connection_info

    local best_ssid=""
    local best_signal=-100

    # Find the best available network based on signal strength
    for entry in "${available_networks[@]}"; do
      local ssid
      local signal
      ssid=$(echo "$entry" | cut -d';' -f1)
      signal=$(echo "$entry" | cut -d';' -f2)

      # Ensure signal is a valid number (handle negative signal values like -70 dBm)
      if ! [[ "$signal" =~ ^-?[0-9]+$ ]]; then
        continue
      fi

      # Check if this SSID is a known network and has a stronger signal
      if [[ -v "KNOWN_NETWORKS[$ssid]" ]] && [ "$signal" -gt "$best_signal" ]; then
        best_signal="$signal"
        best_ssid="$ssid"
        best_password="${KNOWN_NETWORKS[$ssid]}"
      fi
    done

    # Connect to the best available network if it's different from the current one
    if [ "$current_ssid" != "$best_ssid" ] && [ -n "$best_ssid" ]; then
      signal_diff=$((best_signal - current_signal))
      if [ "$signal_diff" -ge "$SIGNAL_THRESHOLD" ]; then
        printf "INFO - Switching to better network '%s' (Signal: %s%%).\n" "$best_ssid" "$best_signal"
        connect_to_network "$best_ssid" "$best_password"
      fi
    fi

    sleep "$SCAN_INTERVAL"  # Wait before next scan
  done
}

# =======================
# Start the Script
# =======================

main_loop  # Start the main loop for continuously checking Wi-Fi status and switching networks
