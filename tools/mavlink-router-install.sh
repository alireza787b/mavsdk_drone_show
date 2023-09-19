#!/bin/bash

# Author: Alireza Ghaderi
# GitHub: alireza787b/mavsdk_drone_show
# Email: p30planets@gmail.com
# Introduction: This script installs mavlink-router as part of the MAVSDK-Drone-Show project.

echo "================================================================="
echo "MAVSDK-Drone-Show Installation Script"
echo "Author: Alireza Ghaderi"
echo "GitHub: alireza787b/mavsdk_drone_show"
echo "Contact: p30planets@gmail.com"
echo "For more information, visit the GitHub profile: alireza787b/mavsdk_drone_show"
echo "================================================================="

# Navigate to home directory
cd ~

# Check if mavlink-router is already installed
if command -v mavlink-routerd &> /dev/null; then
    echo "mavlink-router is already installed. You're good to go!"
    exit 0
fi

# Step 1: Update package lists
echo "Updating package lists..."
sudo apt update

# Step 2: Install required packages
echo "Installing required packages..."
sudo apt install -y git autoconf libtool python3 python3-future python3-lxml g++

# Step 3: Clone mavlink-router repository
echo "Cloning mavlink-router repository..."
git clone https://github.com/mavlink-router/mavlink-router.git

# Step 4: Change directory to mavlink-router
echo "Changing directory to mavlink-router..."
cd mavlink-router

# Step 5: Initialize git submodules
echo "Initializing git submodules..."
git submodule update --init --recursive

# Step 6: Run autogen.sh
echo "Running autogen.sh..."
./autogen.sh

# Step 7: Configure the build system
echo "Configuring the build system..."
./configure CFLAGS='-g -O2' \
            --sysconfdir=/etc --localstatedir=/var --libdir=/usr/lib64 \
            --prefix=/usr

# Step 8: Compile mavlink-router
echo "Compiling mavlink-router..."
make

# Step 9: Install mavlink-router
echo "Installing mavlink-router..."
sudo make install

# Step 10: Navigate back to the home directory
cd ~

# Step 11: Print completion message
echo "mavlink-router installed successfully. You're good to go!"

echo "use this command:"
echo "mavlink-routerd -e 100.100.184.90:14550 0.0.0.0:14550"

# Exit the script
exit 0
