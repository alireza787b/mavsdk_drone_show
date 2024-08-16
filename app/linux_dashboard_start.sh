#!/bin/bash

#########################################
# Drone Services Launcher with Tmux, Enhanced Port Handling, and Session Management
#
# This script manages the execution of the GUI React App and GCS Server
# within tmux (by default) or in separate terminal windows if the flag 
# --no-tmux is passed. It handles port conflicts, manages existing sessions, 
# and provides individual windows for each service or separate terminal windows.
#
# Usage:
#   ./linux_dashboard_start.sh [--no-tmux]
#
# Author: [Your Name]
# Project: MAVSDK Drone Show
#########################################

# Configurable Variables
USE_TMUX=true  # Default behavior is to use tmux. Set to false to run in separate terminals by default.
SESSION_NAME="DroneServices"
GCS_PORT=5000
GUI_PORT=3000
WAIT_TIME=5   # Wait time between retries (in seconds)
GRACE_PERIOD=10 # Extra wait time before starting services to ensure ports are released
RETRY_LIMIT=10  # Maximum number of retries to free ports

# Check if the --no-tmux flag is passed
for arg in "$@"; do
    case $arg in
        -n|--no-tmux)
        USE_TMUX=false
        shift
        ;;
    esac
done

# Function to check if a port is in use
port_in_use() {
    local port=$1
    if lsof -i :$port > /dev/null; then
        return 0  # Port is in use
    else
        return 1  # Port is free
    fi
}

# Function to force kill a process using a specific port and retry until the port is free
force_kill_port() {
    local port=$1
    local retries=0

    while port_in_use $port; do
        local pids=$(lsof -t -i:$port)  # Get the PIDs of processes using the port
        if [ -n "$pids" ]; then
            echo "Attempting to kill processes using port $port: $pids"
            for pid in $pids; do
                kill -9 $pid
                if [ $? -eq 0 ]; then
                    echo "Successfully killed process $pid on port $port."
                else
                    echo "Failed to kill process $pid on port $port."
                fi
            done
        else
            echo "Warning: No process found for port $port, but it is still in use."
        fi

        # Wait and check if the port is free
        sleep $WAIT_TIME
        ((retries++))

        if port_in_use $port; then
            if [ $retries -ge $RETRY_LIMIT ]; then
                echo "Error: Unable to free port $port after $RETRY_LIMIT attempts."
                exit 1
            fi
            echo "Port $port is still in use. Retrying... ($retries/$RETRY_LIMIT)"
        else
            echo "Port $port is now free."
            break
        fi
    done
}

# Function to check if tmux is installed
check_tmux_installed() {
    if ! command -v tmux &> /dev/null && [ "$USE_TMUX" = true ]; then
        echo "Error: tmux is not installed."
        echo "Please install tmux with the following command:"
        echo "  sudo apt-get install -y tmux"
        exit 1
    fi
}

# Function to check if a tmux session exists and handle it
check_existing_tmux_session() {
    if tmux has-session -t $SESSION_NAME 2>/dev/null; then
        echo "Warning: A tmux session named '$SESSION_NAME' is already running."
        read -p "Do you want to kill the existing session? (y/n): " response
        if [[ "$response" == "y" || "$response" == "Y" ]]; then
            tmux kill-session -t $SESSION_NAME
            echo "Existing tmux session '$SESSION_NAME' has been killed."
        else
            echo "Please manually kill the session or attach to it using 'tmux attach -t $SESSION_NAME'."
            exit 1
        fi
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

# Function to start services in separate terminal windows (non-tmux mode)
start_services_no_tmux() {
    if [[ -z "$DISPLAY" ]]; then
        echo "No graphical environment detected. Running services in this terminal."
        echo "Starting GCS Server..."
        bash -c "cd $SCRIPT_DIR/../gcs-server && $VENV_PATH/bin/python app.py &"
        
        echo "Starting GUI React app..."
        bash -c "cd $SCRIPT_DIR/dashboard/drone-dashboard && npm start &"
    else
        echo "Starting GCS Server in a new terminal..."
        gnome-terminal -- bash -c "cd $SCRIPT_DIR/../gcs-server && $VENV_PATH/bin/python app.py; bash"

        echo "Starting GUI React app in a new terminal..."
        gnome-terminal -- bash -c "cd $SCRIPT_DIR/dashboard/drone-dashboard && npm start; bash"
    fi
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

# Ensure tmux is installed (if using tmux)
check_tmux_installed

# Check if the session is already running (if using tmux)
if [ "$USE_TMUX" = true ]; then
    check_existing_tmux_session
fi

# Get the directory of the current script
SCRIPT_DIR="$(dirname "$0")"

# Dynamically determine the user's home directory
USER_HOME=$(eval echo ~$USER)

# Path to the virtual environment
VENV_PATH="$USER_HOME/mavsdk_drone_show/venv"

# Load the virtual environment
load_virtualenv "$VENV_PATH"

# Check if ports are in use and handle conflicts
echo "Checking if ports are in use..."
force_kill_port $GCS_PORT
force_kill_port $GUI_PORT

# Add a grace period to ensure ports are fully released
echo "Waiting for $GRACE_PERIOD seconds to ensure ports are fully released..."
sleep $GRACE_PERIOD

# Final check for ports after grace period
echo "Performing final check for ports..."
force_kill_port $GCS_PORT
force_kill_port $GUI_PORT

# Commands for the GCS Server and the GUI React app
GCS_COMMAND="cd $SCRIPT_DIR/../gcs-server && $VENV_PATH/bin/python app.py"
GUI_COMMAND="cd $SCRIPT_DIR/dashboard/drone-dashboard && npm start"

# Start the services either in tmux or separate terminal windows based on user preference
if [ "$USE_TMUX" = true ]; then
    start_services_in_tmux
else
    start_services_no_tmux
fi

echo ""
echo "==============================================="
echo "  All DroneServices components have been started successfully!"
echo "==============================================="
echo ""
