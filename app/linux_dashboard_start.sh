#!/bin/bash

#########################################
# Drone Services Launcher with Tmux
#
# This script manages the execution of the GUI React App and GCS Server
# within tmux. It sets up individual windows for each service and a
# combined view window with split panes. It checks for port conflicts
# and ensures ports are free before proceeding.
#
# Usage:
#   ./run_droneservices.sh
#########################################

# Tmux session name
SESSION_NAME="DroneServices"
GCS_PORT=5000
GUI_PORT=3000

# Function to check if tmux is installed
check_tmux_installed() {
    if ! command -v tmux &> /dev/null; then
        echo "Error: tmux is not installed."
        echo "Please install tmux with the following command:"
        echo "  sudo apt-get install -y tmux"
        exit 1
    fi
}

# Function to load the virtual environment
load_virtualenv() {
    local venv_path="$1"
    
    if [ -d "$venv_path" ]; then
        source "$venv_path/bin/activate"
        echo "Virtual environment activated."
    else
        echo "Error: Virtual environment not found at $venv_path."
        echo "Please follow the setup instructions at:"
        echo "  https://github.com/alireza787b/mavsdk_drone_show"
        exit 1
    fi
}

# Function to check if a port is in use and force kill the process
force_kill_port() {
    local port=$1
    local service_name=$2
    local pid=$(lsof -ti :$port)

    if [ -n "$pid" ]; then
        echo "Warning: Port $port is in use by process ID $pid."
        echo "This port is required by the $service_name."
        echo "Attempting to terminate the process using port $port..."
        
        kill -9 "$pid"
        
        if [ $? -eq 0 ]; then
            echo "Process on port $port has been successfully terminated."
        else
            echo "Error: Failed to terminate process on port $port."
            exit 1
        fi
    else
        echo "Port $port is free and available for $service_name."
    fi
}

# Function to display tmux instructions to the user
show_tmux_instructions() {
    echo "==============================================="
    echo "  Tmux Session Started"
    echo "==============================================="
    echo "Prefix key (Ctrl+B), then:"
    echo "  - Switch between windows: Number keys (e.g., Ctrl+B, then 1, 2, 3)"
    echo "  - Detach from session: Ctrl+B, then D"
    echo "  - Reattach to session: tmux attach -t $SESSION_NAME"
    echo "  - Close the session and all services: Exit all windows or type 'exit'"
    echo "  - To kill the session entirely: tmux kill-session -t $SESSION_NAME"
    echo "==============================================="
    echo ""
}

# Function to create a tmux session with individual windows and a combined view
start_services_in_tmux() {
    local session="$SESSION_NAME"

    echo "Creating tmux session '$session'..."

    # Create a new tmux session and start the GCS Server in the first window
    tmux new-session -d -s "$session" -n "GCS-Server" "clear; $GCS_COMMAND; bash"

    # Start the GUI React app in a new window
    tmux new-window -t "$session" -n "GUI-React" "clear; $GUI_COMMAND; bash"

    # Create a combined view window with both services in split panes
    tmux new-window -t "$session" -n "Combined-View"
    tmux split-window -h -t "$session:2" "clear; $GCS_COMMAND; bash"
    tmux split-window -v -t "$session:2.0" "clear; $GUI_COMMAND; bash"
    tmux select-layout -t "$session:2" tiled  # Organize panes in a tiled layout

    # Attach to the tmux session in the combined view window by default
    tmux select-window -t "$session:2"
    tmux attach-session -t "$session"
}

# Main execution sequence

# Ensure tmux is installed
check_tmux_installed

# Get the directory of the current script
SCRIPT_DIR="$(dirname "$0")"

# Dynamically determine the user's home directory
USER_HOME=$(eval echo ~$USER)

# Path to the virtual environment
VENV_PATH="$USER_HOME/mavsdk_drone_show/venv"

# Load the virtual environment
load_virtualenv "$VENV_PATH"

# Check if ports are in use and force kill any processes using them
force_kill_port $GCS_PORT "GCS Server"
force_kill_port $GUI_PORT "GUI React App"

# Commands for the GCS Server and the GUI React app
GCS_COMMAND="cd $SCRIPT_DIR/../gcs-server && $VENV_PATH/bin/python app.py"
GUI_COMMAND="cd $SCRIPT_DIR/dashboard/drone-dashboard && npm start"

# Start the services in tmux
start_services_in_tmux

# Show user instructions after tmux session is attached
show_tmux_instructions

echo ""
echo "==============================================="
echo "  All DroneServices components have been started successfully!"
echo "==============================================="
echo ""
