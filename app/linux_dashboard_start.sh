#!/bin/bash

#########################################
# Drone Services Launcher with Tmux Side-by-Side Panes
#
# This script manages the execution of the Drone Dashboard, GCS Server,
# and a debug terminal, providing a side-by-side split view in tmux.
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
    echo "  - Switch between panes: Arrow keys (e.g., Ctrl+B, then →)"
    echo "  - Navigate to a specific pane: Ctrl+B, then pane number (0, 1, 2)"
    echo "  - Pause scrolling in a pane: Ctrl+S (to pause), Ctrl+Q (to resume)"
    echo "  - Detach from session: Ctrl+B, then D"
    echo "  - Reattach to session: tmux attach -t $SESSION_NAME"
    echo "  - Close a pane or window: Type 'exit' or press Ctrl+D"
    echo "==============================================="
    echo ""
}

# Function to create a tmux session with split panes
start_services_in_tmux() {
    local session="$SESSION_NAME"

    echo "Creating tmux session '$session' with side-by-side panes..."

    # Create the session and the first pane for the GCS server
    tmux new-session -d -s "$session" -n "Services" "clear; $GCS_COMMAND; bash"

    # Split horizontally to create the second pane for the Dashboard
    tmux split-window -h -t "$session:0" "clear; $DASHBOARD_COMMAND; bash"

    # Split horizontally again to create the third pane for the Debug terminal
    tmux split-window -h -t "$session:0.1" "clear; echo 'Debug Terminal (Pane 2)'; bash"

    # Adjust layout to distribute the panes evenly
    tmux select-layout -t "$session:0" even-horizontal

    # Attach to the tmux session
    tmux attach-session -t "$session"
}

# Function to run the DroneServices components
run_droneservices_components() {
    echo "Starting DroneServices components in tmux..."

    # Commands for the GCS Server and the Dashboard
    GCS_COMMAND="cd $SCRIPT_DIR/../gcs-server && $PYTHON_CMD app.py"
    DASHBOARD_COMMAND="cd $REACT_APP_DIR && npm start"

    # Start services in tmux with split panes
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
