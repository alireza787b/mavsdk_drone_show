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

# Disconnect from Netbird if connected
echo "Disconnecting from Netbird..."
netbird down

# Clear Netbird configurations
echo "Clearing Netbird configurations..."
sudo rm -rf /etc/netbird/ # Assuming config is stored here; adjust path as necessary

# Configure HWID files
hwid_file="$HOME/mavsdk_drone_show/${drone_id}.hwID"
if [ -f "$hwid_file" ]; then
    echo "HWID file exists - updating..."
    rm "$hwid_file"
fi
touch "$hwid_file"
echo "Hardware ID file created/updated at: $hwid_file"

# Configure system name
echo "Configuring hostname to 'drone$drone_id'..."
echo "drone$drone_id" | sudo tee /etc/hostname
sudo sed -i "s/.*127.0.1.1.*/127.0.1.1\tdrone$drone_id/" /etc/hosts

# Ensure hostname change takes effect
echo "Restarting avahi-daemon to apply hostname changes..."
sudo systemctl restart avahi-daemon

# Reconnect to Netbird with new hostname
echo "Reconnecting to Netbird with new settings..."
netbird up --management-url "$management_url" --setup-key "$netbird_key"
echo "Netbird reconnected with new hostname 'drone$drone_id'."

# Securely remove sensitive information
unset netbird_key

# Setup and start the coordinator service
echo "Setting up the Drone Swarm System Coordinator service..."
sudo bash $HOME/mavsdk_drone_show/tools/update_service.sh

echo "Setup complete! The system is now configured for Drone ID $drone_id."
