#!/bin/bash

# =============================================================================
# Script Name: sync_time_linux.sh
# Description: Synchronizes the system time with NTP servers and logs the process.
# Author: Alireza Ghaderi
# Date: September 2024
# =============================================================================

# Exit immediately if a command exits with a non-zero status,
# if an undefined variable is used, or if any command in a pipeline fails
set -euo pipefail

# =============================================================================
# Function Definitions
# =============================================================================

# Function to log messages to the terminal with timestamps
log_message() {
    local message="$1"
    echo "$(date +"%Y-%m-%d %H:%M:%S") - $message"
}

# Function to handle script termination and cleanup
cleanup() {
    log_message "Interrupt signal received. Exiting time synchronization script."
    exit 0
}

# Trap SIGINT and SIGTERM to execute cleanup
trap 'cleanup' INT TERM

# =============================================================================
# Main Script Execution
# =============================================================================

log_message "=============================================="
log_message "Starting Time Synchronization with NTP"
log_message "=============================================="
log_message ""

# Determine if the script is running as root
if [ "$(id -u)" -ne 0 ]; then
    log_message "Not running as root. Attempting to use sudo for time synchronization."
    SUDO_CMD="sudo"
else
    log_message "Running as root."
    SUDO_CMD=""
fi

# Get the current system time before synchronization
before_sync_time=$(date +"%Y-%m-%d %H:%M:%S")
log_message "Current system time before synchronization: $before_sync_time"

# Synchronize system time with a time server using ntpdate
ntp_server="pool.ntp.org"

log_message "Synchronizing system time with NTP server: $ntp_server"
if ! $SUDO_CMD ntpdate "$ntp_server"; then
    log_message "ERROR: Failed to synchronize time with NTP server: $ntp_server."
    log_message "Continuing, but time may not be synchronized correctly."
fi

# Get the system time after synchronization
after_sync_time=$(date +"%Y-%m-%d %H:%M:%S")
log_message "System time after synchronization: $after_sync_time"

# Calculate the time deviation
before_epoch=$(date -d "$before_sync_time" +%s)
after_epoch=$(date -d "$after_sync_time" +%s)
time_deviation=$((after_epoch - before_epoch))

# Report the times and the deviation
log_message "Time synchronization completed."
log_message "Time deviation after sync: ${time_deviation}s"

if [ "$time_deviation" -ne 0 ]; then
    log_message "WARNING: There was a time deviation of ${time_deviation} seconds. Please ensure that all drones are correctly synchronized."
fi

log_message "=============================================="
log_message "Time Synchronization Process Finished."
log_message "=============================================="
log_message ""
