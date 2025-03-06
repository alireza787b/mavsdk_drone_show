#!/bin/bash
# Install Git Sync (MDS) Service

echo "-----------------------------------------"
echo "Installing Git Sync (MDS) Service"
echo "-----------------------------------------"

# Ensure the script is run as root
if [[ $EUID -ne 0 ]]; then
    echo "Error: This script must be run as root!" 1>&2
    exit 1
fi

# Define paths
GIT_SYNC_SCRIPT="/home/droneshow/mavsdk_drone_show/tools/update_repo_ssh.sh"
SERVICE_FILE="/etc/systemd/system/git_sync_mds.service"
SOURCE_SERVICE_FILE="/home/droneshow/mavsdk_drone_show/tools/git_sync_mds/git_sync_mds.service"

# Step 1: Check if the Git sync script exists
if [ ! -f "$GIT_SYNC_SCRIPT" ]; then
    echo "Error: Git sync script not found at $GIT_SYNC_SCRIPT!" 1>&2
    exit 1
else
    echo "Git sync script found. Proceeding..."
fi

# Step 2: Install or replace the service file
if [ -f "$SERVICE_FILE" ]; then
    echo "Git Sync service file exists. Replacing the existing file..."
    cp "$SOURCE_SERVICE_FILE" "$SERVICE_FILE"
else
    echo "Git Sync service file not found. Installing new service file..."
    if [ ! -f "$SOURCE_SERVICE_FILE" ]; then
        echo "Error: Source Git Sync service file not found at $SOURCE_SERVICE_FILE!" 1>&2
        exit 1
    fi
    cp "$SOURCE_SERVICE_FILE" "$SERVICE_FILE"
fi

# Reload systemd daemon to register the new service
echo "Reloading systemd daemon..."
systemctl daemon-reload

# Enable the Git Sync service to run on boot
echo "Enabling Git Sync service to run on boot..."
systemctl enable git_sync_mds.service

# Start the Git Sync service immediately
echo "Starting Git Sync service..."
systemctl start git_sync_mds.service

# Check the status of the service
echo "Checking the status of the Git Sync service..."
systemctl status git_sync_mds.service --no-pager

echo "-----------------------------------------"
echo "Git Sync (MDS) Service installation complete!"
echo "-----------------------------------------"
