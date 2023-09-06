#!/bin/bash

# Get the current system time before synchronization
before_sync_time=$(date +"%Y-%m-%d %H:%M:%S")

# Synchronize system time with a time server
sudo timedatectl set-ntp false  # Disable NTP
sudo timedatectl set-ntp true  # Enable NTP to force a sync

# Wait a few seconds to allow time for the sync to occur
sleep 5

# Get the system time after synchronization
after_sync_time=$(date +"%Y-%m-%d %H:%M:%S")

# Calculate the time deviation
before_epoch=$(date -d "$before_sync_time" +%s)
after_epoch=$(date -d "$after_sync_time" +%s)
time_deviation=$((after_epoch - before_epoch))

# Report the times and the deviation
echo "Time before sync: $before_sync_time"
echo "Time after sync: $after_sync_time"
echo "Time deviation: ${time_deviation}s"
