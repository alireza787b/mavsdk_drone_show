#!/bin/bash

#########################################
# Drone Services Launcher with Tmux Windows and Split Panes
#
# This script manages the execution of the Drone Dashboard and GCS
# application, providing a combined split view as well as separate
# windows for each service.
#
# Usage:
#   ./run_droneservices.sh
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
    echo "  - Switch between windows: Number keys (e.g., Ctrl+B, then 1, 2)"
    echo "  - Switch between panes: Arrow keys (e.g., Ctrl+B, then →)"
    echo "  - Pause auto-scrolling: Ctrl+S (pause), Ctrl+Q (resume)"
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
    tmux new-session -d -s "$session" -n "CombinedView"
    
    # Split the CombinedView window into three panes
    tmux split-window -h -t "$session:0" "clear; $GCS_COMMAND; bash"
    tmux split-window -v -t "$session:0.0" "clear; $DASHBOARD_COMMAND; bash"
    tmux split-window -v -t "$session:0.1" "clear; $OTHER_SERVICE_COMMAND; bash"
    tmux select-layout -t "$session:0" tiled  # Organize panes in a tiled layout

    # Create separate windows for each service
    start_process_tmux "$session" "GCS" "$GCS_COMMAND"
    start_process_tmux "$session" "Dashboard" "$DASHBOARD_COMMAND"
    start_process_tmux "$session" "OtherService" "$OTHER_SERVICE_COMMAND"

    # Attach to the tmux session and display instructions
    tmux attach-session -t "$session"
    show_tmux_instructions
}

# Function to run the DroneServices components
run_droneservices_components() {
    echo "Starting DroneServices components in tmux..."

    GCS_COMMAND="cd $SCRIPT_DIR/../gcs-server && $PYTHON_CMD app.py"
    DASHBOARD_COMMAND="cd $REACT_APP_DIR && npm start"
    OTHER_SERVICE_COMMAND="cd $SCRIPT_DIR/../other-service && ./run_service.sh"

    start_services_in_tmux
}

# Main execution sequence
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
run_droneservices_components

echo ""
echo "==============================================="
echo "  All DroneServices components have been started successfully!"
echo "==============================================="
echo ""
