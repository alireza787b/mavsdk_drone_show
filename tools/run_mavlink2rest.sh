#!/bin/bash

# =============================================================================
# MAVLink2REST Setup and Run Script (Using Precompiled Binary)
# =============================================================================
#
# This script checks for the installation of mavlink2rest (precompiled binary),
# installs it if needed, and runs it with specified or default settings.
#
# Usage:
#   ./run_mavlink2rest.sh [MAVLINK_SRC] [SERVER_IP_PORT]
#
# Example:
#   ./run_mavlink2rest.sh "udpin:0.0.0.0:14550" "0.0.0.0:8088"
#
# If parameters are not provided, default values will be used.
#
# Author: Alireza Ghaderi
# Date: February 2025
# =============================================================================

# Default Configuration
DEFAULT_MAVLINK_SRC="udpin:127.0.0.1:14569"  # Default MAVLink source
DEFAULT_SERVER_IP_PORT="0.0.0.0:8088"        # Default server IP:port

# Precompiled Binary URL
BINARY_URL="https://github.com/mavlink/mavlink2rest/releases/download/t0.11.23/mavlink2rest-armv7-unknown-linux-musleabihf"
BINARY_NAME="mavlink2rest"
INSTALL_DIR="/usr/local/bin"

# =============================================================================
# Function Definitions
# =============================================================================

# Function to display usage instructions
display_usage() {
    echo "Usage: $0 [MAVLINK_SRC] [SERVER_IP_PORT]"
    echo "Example: $0 \"udpin:0.0.0.0:14550\" \"0.0.0.0:8088\""
    echo "If no arguments are provided, default values will be used."
}

# Function to check if mavlink2rest is already installed
check_mavlink2rest_installed() {
    if command -v $BINARY_NAME >/dev/null 2>&1; then
        echo "mavlink2rest is already installed."
        return 0
    else
        echo "mavlink2rest is not installed."
        return 1
    fi
}

# Function to download and install the precompiled binary
install_mavlink2rest_binary() {
    echo "Downloading mavlink2rest binary from $BINARY_URL..."
    wget -q "$BINARY_URL" -O "$BINARY_NAME"
    
    if [ $? -ne 0 ]; then
        echo "Error downloading mavlink2rest binary. Please check the URL."
        exit 1
    fi

    echo "Making the binary executable..."
    chmod +x "$BINARY_NAME"

    echo "Moving the binary to $INSTALL_DIR..."
    sudo mv "$BINARY_NAME" "$INSTALL_DIR/"

    echo "mavlink2rest installation complete."
}

# Function to run mavlink2rest with specified settings
run_mavlink2rest() {
    echo "Running mavlink2rest with MAVLink source: $MAVLINK_SRC and Server IP:Port: $SERVER_IP_PORT..."
    $BINARY_NAME -c "$MAVLINK_SRC" -s "$SERVER_IP_PORT"
}

# =============================================================================
# Main Script Logic
# =============================================================================

# Welcome message
echo "Welcome to the MAVLink2REST Setup and Run Script"
echo "This script will help you install and run mavlink2rest on your system."
echo "------------------------------------------------------------------------------"

# Check if help is requested
if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    display_usage
    exit 0
fi

# Parse command-line arguments or use default values
MAVLINK_SRC="${1:-$DEFAULT_MAVLINK_SRC}"
SERVER_IP_PORT="${2:-$DEFAULT_SERVER_IP_PORT}"

# Inform user of the configuration being used
echo "MAVLink source: $MAVLINK_SRC"
echo "Server IP:Port: $SERVER_IP_PORT"
echo "------------------------------------------------------------------------------"

# Check if mavlink2rest is installed; install it if not
if ! check_mavlink2rest_installed; then
    install_mavlink2rest_binary
fi

# Run mavlink2rest with the specified settings
run_mavlink2rest

echo "------------------------------------------------------------------------------"
echo "mavlink2rest is now running. Press Ctrl+C to stop."
echo "------------------------------------------------------------------------------"

# =============================================================================
# End of Script
# =============================================================================
