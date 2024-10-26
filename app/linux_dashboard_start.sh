#!/bin/bash

#########################################
# Robust Drone Services Launcher with Repo Sync and Mouse Support in tmux
#
# Project: Drone Show GCS Server
# Author: Alireza Ghaderi
# Date: October 2024
#
# This script starts the GUI React App and GCS Server, manages port conflicts,
# ensures processes run reliably in tmux or standalone terminals, and optionally
# pulls the latest updates from the repository.
#
# Usage:
#   ./run_droneservices.sh [-g|-u|-n|-s|-h] [--sitl] [-b <branch>]
#   Flags:
#     -g : Do NOT run GCS Server (default: enabled)
#     -u : Do NOT run GUI React App (default: enabled)
#     -n : Do NOT use tmux (default: uses tmux)
#     -s : Run components in Separate windows (default: Combined view)
#     --sitl : Use SITL branch (docker-sitl-2) for the repository sync
#     -b <branch> : Specify a custom branch to sync with
#     -h : Display help
#
# Example:
#   ./run_droneservices.sh -g -s --sitl
#   (Runs GUI React App in a separate window, skips the GCS Server, uses the docker-sitl-2 branch)
#
#########################################

# Default flag values (all components enabled by default)
RUN_GCS_SERVER=true
RUN_GUI_APP=true
USE_TMUX=true          # Default behavior is to use tmux
COMBINED_VIEW=true     # Default is combined view
ENABLE_MOUSE=true      # Default behavior is to enable mouse support in tmux
ENABLE_AUTO_PULL=true  # Enable or disable the automatic pulling and syncing of the repository

# Configurable Variables
SESSION_NAME="DroneServices"
GCS_PORT=5000
GUI_PORT=3000
VENV_PATH="$HOME/mavsdk_drone_show/venv"
UPDATE_SCRIPT_PATH="$HOME/mavsdk_drone_show/tools/update_repo_ssh.sh"  # Path to the repo update script
BRANCH_NAME="real-test-1"  # Default branch to sync
SITL_BRANCH="docker-sitl-2" # SITL branch to use with --sitl flag

# Function to display usage instructions
display_usage() {
    echo "Usage: $0 [-g|-u|-n|-s|-h] [--sitl] [-b <branch>]"
    echo "Flags:"
    echo "  -g : Do NOT run GCS Server (default: enabled)"
    echo "  -u : Do NOT run GUI React App (default: enabled)"
    echo "  -n : Do NOT use tmux (default: uses tmux)"
    echo "  -s : Run components in Separate windows (default: Combined view)"
    echo "  --sitl : Use SITL branch (docker-sitl-2) for repository sync"
    echo "  -b <branch> : Specify a custom branch to sync with"
    echo "  -h : Display this help message"
    echo "Example: $0 -g -s --sitl"
}

# Parse command-line options
while getopts "gunshb:" opt; do
    case ${opt} in
        g) RUN_GCS_SERVER=false ;;
        u) RUN_GUI_APP=false ;;
        n) USE_TMUX=false ;;
        s) COMBINED_VIEW=false ;;
        h)
            display_usage
            exit 0
            ;;
        b) BRANCH_NAME="$OPTARG" ;;
        *)
            display_usage
            exit 1
            ;;
    esac
done

# Shift the processed options so we can handle the remaining arguments
shift $((OPTIND - 1))

# Check for --sitl flag (manually handle long options)
for arg in "$@"; do
    if [ "$arg" == "--sitl" ]; then
        BRANCH_NAME="$SITL_BRANCH"
    fi
done

# Function to check if a command is installed and install it if not
check_command_installed() {
    local cmd="$1"
    local pkg="$2"
    if ! command -v "$cmd" &> /dev/null; then
        echo "⚠️  $cmd could not be found. Installing $pkg..."
        sudo apt-get update
        sudo apt-get install -y "$pkg"
    else
        echo "✅ $cmd is already installed."
    fi
}

