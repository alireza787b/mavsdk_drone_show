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

# Disable wpa_supplicant control over Wi-Fi
sudo systemctl stop wpa_supplicant
sudo systemctl disable wpa_supplicant

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

  printf "INFO - Loading known networks from configuration file...\n"
  
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
          printf "INFO - Loaded network: SSID='%s'\n" "$ssid"
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
printf "INFO - Using Wi-Fi interface: %s\n" "$INTERFACE"

# =======================
# Scan Wi-Fi Networks Function
# =======================

scan_wifi_networks() {
  available_networks=()
  local scan_output
  printf "INFO - Scanning for available Wi-Fi networks...\n"
  scan_output=$(nmcli -f SSID,SIGNAL dev wifi list ifname "$INTERFACE" --rescan yes)

  if [ $? -ne 0 ] || [ -z "$scan_output" ]; then
    printf "WARNING - Failed to scan Wi-Fi networks on interface '%s'.\n" "$INTERFACE"
    return
  fi

  printf "INFO - Available networks:\n"
  # Parse SSID and signal strength correctly
  while IFS= read -r line; do
    ssid=$(echo "$line" | awk '{print substr($0, 1, index($0,$NF)-1)}' | xargs)  # Extract SSID correctly
    signal=$(echo "$line" | awk '{print $NF}')
    available_networks+=("$ssid;$signal")
    printf "INFO - Found network: SSID='%s', Signal='%s%%'\n" "$ssid" "$signal"
  done <<< "$(echo "$scan_output" | tail -n +2)"  # Skip the header
}

# =======================
# Get Current Connection Info Function
# =======================

get_current_connection_info() {
  current_ssid=$(nmcli -t -f active,ssid dev wifi | grep '^yes:' | cut -d':' -f2-)
  if [ -n "$current_ssid" ]; then
    current_signal=$(nmcli -t -f IN-USE,SIGNAL dev wifi | grep '^*' | cut -d':' -f2)
    printf "INFO - Currently connected to '%s' with signal strength %s%%.\n" "$current_ssid" "$current_signal"
  else
    current_ssid=""
    current_signal=0
    printf "INFO - Not connected to any network.\n"
  fi
}

# =======================
# Disconnect from Current Network Function
# =======================

disconnect_network() {
  printf "INFO - Disconnecting from current network: SSID='%s'\n" "$current_ssid"
  nmcli device disconnect ifname "$INTERFACE"
}

# =======================
# Connect to Network Function Using nmcli
# =======================

connect_to_network() {
  local ssid="$1"
  local password="$2"
  local timeout=10  # Set a timeout of 10 seconds for the connection attempt

  printf "INFO - Attempting to connect to network: SSID='%s'\n" "$ssid"
  
  nmcli_output=$(timeout "$timeout" nmcli dev wifi connect "$ssid" password "$password" ifname "$INTERFACE" 2>&1)
  nmcli_exit_status=$?

  if [ "$nmcli_exit_status" -eq 0 ]; then
    printf "INFO - Successfully connected to '%s'.\n" "$ssid"
    return 0
  elif [ "$nmcli_exit_status" -eq 124 ]; then  # 124 is the exit code when timeout is reached
    printf "ERROR - Connection attempt to '%s' timed out after %d seconds.\n" "$ssid" "$timeout" >&2
  else
    printf "ERROR - Failed to connect to '%s'. Output: %s\n" "$ssid" "$nmcli_output" >&2
  fi
  return 1
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
    printf "INFO - Evaluating networks for best connection...\n"
    for entry in "${available_networks[@]}"; do
      local ssid
      local signal
      ssid=$(echo "$entry" | cut -d';' -f1)
      signal=$(echo "$entry" | cut -d';' -f2)

      # Ensure signal is a valid number (handle negative signal values like -70 dBm)
      if ! [[ "$signal" =~ ^-?[0-9]+$ ]]; then
        printf "WARNING - Invalid signal strength for SSID='%s'. Skipping...\n" "$ssid"
        continue
      fi

      printf "INFO - Checking network: SSID='%s', Signal='%s%%'\n" "$ssid" "$signal"

      # Check if this SSID is a known network and has a stronger signal
      # Use strict string comparison to avoid errors with trailing spaces
      if [[ -v "KNOWN_NETWORKS[$ssid]" ]]; then
        printf "INFO - SSID='%s' is a known network.\n" "$ssid"
        if [ "$signal" -gt "$best_signal" ]; then
          printf "INFO - SSID='%s' has a better signal (%s%%) compared to current best (%s%%).\n" "$ssid" "$signal" "$best_signal"
          best_signal="$signal"
          best_ssid="$ssid"
          best_password="${KNOWN_NETWORKS[$ssid]}"
        fi
      else
        printf "INFO - SSID='%s' is not in the list of known networks. Skipping...\n" "$ssid"
      fi
    done

    # Decision-making based on the best available network
    if [ "$current_ssid" != "$best_ssid" ] && [ -n "$best_ssid" ]; then
      signal_diff=$((best_signal - current_signal))
      if [ "$signal_diff" -ge "$SIGNAL_THRESHOLD" ]; then
        printf "INFO - Decided to switch to better network '%s' (Signal: %s%%, Improvement: %s%%).\n" "$best_ssid" "$best_signal" "$signal_diff"
        disconnect_network  # Disconnect before switching
        if ! connect_to_network "$best_ssid" "$best_password"; then
          printf "WARNING - Failed to switch to network '%s'. Retrying...\n" "$best_ssid"
        fi
      fi
    elif [ -z "$current_ssid" ] && [ -n "$best_ssid" ]; then
      printf "INFO - Currently disconnected. Attempting to connect to best network '%s' (Signal: %s%%).\n" "$best_ssid" "$best_signal"
      if ! connect_to_network "$best_ssid" "$best_password"; then
        printf "WARNING - Failed to connect to network '%s'. Retrying...\n" "$best_ssid"
      fi
    else
      printf "INFO - No better network found. Staying connected to '%s'.\n" "$current_ssid"
    fi

    sleep "$SCAN_INTERVAL"  # Wait before next scan
  done
}

# =======================
# Start the Script
# =======================

main_loop  # Start the main loop for continuously checking Wi-Fi status and switching networks
