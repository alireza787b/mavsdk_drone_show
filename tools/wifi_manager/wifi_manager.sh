#!/bin/bash

# Wi-Fi Manager Script for Raspberry Pi using nmcli
# Manages Wi-Fi connections based on signal strength and known networks.

CONFIG_FILE="$(dirname "$0")/known_networks.conf"  # Path to the known networks configuration
LOG_FILE="/var/log/wifi_manager.log"               # Log file path
SCAN_INTERVAL=15                                   # Time between scans in seconds
SIGNAL_THRESHOLD=10                                # dBm difference to switch networks
MAX_LOG_SIZE=5242880                               # 5 MB in bytes
BACKUP_COUNT=3                                     # Number of log backups to keep

# =======================
# Initial Setup and Checks
# =======================

if [ "$EUID" -ne 0 ]; then
  printf "ERROR - Please run as root.\n" >&2
  exit 1
fi

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
          else
            mv "$LOG_FILE.$i" "$LOG_FILE.$((i+1))"
          fi
        fi
      done
      mv "$LOG_FILE" "$LOG_FILE.1"
      : > "$LOG_FILE"
    fi
  else
    : > "$LOG_FILE"
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
    key=$(echo "$key" | xargs)
    value=$(echo "$value" | xargs)

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
        fi
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
# Scan Wi-Fi Networks Using nmcli
# =======================

scan_wifi_networks() {
  available_networks=()
  local scan_output
  scan_output=$(nmcli -f SSID,SIGNAL dev wifi list ifname wlan0)

  if [ $? -ne 0 ] || [ -z "$scan_output" ]; then
    printf "WARNING - Failed to scan Wi-Fi networks on interface 'wlan0'.\n" >&2
    return
  fi

  local ssid=""
  local signal=""
  while IFS= read -r line; do
    ssid=$(echo "$line" | awk '{print $1}')
    signal=$(echo "$line" | awk '{print $2}')
    available_networks+=("$ssid;$signal")
  done <<< "$(echo "$scan_output" | tail -n +2)"

  printf "INFO - Scanned %d available networks.\n" "${#available_networks[@]}"
}

# =======================
# Connect to Network Using nmcli
# =======================

connect_to_network() {
  local ssid="$1"
  local password="$2"

  printf "INFO - Attempting to connect to network '%s'.\n" "$ssid"

  if nmcli dev wifi connect "$ssid" password "$password" ifname wlan0; then
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

    local best_ssid=""
    local best_signal=-100

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
      printf "INFO - Connecting to best network '%s' with signal strength '%s'.\n" "$best_ssid" "$best_signal"
      connect_to_network "$best_ssid" "$best_password"
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
