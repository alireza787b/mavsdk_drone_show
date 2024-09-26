#!/bin/bash

# Script: check_and_update_wifi-manager.sh
# Purpose: Checks if the Wi-Fi Manager systemd service file has changed in the repository.
#          If it has, updates the systemd service and schedules a restart.

# Paths
REPO_USER="droneshow"
REPO_DIR="/home/${REPO_USER}/mavsdk_drone_show"
SERVICE_FILE_REPO_PATH="${REPO_DIR}/tools/wifi-manager/wifi-manager.service"
SYSTEMD_SERVICE_PATH="/etc/systemd/system/wifi-manager.service"

# Calculate checksums
new_checksum=$(md5sum "$SERVICE_FILE_REPO_PATH" 2>/dev/null | awk '{ print $1 }')
current_checksum=$(md5sum "$SYSTEMD_SERVICE_PATH" 2>/dev/null | awk '{ print $1 }')

# Compare checksums
if [ "$new_checksum" != "$current_checksum" ]; then
    echo "Wi-Fi Manager service file in the repository has changed. Updating systemd service..."

    # Run the update script
    /home/droneshow/mavsdk_drone_show/tools/wifi-manager/update_wifi-manager_service.sh

    # Schedule a restart of the Wi-Fi Manager service to avoid potential restart loops
    echo "sudo systemctl restart wifi-manager.service" | at now + 1 minute
else
    echo "Wi-Fi Manager service file is up-to-date. No update needed."
fi
