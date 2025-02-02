#!/bin/bash

# Install LED Indicator Service
echo "-----------------------------------------"
echo "Installing LED Indicator Service"
echo "-----------------------------------------"

# Check if we're running as root (necessary to install systemd services)
if [[ $EUID -ne 0 ]]; then
    echo "Error: This script must be run as root!" 1>&2
    exit 1
fi

# Check if the service file exists
SERVICE_FILE="/etc/systemd/system/led_indicator.service"

if [ ! -f "$SERVICE_FILE" ]; then
    echo "Error: LED Indicator service file not found!" 1>&2
    exit 1
fi

# Copy the LED service file to systemd
echo "Copying LED Indicator service file to /etc/systemd/system/..."
cp /home/droneshow/mavsdk_drone_show/tools/led_indicator/led_indicator.service /etc/systemd/system/

# Reload systemd to recognize the new service
echo "Reloading systemd to recognize the new service..."
systemctl daemon-reload

# Enable the service to start on boot
echo "Enabling LED Indicator service to start on boot..."
systemctl enable led_indicator.service

# Start the service immediately
echo "Starting the LED Indicator service..."
systemctl start led_indicator.service

# Check the status of the LED service to ensure it is running
echo "Checking the status of the LED Indicator service..."
systemctl status led_indicator.service

# Output success message
echo "-----------------------------------------"
echo "LED Indicator Service installation complete!"
echo "-----------------------------------------"
