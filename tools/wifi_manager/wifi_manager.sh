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
COUNTRY_CODE="US"                                  # Country code for regulatory purposes

# =======================
# Initial Setup and Checks
# =======================

# Ensure the script runs as root
if [ "$EUID" -ne 0 ]; then
  printf "ERROR - Please run as root.\n" >&2
  exit 1
fi

# Setup logging with timestamps
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
      : > "$LOG_FILE"  # Clear the current log file
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
  local interfaces iface
  interfaces=$(ls /sys/class/net/)
  for iface in $interfaces; do
    if [[ "$iface" == wlan* ]] || [[ "$iface" == wifi* ]]; then
      printf "%s" "$iface"
      return
    fi
  done
  printf "wlan0"
}

INTERFACE=$(get_wifi_interface)
printf "INFO - Using wireless interface: %s\n" "$INTERFACE"

# =======================
# Initialize wpa_supplicant Configuration
# =======================

initialize_wpa_supplicant() {
  local wpa_conf="/etc/wpa_supplicant/wpa_supplicant.conf"

  printf "INFO - Initializing wpa_supplicant configuration with known networks.\n"

  if [ -f "$wpa_conf" ]; then
    cp "$wpa_conf" "${wpa_conf}.bak_$(date '+%Y%m%d%H%M%S')"
    printf "INFO - Backed up existing wpa_supplicant.conf to %s\n" "${wpa_conf}.bak_$(date '+%Y%m%d%H%M%S')"
  fi

  cat <<EOF > "$wpa_conf"
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=$COUNTRY_CODE

EOF

  for ssid in "${!KNOWN_NETWORKS[@]}"; do
    local password="${KNOWN_NETWORKS[$ssid]}"
    printf "INFO - Adding network block for SSID '%s'.\n" "$ssid"
    wpa_passphrase "$ssid" "$password" >> "$wpa_conf" 2>/dev/null
    if [ $? -ne 0 ]; then
      printf "ERROR - Failed to add network '%s' to wpa_supplicant.conf.\n" "$ssid" >&2
    else
      printf "INFO - Added network '%s' to wpa_supplicant.conf.\n" "$ssid"
    fi
  done

  chmod 600 "$wpa_conf"
  printf "INFO - wpa_supplicant.conf initialized with known networks.\n"
}

# =======================
# Restart wpa_supplicant Service
# =======================

restart_wpa_supplicant() {
  printf "INFO - Restarting wpa_supplicant service.\n"
  systemctl restart wpa_supplicant.service

  if [ $? -ne 0 ]; then
    printf "ERROR - Failed to restart wpa_supplicant.service.\n" >&2
    return 1
  fi

  printf "INFO - wpa_supplicant service restarted successfully.\n"
  sleep 5
}

# =======================
# Scan Wi-Fi Networks Function
# =======================

scan_wifi_networks() {
  available_networks=()
  local scan_output
  scan_output=$(iwlist "$INTERFACE" scanning 2>/dev/null)

  if [ $? -ne 0 ] || [ -z "$scan_output" ]; then
    printf "WARNING - Failed to scan Wi-Fi networks on interface '%s'.\n" "$INTERFACE" >&2
    return
  fi

  local ssid=""
  local signal=""
  while IFS= read -r line; do
    line=$(echo "$line" | sed 's/^[ \t]*//')
    if [[ "$line" == "Cell "* ]]; then
      ssid=""
      signal=""
    elif [[ "$line" == ESSID:* ]]; then
      ssid=$(echo "$line" | sed 's/ESSID:"\(.*\)"/\1/')
    elif [[ "$line" == *"Signal level="* ]]; then
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

  printf "INFO - Scanned %d available networks.\n" "${#available_networks[@]}"
}

# =======================
# Get Current Connection Info Function
# =======================

