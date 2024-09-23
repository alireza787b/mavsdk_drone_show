#!/bin/bash

# Script to download the mavsdk_server binary for Raspberry Pi 4 (64-bit)
# Ensures it's run from the directory '~/mavsdk_drone_show', uses sudo for necessary operations,
# and provides detailed reporting of each step.

# URL for the latest mavsdk_server binary for Raspberry Pi 4 (64-bit) as of 23 July 2024
BINARY_URL="https://github.com/mavlink/MAVSDK/releases/download/v2.12.6/mavsdk_server_linux-arm64-musl"

# Define the expected repository directory dynamically
EXPECTED_DIR="$(eval echo ~$SUDO_USER)/mavsdk_drone_show"

# Check if the script is running in the correct directory
if [ "$(pwd)" != "$EXPECTED_DIR" ]; then
    echo "Error: This script must be run from the '$EXPECTED_DIR' directory."
    echo "Please navigate to $EXPECTED_DIR and rerun this script."
    exit 1
fi

echo "Confirmed: Script is running from the correct directory."


# Download the binary to the current directory
echo "Starting download of mavsdk_server..."
wget -O mavsdk_server_temp $BINARY_URL --show-progress

# Check download success
if [ $? -eq 0 ]; then
    echo "Download successful."

    # Replace existing binary if it exists
    if [ -f mavsdk_server ]; then
        echo "Replacing existing mavsdk_server binary."
        rm -f mavsdk_server
    fi

    # Move the temporary file to the final binary name
    mv mavsdk_server_temp mavsdk_server
    echo "mavsdk_server binary is updated."

    # Set executable permissions using sudo
    sudo chmod +x mavsdk_server
    echo "Executable permissions set for mavsdk_server."

    echo "Operation completed successfully. mavsdk_server is ready for use."
else
    echo "Download failed. Please check the URL and your internet connection."
    rm -f mavsdk_server_temp
    exit 1
fi
