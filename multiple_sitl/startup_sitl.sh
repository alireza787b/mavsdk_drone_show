#!/bin/bash

# =============================================================================
# Script Name: startup_sitl.sh
# Description: Initializes and manages the SITL simulation for MAVSDK_Drone_Show.
#              Configures environment, updates repository, sets system IDs, synchronizes
#              system time with NTP using an external script, and starts the SITL simulation
#              along with coordinator.py.
# Author: Alireza Ghaderi
# Date: September 2024
# =============================================================================

# Exit immediately if a command exits with a non-zero status,
# if an undefined variable is used, or if any command in a pipeline fails
set -euo pipefail

# Enable debug mode if needed (uncomment the following line for debugging)
# set -x

# =============================================================================
# Configuration Variables
# =============================================================================

# GitHub Repository Details
DEFAULT_GIT_REMOTE="origin"
DEFAULT_GIT_BRANCH="docker-sitl-2"
GITHUB_REPO_URL="https://github.com/alireza787b/mavsdk_drone_show.git"

# Option to use global Python
USE_GLOBAL_PYTHON=false  # Set to true to use global Python instead of venv

# Default geographic position: Azadi Stadium
DEFAULT_LAT=35.724435686078365
DEFAULT_LON=51.275581311948706
DEFAULT_ALT=1278

# Directory Paths
BASE_DIR="$HOME/mavsdk_drone_show"
VENV_DIR="$BASE_DIR/venv"
CONFIG_FILE="$BASE_DIR/config_sitl.csv"
PX4_DIR="$HOME/PX4-Autopilot"
mavlink2rest_SCRIPT="$BASE_DIR/tools/run_mavlink2rest.sh"


# Path to the external time synchronization script
# SYNC_SCRIPT="$BASE_DIR/tools/sync_time_linux.sh"

# Script Metadata
SCRIPT_NAME=$(basename "$0")
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Default Simulation Mode (h: headless, g: graphical, j: jmavsim)
SIMULATION_MODE="h"

# Initialize Git variables
GIT_REMOTE="$DEFAULT_GIT_REMOTE"
GIT_BRANCH="$DEFAULT_GIT_BRANCH"

# =============================================================================
# Function Definitions
# =============================================================================

# Function to display usage information
usage() {
    cat << EOF
Usage: $SCRIPT_NAME [options]

Options:
  -r <git_remote>       Specify the GitHub repository remote name (default: $DEFAULT_GIT_REMOTE)
  -b <git_branch>       Specify the GitHub repository branch name (default: $DEFAULT_GIT_BRANCH)
  -s <simulation_mode>  Specify simulation mode: 'g' for graphical, 'h' for headless, 'j' for jmavsim (default: $SIMULATION_MODE)
  -h, --help            Display this help message

Examples:
  $SCRIPT_NAME
  $SCRIPT_NAME -r upstream -b develop
  $SCRIPT_NAME -s g
EOF
    exit 1
}

# Function to log messages to the terminal with timestamps
log_message() {
    local message="$1"
    echo "$(date +"%Y-%m-%d %H:%M:%S") - $message"
}

# Function to handle script termination and cleanup
cleanup() {
    echo ""
    log_message "Received interrupt signal. Terminating background processes..."
    if [[ -n "${simulation_pid:-}" ]]; then
        kill "$simulation_pid" 2>/dev/null || true
        log_message "Terminated SITL simulation with PID: $simulation_pid"
    fi
    if [[ -n "${coordinator_pid:-}" ]]; then
        kill "$coordinator_pid" 2>/dev/null || true
        log_message "Terminated coordinator.py with PID: $coordinator_pid"
    fi
    if [ "${USE_GLOBAL_PYTHON:-false}" = false ]; then
        deactivate 2>/dev/null || true
        log_message "Deactivated Python virtual environment."
    fi
    exit 0
}

# Function to install 'bc' if not present
install_bc() {
    log_message "'bc' is not installed. Installing 'bc'..."
    if ! sudo apt-get update && sudo apt-get install -y bc; then
        log_message "ERROR: Failed to install 'bc'. Please install it manually."
        exit 1
    fi
    log_message "'bc' installed successfully."
}

# Function to parse script arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -r)
                if [[ -n "${2:-}" && ! $2 =~ ^- ]]; then
                    GIT_REMOTE="$2"
                    shift 2
                else
                    log_message "ERROR: -r requires a non-empty option argument."
                    usage
                fi
                ;;
            -b)
                if [[ -n "${2:-}" && ! $2 =~ ^- ]]; then
                    GIT_BRANCH="$2"
                    shift 2
                else
                    log_message "ERROR: -b requires a non-empty option argument."
                    usage
                fi
                ;;
            -s)
                if [[ -n "${2:-}" && ! $2 =~ ^- ]]; then
                    SIMULATION_MODE="$2"
                    shift 2
                else
                    log_message "ERROR: -s requires a non-empty option argument."
                    usage
                fi
                ;;
            -h|--help)
                usage
                ;;
            *)
                log_message "ERROR: Unknown option: $1"
                usage
                ;;
        esac
    done
}

