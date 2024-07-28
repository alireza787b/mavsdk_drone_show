#!/bin/bash

# Get user inputs
read -p "Enter Drone ID: " drone_id
read -s -p "Enter Netbird Setup Key: " netbird_key  # -s to hide input for security
echo
read -p "Enter Netbird Management URL (Press enter for default): " management_url

# Default management URL if not provided
if [ -z "$management_url" ]; then
    management_url="https://nb1.joomtalk.ir"  # Change this to your actual default URL
fi

# Configure HWID files
touch ~/mavsdk_drone_show/"$drone_id".hwID

# Configure system name
echo "drone$drone_id" | sudo tee /etc/hostname
sudo sed -i "s/.*127.0.1.1.*/127.0.1.1\tdrone$drone_id/" /etc/hosts

# Netbird setup
netbird up --management-url "$management_url" --setup-key "$netbird_key"

# Securely remove sensitive information
unset netbird_key

# Additional configurations can be added here
