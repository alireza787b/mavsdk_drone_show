#!/bin/bash

# Define the script path
script_path="$HOME/mavsdk_drone_show/tools/raspberry_setup.sh"

# Get absolute path to avoid issues with 'cd' commands later
script_path=$(realpath $script_path)

# Calculate initial hash of the script
initial_hash=$(md5sum $script_path | cut -d ' ' -f 1)

# Define the branch name for the repository operations
branch_name="real-test-1"  # Default branch
read -p "Enter the Git branch name you want to use ($branch_name by default): " user_branch
if [ ! -z "$user_branch" ]; then
    branch_name="$user_branch"
fi

# Navigate to the repository directory
cd $(dirname $script_path)

# Stashing any local changes and pulling the latest updates from Git
echo "Stashing any local changes and updating from Git repository..."
git stash push --include-untracked
git checkout $branch_name
git pull origin $branch_name

# Calculate new hash and check if script has changed
new_hash=$(md5sum $script_path | cut -d ' ' -f 1)
if [ "$initial_hash" != "$new_hash" ]; then
    echo "Script has been updated. Restarting with the latest version..."
    exec bash $script_path
fi

echo "Starting setup for the Drone Swarm System..."
echo "NOTE: If this Drone ID has been used before, running this setup might create a duplicate entry in Netbird."

# Get user inputs
read -p "Enter Drone ID (e.g., 1, 2): " drone_id
echo "You entered Drone ID: $drone_id"
read -s -p "Enter Netbird Setup Key: " netbird_key
echo

# Optional: Enter Netbird Management URL
read -p "Enter Netbird Management URL (Press enter for default): " management_url
management_url="${management_url:-https://nb1.joomtalk.ir}"
echo "Using Netbird Management URL: $management_url"

echo "Disconnecting from Netbird..."
netbird down

echo "Clearing Netbird configurations..."
sudo rm -rf /etc/netbird/

hwid_file="$HOME/mavsdk_drone_show/${drone_id}.hwID"
if [ -f "$hwid_file" ]; then
    echo "HWID file exists - updating..."
    rm "$hwid_file"
fi
touch "$hwid_file"
echo "Hardware ID file created/updated at: $hwid_file"

echo "Configuring hostname to 'drone$drone_id'..."
echo "drone$drone_id" | sudo tee /etc/hostname
sudo sed -i "s/.*127.0.1.1.*/127.0.1.1\tdrone$drone_id/" /etc/hosts

echo "Reloading hostname service to apply changes immediately..."
sudo hostnamectl set-hostname "drone$drone_id"
sudo systemctl restart systemd-logind

echo "Restarting avahi-daemon to apply hostname changes..."
sudo systemctl restart avahi-daemon

echo "Reconnecting to Netbird with new settings..."
netbird up --management-url "$management_url" --setup-key "$netbird_key"
echo "Netbird reconnected with new hostname 'drone$drone_id'."

unset netbird_key

echo "Setting up the Drone Swarm System Coordinator service..."
sudo bash $HOME/mavsdk_drone_show/tools/update_service.sh

echo "Downloading and configuring MAVSDK server..."
if [ -f "$HOME/mavsdk_drone_show/tools/download_mavsdk_server.sh" ]; then
    sudo bash $HOME/mavsdk_drone_show/tools/download_mavsdk_server.sh
    echo "Note: You might need to manually update the download URL in the 'download_mavsdk_server.sh' script to match the latest MAVSDK server version."
else
    echo "Error: MAVSDK server download script not found."
fi

echo "Setup complete! The system is now configured for Drone ID $drone_id."
