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
LED_INDICATOR_SCRIPT="/home/droneshow/mavsdk_drone_show/tools/led_indicator/led_indicator.py"
SERVICE_FILE="/etc/systemd/system/led_indicator.service"
SOURCE_SERVICE_FILE="/home/droneshow/mavsdk_drone_show/tools/led_indicator/led_indicator.service"

# Step 1: Check if the Python LED indicator script exists
if [ ! -f "$LED_INDICATOR_SCRIPT" ]; then
    echo "LED Indicator Python script not found. Creating the script..."

    # Create the Python script for controlling the LED (self-contained)
    cat <<EOF > "$LED_INDICATOR_SCRIPT"
#!/usr/bin/env python3

import sys
import time
import logging
from rpi_ws281x import PixelStrip, Color

# Configuration for the LED (set directly in the script)
LED_PIN = 10  # GPIO pin connected to the LED strip
LED_COUNT = 25  # Number of LEDs
LED_FREQ_HZ = 800000  # LED signal frequency in Hz
LED_DMA = 10  # DMA channel
LED_BRIGHTNESS = 255  # Brightness level
LED_INVERT = False  # Whether to invert the signal
LED_CHANNEL = 0  # GPIO channel

# Define the color to set the LEDs to (red in this case)
RED_COLOR = Color(255, 0, 0)  # RGB for red

# Setup logging for error handling
logging.basicConfig(level=logging.INFO)

try:
    # Initialize the LED strip
    strip = PixelStrip(LED_COUNT, LED_PIN, freq_hz=LED_FREQ_HZ, dma=LED_DMA, invert=LED_INVERT, brightness=LED_BRIGHTNESS, channel=LED_CHANNEL)
    strip.begin()

    # Set all LEDs to red
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, RED_COLOR)
    strip.show()

    logging.info("LEDs set to red")

    # Keep the LEDs on for 5 seconds
    time.sleep(5)

    # Optionally, you can turn off the LEDs after the 5 seconds
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, Color(0, 0, 0))  # Set all LEDs to off
    strip.show()

    logging.info("LEDs turned off")

except Exception as e:
    # Log any errors that occur during the process
    logging.error(f"Error initializing or controlling LEDs: {e}")
    sys.exit(0)
EOF

    # Make the script executable
    chmod +x "$LED_INDICATOR_SCRIPT"
    echo "LED Indicator Python script created and made executable."
fi

# Step 2: Check if the service file exists, if not, create and install it
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
