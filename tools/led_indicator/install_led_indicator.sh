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

# Define paths
LED_INDICATOR_SCRIPT="/home/droneshow/mavsdk_drone_show/led_indicator.py"
SERVICE_FILE="/etc/systemd/system/led_indicator.service"
SOURCE_SERVICE_FILE="/home/droneshow/mavsdk_drone_show/tools/led_indicator/led_indicator.service"

# Step 1: Check if the Python LED indicator script exists
if [ ! -f "$LED_INDICATOR_SCRIPT" ]; then
    echo "Error: LED Indicator Python script not found at $LED_INDICATOR_SCRIPT!" 1>&2
    exit 1
else
    echo "LED Indicator Python script already exists. Skipping creation."
fi

# Step 2: Check if the service file exists, if not, install it
if [ -f "$SERVICE_FILE" ]; then
    echo "LED Indicator service file already exists. Skipping installation."
else
    echo "LED Indicator service file not found. Installing the service file..."

    # Check if the source service file exists
    if [ ! -f "$SOURCE_SERVICE_FILE" ]; then
        echo "Error: Source LED Indicator service file not found at $SOURCE_SERVICE_FILE!" 1>&2
        exit 1
    fi

    # Copy the LED service file to /etc/systemd/system/
    echo "Copying LED Indicator service file to /etc/systemd/system/..."
    cp "$SOURCE_SERVICE_FILE" "$SERVICE_FILE"

    # Reload systemd to recognize the new service
    echo "Reloading systemd to recognize the new service..."
    systemctl daemon-reload
fi

# Step 3: Enable the service to start on boot
echo "Enabling LED Indicator service to start on boot..."
systemctl enable led_indicator.service

# Step 4: Start the service immediately
echo "Starting the LED Indicator service..."
systemctl start led_indicator.service

# Step 5: Check the status of the LED service to ensure it is running
echo "Checking the status of the LED Indicator service..."
systemctl status led_indicator.service

# Output success message
echo "-----------------------------------------"
echo "LED Indicator Service installation complete!"
echo "-----------------------------------------"
