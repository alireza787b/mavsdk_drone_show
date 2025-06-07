#!/usr/bin/env bash
# Wi-Fi Manager for Drone Show — robust, self-healing, connectivity-aware
set -euo pipefail
IFS=$'\n\t'

# =======================
# Configuration Parameters
# =======================
CONFIG_FILE="$(dirname "$0")/known_networks.conf"
LOG_FILE="/var/log/wifi-manager.log"
SCAN_INTERVAL=10             # seconds between scans
SIGNAL_THRESHOLD=30          # minimum % improvement to switch
MAX_LOG_SIZE=5242880         # 5 MiB
BACKUP_COUNT=3
LOCK_FILE="/var/run/wifi-manager.lock"

# Connectivity check settings
# Set CONNECTIVITY_CHECK_ENABLED to "true" or "false" to enable/disable ping-based validation
CONNECTIVITY_CHECK_ENABLED=false
PING_TARGET="8.8.8.8"
PING_COUNT=2
PING_TIMEOUT=1               # seconds per ping

# Required commands
REQUIRED_CMDS=(nmcli flock timeout stat ping awk)
for cmd in "${REQUIRED_CMDS[@]}"; do
  command -v "$cmd" >/dev/null || { echo "ERROR: '$cmd' not found"; exit 1; }
done

# =======================
# Logging
# =======================
log() {
  local level="$1"; shift
  local ts; ts=$(date '+%Y-%m-%d %H:%M:%S')
  echo "$ts [$level] $*" | tee -a "$LOG_FILE"
}

# =======================
# Lockfile (prevent multiple instances)
# =======================
exec 200>"$LOCK_FILE"
flock -n 200 || { log ERROR "Another instance is running."; exit 1; }
echo $$ >&200
trap 'rm -f "$LOCK_FILE"' EXIT

# Ensure log file exists
mkdir -p "$(dirname "$LOG_FILE")"
touch "$LOG_FILE"
chmod 600 "$LOG_FILE"

# =======================
# Log Rotation
# =======================
rotate_logs() {
  [ -f "$LOG_FILE" ] || { : > "$LOG_FILE"; return; }
  local size; size=$(stat -c%s "$LOG_FILE")
  if (( size >= MAX_LOG_SIZE )); then
    for ((i=BACKUP_COUNT; i>0; i--)); do
      [ -f "$LOG_FILE.$i" ] && mv "$LOG_FILE.$i" "$LOG_FILE.$((i+1))"
    done
    mv "$LOG_FILE" "$LOG_FILE.1"
    : > "$LOG_FILE"
    log INFO "Rotated logs."
  fi
}

# =======================
# Load Known Networks
# =======================
declare -A KNOWN_NETWORKS
load_known_networks() {
  [ -f "$CONFIG_FILE" ] || { log ERROR "Missing $CONFIG_FILE"; exit 1; }
  KNOWN_NETWORKS=()
  while IFS='=' read -r key val; do
    key=${key//[[:space:]]/}
    val=${val//[[:space:]]/}
    case "$key" in
      ssid)  ssid="$val" ;;
      password)
        KNOWN_NETWORKS[$ssid]="$val"
        log INFO "Loaded SSID='$ssid'"
        ;;
      *) [[ "$key" =~ ^# ]] || log WARNING "Unknown key '$key'" ;;
    esac
  done < "$CONFIG_FILE"
  (( ${#KNOWN_NETWORKS[@]} )) || { log ERROR "No networks loaded"; exit 1; }
}

# =======================
# Interface Detection
# =======================
get_interface() {
  nmcli -t -f DEVICE,TYPE dev status | awk -F: '$2=="wifi"{print $1; exit}' || echo wlan0
}
INTERFACE=$(get_interface)
log INFO "Using interface: $INTERFACE"

# =======================
# Scan Wi-Fi
# =======================
scan_wifi_networks() {
  available_networks=()
  local out
  out=$(nmcli -t -f SSID,SIGNAL dev wifi list ifname "$INTERFACE" --rescan yes 2>&1) || {
    log WARNING "Scan failed: $out"; return
  }
  while IFS=: read -r ss sig; do
    ss=${ss// /}
    sig=${sig// /}
    [[ -z "$ss" ]] && continue
    available_networks+=("$ss;$sig")
  done <<< "$out"
}

# =======================
# Current Connection
# =======================
get_current_connection_info() {
  current_ssid=$(nmcli -t -f ACTIVE,SSID dev wifi | awk -F: '$1=="yes"{print $2}')
  if [[ -n "$current_ssid" ]]; then
    current_signal=$(nmcli -t -f ACTIVE,SIGNAL dev wifi | awk -F: '$1=="yes"{print $2}')
    log INFO "Connected: '$current_ssid' ($current_signal%)"
  else
    current_ssid=""; current_signal=0
    log INFO "Not connected to any network."
  fi
}

# =======================
# Connectivity Check (optional)
# =======================
check_connectivity() {
  if ! ping -c"$PING_COUNT" -W"$PING_TIMEOUT" "$PING_TARGET" >/dev/null 2>&1; then
    log WARNING "Ping to $PING_TARGET failed."
    return 1
  fi
  return 0
}

# =======================
# Connect
# =======================
connect_to_network() {
  local ssid="$1" pwd="$2"
  log INFO "Connecting to '$ssid'..."
  nmcli_output=$(timeout 15 nmcli dev wifi connect "$ssid" password "$pwd" ifname "$INTERFACE" 2>&1) || true
  if [[ "$CONNECTIVITY_CHECK_ENABLED" == "true" ]]; then
    if check_connectivity; then
      log INFO "Online on '$ssid'."
      return 0
    else
      log ERROR "No Internet; disconnecting."
      nmcli con down id "$ssid" || true
      return 1
    fi
  else
    log INFO "Skipping connectivity check (disabled)."
    return 0
  fi
  log ERROR "Cannot join '$ssid': $nmcli_output"
  return 1
}

# =======================
# Main Loop
# =======================
main_loop() {
  while true; do
    {
      rotate_logs
      load_known_networks
      scan_wifi_networks
      get_current_connection_info

      best_ssid=""; best_signal=-999
      for entry in "${available_networks[@]}"; do
        IFS=';' read -r ss sig <<< "$entry"
        (( sig > best_signal )) && [[ -v KNOWN_NETWORKS["$ss"] ]] && {
          best_signal=$sig; best_ssid=$ss
        }
      done

      if [[ "$current_ssid" != "$best_ssid" && -n "$best_ssid" ]]; then
        diff=$(( best_signal - current_signal ))
        if (( diff >= SIGNAL_THRESHOLD || current_ssid=="" )); then
          connect_to_network "$best_ssid" "${KNOWN_NETWORKS[$best_ssid]}"
        else
          log INFO "Better SSID '$best_ssid' ($best_signal%), but Δ=$diff% < threshold."
        fi
      else
        log DEBUG "Staying on '$current_ssid'."
      fi
    } || log ERROR "Iteration error—retrying in $SCAN_INTERVAL s"
    sleep "$SCAN_INTERVAL"
  done
}

main_loop