# Function to check and install dependencies
check_dependencies() {
    if ! command -v bc &> /dev/null; then
        install_bc
    else
        log_message "'bc' is already installed."
    fi
    if ! command -v git &> /dev/null; then
        log_message "'git' is not installed. Installing 'git'..."
        if ! sudo apt-get update && sudo apt-get install -y git; then
            log_message "ERROR: Failed to install 'git'. Please install it manually."
            exit 1
        fi
        log_message "'git' installed successfully."
    else
        log_message "'git' is already installed."
    fi
}

# Function to wait for the .hwID file
wait_for_hwid() {
    log_message "Waiting for .hwID file in $BASE_DIR..."
    while true; do
        HWID_FILE=$(ls "$BASE_DIR"/*.hwID 2>/dev/null | head -n 1 || true)
        if [[ -n "$HWID_FILE" ]]; then
            HWID=$(basename "$HWID_FILE" .hwID)
            log_message "Found .hwID file: $HWID.hwID"
            break
        else
            log_message "  - .hwID file not found. Retrying in 1 second..."
            sleep 1
        fi
    done

    # Validate that HWID is a positive integer
    if ! [[ "$HWID" =~ ^[1-9][0-9]*$ ]]; then
        log_message "ERROR: Extracted HWID '$HWID' is not a positive integer."
        exit 1
    fi
}

# Function to update the repository
update_repository() {
    log_message "Navigating to $BASE_DIR..."
    cd "$BASE_DIR"

    log_message "Stashing any local changes..."
    git stash

    log_message "Setting Git remote to $GIT_REMOTE..."
    git remote set-url "$GIT_REMOTE" "$GITHUB_REPO_URL" || true

    log_message "Fetching latest changes from $GIT_REMOTE/$GIT_BRANCH..."
    if ! git fetch "$GIT_REMOTE" "$GIT_BRANCH"; then
        log_message "ERROR: Failed to fetch from $GIT_REMOTE/$GIT_BRANCH."
        exit 1
    fi

    log_message "Checking out branch $GIT_BRANCH..."
    if ! git checkout "$GIT_BRANCH"; then
        log_message "ERROR: Failed to checkout branch $GIT_BRANCH."
        exit 1
    fi

    log_message "Pulling latest changes from $GIT_REMOTE/$GIT_BRANCH..."
    if ! git pull "$GIT_REMOTE" "$GIT_BRANCH"; then
        log_message "ERROR: Failed to pull latest changes from $GIT_REMOTE/$GIT_BRANCH."
        exit 1
    fi

    log_message "Repository updated successfully."
}


# Function to run mavlink2rest
run_mavlink2rest() {

    bash $mavlink2rest_SCRIPT

    log_message "mavlink2rest script run successfully."
}


# Function to set up Python environment
setup_python_env() {
    if [ "$USE_GLOBAL_PYTHON" = false ]; then
        if [ ! -d "$VENV_DIR" ]; then
            log_message "Creating a Python virtual environment at $VENV_DIR..."
            python3 -m venv "$VENV_DIR"
            log_message "Virtual environment created successfully."
        else
            log_message "Python virtual environment already exists at $VENV_DIR."
        fi

        log_message "Activating the virtual environment..."
        source "$VENV_DIR/bin/activate"

        log_message "Installing Python requirements..."
        if pip install --upgrade pip && pip install -r "$BASE_DIR/requirements.txt"; then
            log_message "Python requirements installed successfully."
        else
            log_message "ERROR: Failed to install Python requirements."
            exit 1
        fi
    else
        log_message "Using global Python installation."
    fi
}

# Function to set MAV_SYS_ID
set_mav_sys_id() {
    log_message "Setting MAV_SYS_ID using set_sys_id.py..."
    if python3 "$BASE_DIR/multiple_sitl/set_sys_id.py"; then
        log_message "MAV_SYS_ID set successfully."
    else
        log_message "ERROR: Failed to set MAV_SYS_ID."
        exit 1
    fi
}

# Function to read offsets from config.csv
read_offsets() {
    log_message "Reading offsets from $CONFIG_FILE for HWID: $HWID..."

    OFFSET_X=0
    OFFSET_Y=0

    if [ ! -f "$CONFIG_FILE" ]; then
        log_message "WARNING: Configuration file $CONFIG_FILE does not exist. Using default offsets (0,0)."
        return
    fi

    while IFS=, read -r hw_id pos_id x y ip mavlink_port debug_port gcs_ip; do
        if [ "$hw_id" == "$HWID" ]; then
            OFFSET_X="$x"
            OFFSET_Y="$y"
            log_message "Found offsets - X: $OFFSET_X, Y: $OFFSET_Y"
            return
        fi
    done < "$CONFIG_FILE"

    log_message "WARNING: HWID $HWID not found in $CONFIG_FILE. Using default offsets (0,0)."
}

# Function to calculate new geographic coordinates
calculate_new_coordinates() {
    log_message "Calculating new geographic coordinates based on offsets..."

    # Constants
    EARTH_RADIUS=6371000  # in meters
    PI=3.141592653589793238

    # Convert latitude from degrees to radians
    LAT_RAD=$(echo "$DEFAULT_LAT * ($PI / 180)" | bc -l)

    # Calculate new latitude based on northward offset (OFFSET_X)
    # Formula: Δφ = (Offset_X / R) * (180 / π)
    NEW_LAT=$(echo "$DEFAULT_LAT + ($OFFSET_X / $EARTH_RADIUS) * (180 / $PI)" | bc -l)

    # Calculate meters per degree of longitude at the current latitude
    # Formula: M_per_degree = (π / 180) * R * cos(lat_rad)
    M_PER_DEGREE=$(echo "scale=10; ($PI / 180) * $EARTH_RADIUS * c($LAT_RAD)" | bc -l)

    # Calculate new longitude based on eastward offset (OFFSET_Y)
    # Formula: Δλ = Offset_Y / M_per_degree
    NEW_LON=$(echo "$DEFAULT_LON + ($OFFSET_Y / $M_PER_DEGREE)" | bc -l)

    log_message "New Coordinates - Latitude: $NEW_LAT, Longitude: $NEW_LON"
}

# Function to export environment variables for PX4 SITL
export_env_vars() {
    log_message "Exporting environment variables for PX4 SITL..."
    export PX4_HOME_LAT="$NEW_LAT"
    export PX4_HOME_LON="$NEW_LON"
    export PX4_HOME_ALT="$DEFAULT_ALT"
    export MAV_SYS_ID="$HWID"
    log_message "Environment variables set: PX4_HOME_LAT=$PX4_HOME_LAT, PX4_HOME_LON=$PX4_HOME_LON, PX4_HOME_ALT=$PX4_HOME_ALT, MAV_SYS_ID=$MAV_SYS_ID"
}

# Function to determine the simulation command
determine_simulation_command() {
    case $SIMULATION_MODE in
        g)
            SIMULATION_COMMAND="make px4_sitl gazebo"
            log_message "Simulation Mode: Graphics Enabled (Gazebo)"
            ;;
        j)
            SIMULATION_COMMAND="make px4_sitl jmavsim"
            log_message "Simulation Mode: Using jmavsim"
            ;;
        h)
            SIMULATION_COMMAND="HEADLESS=1 make px4_sitl gazebo"
            log_message "Simulation Mode: Headless (Graphics Disabled)"
            ;;
        *)
            log_message "Invalid simulation mode: $SIMULATION_MODE. Defaulting to headless mode."
            SIMULATION_COMMAND="HEADLESS=1 make px4_sitl gazebo"
            ;;
    esac

    log_message "Simulation Command: $SIMULATION_COMMAND"
}

# Function to start SITL simulation
start_simulation() {
    log_message "Starting SITL simulation..."
    cd "$PX4_DIR"

    # Export instance identifier
    export px4_instance="${HWID}-1"

    # Execute the simulation command in the background
    eval "$SIMULATION_COMMAND" &
    simulation_pid=$!
    log_message "SITL simulation started with PID: $simulation_pid"
}

# Function to manually run coordinator.py
run_coordinator_manually() {
    log_message "Starting coordinator.py..."
    cd "$BASE_DIR"
    if [ "$USE_GLOBAL_PYTHON" = false ]; then
        source "$VENV_DIR/bin/activate"
    fi
    python3 "$BASE_DIR/coordinator.py" &
    coordinator_pid=$!
    log_message "coordinator.py started with PID: $coordinator_pid"
}

# =============================================================================
# Main Script Execution
# =============================================================================

# Parse script arguments
parse_args "$@"

# Trap SIGINT and SIGTERM to execute cleanup
trap 'cleanup' INT TERM

log_message "=============================================="
log_message " Welcome to the SITL Startup Script!"
log_message "=============================================="
log_message ""
log_message "Configuration:"
log_message "  Git Remote: $GIT_REMOTE"
log_message "  Git Branch: $GIT_BRANCH"
log_message "  Use Global Python: $USE_GLOBAL_PYTHON"
log_message "  Base Directory: $BASE_DIR"
log_message "  Simulation Mode: $SIMULATION_MODE"
log_message ""

# Check for necessary dependencies
check_dependencies

# Wait for the .hwID file
wait_for_hwid

# Update the repository
update_repository

# Run MAVLink2rest
run_mavlink2rest

# Set up Python environment
setup_python_env

# Set MAV_SYS_ID
set_mav_sys_id

# Read offsets from config.csv
read_offsets

# Calculate new geographic coordinates
calculate_new_coordinates

# Export environment variables
export_env_vars

# Determine simulation mode
determine_simulation_command

# Start SITL simulation
start_simulation

# Start coordinator.py
run_coordinator_manually

log_message ""
log_message "=============================================="
log_message "All processes have been initialized."
log_message "coordinator.py is running."
log_message "Press Ctrl+C to terminate the simulation."
log_message "=============================================="
log_message ""

# Wait for the simulation process to complete
wait "$simulation_pid"

# Wait for coordinator.py process to complete
log_message "Waiting for coordinator.py process to complete..."
wait "$coordinator_pid"

# Exit successfully
exit 0
