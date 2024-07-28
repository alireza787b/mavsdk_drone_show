#!/bin/bash

# Script: update_service.sh
# Purpose: This script automates the deployment or update of the Drone Swarm System Coordinator service.
# It ensures that the systemd service file (coordinator.service) is correctly placed in the system's
# systemd directory and that the service is enabled and started. This script should be run with sufficient
# privileges to manage systemd services.
#
# Usage:
# - This script is intended to be executed on systems where the Drone Swarm System Coordinator needs to be
#   installed or updated.
# - Run this script directly in a terminal or as part of a larger deployment process.
# - Ensure the script has executable permissions:
#       chmod +x update_service.sh
# - Execute the script:
#       ./update_service.sh
#
# Configuration:
# - The script assumes the Drone Swarm System Coordinator service file is located within a known path in
#   the user's home directory under the repository 'mavsdk_drone_show'.
# - Users may need to modify the 'REPO_DIR' variable to match the repository's location on their system.
#
# System Requirements:
# - A Linux distribution with systemd installed and enabled.
# - The user executing the script must have sudo privileges to manage systemd services.
#
# Output:
# - The script provides console output that details each step of the process, including any failures.
# - In case of failure, appropriate error messages are displayed to help diagnose issues.
#
# Author: [Your Name or Your Team's Name]
# Date: [Date of creation]
# Version: 1.0

# Define the base directory for the repository. Modify this path as needed.
REPO_DIR="${HOME}/mavsdk_drone_show"

# Path to the service file in the repository
SERVICE_FILE_PATH="${REPO_DIR}/tools/coordinator.service"

# Path to the systemd service directory
SYSTEMD_SERVICE_PATH="/etc/systemd/system/coordinator.service"

# Check if the service file exists at the destination
if [ -f "$SYSTEMD_SERVICE_PATH" ]; then
    echo "Service file already exists. Updating..."
else
    echo "Service file does not exist. Creating..."
fi

# Copy the service file to the systemd directory
sudo cp "$SERVICE_FILE_PATH" "$SYSTEMD_SERVICE_PATH"

if [ $? -ne 0 ]; then
    echo "Failed to copy the service file."
    exit 1
else
    echo "Service file copied successfully."
fi

# Reload systemd to recognize changes
sudo systemctl daemon-reload

if [ $? -ne 0 ]; then
    echo "Failed to reload systemd."
    exit 1
else
    echo "Systemd reloaded successfully."
fi

# Enable the service to start on boot
sudo systemctl enable coordinator.service

if [ $? -ne 0 ]; then
    echo "Failed to enable the service."
    exit 1
else
    echo "Service enabled successfully."
fi

# Start the service
sudo systemctl restart coordinator.service

if [ $? -ne 0 ]; then
    echo "Failed to start the service."
    exit 1
else
    echo "Service started successfully."
fi

echo "Service setup completed successfully."
