#!/bin/bash

# Paths
REPO_USER="droneshow"
REPO_DIR="/home/${REPO_USER}/mavsdk_drone_show"
SERVICE_FILE_REPO_PATH="${REPO_DIR}/tools/coordinator.service"
SYSTEMD_SERVICE_PATH="/etc/systemd/system/coordinator.service"

# Calculate checksums
new_checksum=$(md5sum "$SERVICE_FILE_REPO_PATH" 2>/dev/null | awk '{ print $1 }')
current_checksum=$(md5sum "$SYSTEMD_SERVICE_PATH" 2>/dev/null | awk '{ print $1 }')

# Compare checksums
if [ "$new_checksum" != "$current_checksum" ]; then
    echo "Service file in the repository has changed. Updating systemd service..."
    # Run the update script
    /home/droneshow/mavsdk_drone_show/tools/update_service.sh

    # Schedule a restart of the service to avoid restart loop
    echo "sudo systemctl restart coordinator.service" | at now + 1 minute
else
    echo "Service file is up-to-date. No update needed."
fi
