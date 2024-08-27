#!/bin/bash

# Function to log messages to the terminal with timestamps
log_message() {
    local message="$1"
    echo "$(date +"%Y-%m-%d %H:%M:%S") - $message"
}

# If the script is not being run as root, re-run it with sudo
if [ "$(id -u)" != "0" ]; then
    log_message "This script must be run as root or with sudo privileges. Re-running with sudo..."
    exec sudo /bin/bash "$0" "$@"
fi

# Get the current system time before synchronization
before_sync_time=$(date +"%Y-%m-%d %H:%M:%S")
log_message "Current system time before synchronization: $before_sync_time"

# Synchronize system time with a time server
log_message "Disabling NTP to force a sync..."
if ! timedatectl set-ntp false; then
    log_message "Warning: Failed to disable NTP. Continuing with the script..."
fi

log_message "Enabling NTP to force a time sync..."
if ! timedatectl set-ntp true; then
    log_message "Error: Failed to enable NTP for time synchronization. Please check the NTP configuration."
    log_message "Continuing, but time may not be synchronized correctly."
fi

# Wait a few seconds to allow time for the sync to occur
sleep 5

# Get the system time after synchronization
after_sync_time=$(date +"%Y-%m-%d %H:%M:%S")
log_message "System time after synchronization: $after_sync_time"

# Calculate the time deviation
before_epoch=$(date -d "$before_sync_time" +%s)
after_epoch=$(date -d "$after_sync_time" +%s)
time_deviation=$((after_epoch - before_epoch - 5))  # Subtract 5 seconds for the sleep duration

# Report the times and the deviation
log_message "Time synchronization completed."
log_message "Time deviation after sync: ${time_deviation}s"

if [ "$time_deviation" -ne 0 ]; then
    log_message "Warning: There was a time deviation of ${time_deviation} seconds. Please ensure that all drones are correctly synchronized."
fi
