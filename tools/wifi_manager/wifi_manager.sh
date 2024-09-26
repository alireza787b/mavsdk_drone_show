#!/bin/bash

# Wi-Fi Manager Script for Raspberry Pi using nmcli
# Manages Wi-Fi connections based on signal strength and known networks.

# =======================
# Configuration Parameters
# =======================

CONFIG_FILE="$(dirname "$0")/known_networks.conf"  # Path to the known networks configuration
LOG_FILE="/var/log/wifi_manager.log"               # Log file path
SCAN_INTERVAL=15                                   # Time between scans in seconds
SIGNAL_THRESHOLD=10                                # dBm difference to switch networks
MAX_LOG_SIZE=5242880                               # 5 MB in bytes
BACKUP_COUNT=3                                     # Number of log backups to keep

# =======================
# Initial Setup and Checks
# =======================

# Ensure the script runs as root
if [ "$EUID" -ne 0 ]; then
  printf "ERROR - Please run as root.\n" >&2
  exit 1
fi

# Setup logging with timestamps
# All stdout and stderr will be logged with timestamps and also output to the console
exec >> >(while IFS= read -r line; do printf "%s - %s\n" "$(date '+%Y-%m-%d %H:%M:%S')" "$line"; done | tee -a "$LOG_FILE") 2>&1

# =======================
# Log Rotation Function
# =======================

