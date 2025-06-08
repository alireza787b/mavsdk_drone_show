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
#   ./linux_dashboard_start.sh [-g|-u|-n|-s|-h] [--sitl | --real] [--overwrite-ip <IP>] [-b <branch>]
#   Flags:
#     -g : Do NOT run GCS Server (default: enabled)
#     -u : Do NOT run GUI React App (default: enabled)
#     -n : Do NOT use tmux (default: uses tmux)
#     -s : Run components in Separate windows (default: Combined view)
#     --sitl : Switch to simulation mode by deleting 'real.mode' file
#     --real : Switch to real mode by creating 'real.mode' file
#     --overwrite-ip <IP> : Overwrite the server IP in .env
#     -b <branch> : Specify a custom branch to sync with (default: main-candidate)
#     -h : Display help
#
# Example:
#   ./linux_dashboard_start.sh -g -s --sitl --overwrite-ip 100.84.222.4
#   (Runs GUI React App in a separate window, skips the GCS Server, switches to simulation mode, and overwrites the server IP)
#
#########################################

# Display ASCII Art Banner
cat << "EOF"


  __  __   ___   _____ ___  _  __  ___  ___  ___  _  _ ___   ___ _  _  _____      __   ____  __ ___  _____  
 |  \/  | /_\ \ / / __|   \| |/ / |   \| _ \/ _ \| \| | __| / __| || |/ _ \ \    / /  / /  \/  |   \/ __\ \ 
 | |\/| |/ _ \ V /\__ \ |) | ' <  | |) |   / (_) | .` | _|  \__ \ __ | (_) \ \/\/ /  | || |\/| | |) \__ \| |
 |_|  |_/_/ \_\_/ |___/___/|_|\_\ |___/|_|_\\___/|_|\_|___| |___/_||_|\___/ \_/\_/   | ||_|  |_|___/|___/| |
                                                                                      \_\               /_/ 


EOF

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
VENV_PATH="$HOME/UAV_sepehr/venv"
UPDATE_SCRIPT_PATH="$HOME/UAV_sepehr/tools/update_repo_ssh.sh"  # Path to the repo update script
BRANCH_NAME="main-candidate"  # Set default branch to main-candidate

# Get the script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"  # One directory above the script's directory

# Path to the .env file
ENV_FILE_PATH="$SCRIPT_DIR/dashboard/drone-dashboard/.env"

# Path to the real.mode file (one directory above the script)
REAL_MODE_FILE="$PARENT_DIR/real.mode"

# Initialize variables for new arguments
USE_SITL=false
USE_REAL=false
OVERWRITE_IP=""

# Function to display usage instructions
display_usage() {
    echo "Usage: $0 [-g|-u|-n|-s|-h] [--sitl | --real] [--overwrite-ip <IP>] [-b <branch>]"
    echo "Flags:"
    echo "  -g : Do NOT run GCS Server (default: enabled)"
    echo "  -u : Do NOT run GUI React App (default: enabled)"
    echo "  -n : Do NOT use tmux (default: uses tmux)"
    echo "  -s : Run components in Separate windows (default: Combined view)"
    echo "  --sitl : Switch to simulation mode by deleting 'real.mode' file"
    echo "  --real : Switch to real mode by creating 'real.mode' file"
    echo "  --overwrite-ip <IP> : Overwrite the server IP in .env"
    echo "  -b <branch> : Specify a custom branch to sync with (default: main-candidate)"
    echo "  -h : Display this help message"
    echo ""
    echo "Examples:"
    echo "  $0 -g -s --sitl --overwrite-ip 100.84.222.4"
    echo "    (Runs GUI React App in a separate window, skips the GCS Server, switches to simulation mode, and overwrites the server IP)"
    echo ""
    echo "  $0 --real"
    echo "    (Switches to real mode by creating 'real.mode' file and uses the main-candidate branch)"
}

# Manually handle long options (--sitl, --real, --overwrite-ip) and combine with getopts for short options
PARSED_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --sitl)
            if [ "$USE_REAL" = true ]; then
                echo "❌ Cannot use --sitl and --real simultaneously."
                exit 1
            fi
            USE_SITL=true
            shift
            ;;
        --real)
            if [ "$USE_SITL" = true ]; then
                echo "❌ Cannot use --sitl and --real simultaneously."
                exit 1
            fi
            USE_REAL=true
            shift
            ;;
        --overwrite-ip)
            if [ -n "$2" ]; then
                OVERWRITE_IP="$2"
                shift 2
            else
                echo "❌ --overwrite-ip requires an argument."
                display_usage
                exit 1
            fi
            ;;
        -g|-u|-n|-s|-h|-b)
            PARSED_ARGS+=("$1" "$2")
            if [ "$1" = "-b" ]; then
                shift 2
            else
                shift 1
            fi
            ;;
        *)
            PARSED_ARGS+=("$1")
            shift
            ;;
    esac
