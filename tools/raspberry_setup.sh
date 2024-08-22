#!/bin/bash

# Setup script for configuring a Raspberry Pi for Drone Swarm System
echo "Starting setup for the Drone Swarm System..."

# Check current working directory
if [[ "$(pwd)" != "$HOME/mavsdk_drone_show/tools" ]]; then
    echo "Script not running from expected directory."
    echo "Please run this script from: ~/mavsdk_drone_show/tools"
    exit 1
fi

# Inform user about potential duplication
echo "NOTE: If this Drone ID has been used before, running this setup might create a duplicate entry in Netbird."

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

# Reload hostname service and confirm the change
echo "Reloading hostname service to apply changes immediately..."
sudo hostnamectl set-hostname "drone$drone_id"
sudo systemctl restart systemd-logind
hostname | grep "drone$drone_id" &> /dev/null && echo "Hostname successfully changed to drone$drone_id." || echo "Failed to update hostname."

# Ensure hostname change takes effect
echo "Restarting avahi-daemon to apply hostname changes..."
sudo systemctl restart avahi-daemon

# Wait for system to stabilize after hostname change
sleep 5

# Reconnect to Netbird with new hostname
echo "Reconnecting to Netbird with new settings..."
netbird up --management-url "$management_url" --setup-key "$netbird_key"
echo "Netbird reconnected with new hostname 'drone$drone_id'."

# Securely remove sensitive information
unset netbird_key

# Setup and start the coordinator service
echo "Setting up the Drone Swarm System Coordinator service..."
sudo bash $HOME/mavsdk_drone_show/tools/update_service.sh

# Download and configure the MAVSDK server
echo "Downloading and configuring MAVSDK server..."
if [ -f "$HOME/mavsdk_drone_show/tools/download_mavsdk_server.sh" ]; then
    sudo bash $HOME/mavsdk_drone_show/tools/download_mavsdk_server.sh
    echo "Note: You might need to manually update the download URL in the 'download_mavsdk_server.sh' script to match the latest MAVSDK server version."
else
    echo "Error: MAVSDK server download script not found."
fi

echo "Setup complete! The system is now configured for Drone ID $drone_id."
