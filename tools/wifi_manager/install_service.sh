#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Variables
SERVICE_FILE="wifi_manager.service"
PYTHON_SCRIPT="wifi_manager.py"
CONFIG_FILE="known_networks.json"  # Optional
INSTALL_DIR="$HOME/mavsdk_drone_show/tools/wifi_manager"
SERVICE_DEST_DIR="/etc/systemd/system"
SERVICE_DEST_PATH="$SERVICE_DEST_DIR/$SERVICE_FILE"
SCRIPT_PATH="$INSTALL_DIR/$PYTHON_SCRIPT"
CONFIG_PATH="$INSTALL_DIR/$CONFIG_FILE"
LOG_FILE="/var/log/wifi_manager_install.log"
REQUIREMENTS_FILE="requirements.txt"  # Optional
REQUIREMENTS_PATH="$INSTALL_DIR/$REQUIREMENTS_FILE"

# Redirect all output to log file and to console
exec > >(tee -a "$LOG_FILE") 2>&1

echo "========================================="
echo "  Wi-Fi Manager Installation Script      "
echo "========================================="
echo "Installation started at $(date)"

# Function to check if a file exists
file_exists() {
    local file="$1"
    if [ -f "$file" ]; then
        return 0
    else
        return 1
    fi
}

# Update package lists
echo "Updating package lists..."
sudo apt-get update -y

# Install required packages
echo "Installing required dependencies..."
sudo apt-get install -y wireless-tools wpasupplicant python3 python3-pip

# Install Python dependencies if requirements.txt exists
if file_exists "$REQUIREMENTS_PATH"; then
    echo "Installing Python dependencies from requirements.txt..."
    sudo pip3 install -r "$REQUIREMENTS_PATH"
else
    echo "Notice: requirements.txt not found. Skipping Python dependencies installation."
fi

# Verify Python script exists
if file_exists "$SCRIPT_PATH"; then
    echo "Python script found at $SCRIPT_PATH."
else
    echo "Error: $PYTHON_SCRIPT not found in $INSTALL_DIR."
    exit 1
fi

# Copy the service file to /etc/systemd/system/
if file_exists "$SERVICE_FILE"; then
    echo "Copying service file to $SERVICE_DEST_DIR..."
    sudo cp "$SERVICE_FILE" "$SERVICE_DEST_PATH"
    sudo chmod 644 "$SERVICE_DEST_PATH"
else
    echo "Error: $SERVICE_FILE not found in $INSTALL_DIR."
    exit 1
fi

# Handle existing service
if systemctl list-unit-files | grep -q "^wifi_manager.service"; then
    echo "Existing Wi-Fi Manager service found. Stopping and disabling it..."
    sudo systemctl stop wifi_manager.service || echo "Service was not running."
    sudo systemctl disable wifi_manager.service || echo "Service was not enabled."
fi

# Reload systemd daemon to recognize the new/updated service
echo "Reloading systemd daemon..."
sudo systemctl daemon-reload

# Enable the service to start on boot
echo "Enabling Wi-Fi Manager service to start on boot..."
sudo systemctl enable "$SERVICE_FILE"

# Start the service immediately
echo "Starting Wi-Fi Manager service..."
sudo systemctl start "$SERVICE_FILE"

# Verify service status
echo "Verifying service status..."
sudo systemctl status "$SERVICE_FILE" --no-pager

echo "Wi-Fi Manager Service installed and started successfully at $(date)."
echo "Installation complete."
