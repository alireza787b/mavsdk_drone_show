#!/bin/bash

#########################################
# Robust Drone Services Launcher
#
# This script starts the GUI React App and GCS Server, managing port conflicts
# and ensuring processes run reliably, either in tmux or standalone terminals.
#########################################

# Configurable Variables
SESSION_NAME="DroneServices"
GCS_PORT=5000
GUI_PORT=3000
VENV_PATH="$HOME/mavsdk_drone_show/venv"
USE_TMUX=true  # Default behavior is to use tmux
RETRY_LIMIT=5  # Number of retries before giving up

#########################################
# Utility Functions
#########################################

# Function to check if a port is in use
port_in_use() {
    lsof -i :$1 &> /dev/null
    return $?  # 0 if in use, 1 if free
}

# Function to kill a process using a specific port with sudo fallback
kill_port_process() {
    local port=$1
    local pid=$(lsof -t -i:$port)

    if [ -n "$pid" ]; then
        echo "Attempting to kill process $pid on port $port..."
        kill -9 $pid 2>/dev/null
        if [ $? -ne 0 ]; then
            echo "Operation not permitted. Retrying with sudo..."
            sudo kill -9 $pid
            if [ $? -ne 0 ]; then
                echo "Failed to kill process $pid even with sudo. Please handle manually."
            else
                sleep 1  # Give time for the system to release the port
            fi
        else
            sleep 1  # Give time for the system to release the port
        fi
    else
        echo "No process found for port $port."
    fi
}

# Function to ensure a port is free
ensure_port_free() {
    local port=$1
    local retries=0

    while port_in_use $port; do
        kill_port_process $port
        if port_in_use $port; then
            retries=$((retries + 1))
            if [ $retries -ge $RETRY_LIMIT ]; then
                echo "Error: Unable to free port $port after $RETRY_LIMIT attempts."
                exit 1
            fi
            echo "Port $port is still in use. Retrying... ($retries/$RETRY_LIMIT)"
            sleep 2
        else
            echo "Port $port is now free."
            break
        fi
    done
}

# Function to load the virtual environment
load_virtualenv() {
    if [ -d "$VENV_PATH" ]; then
        source "$VENV_PATH/bin/activate"
        echo "Virtual environment activated."
    else
        echo "Error: Virtual environment not found at $VENV_PATH."
        exit 1
    fi
}

# Function to check and handle tmux sessions
check_tmux_session() {
    if tmux has-session -t $SESSION_NAME 2>/dev/null; then
        echo "Existing tmux session '$SESSION_NAME' detected."
        read -p "Kill the existing session? (y/n): " response
        if [[ "$response" =~ ^[Yy]$ ]]; then
            tmux kill-session -t $SESSION_NAME
            echo "Tmux session '$SESSION_NAME' killed."
            sleep 2  # Ensure tmux session is fully terminated
        else
            echo "Please handle the session manually."
            exit 1
        fi
    fi
}

#########################################
# Service Launch Functions
#########################################

start_services_tmux() {
    echo "Creating tmux session '$SESSION_NAME'..."
    tmux new-session -d -s "$SESSION_NAME" -n "GCS-Server" "cd $SCRIPT_DIR/../gcs-server && $VENV_PATH/bin/python app.py; bash"
    tmux new-window -t "$SESSION_NAME" -n "GUI-React" "cd $SCRIPT_DIR/dashboard/drone-dashboard && npm start; bash"
    tmux select-window -t "$SESSION_NAME:0"
    tmux attach-session -t "$SESSION_NAME"
}

start_services_no_tmux() {
    echo "Starting services without tmux..."
    gnome-terminal -- bash -c "cd $SCRIPT_DIR/../gcs-server && $VENV_PATH/bin/python app.py; bash"
    gnome-terminal -- bash -c "cd $SCRIPT_DIR/dashboard/drone-dashboard && npm start; bash"
}

#########################################
# Main Execution Sequence
#########################################

# Determine if tmux should be used
for arg in "$@"; do
    case $arg in
        -n|--no-tmux)
        USE_TMUX=false
        shift
        ;;
    esac
done

# Get the script directory
SCRIPT_DIR="$(dirname "$0")"

# Load virtual environment
load_virtualenv

# Check and free up ports
echo "Ensuring ports are free..."
ensure_port_free $GCS_PORT
ensure_port_free $GUI_PORT

# Start services in tmux or separate terminals
if [ "$USE_TMUX" = true ]; then
    check_tmux_session
    start_services_tmux
else
    start_services_no_tmux
fi

echo "All DroneServices components started successfully."
