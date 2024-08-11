#!/bin/bash

# Function to check if a port is in use
port_in_use() {
    netstat -tln | grep ":$1 " > /dev/null
}

# Function to start a process in either a new terminal or in the background
start_process() {
    local description="$1"
    local command="$2"
    
    echo "Starting $description..."
    if [ "$3" == "g" ]; then
        gnome-terminal -- bash -c "$command; exec bash" &
    else
        eval "$command &"
    fi
    
    sleep 5
}

echo "==============================================="
echo "  Welcome to the Drone Dashboard and GCS Terminal App Startup Script!"
echo "==============================================="
echo ""
echo "MAVSDK_Drone_Show Version 0.9"
echo ""
echo "This script will:"
echo "1. Check if the Drone Dashboard (Node.js React app) is running."
echo "2. Start the Drone Dashboard if it's not running."
echo "   - Once started, access the dashboard at http://localhost:3000"
echo "3. Open the terminal-based GCS (Ground Control Station) app."
echo "4. Start the getElevation server for elevation data fetching."
echo ""
echo "Please wait as the script checks and initializes the necessary components..."
echo ""

# Get the directory of the current script
SCRIPT_DIR="$(dirname "$0")"

# Path to the virtual environment
VENV_PATH="/home/droneshow/mavsdk_drone_show/venv"
PYTHON_CMD="$VENV_PATH/bin/python"

# Activate virtual environment
if [ -d "$VENV_PATH" ]; then
    source "$VENV_PATH/bin/activate"
    echo "Virtual environment activated."
else
    echo "Error: Virtual environment not found at $VENV_PATH. Please check the path and try again."
    exit 1
fi

# Check for first-time setup for React app
REACT_APP_DIR="$SCRIPT_DIR/dashboard/drone-dashboard"
if [ ! -d "$REACT_APP_DIR/node_modules" ]; then
    echo "WARNING: The 'node_modules' directory is missing. It seems like 'npm install' hasn't been run yet."
    read -p "Would you like to automatically run 'npm install' now? [y/n]: " install_choice

    if [[ "$install_choice" =~ ^[Yy]$ ]]; then
        echo "Running 'npm install' in $REACT_APP_DIR..."
        cd "$REACT_APP_DIR"
        npm install
        if [ $? -eq 0 ]; then
            echo "'npm install' completed successfully."
        else
            echo "Error: 'npm install' failed. Please resolve the issue manually."
            exit 1
        fi
    else
        echo "Please navigate to $REACT_APP_DIR and run 'npm install' manually before proceeding."
        exit 1
    fi
fi

# Check and start the Drone Dashboard server
if ! port_in_use 3000; then
    start_process "Drone Dashboard server" "cd $REACT_APP_DIR && npm start" "$1"
else
    echo "Drone Dashboard server is already running on port 3000!"
fi

# Check and start the getElevation server
if ! port_in_use 5001; then
    start_process "getElevation server" "cd $SCRIPT_DIR/dashboard/getElevation && node server.js" "$1"
else
    echo "getElevation server is already running on port 5001!"
fi

# Start the GCS Terminal App with Flask
echo "Now starting the GCS Terminal App with Flask..."
start_process "GCS Terminal App" "cd $SCRIPT_DIR/../gcs-server && $PYTHON_CMD app.py" "$1"

echo ""
echo "==============================================="
echo "  All services have been started successfully!"
echo "==============================================="
echo ""
echo "For more details, please check the documentation in the 'docs' folder."
echo "GitHub repo: https://github.com/alireza787b/mavsdk_drone_show"
echo "For tutorials and content, visit Alireza Ghaderi's YouTube channel:"
echo "https://www.youtube.com/@alirezaghaderi"
echo ""

# End of the script
read -p "Press any key to exit the script..."