# Function to check if tmux is installed and install it if not
check_tmux_installed() {
    check_command_installed "tmux" "tmux"
}

# Function to check if a port is in use and kill the process using it
check_and_kill_port() {
    local port="$1"
    # Ensure lsof is installed
    check_command_installed "lsof" "lsof"
    # Find the process ID (PID) using the port
    pid=$(lsof -t -i :"$port")
    if [ -n "$pid" ]; then
        echo "⚠️  Port $port is in use by process $pid."
        # Get the process name
        process_name=$(ps -p "$pid" -o comm=)
        echo "Process using port $port: $process_name (PID: $pid)"
        # Kill the process
        echo "Killing process $pid..."
        kill -9 "$pid"
        echo "✅ Process $pid killed."
    else
        echo "✅ Port $port is free."
    fi
}

# Function to display tmux instructions
show_tmux_instructions() {
    echo ""
    echo "==============================================="
    echo "  Quick tmux Guide:"
    echo "==============================================="
    echo "Prefix key (Ctrl+B), then:"
    if [ "$COMBINED_VIEW" = true ]; then
        echo "  - Switch between panes: Arrow keys (e.g., Ctrl+B, then →)"
        echo "  - Resize panes: Hold Ctrl+B, then press and hold an arrow key"
    else
        echo "  - Switch between windows: Number keys (e.g., Ctrl+B, then 1, 2)"
    fi
    echo "  - Detach from session: Ctrl+B, then D"
    echo "  - Reattach to session: tmux attach -t $SESSION_NAME"
    echo "  - Close pane/window: Type 'exit' or press Ctrl+D"
    echo "==============================================="
    echo ""
}

# Get the script directory
SCRIPT_DIR="$(dirname "$0")"

# Paths to component scripts
GCS_SERVER_SCRIPT="cd $SCRIPT_DIR/../gcs-server && $VENV_PATH/bin/python app.py"
GUI_APP_SCRIPT="cd $SCRIPT_DIR/dashboard/drone-dashboard && npm start"

