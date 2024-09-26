#!/bin/bash

# Script: update_wifi-manager_service.sh
# Purpose: Automates the deployment or update of the Wi-Fi Manager systemd service for drones.
#          It ensures that the systemd service file (wifi-manager.service) is updated only if it has changed.
#          The script compares the checksum of the current service file with the one in the repository.
#          If there's a difference, it updates the service file, reloads systemd, and restarts the service.
#
# Usage:
# - Run this script directly in a terminal or as part of a deployment process.
# - Ensure the script has executable permissions:
#       chmod +x update_wifi-manager_service.sh
# - Execute the script:
#       ./update_wifi-manager_service.sh
#
# Configuration:
# - The script assumes the Wi-Fi Manager service file is located in the 'tools' directory
#   of the 'mavsdk_drone_show' repository in the 'droneshow' user's home directory.
# - Modify the 'REPO_DIR' variable if your repository is located in a different path.
#
# System Requirements:
# - A Linux distribution with systemd installed and enabled.
# - The user executing the script must have sudo privileges to manage systemd services.
#
# Output:
# - The script provides console output detailing each step of the process, including any failures.
# - In case of failure, appropriate error messages are displayed to help diagnose issues.

# Define the user and repository details
REPO_USER="droneshow"
REPO_DIR="/home/${REPO_USER}/mavsdk_drone_show"

# Path to the service file in the repository
SERVICE_FILE_PATH="${REPO_DIR}/tools/wifi-manager/wifi-manager.service"

# Path to the systemd service directory
SYSTEMD_SERVICE_PATH="/etc/systemd/system/wifi-manager.service"

# Backup path for the existing service file
BACKUP_PATH="/etc/systemd/system/wifi-manager.service.bak"

# Check if the new service file exists in the repository
if [ ! -f "$SERVICE_FILE_PATH" ]; then
    echo "Error: Service file not found in ${SERVICE_FILE_PATH}."
    exit 1
fi

# Calculate checksums of the current and new service files
current_checksum=$(md5sum "$SYSTEMD_SERVICE_PATH" 2>/dev/null | awk '{ print $1 }')
new_checksum=$(md5sum "$SERVICE_FILE_PATH" | awk '{ print $1 }')

# Check if the service file needs updating
if [ "$current_checksum" != "$new_checksum" ]; then
    echo "Detected a difference in the Wi-Fi Manager service file. Updating..."

    # Backup the current service file if it exists
    if [ -f "$SYSTEMD_SERVICE_PATH" ]; then
        echo "Backing up the current service file..."
        sudo cp "$SYSTEMD_SERVICE_PATH" "$BACKUP_PATH"
        if [ $? -ne 0 ]; then
            echo "Error: Failed to backup the existing service file. Aborting update."
            exit 1
        fi
    fi

    # Copy the new service file to the systemd directory
    echo "Copying the new service file..."
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

    # Restart the Wi-Fi Manager service
    echo "Restarting the Wi-Fi Manager service..."
    sudo systemctl restart wifi-manager.service
    if [ $? -ne 0 ]; then
        echo "Error: Failed to restart the Wi-Fi Manager service. Please check the service logs."
        exit 1
    else
        echo "Wi-Fi Manager service restarted successfully."
    fi
else
    echo "Wi-Fi Manager service file is already up-to-date. No action needed."
fi

echo "Wi-Fi Manager service update process completed."
