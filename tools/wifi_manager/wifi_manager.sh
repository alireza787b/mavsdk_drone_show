#!/bin/bash

# Wi-Fi Manager Script for Raspberry Pi
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
COUNTRY_CODE="IR"                                  # Country code for regulatory purposes

# =======================
# Initial Setup and Checks
# =======================

# Ensure the script runs as root
if [ "$EUID" -ne 0 ]; then
  echo "ERROR - Please run as root." >&2
  exit 1
fi

# Setup logging with timestamps
# All stdout and stderr will be logged with timestamps and also output to the console
exec >> >(while IFS= read -r line; do echo "$(date '+%Y-%m-%d %H:%M:%S') - $line"; done | tee -a "$LOG_FILE") 2>&1

# =======================
# Log Rotation Function
# =======================

rotate_logs() {
  if [ -f "$LOG_FILE" ]; then
    LOG_SIZE=$(stat -c%s "$LOG_FILE")
    if [ "$LOG_SIZE" -ge "$MAX_LOG_SIZE" ]; then
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
    echo "ERROR - Configuration file $CONFIG_FILE not found."
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
          echo "WARNING - Incomplete network entry: SSID='$ssid', Password='$password'"
        fi
        ;;
      *)
        echo "WARNING - Unknown key '$key' in configuration file."
        ;;
    esac
  done < "$CONFIG_FILE"

  if [ ${#KNOWN_NETWORKS[@]} -eq 0 ]; then
    echo "ERROR - No known networks loaded from $CONFIG_FILE."
    exit 1
  fi

  echo "INFO - Loaded ${#KNOWN_NETWORKS[@]} known networks."
}

# =======================
# Get Wi-Fi Interface Function
# =======================

get_wifi_interface() {
  local interfaces
  interfaces=$(ls /sys/class/net/)
  for iface in $interfaces; do
    if [[ "$iface" == wlan* ]] || [[ "$iface" == wifi* ]]; then
      echo "$iface"
      return
    fi
  done
  echo "wlan0"  # Default interface name
}

# Get the wireless interface
INTERFACE=$(get_wifi_interface)
echo "INFO - Using wireless interface: $INTERFACE"

# =======================
# Scan Wi-Fi Networks Function
# =======================

scan_wifi_networks() {
  available_networks=()
  local scan_output
  scan_output=$(iwlist "$INTERFACE" scanning 2>/dev/null)

  if [ $? -ne 0 ] || [ -z "$scan_output" ]; then
    echo "WARNING - Failed to scan Wi-Fi networks on interface '$INTERFACE'."
    return
  fi

  local ssid=""
  local signal=""
  while IFS= read -r line; do
    line=$(echo "$line" | sed 's/^[ \t]*//')  # Trim leading whitespace
    if [[ "$line" == "Cell "* ]]; then
      ssid=""
      signal=""
    elif [[ "$line" == ESSID:* ]]; then
      ssid=$(echo "$line" | sed 's/ESSID:"\(.*\)"/\1/')
    elif [[ "$line" == *"Signal level="* ]]; then
      # Extract signal level in dBm
      if [[ "$line" =~ Signal\ level=([\-0-9]+) ]]; then
        signal="${BASH_REMATCH[1]}"
      elif [[ "$line" =~ Quality=[0-9]+/[0-9]+\ +Signal\ level=([\-0-9]+) ]]; then
        signal="${BASH_REMATCH[1]}"
      fi
    fi

    if [ -n "$ssid" ] && [ -n "$signal" ]; then
      available_networks+=("$ssid;$signal")
      ssid=""
      signal=""
    fi
  done <<< "$scan_output"

  echo "INFO - Scanned ${#available_networks[@]} available networks."
}

# =======================
# Get Current Connection Info Function
# =======================

get_current_connection_info() {
  current_ssid=$(iwgetid -r)
  if [ -n "$current_ssid" ]; then
    # Extract signal level using iwconfig
    current_signal=$(iwconfig "$INTERFACE" | grep -i --color=never 'signal level' | awk -F'=' '{print $3}' | awk '{print $1}' | sed 's/dBm//g')
    if [ -z "$current_signal" ]; then
      current_signal=-100  # Assign a low value if unable to retrieve
      echo "WARNING - Could not retrieve signal level for current SSID '$current_ssid'. Setting to $current_signal dBm."
    else
      echo "INFO - Currently connected to '$current_ssid' with signal level $current_signal dBm."
    fi
  else
    current_ssid=""
    current_signal=-100
    echo "INFO - Not connected to any network."
  fi
}

# =======================
# Connect to Network Function
# =======================

connect_to_network() {
  local ssid="$1"
  local password="$2"

  local wpa_conf="/etc/wpa_supplicant/wpa_supplicant.conf"

  echo "INFO - Generating wpa_supplicant configuration for '$ssid'."

  # Backup existing wpa_supplicant.conf
  if [ -f "$wpa_conf" ]; then
    cp "$wpa_conf" "${wpa_conf}.bak_$(date '+%Y%m%d%H%M%S')"
    echo "INFO - Backed up existing wpa_supplicant.conf to ${wpa_conf}.bak_$(date '+%Y%m%d%H%M%S')"
  fi

  # Generate wpa_supplicant configuration using wpa_passphrase for security
  if ! wpa_passphrase "$ssid" "$password" > /tmp/wpa_temp.conf; then
    echo "ERROR - Failed to generate wpa_supplicant configuration for '$ssid'."
    return 1
  fi

  # Append to existing wpa_supplicant.conf instead of replacing to allow multiple networks
  if grep -q "^network={" "$wpa_conf" 2>/dev/null; then
    cat /tmp/wpa_temp.conf >> "$wpa_conf"
  else
    # If wpa_supplicant.conf is empty or does not have network block, add the configuration
    cat /tmp/wpa_temp.conf > "$wpa_conf"
  fi

  rm -f /tmp/wpa_temp.conf
  chmod 600 "$wpa_conf"
  echo "INFO - Updated wpa_supplicant configuration."

  # Restart wpa_supplicant service to apply changes
  echo "INFO - Restarting wpa_supplicant service."
  if ! systemctl restart wpa_supplicant.service; then
    echo "ERROR - Failed to restart wpa_supplicant.service."
    return 1
  fi

  # Wait for the connection to establish
  echo "INFO - Waiting for 10 seconds to establish connection to '$ssid'."
  sleep 10

  # Verify connection
  new_ssid=$(iwgetid -r)
  if [ "$new_ssid" == "$ssid" ]; then
    echo "INFO - Successfully connected to '$ssid'."
    return 0
  else
    echo "ERROR - Failed to connect to '$ssid'."
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
    get_current_connection_info
    scan_wifi_networks

    best_ssid=""
    best_signal=-100

    # Identify the best known network based on signal strength
    for entry in "${available_networks[@]}"; do
      ssid=$(echo "$entry" | cut -d';' -f1)
      signal=$(echo "$entry" | cut -d';' -f2)

      # Ensure signal is a valid number
      if ! [[ "$signal" =~ ^-?[0-9]+$ ]]; then
        echo "WARNING - Invalid signal level '$signal' for SSID '$ssid'. Skipping."
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
          echo "INFO - Not connected. Connecting to '$best_ssid' ($best_signal dBm)."
          if connect_to_network "$best_ssid" "$best_password"; then
            echo "INFO - Connected to '$best_ssid'."
          else
            echo "ERROR - Could not connect to '$best_ssid'. Will retry in next scan."
          fi
        else
          # Calculate signal difference
          signal_diff=$((best_signal - current_signal))
          if [ "$signal_diff" -ge "$SIGNAL_THRESHOLD" ]; then
            echo "INFO - Found better network '$best_ssid' ($best_signal dBm) compared to current '$current_ssid' ($current_signal dBm). Difference: $signal_diff dBm. Switching..."
            if connect_to_network "$best_ssid" "$best_password"; then
              echo "INFO - Switched to '$best_ssid'."
            else
              echo "ERROR - Failed to switch to '$best_ssid'. Will retry in next scan."
            fi
          else
            echo "INFO - Current network '$current_ssid' ($current_signal dBm) is sufficient. No switch needed. Best available: '$best_ssid' ($best_signal dBm) with difference $signal_diff dBm."
          fi
        fi
      else
        echo "INFO - Already connected to the best network '$current_ssid' ($current_signal dBm)."
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
