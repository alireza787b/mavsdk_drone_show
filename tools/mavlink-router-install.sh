#!/bin/bash

echo "================================================================="
echo "MAVSDK-Drone-Show Mavlink-router Installation Script"
echo "Author: Alireza Ghaderi"
echo "GitHub: https://github.com/alireza787b/mavsdk_drone_show"
echo "Contact: p30planets@gmail.com"
echo "For more information, visit the GitHub Repo"
echo "================================================================="

# Navigate to home directory
cd ~

# Check if mavlink-router is already installed
if command -v mavlink-routerd &> /dev/null; then
    echo "mavlink-router is already installed. You're good to go!"
    echo "Use this command:"
    echo "mavlink-routerd -e GCS_IP:24550 0.0.0.0:34550"
    exit 0
fi

# If the mavlink-router directory exists, remove it
if [ -d "mavlink-router" ]; then
    echo "Removing existing mavlink-router directory..."
    rm -rf mavlink-router
fi

# Update and install packages
sudo apt update && sudo apt install -y git meson ninja-build pkg-config gcc g++ systemd || { echo "Installation of packages failed"; exit 1; }

# Clone and navigate into the repository
git clone https://github.com/mavlink-router/mavlink-router.git || { echo "Cloning of repository failed"; exit 1; }
cd mavlink-router || { echo "Changing directory failed"; exit 1; }

# Fetch dependencies (submodules)
git submodule update --init --recursive || { echo "Submodule update failed"; exit 1; }

# Build with Meson and Ninja
meson setup build . || { echo "Meson setup failed"; exit 1; }
ninja -C build || { echo "Ninja build failed"; exit 1; }

# Install
sudo ninja -C build install || { echo "Installation failed"; exit 1; }

# Navigate back to home directory
cd ~

# Print success message
echo "mavlink-router installed successfully. You're good to go!"
echo "Use this command:"
echo "mavlink-routerd -e GCS_IP:24550 0.0.0.0:34550"

# Exit the script
exit 0
