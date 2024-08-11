#!/bin/bash

# Function to check if a port is in use
port_in_use() {
    netstat -tln | grep ":$1 " > /dev/null
}

# Function to check if tmux is installed
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
    echo "  - Switch between windows: Number keys (e.g., Ctrl+B, then 1)"
    echo "  - Switch between panes: Arrow keys (e.g., Ctrl+B, then →)"
    echo "  - Detach from session: Ctrl+B, then D"
    echo "  - Reattach to session: tmux attach -t DroneServices"
    echo "  - Close pane/window: Type 'exit' or press Ctrl+D"
    echo "==============================================="
    echo ""
}

# Function to start a process in a new tmux window
start_process_tmux() {
    local session="$1"
    local window_name="$2"
    local command="$3"
    
    tmux new-window -t "$session" -n "$window_name" "clear; show_tmux_instructions; $command"
    sleep 2
}

# Function to create a tmux session and start all services
start_services_in_tmux() {
    local session="DroneServices"

    echo "Creating tmux session '$session'..."
    tmux new-session -d -s "$session" -n "GCS" "clear; show_tmux_instructions; cd $SCRIPT_DIR/../gcs-server && $PYTHON_CMD app.py"

    # Start the Drone Dashboard server
    echo "Starting Drone Dashboard server in tmux..."
    start_process_tmux "$session" "Dashboard" "cd $REACT_APP_DIR && npm start"

    # Start the getElevation server
    echo "Starting getElevation server in tmux..."
    start_process_tmux "$session" "Elevation" "cd $SCRIPT_DIR/dashboard/getElevation && node server.js"

    # Attach to the tmux session
    tmux attach-session -t "$session"
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

# Check if services are already running and start them in tmux
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