get_current_connection_info() {
  current_ssid=$(iwgetid -r)
  if [ -n "$current_ssid" ]; then
    current_signal=$(iwconfig "$INTERFACE" | grep -i 'signal level' | awk -F'=' '{print $3}' | awk '{print $1}' | sed 's/dBm//g')
    if [ -z "$current_signal" ]; then
      current_signal=-100
      printf "WARNING - Could not retrieve signal level for current SSID '%s'. Setting to %d dBm.\n" "$current_ssid" "$current_signal"
    else
      printf "INFO - Currently connected to '%s' with signal level %d dBm.\n" "$current_ssid" "$current_signal"
    fi
  else
    current_ssid=""
    current_signal=-100
    printf "INFO - Not connected to any network.\n"
  fi
}

# =======================
# Connect to Network Function
# =======================

connect_to_network() {
  local ssid="$1"
  local password="$2"

  printf "INFO - Attempting to connect to network '%s'.\n" "$ssid"

  local network_id
  network_id=$(wpa_cli -i "$INTERFACE" list_networks | awk -v ssid="$ssid" '$2 == ssid {print $1}')

  if [ -z "$network_id" ]; then
    network_id=$(wpa_cli -i "$INTERFACE" add_network)
    if [ -z "$network_id" ]; then
      printf "ERROR - Failed to add network '%s' via wpa_cli.\n" "$ssid" >&2
      return 1
    fi

    wpa_cli -i "$INTERFACE" set_network "$network_id" ssid "\"$ssid\""
    wpa_cli -i "$INTERFACE" set_network "$network_id" psk "\"$password\""
    wpa_cli -i "$INTERFACE" enable_network "$network_id"
    wpa_cli -i "$INTERFACE" select_network "$network_id"

    printf "INFO - Network '%s' added and selected.\n" "$ssid"
  else
    wpa_cli -i "$INTERFACE" enable_network "$network_id"
    wpa_cli -i "$INTERFACE" select_network "$network_id"
    printf "INFO - Network '%s' enabled and selected.\n" "$ssid"
  fi

  wpa_cli -i "$INTERFACE" save_config

  printf "INFO - Waiting for 10 seconds to establish connection to '%s'.\n" "$ssid"
  sleep 10

  local new_ssid
  new_ssid=$(iwgetid -r)
  if [ "$new_ssid" == "$ssid" ]; then
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
    get_current_connection_info
    scan_wifi_networks

    local best_ssid=""
    local best_signal=-100

    for entry in "${available_networks[@]}"; do
      local ssid
      local signal
      ssid=$(echo "$entry" | cut -d';' -f1)
      signal=$(echo "$entry" | cut -d';' -f2)

      if ! [[ "$signal" =~ ^-?[0-9]+$ ]]; then
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
          printf "INFO - Not connected. Connecting to '%s' (%d dBm).\n" "$best_ssid" "$best_signal"
          if connect_to_network "$best_ssid" "$best_password"; then
            printf "INFO - Connected to '%s'.\n" "$best_ssid"
          else
            printf "ERROR - Could not connect to '%s'. Will retry in next scan.\n" "$best_ssid" >&2
          fi
        else
          local signal_diff=$((best_signal - current_signal))
          if [ "$signal_diff" -ge "$SIGNAL_THRESHOLD" ]; then
            printf "INFO - Found better network '%s' (%d dBm) compared to current '%s' (%d dBm). Difference: %d dBm. Switching...\n" "$best_ssid" "$best_signal" "$current_ssid" "$current_signal" "$signal_diff"
            if connect_to_network "$best_ssid" "$best_password"; then
              printf "INFO - Switched to '%s'.\n" "$best_ssid"
            else
              printf "ERROR - Failed to switch to '%s'. Will retry in next scan.\n" "$best_ssid" >&2
            fi
          else
            printf "INFO - Current network '%s' (%d dBm) is sufficient. No switch needed. Best available: '%s' (%d dBm) with difference %d dBm.\n" "$current_ssid" "$current_signal" "$best_ssid" "$best_signal" "$signal_diff"
          fi
        fi
      else
        printf "INFO - Already connected to the best network '%s' (%d dBm).\n" "$current_ssid" "$current_signal"
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

initialize_wpa_supplicant

if ! restart_wpa_supplicant; then
  printf "ERROR - Could not restart wpa_supplicant. Exiting...\n" >&2
  exit 1
fi

# Begin the main loop for monitoring and connecting to the strongest Wi-Fi network
main_loop
