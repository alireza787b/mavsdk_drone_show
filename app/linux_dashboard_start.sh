#!/bin/bash

#########################################
# Drone Services Launcher with Tmux Windows and Split Panes
#
# This script manages the execution of the Drone Dashboard, GCS Server,
# and a debug terminal, providing both individual windows and a combined
# split-pane view in tmux.
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

# Function to display tmux instructions to the user
show_tmux_instructions() {
    echo "==============================================="
    echo "  Quick tmux Guide:"
    echo "==============================================="
    echo "Prefix key (Ctrl+B), then:"
    echo "  - Switch between windows: Number keys (e.g., Ctrl+B, then 1, 2, 3)"
    echo "  - Switch between panes (in combined view): Arrow keys (e.g., Ctrl+B, then →)"
    echo "  - Pause scrolling in any window or pane: Ctrl+S (to pause), Ctrl+Q (to resume)"
    echo "  - Detach from session: Ctrl+B, then D"
    echo "  - Reattach to session: tmux attach -t $SESSION_NAME"
    echo "  - Close a window/pane: Type 'exit' or press Ctrl+D"
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

    # Create separate windows for each service
    tmux new-session -d -s "$session" -n "GCS" "clear; $GCS_COMMAND; bash"
    start_process_tmux "$session" "Dashboard" "$DASHBOARD_COMMAND"
    start_process_tmux "$session" "Debug" "clear; echo 'Debug Terminal (Pane 2)'; bash"

    # Create a window with split panes for a combined view
    tmux new-window -t "$session" -n "CombinedView"
    tmux split-window -h -t "$session:3" "clear; $GCS_COMMAND; bash"
    tmux split-window -v -t "$session:3.0" "clear; $DASHBOARD_COMMAND; bash"
    tmux split-window -v -t "$session:3.1" "clear; echo 'Debug Terminal (Pane 2)'; bash"
    tmux select-layout -t "$session:3" tiled  # Organize panes in a tiled layout

    # Attach to the tmux session in the CombinedView window
    tmux select-window -t "$session:3"
    tmux attach-session -t "$session"
}

# Function to run the DroneServices components
run_droneservices_components() {
    echo "Starting DroneServices components in tmux..."

    # Commands for the GCS Server and the Dashboard
    GCS_COMMAND="cd $SCRIPT_DIR/../gcs-server && $PYTHON_CMD app.py"
    DASHBOARD_COMMAND="cd $REACT_APP_DIR && npm start"

    # Start services in tmux with separate windows and a combined view
    start_services_in_tmux

    # Show user instructions after tmux session is attached
    show_tmux_instructions
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