# Function to update the repository
update_repository() {
    if [ "$ENABLE_AUTO_PULL" = true ]; then
        echo "Running repository update script for branch '$BRANCH_NAME'..."
        if [ -f "$UPDATE_SCRIPT_PATH" ]; then
            bash "$UPDATE_SCRIPT_PATH" -b "$BRANCH_NAME"
            if [ $? -ne 0 ]; then
                echo "Error: Repository update failed. Exiting."
                exit 1
            else
                echo "Repository successfully updated."
            fi
        else
            echo "Error: Update script not found at $UPDATE_SCRIPT_PATH."
            exit 1
        fi
    else
        echo "Auto-pull is disabled. Skipping repository update."
    fi
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

# Function to start services in tmux
start_services_in_tmux() {
    local session="$SESSION_NAME"

    # Kill existing session if it exists
    if tmux has-session -t "$session" 2>/dev/null; then
        echo "⚠️  Killing existing tmux session '$session'..."
        tmux kill-session -t "$session"
    fi

    echo "Creating tmux session '$session'..."
    tmux new-session -d -s "$session"

    if [ "$ENABLE_MOUSE" = true ]; then
        tmux set-option -g mouse on  # Enable mouse support
    fi

    # Create an associative array to hold enabled components
    declare -A components

    if [ "$RUN_GCS_SERVER" = true ]; then
        components["GCS-Server"]="$GCS_SERVER_SCRIPT"
    fi

    if [ "$RUN_GUI_APP" = true ]; then
        components["GUI-React"]="$GUI_APP_SCRIPT"
    fi

    if [ "$COMBINED_VIEW" = true ]; then
        # Combined view with split panes
        tmux rename-window -t "$session:0" "CombinedView"
        local pane_index=0
        for component_name in "${!components[@]}"; do
            if [ $pane_index -eq 0 ]; then
                tmux send-keys -t "$session:CombinedView.$pane_index" "clear; ${components[$component_name]}; bash" C-m
            else
                tmux split-window -t "$session:CombinedView" -h
                tmux select-pane -t "$session:CombinedView.$pane_index"
                tmux send-keys -t "$session:CombinedView.$pane_index" "clear; ${components[$component_name]}; bash" C-m
            fi
            pane_index=$((pane_index + 1))
        done

        if [ $pane_index -gt 1 ]; then
            tmux select-layout -t "$session:CombinedView" tiled
        fi
    else
        # Start components in separate windows
        local window_index=0
        for component_name in "${!components[@]}"; do
            if [ $window_index -eq 0 ]; then
                # Rename the first window (created by default)
                tmux rename-window -t "$session:0" "$component_name"
                tmux send-keys -t "$session:$component_name" "clear; ${components[$component_name]}; bash" C-m
            else
                tmux new-window -t "$session" -n "$component_name"
                tmux send-keys -t "$session:$component_name" "clear; ${components[$component_name]}; bash" C-m
            fi
            window_index=$((window_index + 1))
        done
    fi

    # Display tmux instructions before attaching
    show_tmux_instructions

    # Attach to the tmux session
    tmux attach-session -t "$session"
}

# Function to start services without tmux
start_services_no_tmux() {
    echo "Starting services without tmux..."
    if [ "$RUN_GCS_SERVER" = true ]; then
        gnome-terminal -- bash -c "$GCS_SERVER_SCRIPT; bash"
    fi
    if [ "$RUN_GUI_APP" = true ]; then
        gnome-terminal -- bash -c "$GUI_APP_SCRIPT; bash"
    fi
}

#########################################
# Main Execution Sequence
#########################################

echo "==============================================="
echo "  Initializing DroneServices System..."
echo "==============================================="
echo ""

# Check if required commands are installed
check_tmux_installed
check_command_installed "lsof" "lsof"

# Update repository if auto-pull is enabled
update_repository

# Load virtual environment
load_virtualenv

# Check and kill processes using default ports
echo "-----------------------------------------------"
echo "Checking and freeing up default ports..."
echo "-----------------------------------------------"
if [ "$RUN_GCS_SERVER" = true ]; then
    check_and_kill_port "$GCS_PORT"
fi

if [ "$RUN_GUI_APP" = true ]; then
    check_and_kill_port "$GUI_PORT"
fi

# Function to run the DroneServices components
run_droneservices_components() {
    echo ""
    echo "-----------------------------------------------"
    echo "Starting DroneServices components..."
    echo "-----------------------------------------------"

    if [ "$RUN_GCS_SERVER" = true ]; then
        echo "✅ GCS Server will be started."
    else
        echo "❌ GCS Server is disabled."
    fi

    if [ "$RUN_GUI_APP" = true ]; then
        echo "✅ GUI React App will be started."
    else
        echo "❌ GUI React App is disabled."
    fi

    if [ "$USE_TMUX" = true ]; then
        if [ "$COMBINED_VIEW" = true ]; then
            echo "Components will be started in a combined view (split panes)."
        else
            echo "Components will be started in separate tmux windows."
        fi
        start_services_in_tmux
    else
        echo "Starting services without tmux..."
        start_services_no_tmux
    fi
}

# Run the components
run_droneservices_components

echo ""
echo "==============================================="
echo "  DroneServices System Startup Complete!"
echo "==============================================="
echo ""
echo "All selected components are now running."
if [ "$USE_TMUX" = true ]; then
    echo "You can detach from the tmux session without stopping the services."
    echo "Use 'tmux attach -t $SESSION_NAME' to reattach to the session."
    echo ""
    echo "To kill the tmux session and stop all components, run:"
    echo "👉 tmux kill-session -t $SESSION_NAME"
    echo ""
    echo "To kill all tmux sessions (caution: this will kill all tmux sessions on the system), run:"
    echo "👉 tmux kill-server"
    echo ""
fi
