#!/bin/bash

#########################################
# gcs server and dashboard Launcher with Tmux Split Panes and Windows
#
# Project: MAVSDK Drone Show
# Author: Alireza Ghaderi
# Date: August 2024
#
# This script manages the execution of the DroneServices system,
# including the GCS (Ground Control Station) and the Drone Dashboard.
# Each component runs in its own tmux window, and a combined split-pane view
# is also provided for easy monitoring of both services side-by-side.
#
# Usage:
#   ./app/linux_dashboard_start.sh.sh
#
#########################################

# Tmux session name
SESSION_NAME="DroneServices"

# Function to check if tmux is installed and install it if not
check_tmux_installed() {
    if ! command -v tmux &> /dev/null; then
        echo "tmux could not be found. Installing tmux..."
        sudo apt-get update
        sudo apt-get install -y tmux
    else
        echo "tmux is already installed."
    fi
}

# Function to display tmux instructions
show_tmux_instructions() {
    echo "==============================================="
    echo "  Quick tmux Guide:"
    echo "==============================================="
    echo "Prefix key (Ctrl+B), then:"
    echo "  - Switch between windows: Number keys (e.g., Ctrl+B, then 1, 2, 3)"
    echo "  - Switch between panes: Arrow keys (e.g., Ctrl+B, then →)"
    echo "  - Stop scrolling in a pane for debugging: Ctrl+B, then ["
    echo "  - Detach from session: Ctrl+B, then D"
    echo "  - Reattach to session: tmux attach -t $SESSION_NAME"
    echo "  - Close pane/window: Type 'exit' or press Ctrl+D"
    echo "==============================================="
    echo ""
}

# Function to start a process in a new tmux window
start_process_tmux() {
    local session="$1"
    local window_name="$2"
    local command="$3"
    
    tmux new-window -t "$session" -n "$window_name" "clear; $command"
    sleep 2
}

# Function to create a tmux session with both windows and split panes
start_services_in_tmux() {
    local session="$SESSION_NAME"

    echo "Creating tmux session '$session'..."
    tmux new-session -d -s "$session" -n "GCS" "clear; show_tmux_instructions; cd $SCRIPT_DIR/../gcs-server && $PYTHON_CMD app.py"

    # Start the Drone Dashboard service in a new window
    echo "Starting Drone Dashboard server in tmux..."
    start_process_tmux "$session" "Dashboard" "cd $REACT_APP_DIR && npm start"

    # Create a combined window with split panes for side-by-side view
    tmux new-window -t "$session" -n "CombinedView"
    tmux split-window -h -t "$session:3" "clear; cd $SCRIPT_DIR/../gcs-server && $PYTHON_CMD app.py"
    tmux split-window -v -t "$session:3.0" "clear; cd $REACT_APP_DIR && npm start"
    tmux select-layout -t "$session:3" tiled

    # Attach to the tmux session and display instructions
    tmux attach-session -t "$session"
    show_tmux_instructions
}

echo "==============================================="
echo "  Welcome to the Drone Dashboard and GCS Terminal App Startup Script!"
echo "==============================================="
echo ""
echo "MAVSDK_Drone_Show Version 1.0"
echo ""
echo "This script will:"
echo "1. Start the Drone Dashboard (Node.js React app) and GCS (Ground Control Station) in tmux."
echo "2. Provide both separate windows for each service and a split-screen combined view."
echo ""
echo "Please wait as the script checks and initializes the necessary components..."
echo ""

# Check if tmux is installed and install if necessary
check_tmux_installed

# Get the directory of the current script
SCRIPT_DIR="$(dirname "$0")"

# Dynamically determine the user's home directory
USER_HOME=$(eval echo ~$USER)

# Path to the virtual environment
VENV_PATH="$USER_HOME/mavsdk_drone_show/venv"
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
    echo "WARNING: The 'node_modules' directory is missing. Running 'npm install' now..."
    cd "$REACT_APP_DIR"
    npm install
    if [ $? -eq 0 ]; then
        echo "'npm install' completed successfully."
    else
        echo "Error: 'npm install' failed. Please resolve the issue manually."
        exit 1
    fi
fi

# Start the services in tmux
start_services_in_tmux

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
