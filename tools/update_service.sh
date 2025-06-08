#!/bin/bash

# Script: update_service.sh
# Purpose: Automates the deployment or update of the Drone Swarm System Coordinator service.
#          It ensures that the systemd service file (coordinator.service) is updated only if it has changed.
#          The script compares the checksum of the current service file with the one in the repository.
#          If there's a difference, it updates the service file, reloads systemd, and restarts the service.
#
# Usage:
# - Run this script directly in a terminal or as part of a deployment process.
# - Ensure the script has executable permissions:
#       chmod +x update_service.sh
# - Execute the script:
#       ./update_service.sh
#
# Configuration:
# - The script assumes the Drone Swarm System Coordinator service file is located in the 'tools' directory
#   of the 'mavsdk_drone_show' repository in the user's home directory.
# - Modify the 'REPO_DIR' variable if your repository is located in a different path.
#
# System Requirements:
# - A Linux distribution with systemd installed and enabled.
# - The user executing the script must have sudo privileges to manage systemd services.
#
# Output:
# - The script provides console output detailing each step of the process, including any failures.
# - In case of failure, appropriate error messages are displayed to help diagnose issues.

# Assume the user is 'droneshow' for the script execution context; modify as needed for other users.
REPO_USER="AeroHive"

# Define the base directory for the repository.
REPO_DIR="/home/${REPO_USER}/UAV_sepehr"

# Path to the service file in the repository
SERVICE_FILE_PATH="${REPO_DIR}/tools/coordinator.service"

# Path to the systemd service directory
SYSTEMD_SERVICE_PATH="/etc/systemd/system/coordinator.service"

# Backup path for the existing service file
BACKUP_PATH="/etc/systemd/system/coordinator.service.bak"

# Calculate checksums of the current and new service files
current_checksum=$(md5sum "$SYSTEMD_SERVICE_PATH" 2>/dev/null | awk '{ print $1 }')
new_checksum=$(md5sum "$SERVICE_FILE_PATH" 2>/dev/null | awk '{ print $1 }')

# Check if the service file needs updating
if [ "$current_checksum" != "$new_checksum" ]; then
    echo "Detected a difference in the service file. Updating..."

    # Backup the current service file if it exists
    if [ -f "$SYSTEMD_SERVICE_PATH" ]; then
        echo "Backing up current service file..."
        sudo cp "$SYSTEMD_SERVICE_PATH" "$BACKUP_PATH"
        if [ $? -ne 0 ]; then
            echo "Error: Failed to backup the existing service file. Aborting update."
            exit 1
        fi
    fi

    # Copy the new service file to the systemd directory
    echo "Copying new service file..."
    sudo cp "$SERVICE_FILE_PATH" "$SYSTEMD_SERVICE_PATH"
    if [ $? -ne 0 ]; then
        echo "Error: Failed to copy the new service file. Restoring backup..."
        sudo cp "$BACKUP_PATH" "$SYSTEMD_SERVICE_PATH"
        exit 1
    else
        echo "Service file copied successfully."
    fi

    # Reload systemd to recognize changes
    echo "Reloading systemd..."
    sudo systemctl daemon-reload
    if [ $? -ne 0 ]; then
        echo "Error: Failed to reload systemd. Aborting."
        exit 1
    fi

    # Restart the service
    echo "Restarting the coordinator service..."
    sudo systemctl restart coordinator.service
    if [ $? -ne 0 ]; then
        echo "Error: Failed to restart the service. Please check the service logs."
        exit 1
    else
        echo "Service restarted successfully."
    fi
else
    echo "Service file is already up-to-date. No action needed."
fi

echo "Service update process completed."
