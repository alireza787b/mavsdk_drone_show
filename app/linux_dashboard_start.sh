#!/bin/bash

# Function to check if a port is in use
port_in_use() {
   netstat -tln | grep $1 > /dev/null
}

# Start a process either in a new terminal or in the background
start_process() {
    if [ "$1" == "g" ]; then
        gnome-terminal -- bash -c "$2; exec bash" &
    else
        eval "$2 &"
    fi
}

echo "Welcome to the Drone Dashboard and GCS Terminal App Startup Script!"
echo "MAVSDK_Drone_Show Version 0.8"
echo ""
echo "This script will do the following:"
echo "1. Check if the Drone Dashboard (a Node.js React app) is running."
echo "2. If not, it will start the Drone Dashboard. Once started, you can access the dashboard at http://localhost:3000"
echo "3. The script will also open the terminal-based GCS (Ground Control Station) app."
echo "4. Start the getElevation server that acts as a proxy for fetching elevation data."
echo ""
echo "Please wait as the script checks and initializes the necessary components..."
echo ""

# Get the directory of the current script
SCRIPT_DIR="$(dirname "$0")"

# Check Python version and set appropriate alias
# If Python 3 is your default, you can just use 'python' here
PYTHON_CMD=python3

# Start the Drone Dashboard server if not running
if ! port_in_use 3000; then
    echo "Starting the Drone Dashboard server..."
    start_process "$1" "cd $SCRIPT_DIR/dashboard/drone-dashboard && npm start"
    sleep 5
else
    echo "Drone Dashboard server is already running!"
fi

# Check for first-time setup for React app
if [ ! -d "$SCRIPT_DIR/dashboard/drone-dashboard/node_modules" ]; then
    echo "WARNING: It seems like you haven't done 'npm install' in the React app directory. Please navigate to $SCRIPT_DIR/dashboard/drone-dashboard and run 'npm install' before proceeding."
fi

# Start the getElevation server if not running
if ! port_in_use 5001; then
    echo "Starting the getElevation server..."
    start_process "$1" "cd $SCRIPT_DIR/dashboard/getElevation && node server.js"
    sleep 5
else
    echo "getElevation server is already running!"
fi

# Start the GCS Terminal App with Flask
echo "Now starting the GCS Terminal App with Flask..."
# Navigate to the correct directory and run the Python script
start_process "$1" "cd $SCRIPT_DIR/.. && $PYTHON_CMD gcs_with_flask.py"

echo ""
echo "For more details, please check the documentation in the 'docs' folder."
echo "You can also refer to GitHub repo: https://github.com/alireza787b/mavsdk_drone_show"
echo "For tutorials and additional content, visit Alireza Ghaderi's YouTube channel: https://www.youtube.com/@alirezaghaderi"
echo ""

# End of the script
read -p "Press any key to close this script..."
