#!/bin/bash

# =============================================================================
# MAVLink2REST Setup and Run Script for PixEagle
# =============================================================================
#
# This script checks for the installation of mavlink2rest, installs it if needed,
# clones the repository into the ~/mavlink2rest/ directory, and runs mavlink2rest
# with specified or default server settings. It also handles swap space increase
# for low-memory devices like Raspberry Pi Zero.
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
# Date: August 2024
# =============================================================================

# Default Configuration: Define your MAVLink source and server settings here.
DEFAULT_MAVLINK_SRC="udpin:127.0.0.1:14569"  # Default: UDP input from localhost on port 14569
DEFAULT_SERVER_IP_PORT="0.0.0.0:8088"        # Default: Server listens on all IPs at port 8088

# Directory where mavlink2rest will be installed.
INSTALL_DIR="$HOME/mavlink2rest"

# =============================================================================
# Function Definitions
# =============================================================================

# Function to display usage instructions
display_usage() {
    echo "Usage: $0 [MAVLINK_SRC] [SERVER_IP_PORT]"
    echo "Example: $0 \"udpin:0.0.0.0:14550\" \"0.0.0.0:8088\""
    echo "If no arguments are provided, default values will be used."
}

# Function to install Rust and Cargo
install_rust() {
    echo "Installing Rust and Cargo..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    source $HOME/.cargo/env
    echo "Rust and Cargo installation complete."
}

# Function to clone mavlink2rest repository
clone_mavlink2rest_repo() {
    echo "Cloning mavlink2rest repository into $INSTALL_DIR..."
    git clone https://github.com/mavlink/mavlink2rest.git "$INSTALL_DIR"
    echo "Repository cloned."
}

# Function to install mavlink2rest using Cargo
install_mavlink2rest() {
    echo "Installing mavlink2rest using Cargo..."
    increase_swap
    trap reset_swap EXIT

    if cargo install --path "$INSTALL_DIR"; then
        echo "mavlink2rest installation complete."
    else
        echo "mavlink2rest installation failed."
        exit 1
    fi

    reset_swap
    trap - EXIT
}

# Function to check if mavlink2rest is already installed
check_mavlink2rest_installed() {
    if command -v mavlink2rest >/dev/null 2>&1; then
        echo "mavlink2rest is already installed."
        return 0
    else
        echo "mavlink2rest is not installed."
        return 1
    fi
}

# Function to check and update PATH if necessary
check_and_update_path() {
    if [[ ":$PATH:" != *":$HOME/.cargo/bin:"* ]]; then
        echo "Adding ~/.cargo/bin to PATH..."
        export PATH="$HOME/.cargo/bin:$PATH"
        if ! grep -q 'export PATH="$HOME/.cargo/bin:$PATH"' ~/.bashrc; then
            echo 'export PATH="$HOME/.cargo/bin:$PATH"' >> ~/.bashrc
            echo "Added ~/.cargo/bin to PATH in ~/.bashrc."
        fi
    else
        echo "~/.cargo/bin is already in PATH."
    fi
}

# Function to run mavlink2rest with specified settings
run_mavlink2rest() {
    echo "Running mavlink2rest with MAVLink source: $MAVLINK_SRC and Server IP:Port: $SERVER_IP_PORT..."
    mavlink2rest -c "$MAVLINK_SRC" -s "$SERVER_IP_PORT"
    echo "mavlink2rest is now running. Press Ctrl+C to stop."
}

# Function to increase swap size
increase_swap() {
    echo "Increasing swap space..."
    # Check if dphys-swapfile is installed
    if ! command -v dphys-swapfile >/dev/null 2>&1; then
        echo "dphys-swapfile is not installed. Installing it..."
        sudo apt-get update
        sudo apt-get install -y dphys-swapfile
    fi

    # Get current swap size
    ORIGINAL_SWAPSIZE=$(grep -E '^CONF_SWAPSIZE=' /etc/dphys-swapfile | cut -d'=' -f2)
    if [ -z "$ORIGINAL_SWAPSIZE" ]; then
        echo "Unable to determine original swap size. Defaulting to 100MB."
        ORIGINAL_SWAPSIZE=100
        echo "Setting original swap size to 100MB."
        sudo sed -i '/^CONF_SWAPSIZE=/d' /etc/dphys-swapfile
        echo "CONF_SWAPSIZE=$ORIGINAL_SWAPSIZE" | sudo tee -a /etc/dphys-swapfile >/dev/null
    fi
    # Save original swap size to a temp file
    echo "$ORIGINAL_SWAPSIZE" > /tmp/original_swapsize.txt

    # Set new swap size
    echo "Increasing swap size to 2048MB..."
    sudo dphys-swapfile swapoff
    sudo sed -i "s/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=2048/" /etc/dphys-swapfile
    sudo dphys-swapfile setup
    sudo dphys-swapfile swapon
}

# Function to reset swap size
reset_swap() {
    echo "Resetting swap space to original size..."
    if [ ! -f /tmp/original_swapsize.txt ]; then
        echo "Original swap size not found. Cannot reset swap size."
        return
    fi
    ORIGINAL_SWAPSIZE=$(cat /tmp/original_swapsize.txt)
    sudo dphys-swapfile swapoff
    sudo sed -i "s/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=$ORIGINAL_SWAPSIZE/" /etc/dphys-swapfile
    sudo dphys-swapfile setup
    sudo dphys-swapfile swapon
    # Remove the temp file
    rm /tmp/original_swapsize.txt
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

# Check if Rust and Cargo are installed
if ! command -v cargo >/dev/null 2>&1; then
    echo "Rust and Cargo are not installed on your system."
    install_rust
else
    echo "Rust and Cargo are already installed."
fi

# Ensure ~/.cargo/bin is in the PATH
check_and_update_path

# Check if mavlink2rest is installed
if ! check_mavlink2rest_installed; then
    # If mavlink2rest is not installed, clone the repository and install it
    if [ ! -d "$INSTALL_DIR" ]; then
        clone_mavlink2rest_repo
    else
        echo "Directory $INSTALL_DIR already exists. Skipping clone."
    fi
    install_mavlink2rest
fi

# Run mavlink2rest with the specified settings
run_mavlink2rest

# =============================================================================
# End of Script
# =============================================================================
