#!/bin/bash

# Wi-Fi Manager Script for Raspberry Pi using nmcli
# Manages Wi-Fi connections based on signal strength and known networks.

# =======================
# Configuration Parameters
# =======================

CONFIG_FILE="$(dirname "$0")/known_networks.conf"  # Path to the known networks configuration
LOG_FILE="/var/log/wifi_manager.log"               # Log file path
SCAN_INTERVAL=15                                   # Time between scans in seconds
SIGNAL_THRESHOLD=10                                # Percentage difference to switch networks
MAX_LOG_SIZE=5242880                               # 5 MB in bytes
BACKUP_COUNT=3                                     # Number of log backups to keep
LOCK_FILE="/var/run/wifi_manager.lock"            # Lock file to prevent multiple instances

# =======================
# Initial Setup and Checks
# =======================

# Ensure the script runs as root
if [ "$EUID" -ne 0 ]; then
  echo "ERROR - Please run as root." >&2
  exit 1
fi

# Prevent multiple instances
if [ -f "$LOCK_FILE" ]; then
  echo "ERROR - Another instance of the script is running." >&2
  exit 1
fi

# Create a lock file
touch "$LOCK_FILE"

# Ensure the lock file is removed on script exit
trap "rm -f $LOCK_FILE; exit" INT TERM EXIT

# Setup logging with timestamps
# All stdout and stderr will be logged with timestamps and also output to the console
exec >> >(while IFS= read -r line; do echo "$(date '+%Y-%m-%d %H:%M:%S') - $line"; done | tee -a "$LOG_FILE") 2>&1

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
            echo "INFO - Removed oldest log backup: $LOG_FILE.$i"
          else
            mv "$LOG_FILE.$i" "$LOG_FILE.$((i+1))"
            echo "INFO - Rotated log: $LOG_FILE.$i -> $LOG_FILE.$((i+1))"
          fi
        fi
      done
      mv "$LOG_FILE" "$LOG_FILE.1"
      touch "$LOG_FILE"
      echo "INFO - Rotated log: $LOG_FILE -> $LOG_FILE.1"
    fi
  else
    touch "$LOG_FILE"
    echo "INFO - Created new log file: $LOG_FILE"
  fi
}

# =======================
# Load Known Networks Function
# =======================

load_known_networks() {
  if [ ! -f "$CONFIG_FILE" ]; then
    echo "ERROR - Configuration file $CONFIG_FILE not found." >&2
    exit 1
  fi

  declare -gA KNOWN_NETWORKS
  local ssid=""
  local password=""

  while IFS='=' read -r key value || [ -n "$key" ]; do
    # Trim leading/trailing whitespace
    key=$(echo "$key" | xargs)
    value=$(echo "$value" | xargs)

    # Skip empty lines or lines starting with '#'
    if [[ -z "$key" ]] || [[ -z "$value" ]] || [[ "$key" == \#* ]]; then
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
          echo "WARNING - Incomplete network entry: SSID='$ssid', Password='$password'"
        fi
        ;;
      *)
        echo "WARNING - Unknown key '$key' in configuration file."
        ;;
    esac
  done < "$CONFIG_FILE"

  if [ ${#KNOWN_NETWORKS[@]} -eq 0 ]; then
    echo "ERROR - No known networks loaded from $CONFIG_FILE." >&2
    exit 1
  fi

  echo "INFO - Loaded ${#KNOWN_NETWORKS[@]} known networks."
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
echo "INFO - Using wireless interface: $INTERFACE"

# =======================
# Scan Wi-Fi Networks Using nmcli
# =======================

scan_wifi_networks() {
  available_networks=()
  local scan_output
  scan_output=$(nmcli -f SSID,SIGNAL dev wifi list ifname "$INTERFACE" --rescan yes)

  if [ $? -ne 0 ] || [ -z "$scan_output" ]; then
    echo "WARNING - Failed to scan Wi-Fi networks on interface '$INTERFACE'."
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

  echo "INFO - Scanned ${#available_networks[@]} available networks."
}

# =======================
# Get Current Connection Info Function
# =======================

get_current_connection_info() {
  current_ssid=$(nmcli -t -f active,ssid dev wifi | grep '^yes:' | cut -d':' -f2-)
  if [ -n "$current_ssid" ]; then
    # Get signal strength of the current connection
    current_signal=$(nmcli -t -f SIGNAL connection show --active | head -n1 | cut -d':' -f1)
    if [ -z "$current_signal" ]; then
      current_signal=0  # Default to 0 if unable to retrieve
      echo "WARNING - Could not retrieve signal strength for current SSID '$current_ssid'. Setting to $current_signal%."
    else
      echo "INFO - Currently connected to '$current_ssid' with signal strength $current_signal%."
    fi
  else
    current_ssid=""
    current_signal=0
    echo "INFO - Not connected to any network."
  fi
}

# =======================
# Connect to Network Using nmcli
# =======================

connect_to_network() {
  local ssid="$1"
  local password="$2"

  echo "INFO - Attempting to connect to network '$ssid'."

  # Capture nmcli output and exit status
  nmcli_output=$(nmcli dev wifi connect "$ssid" password "$password" ifname "$INTERFACE" 2>&1)
  nmcli_exit_status=$?

  if [ "$nmcli_exit_status" -eq 0 ]; then
    echo "INFO - Successfully connected to '$ssid'."
    echo "INFO - nmcli output: $nmcli_output"
    return 0
  else
    echo "ERROR - Failed to connect to '$ssid'. nmcli output: $nmcli_output" >&2
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
          echo "INFO - Not connected. Connecting to '$best_ssid' ($best_signal%)."
          if connect_to_network "$best_ssid" "$best_password"; then
            echo "INFO - Connected to '$best_ssid'."
          else
            echo "ERROR - Could not connect to '$best_ssid'. Will retry in next scan."
          fi
        else
          # Calculate signal difference
          signal_diff=$((best_signal - current_signal))
          if [ "$signal_diff" -ge "$SIGNAL_THRESHOLD" ]; then
            echo "INFO - Found better network '$best_ssid' ($best_signal%) compared to current '$current_ssid' ($current_signal%). Difference: $signal_diff%. Switching..."
            if connect_to_network "$best_ssid" "$best_password"; then
              echo "INFO - Switched to '$best_ssid'."
            else
              echo "ERROR - Failed to switch to '$best_ssid'. Will retry in next scan."
            fi
          else
            echo "INFO - Current network '$current_ssid' ($current_signal%) is sufficiently strong. Best available: '$best_ssid' ($best_signal%) with a difference of $signal_diff%."
          fi
        fi
      else
        echo "INFO - Already connected to the best available network '$current_ssid' ($current_signal%)."
      fi
    else
      echo "WARNING - No known networks available to connect."
    fi

    sleep "$SCAN_INTERVAL"
  done
}

# =======================
# Start the Script
# =======================

main_loop
