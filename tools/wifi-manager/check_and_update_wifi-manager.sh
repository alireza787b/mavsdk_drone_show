#!/bin/bash

# Script: check_and_update_wifi-manager.sh
# Purpose: Checks if the Wi-Fi Manager systemd service file has changed in the repository.
#          If it has, updates the systemd service and restarts it.

set -euo pipefail

# Paths
REPO_USER="droneshow"
REPO_DIR="/home/${REPO_USER}/mavsdk_drone_show"
SERVICE_FILE_REPO_PATH="${REPO_DIR}/tools/wifi-manager/wifi-manager.service"
SYSTEMD_SERVICE_PATH="/etc/systemd/system/wifi-manager.service"

# Ensure the service file exists in the repository
if [ ! -f "$SERVICE_FILE_REPO_PATH" ]; then
    echo "Wi-Fi Manager service file not found in repository: $SERVICE_FILE_REPO_PATH"
    exit 1
fi

# Calculate checksums
new_checksum=$(md5sum "$SERVICE_FILE_REPO_PATH" | awk '{ print $1 }')
current_checksum=$(md5sum "$SYSTEMD_SERVICE_PATH" 2>/dev/null | awk '{ print $1 }' || echo "")

# Compare checksums
if [ "$new_checksum" != "$current_checksum" ]; then
    echo "Wi-Fi Manager service file in the repository has changed. Updating systemd service..."

    # Copy the new service file
    sudo cp "$SERVICE_FILE_REPO_PATH" "$SYSTEMD_SERVICE_PATH"

    # Reload systemd daemon
    sudo systemctl daemon-reload

    # Restart the Wi-Fi Manager service
    sudo systemctl restart wifi-manager.service

    echo "Wi-Fi Manager service updated and restarted."
else
    echo "Wi-Fi Manager service file is up-to-date. No update needed."
fi
