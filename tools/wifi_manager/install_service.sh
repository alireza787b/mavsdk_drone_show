#!/bin/bash

SERVICE_FILE="wifi_manager.service"
SERVICE_PATH="/etc/systemd/system/$SERVICE_FILE"

echo "Installing required dependencies..."

sudo apt-get update
sudo apt-get install wireless-tools wpasupplicant python3

echo "Installing Wi-Fi Manager Service..."

# Copy the service file
sudo cp $SERVICE_FILE $SERVICE_PATH

# Reload systemd to recognize the new service
sudo systemctl daemon-reload

# Enable the service to start on boot
sudo systemctl enable wifi_manager.service

# Start the service immediately
sudo systemctl start wifi_manager.service

echo "Wi-Fi Manager Service installed and started."
