#!/bin/bash

# Script to download the latest mavsdk_server binary for Raspberry Pi 4 (64-bit)
# This version is optimized for Raspberry Pi 4 running a 64-bit OS as of 23 July 2024.
# The script is stored in the 'tools' directory but downloads the binary to the repository root.

# Define the URL for the latest ARM64 mavsdk_server binary as of 23 July 2024
BINARY_URL="https://github.com/mavlink/MAVSDK/releases/download/v2.12.2/mavsdk_server_linux-arm64-musl"

# Move to the repository root from the tools directory
cd ..

# Start download
echo "Starting download of mavsdk_server for Raspberry Pi 4 (64-bit)..."
wget -O mavsdk_server $BINARY_URL --show-progress

# Check if the download was successful
if [ $? -eq 0 ]; then
    echo "Download successful. Binary is placed in the repository root."
    
    # Set the file permissions to read/write for the owner, read-only for group and others
    chmod 644 mavsdk_server
    echo "File permissions set: Owner (read/write), Group/Others (read-only)."

    # Move back to the tools directory
    cd tools
else
    echo "Download failed. Please check the URL and your internet connection."
    # Move back to the tools directory in case of failure
    cd tools
    exit 1
fi

echo "Operation completed. The mavsdk_server binary is ready for use."
# Note: Ensure you have the necessary permissions to execute this script and modify the target directory.
