#!/bin/bash
clear

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

# Check if the server is running
if curl --output /dev/null --silent --head --fail "http://localhost:3000"; then
    echo "Drone Dashboard server is already running!"
else
    echo "Starting the Drone Dashboard server..."
    cd dashboard/drone-dashboard
    npm start & # The ampersand will run the command in the background
    sleep 5 # Giving it some time to start
    echo "Drone Dashboard server started successfully!"
    cd ../.. # Navigate back to root directory
fi

echo "Now starting the GCS Terminal App with Flask..."
python3 ./gcs_with_flask.py & # Running the Python app in the background
echo "GCS Terminal App started successfully!"

echo ""
echo "For more details, please check the documentation in the 'docs' folder."
echo "You can also refer to Alireza Ghaderi's GitHub repo: https://github.com/alireza787b/mavsdk_drone_show"
echo "For tutorials and additional content, visit Alireza Ghaderi's YouTube channel: https://www.youtube.com/@alirezaghaderi"
echo ""
read -p "Press any key to close this script..."
