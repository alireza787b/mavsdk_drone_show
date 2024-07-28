#!/bin/bash

# Setup script for configuring a Raspberry Pi for Drone Swarm System
echo "Starting setup for the Drone Swarm System..."

# Get user inputs
read -p "Enter Drone ID (e.g., 1, 2): " drone_id
echo "You entered Drone ID: $drone_id"

# Ask for Netbird setup key
read -s -p "Enter Netbird Setup Key: " netbird_key  # -s to hide input for security
echo

# Optional: Enter Netbird Management URL
read -p "Enter Netbird Management URL (Press enter for default): " management_url
management_url="${management_url:-https://nb1.joomtalk.ir}"  # Default URL if not provided
echo "Using Netbird Management URL: $management_url"

# Configure HWID files
hwid_file="~/mavsdk_drone_show/${drone_id}.hwID"
touch $hwid_file
echo "Hardware ID file created at: $hwid_file"

# Configure system name
echo "Configuring hostname to 'drone$drone_id'..."
echo "drone$drone_id" | sudo tee /etc/hostname
sudo sed -i "s/.*127.0.1.1.*/127.0.1.1\tdrone$drone_id/" /etc/hosts

# Netbird setup
echo "Setting up Netbird..."
netbird up --management-url "$management_url" --setup-key "$netbird_key"
echo "Netbird setup complete."

# Securely remove sensitive information
unset netbird_key

# Setup and start the coordinator service
echo "Setting up the Drone Swarm System Coordinator service..."
sudo bash /home/droneshow/mavsdk_drone_show/tools/update_service.sh

echo "Setup complete! The system is now configured for Drone ID $drone_id."