rotate_logs() {
  if [ -f "$LOG_FILE" ]; then
    local log_size
    log_size=$(stat -c%s "$LOG_FILE")
    if [ "$log_size" -ge "$MAX_LOG_SIZE" ]; then
      for ((i=BACKUP_COUNT; i>=1; i--)); do
        if [ -f "$LOG_FILE.$i" ]; then
          if [ "$i" -eq "$BACKUP_COUNT" ]; then
            rm -f "$LOG_FILE.$i"
            printf "INFO - Removed oldest log backup: %s.%d\n" "$LOG_FILE" "$i"
          else
            mv "$LOG_FILE.$i" "$LOG_FILE.$((i+1))"
            printf "INFO - Rotated log: %s.%d -> %s.%d\n" "$LOG_FILE" "$i" "$LOG_FILE" "$((i+1))"
          fi
        fi
      done
      mv "$LOG_FILE" "$LOG_FILE.1"
      : > "$LOG_FILE"
      printf "INFO - Rotated log: %s -> %s.1\n" "$LOG_FILE" "$LOG_FILE"
    fi
  else
    : > "$LOG_FILE"
    printf "INFO - Created new log file: %s\n" "$LOG_FILE"
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

  declare -gA KNOWN_NETWORKS
  local ssid=""
  local password=""

  while IFS='=' read -r key value || [ -n "$key" ]; do
    # Trim leading/trailing whitespace
    key=$(echo "$key" | xargs)
    value=$(echo "$value" | xargs)

    # Skip empty lines or lines without '='
    if [ -z "$key" ] || [ -z "$value" ]; then
      continue
    fi

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
        else
          printf "WARNING - Incomplete network entry: SSID='%s', Password='%s'\n" "$ssid" "$password"
        fi
        ;;
      *)
        printf "WARNING - Unknown key '%s' in configuration file.\n" "$key"
        ;;
    esac
  done < "$CONFIG_FILE"

  if [ ${#KNOWN_NETWORKS[@]} -eq 0 ]; then
    printf "ERROR - No known networks loaded from %s.\n" "$CONFIG_FILE" >&2
    exit 1
  fi

  printf "INFO - Loaded %d known networks.\n" "${#KNOWN_NETWORKS[@]}"
}

# =======================
# Get Wi-Fi Interface Function
# =======================

get_wifi_interface() {
  local interfaces
  interfaces=$(nmcli device status | awk '$2 == "wifi" {print $1}')
  if [ -n "$interfaces" ]; then
    echo "$interfaces"
  else
    echo "wlan0"  # Fallback to wlan0 if detection fails
  fi
}

# Get the wireless interface
INTERFACE=$(get_wifi_interface)
printf "INFO - Using wireless interface: %s\n" "$INTERFACE"

# =======================
# Scan Wi-Fi Networks Using nmcli
# =======================

scan_wifi_networks() {
  available_networks=()
  local scan_output
  scan_output=$(nmcli -f SSID,SIGNAL dev wifi list ifname "$INTERFACE" --rescan yes)

  if [ $? -ne 0 ] || [ -z "$scan_output" ]; then
    printf "WARNING - Failed to scan Wi-Fi networks on interface '%s'.\n" "$INTERFACE" >&2
    return
  fi

  local line
  while IFS= read -r line; do
    # Extract signal as the last field
    signal=$(echo "$line" | awk '{print $NF}')
    # Extract SSID by removing the signal field
    ssid=$(echo "$line" | sed "s/$signal\$//" | xargs)
    available_networks+=("$ssid;$signal")
  done <<< "$(echo "$scan_output" | tail -n +2)"

  printf "INFO - Scanned %d available networks.\n" "${#available_networks[@]}"
}

# =======================
# Get Current Connection Info Function
# =======================

get_current_connection_info() {
  current_ssid=$(nmcli -t -f active,ssid dev wifi | grep '^yes:' | cut -d':' -f2-)
  if [ -n "$current_ssid" ]; then
    # Get signal strength of the current connection
    current_signal=$(nmcli -t -f SIGNAL,DEVICE connection show --active | grep "$INTERFACE" | cut -d':' -f1)
    if [ -z "$current_signal" ]; then
      current_signal=0  # Default to 0 if unable to retrieve
      printf "WARNING - Could not retrieve signal strength for current SSID '%s'. Setting to %d.\n" "$current_ssid" "$current_signal"
    else
      printf "INFO - Currently connected to '%s' with signal strength %d%%.\n" "$current_ssid" "$current_signal"
    fi
  else
    current_ssid=""
    current_signal=0
    printf "INFO - Not connected to any network.\n"
  fi
}

# =======================
# Connect to Network Using nmcli
# =======================

connect_to_network() {
  local ssid="$1"
  local password="$2"

  printf "INFO - Attempting to connect to network '%s'.\n" "$ssid"

  if nmcli dev wifi connect "$ssid" password "$password" ifname "$INTERFACE"; then
    printf "INFO - Successfully connected to '%s'.\n" "$ssid"
    return 0
  else
    printf "ERROR - Failed to connect to '%s'.\n" "$ssid" >&2
    return 1
  fi
}

# =======================
# Main Loop Function
# =======================

main_loop() {
  while true; do
    rotate_logs
    load_known_networks
    scan_wifi_networks
    get_current_connection_info

    local best_ssid=""
    local best_signal=-100

    # Identify the best known network based on signal strength
    for entry in "${available_networks[@]}"; do
      local ssid
      local signal
      ssid=$(echo "$entry" | cut -d';' -f1)
      signal=$(echo "$entry" | cut -d';' -f2)

      if ! [[ "$signal" =~ ^[0-9]+$ ]]; then
        printf "WARNING - Invalid signal level '%s' for SSID '%s'. Skipping.\n" "$signal" "$ssid"
        continue
      fi

      if [[ -v "KNOWN_NETWORKS[$ssid]" ]]; then
        if [ "$signal" -gt "$best_signal" ]; then
          best_signal="$signal"
          best_ssid="$ssid"
          best_password="${KNOWN_NETWORKS[$ssid]}"
        fi
      fi
    done

    if [ -n "$best_ssid" ]; then
      if [ "$current_ssid" != "$best_ssid" ]; then
        if [ "$current_ssid" == "" ]; then
          printf "INFO - Not connected. Connecting to '%s' (%d%% signal).\n" "$best_ssid" "$best_signal"
          connect_to_network "$best_ssid" "$best_password"
        else
          # Compare signal strengths
          signal_diff=$((best_signal - current_signal))
          if [ "$signal_diff" -ge "$SIGNAL_THRESHOLD" ]; then
            printf "INFO - Found better network '%s' (%d%%) compared to current '%s' (%d%%). Difference: %d%%. Switching...\n" "$best_ssid" "$best_signal" "$current_ssid" "$current_signal" "$signal_diff"
            connect_to_network "$best_ssid" "$best_password"
          else
            printf "INFO - Current network '%s' (%d%%) is sufficiently strong. Best available: '%s' (%d%%) with a difference of %d%%.\n" "$current_ssid" "$current_signal" "$best_ssid" "$best_signal" "$signal_diff"
          fi
        fi
      else
        printf "INFO - Already connected to the best available network '%s' (%d%%).\n" "$current_ssid" "$current_signal"
      fi
    else
      printf "WARNING - No known networks available to connect.\n" >&2
    fi

    sleep "$SCAN_INTERVAL"
  done
}

# =======================
# Start the Script
# =======================

main_loop
