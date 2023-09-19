#!/bin/bash

# Author: Alireza Ghaderi
# GitHub: alireza787b/mavsdk_drone_show
# Email: p30planets@gmail.com
# Introduction: This script installs mavlink-router as part of the MAVSDK-Drone-Show project.


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
    echo "use this command:"
    echo "mavlink-routerd -e 100.100.184.90:14550 0.0.0.0:14550"   
    exit 0
fi

# If the mavlink-router directory exists, remove it
if [ -d "mavlink-router" ]; then
    echo "Removing existing mavlink-router directory..."
    rm -rf mavlink-router
fi

# Update and install packages
sudo apt update && sudo apt install -y git autoconf libtool python3 python3-future python3-lxml g++ || { echo "Installation of packages failed"; exit 1; }

# Clone and navigate into the repository
git clone https://github.com/mavlink-router/mavlink-router.git || { echo "Cloning of repository failed"; exit 1; }
cd mavlink-router

# Build and install
git submodule update --init --recursive && \
./autogen.sh && \
./configure CFLAGS='-g -O2' \
            --sysconfdir=/etc --localstatedir=/var --libdir=/usr/lib64 \
            --prefix=/usr && \
make && \
sudo make install || { echo "Build or installation failed"; exit 1; }

# Navigate back to home directory
cd ~

# Print success message
echo "mavlink-router installed successfully. You're good to go!"
echo "use this command:"
echo "mavlink-routerd -e 100.100.184.90:14550 0.0.0.0:14550"

# Exit the script
exit 0
