#!/bin/bash

# Script: check_and_update_service.sh
# Purpose: Checks if the Coordinator service file has changed and updates it if necessary.

set -euo pipefail

# Paths
REPO_USER="droneshow"
REPO_DIR="/home/${REPO_USER}/mavsdk_drone_show"
SERVICE_FILE_REPO_PATH="${REPO_DIR}/tools/coordinator.service"
SYSTEMD_SERVICE_PATH="/etc/systemd/system/coordinator.service"

# Ensure the service file exists in the repository
if [ ! -f "$SERVICE_FILE_REPO_PATH" ]; then
    echo "Coordinator service file not found in repository: $SERVICE_FILE_REPO_PATH"
    exit 1
fi

# Calculate checksums
new_checksum=$(md5sum "$SERVICE_FILE_REPO_PATH" | awk '{ print $1 }')
current_checksum=$(md5sum "$SYSTEMD_SERVICE_PATH" 2>/dev/null | awk '{ print $1 }' || echo "")

# Compare checksums
if [ "$new_checksum" != "$current_checksum" ]; then
    echo "Coordinator service file has changed. Updating systemd service..."

    # Copy the new service file
    sudo cp "$SERVICE_FILE_REPO_PATH" "$SYSTEMD_SERVICE_PATH"

    # Reload systemd daemon
    sudo systemctl daemon-reload

    # Restart the Coordinator service
    sudo systemctl restart coordinator.service

    echo "Coordinator service updated and restarted."
else
    echo "Coordinator service file is up-to-date. No update needed."
fi