done

# Repass parsed options to getopts for short options processing
set -- "${PARSED_ARGS[@]}"

# Parse command-line options using getopts for short options
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

# Function to check if a command is installed and install it if not
check_command_installed() {
    local cmd="$1"
    local pkg="$2"
    if ! command -v "$cmd" &> /dev/null; then
        echo "⚠️  $cmd could not be found. Installing $pkg..."
        sudo apt-get update
        sudo apt-get install -y "$pkg"
        if [ $? -ne 0 ]; then
            echo "❌ Failed to install $pkg. Please install it manually."
            exit 1
        else
            echo "✅ $pkg installed successfully."
        fi
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
    check_command_installed "lsof" "lsof"
    pids=$(lsof -t -i :"$port")
    if [ -n "$pids" ]; then
        echo "⚠️  Port $port is in use by process(es): $pids"
        for pid in $pids; do
            process_name=$(ps -p "$pid" -o comm=)
            echo "Process using port $port: $process_name (PID: $pid)"
            echo "Killing process $pid..."
            kill -9 "$pid"
            if [ $? -eq 0 ]; then
                echo "✅ Process $pid killed."
            else
                echo "❌ Failed to kill process $pid."
                exit 1
            fi
        done
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

# Paths to component scripts
# Change directory to PARENT_DIR before running the GCS server app
GCS_SERVER_SCRIPT="cd $PARENT_DIR && $VENV_PATH/bin/python gcs-server/app.py"
GUI_APP_SCRIPT="cd $SCRIPT_DIR/dashboard/drone-dashboard && npm start"

# Function to update the repository
update_repository() {
    if [ -n "$BRANCH_NAME" ]; then
        echo "🔄 Running repository update script for branch '$BRANCH_NAME'..."
        if [ -f "$UPDATE_SCRIPT_PATH" ]; then
            bash "$UPDATE_SCRIPT_PATH" -b "$BRANCH_NAME"
            if [ $? -ne 0 ]; then
                echo "❌ Error: Repository update failed. Exiting."
                exit 1
            else
                echo "✅ Repository successfully updated."
            fi
        else
            echo "❌ Error: Update script not found at $UPDATE_SCRIPT_PATH."
            exit 1
        fi
    else
        echo "🔄 No branch flag provided. Keeping the current branch."
    fi
}

# Function to load the virtual environment
load_virtualenv() {
    if [ -d "$VENV_PATH" ]; then
        source "$VENV_PATH/bin/activate"
        echo "✅ Virtual environment activated."
    else
        echo "❌ Error: Virtual environment not found at $VENV_PATH."
        exit 1
    fi
}

# Function to handle .env file with overwrite option
handle_env_file() {
    echo "-----------------------------------------------"
    echo "  Checking for .env configuration file..."
    echo "-----------------------------------------------"

    if [ -f "$ENV_FILE_PATH" ]; then
        echo "✅ .env file found at $ENV_FILE_PATH."
        if [ -n "$OVERWRITE_IP" ]; then
            echo "🔧 Overwriting server IP to $OVERWRITE_IP in .env."
            # Create a backup before modifying
            cp "$ENV_FILE_PATH" "$ENV_FILE_PATH.bak"
            if [ $? -ne 0 ]; then
                echo "❌ Failed to create backup of .env file. Please check permissions."
                exit 1
            fi
            # Update the REACT_APP_SERVER_URL in .env
            sed -i "s|^REACT_APP_SERVER_URL=.*|REACT_APP_SERVER_URL=http://$OVERWRITE_IP|" "$ENV_FILE_PATH"
            if [ $? -eq 0 ]; then
                echo "✅ REACT_APP_SERVER_URL updated to http://$OVERWRITE_IP"
                echo "✅ Backup of original .env saved as .env.bak"
            else
                echo "❌ Failed to update REACT_APP_SERVER_URL. Please check permissions."
                exit 1
            fi
        else
            echo "Current Configuration:"
            echo "---------------------------------"
            # Extract and display relevant variables
            REACT_APP_SERVER_URL=$(grep '^REACT_APP_SERVER_URL=' "$ENV_FILE_PATH" | cut -d '=' -f2)
            REACT_APP_FLASK_PORT=$(grep '^REACT_APP_FLASK_PORT=' "$ENV_FILE_PATH" | cut -d '=' -f2)
            DRONE_APP_FLASK_PORT=$(grep '^DRONE_APP_FLASK_PORT=' "$ENV_FILE_PATH" | cut -d '=' -f2)
            GENERATE_SOURCEMAP=$(grep '^GENERATE_SOURCEMAP=' "$ENV_FILE_PATH" | cut -d '=' -f2)

            echo "REACT_APP_SERVER_URL=$REACT_APP_SERVER_URL"
            echo "REACT_APP_FLASK_PORT=$REACT_APP_FLASK_PORT"
            echo "DRONE_APP_FLASK_PORT=$DRONE_APP_FLASK_PORT"
            echo "GENERATE_SOURCEMAP=$GENERATE_SOURCEMAP"
            echo "---------------------------------"
        fi
    else
        echo "⚠️  .env file not found at $ENV_FILE_PATH."
        echo "Please provide the server IP accessible from the client."

        # Determine if overwrite IP is provided
        if [ -n "$OVERWRITE_IP" ]; then
            SERVER_IP="$OVERWRITE_IP"
            echo "🔧 Overwrite IP provided. Using IP: $SERVER_IP"
        else
            # Prompt the user for server IP
            read -p "Enter the server IP (e.g., 100.84.222.4): " SERVER_IP
        fi

        # Validate the input (basic validation)
        if [[ ! $SERVER_IP =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            echo "❌ Invalid IP address format. Exiting."
            exit 1
        fi

        # Ensure the directory exists
        TARGET_DIR=$(dirname "$ENV_FILE_PATH")
        if [ ! -d "$TARGET_DIR" ]; then
            echo "📁 Directory $TARGET_DIR does not exist. Creating it..."
            mkdir -p "$TARGET_DIR"
            if [ $? -ne 0 ]; then
                echo "❌ Failed to create directory $TARGET_DIR. Please check permissions."
                exit 1
            else
                echo "✅ Directory $TARGET_DIR created successfully."
            fi
        fi

        # Create the .env file with the provided IP
        echo "Creating .env file at $ENV_FILE_PATH..."
        cat <<EOL > "$ENV_FILE_PATH"
# .env file
# REACT_APP_SERVER_URL=http://<SERVER_IP_OR_HOSTNAME>
REACT_APP_SERVER_URL=http://$SERVER_IP
REACT_APP_FLASK_PORT=5000
DRONE_APP_FLASK_PORT=7070

GENERATE_SOURCEMAP=false
EOL

        if [ $? -eq 0 ]; then
            echo "✅ .env file created successfully."
            echo "You can manually edit the .env file later if needed."
        else
            echo "❌ Failed to create .env file. Please check permissions."
            exit 1
        fi
    fi
}

# Function to create or delete the real.mode file based on mode flags
handle_real_mode_file() {
    if [ "$USE_REAL" = true ]; then
        echo "-----------------------------------------------"
        echo "  Switching to Real Mode: Creating 'real.mode' file..."
        echo "-----------------------------------------------"
        # Create the real.mode file
        touch "$REAL_MODE_FILE"
        if [ $? -eq 0 ]; then
            echo "✅ 'real.mode' file created at $REAL_MODE_FILE."
        else
            echo "❌ Failed to create 'real.mode' file. Please check permissions."
            exit 1
        fi
    elif [ "$USE_SITL" = true ]; then
        echo "-----------------------------------------------"
        echo "  Switching to Simulation Mode: Deleting 'real.mode' file if exists..."
        echo "-----------------------------------------------"
        if [ -f "$REAL_MODE_FILE" ]; then
            rm "$REAL_MODE_FILE"
            if [ $? -eq 0 ]; then
                echo "✅ 'real.mode' file deleted from $REAL_MODE_FILE."
            else
                echo "❌ Failed to delete 'real.mode' file. Please check permissions."
                exit 1
            fi
        else
            echo "ℹ️  'real.mode' file does not exist. Already in Simulation Mode."
        fi
    else
        echo "-----------------------------------------------"
        echo "  No mode switch argument provided. Keeping current mode."
        echo "-----------------------------------------------"
    fi
}

# Function to start services in tmux
start_services_in_tmux() {
    local session="$SESSION_NAME"

    # Kill existing tmux session if it exists
    if tmux has-session -t "$session" 2>/dev/null; then
        echo "⚠️  Killing existing tmux session '$session'..."
        tmux kill-session -t "$session"
        sleep 1
    fi

    echo "🟢 Creating tmux session '$session'..."
    tmux new-session -d -s "$session"

    if [ "$ENABLE_MOUSE" = true ]; then
        tmux set-option -g mouse on
    fi

    declare -A components

    if [ "$RUN_GCS_SERVER" = true ]; then
        components["GCS-Server"]="$GCS_SERVER_SCRIPT"
    fi

    if [ "$RUN_GUI_APP" = true ]; then
        components["GUI-React"]="$GUI_APP_SCRIPT"
    fi

    if [ "$COMBINED_VIEW" = true ]; then
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
        local window_index=0
        for component_name in "${!components[@]}"; do
            if [ "$window_index" -eq 0 ]; then
                tmux rename-window -t "$session:0" "$component_name"
                tmux send-keys -t "$session:$component_name" "clear; ${components[$component_name]}; bash" C-m
            else
                tmux new-window -t "$session" -n "$component_name"
                tmux send-keys -t "$session:$component_name" "clear; ${components[$component_name]}; bash" C-m
            fi
            window_index=$((window_index + 1))
        done
    fi

    show_tmux_instructions
    tmux attach-session -t "$session"
}

# Function to start services without tmux
start_services_no_tmux() {
    echo "🟢 Starting services without tmux..."
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

# Check for required commands
check_tmux_installed
check_command_installed "lsof" "lsof"

# Handle mode switching (--real or --sitl)
handle_real_mode_file

# Update repository based on branch selection
update_repository

# Load the virtual environment
load_virtualenv

# Handle .env file with overwrite option
handle_env_file

# Display summary of selected options
echo ""
echo "==============================================="
echo "  Configuration Summary:"
echo "==============================================="
if [ "$USE_SITL" = true ]; then
    echo "✔️  Mode: Simulation (SITL)"
elif [ "$USE_REAL" = true ]; then
    echo "✔️  Mode: Real"
else
    CURRENT_MODE="Unknown (based on 'real.mode' file)"
    if [ -f "$REAL_MODE_FILE" ]; then
        CURRENT_MODE="Real Mode"
    else
        CURRENT_MODE="Simulation Mode"
    fi
    echo "✔️  Mode: $CURRENT_MODE"
fi

echo "✔️  Branch: $BRANCH_NAME"
echo "✔️  GCS Server: $([ "$RUN_GCS_SERVER" = true ] && echo "Enabled" || echo "Disabled")"
echo "✔️  GUI React App: $([ "$RUN_GUI_APP" = true ] && echo "Enabled" || echo "Disabled")"
echo "✔️  Use tmux: $([ "$USE_TMUX" = true ] && echo "Yes" || echo "No")"
echo "✔️  View Mode: $([ "$COMBINED_VIEW" = true ] && echo "Combined" || echo "Separate Windows")"
if [ -n "$OVERWRITE_IP" ]; then
    echo "✔️  Server IP Overwrite: Enabled ($OVERWRITE_IP)"
else
    echo "✔️  Server IP Overwrite: Disabled"
fi
echo "==============================================="
echo ""

# Kill existing tmux session if it exists
echo "-----------------------------------------------"
echo "Ensuring no existing tmux session named '$SESSION_NAME' is running..."
echo "-----------------------------------------------"
if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo "⚠️  Killing existing tmux session '$SESSION_NAME'..."
    tmux kill-session -t "$SESSION_NAME"
    sleep 1
else
    echo "✅ No existing tmux session named '$SESSION_NAME'."
fi

# Check and free up ports
echo "-----------------------------------------------"
echo "Checking and freeing up default ports..."
echo "-----------------------------------------------"
if [ "$RUN_GCS_SERVER" = true ]; then
    check_and_kill_port "$GCS_PORT"
fi

if [ "$RUN_GUI_APP" = true ]; then
    check_and_kill_port "$GUI_PORT"
fi

# Start DroneServices components
run_droneservices_components() {
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
            echo "🟢 Components will be started in a combined view (split panes)."
        else
            echo "🟢 Components will be started in separate tmux windows."
        fi
        start_services_in_tmux
    else
        echo "🟢 Starting services without tmux..."
        start_services_no_tmux
    fi
}

run_droneservices_components

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
