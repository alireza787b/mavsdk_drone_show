#!/bin/bash

# Clear the screen
clear

# Welcome message
echo "Welcome to the Drone Dashboard and GCS Terminal App Startup Script!"
echo "MAVSDK_Drone_Show Version 0.7"
echo ""
echo "This script will do the following:"
echo "1. Check if the Drone Dashboard (a Node.js React app) is running."
echo "2. If not, it will start the Drone Dashboard. Once started, you can access the dashboard at http://localhost:3000 (can also be done manually with npm start command)"
echo "3. The script will also open the terminal-based GCS (Ground Control Station) app. This GCS app serves data to the Drone Dashboard using Flask endpoints + ability to send command and receive telemetry from drones using terminal."
echo ""
echo "Please wait as the script checks and initializes the necessary components..."
echo ""

# Get the directory of the current script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Check if the server is running
curl -s -o /dev/null http://localhost:3000

if [ $? -ne 0 ]; then
    echo "Starting the Drone Dashboard server..."
    cd "$SCRIPT_DIR/dashboard/drone-dashboard"
    gnome-terminal -- npm start &
    echo "Drone Dashboard server started successfully!"
else
    echo "Drone Dashboard server is already running!"
fi

echo "Now starting the GCS Terminal App with Flask..."
cd "$SCRIPT_DIR/.."
gnome-terminal -- python3 gcs_with_flask.py &
echo "GCS Terminal App started successfully!"

echo ""
echo "For more details, please check the documentation in the 'docs' folder."
echo "You can also refer to Alireza Ghaderi's GitHub repo: https://github.com/alireza787b/mavsdk_drone_show"
echo "For tutorials and additional content, visit Alireza Ghaderi's YouTube channel: https://www.youtube.com/@alirezaghaderi"
echo ""
read -n 1 -s -r -p "Press any key to close this script..."
