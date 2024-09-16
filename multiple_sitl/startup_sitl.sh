#!/bin/bash

# =============================================================================
# Script Name: startup_sitl.sh
# Description: Initializes and manages the SITL simulation for MAVSDK_Drone_Show.
#              Configures environment, updates repository, sets system IDs, and
#              starts the SITL simulation. The coordinator process is managed
#              by coordinator.service by default, with an option to run it manually.
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
DEFAULT_GIT_BRANCH="real-test-1"
GITHUB_REPO_URL="https://github.com/alireza787b/mavsdk_drone_show.git"

# Option to use global Python
USE_GLOBAL_PYTHON=false  # Set to true to use global Python instead of venv

# Default geographic position: Azadi Stadium
DEFAULT_LAT=35.725125060059966
DEFAULT_LON=51.27585107671351
DEFAULT_ALT=1278.5

# Directory Paths
BASE_DIR="$HOME/mavsdk_drone_show"
VENV_DIR="$BASE_DIR/venv"
CONFIG_FILE="$BASE_DIR/../config.csv"
PX4_DIR="$HOME/PX4-Autopilot"

# Script Metadata
SCRIPT_NAME=$(basename "$0")
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# =============================================================================
# Function Definitions
# =============================================================================

# Function to display usage information
usage() {
    cat << EOF
Usage: $SCRIPT_NAME [options]

Options:
  -r <git_remote>       Specify the GitHub repository remote name (default: origin)
  -b <git_branch>       Specify the GitHub repository branch name (default: real-test-1)
  -m                    Manually run coordinator.py instead of using coordinator.service
  -h, --help            Display this help message

Examples:
  $SCRIPT_NAME
  $SCRIPT_NAME -r upstream -b develop
  $SCRIPT_NAME -m
EOF
    exit 1
}

# Function to handle script termination and cleanup
cleanup() {
    echo ""
    echo "Received interrupt signal. Terminating background processes..."
    if [[ -n "${simulation_pid:-}" ]]; then
        kill "$simulation_pid" 2>/dev/null || true
    fi
    if [ "${RUN_MANUALLY:-false}" = true ] && [[ -n "${coordinator_pid:-}" ]]; then
        kill "$coordinator_pid" 2>/dev/null || true
    fi
    if [ "${USE_GLOBAL_PYTHON:-false}" = false ]; then
        deactivate 2>/dev/null || true
    fi
    exit 0
}

# Function to install 'bc' if not present
install_bc() {
    echo "'bc' is not installed. Installing 'bc'..."
    if ! sudo apt-get update && sudo apt-get install -y bc; then
        echo "ERROR: Failed to install 'bc'. Please install it manually."
        exit 1
    fi
}

# Function to parse script arguments
parse_args() {
    RUN_MANUALLY=false
    while [[ $# -gt 0 ]]; do
        case $1 in
            -r)
                if [[ -n "${2:-}" && ! $2 =~ ^- ]]; then
                    GIT_REMOTE="$2"
                    shift 2
                else
                    echo "ERROR: -r requires a non-empty option argument."
                    usage
                fi
                ;;
            -b)
                if [[ -n "${2:-}" && ! $2 =~ ^- ]]; then
                    GIT_BRANCH="$2"
                    shift 2
                else
                    echo "ERROR: -b requires a non-empty option argument."
                    usage
                fi
                ;;
            -m)
                RUN_MANUALLY=true
                shift
                ;;
            -h|--help)
                usage
                ;;
            *)
                echo "ERROR: Unknown option: $1"
                usage
                ;;
        esac
    done
}

# Function to check and install dependencies
check_dependencies() {
    if ! command -v bc &> /dev/null; then
        install_bc
    fi
    if ! command -v git &> /dev/null; then
        echo "'git' is not installed. Installing 'git'..."
        if ! sudo apt-get update && sudo apt-get install -y git; then
            echo "ERROR: Failed to install 'git'. Please install it manually."
            exit 1
        fi
    fi
}

# Function to wait for the .hwID file
wait_for_hwid() {
    echo "Waiting for .hwID file in $BASE_DIR..."
    while ! ls "$BASE_DIR"/*.hwID &> /dev/null; do
        echo "  - .hwID file not found. Retrying in 1 second..."
        sleep 1
    done
    HWID=$(basename "$BASE_DIR"/*.hwID .hwID)
    echo "Found .hwID file: $HWID.hwID"
    
    # Validate that HWID is a positive integer
    if ! [[ "$HWID" =~ ^[1-9][0-9]*$ ]]; then
        echo "ERROR: Extracted HWID '$HWID' is not a positive integer."
        exit 1
    fi
}

# Function to update the repository
update_repository() {
    echo "Navigating to $BASE_DIR..."
    cd "$BASE_DIR"

    echo "Stashing any local changes..."
    git stash

    echo "Setting Git remote to $GIT_REMOTE..."
    git remote set-url "$GIT_REMOTE" "$GITHUB_REPO_URL" || true

    echo "Fetching latest changes from $GIT_REMOTE/$GIT_BRANCH..."
    if ! git fetch "$GIT_REMOTE" "$GIT_BRANCH"; then
        echo "ERROR: Failed to fetch from $GIT_REMOTE/$GIT_BRANCH."
        exit 1
    fi

    echo "Checking out branch $GIT_BRANCH..."
    if ! git checkout "$GIT_BRANCH"; then
        echo "ERROR: Failed to checkout branch $GIT_BRANCH."
        exit 1
    fi

    echo "Pulling latest changes from $GIT_REMOTE/$GIT_BRANCH..."
    if ! git pull "$GIT_REMOTE" "$GIT_BRANCH"; then
        echo "ERROR: Failed to pull latest changes from $GIT_REMOTE/$GIT_BRANCH."
        exit 1
    fi
}

# Function to set up Python environment
setup_python_env() {
    if [ "$USE_GLOBAL_PYTHON" = false ]; then
        if [ ! -d "$VENV_DIR" ]; then
            echo "Creating a Python virtual environment at $VENV_DIR..."
            python3 -m venv "$VENV_DIR"
        fi

        echo "Activating the virtual environment..."
        source "$VENV_DIR/bin/activate"

        echo "Installing Python requirements..."
        if ! pip install --upgrade pip && pip install -r requirements.txt; then
            echo "ERROR: Failed to install Python requirements."
            exit 1
        fi
    else
        echo "Using global Python installation."
    fi
}

# Function to set MAV_SYS_ID
set_mav_sys_id() {
    echo "Setting MAV_SYS_ID using set_sys_id.py..."
    if ! python3 "$BASE_DIR/multiple_sitl/set_sys_id.py"; then
        echo "ERROR: Failed to set MAV_SYS_ID."
        exit 1
    fi
}

# Function to read offsets from config.csv
read_offsets() {
    echo "Reading offsets from $CONFIG_FILE for HWID: $HWID..."

    OFFSET_X=0
    OFFSET_Y=0

    if [ ! -f "$CONFIG_FILE" ]; then
        echo "WARNING: Configuration file $CONFIG_FILE does not exist. Using default offsets (0,0)."
        return
    fi

    while IFS=, read -r hw_id pos_id x y ip mavlink_port debug_port gcs_ip; do
        if [ "$hw_id" == "$HWID" ]; then
            OFFSET_X="$x"
            OFFSET_Y="$y"
            echo "Found offsets - X: $OFFSET_X, Y: $OFFSET_Y"
            return
        fi
    done < "$CONFIG_FILE"

    echo "WARNING: HWID $HWID not found in $CONFIG_FILE. Using default offsets (0,0)."
}

# Function to calculate new geographic coordinates
calculate_new_coordinates() {
    echo "Calculating new geographic coordinates based on offsets..."

    # Convert latitude from degrees to radians
    LAT_RAD=$(echo "scale=10; $DEFAULT_LAT * (4*a(1)/180)" | bc -l)

    # Calculate meters per degree longitude at the given latitude
    M_PER_DEGREE=$(echo "scale=10; 111320 * c($LAT_RAD)" | bc -l)

    # Calculate new latitude and longitude
    NEW_LAT=$(echo "scale=10; $DEFAULT_LAT + $OFFSET_X / 111320" | bc -l)
    NEW_LON=$(echo "scale=10; $DEFAULT_LON + $OFFSET_Y / $M_PER_DEGREE" | bc -l)

    echo "New Coordinates - Latitude: $NEW_LAT, Longitude: $NEW_LON"
}

# Function to export environment variables for PX4 SITL
export_env_vars() {
    echo "Exporting environment variables for PX4 SITL..."
    export PX4_HOME_LAT="$NEW_LAT"
    export PX4_HOME_LON="$NEW_LON"
    export PX4_HOME_ALT="$DEFAULT_ALT"
    export MAV_SYS_ID="$HWID"
    echo "MAV_SYS_ID set to $MAV_SYS_ID"
}

# Function to determine the simulation command
determine_simulation_command() {
    case $SIMULATION_MODE in
        g)
            SIMULATION_COMMAND="make px4_sitl gazebo"
            echo "Simulation Mode: Graphics Enabled (Gazebo)"
            ;;
        j)
            SIMULATION_COMMAND="make px4_sitl jmavsim"
            echo "Simulation Mode: Using jmavsim"
            ;;
        h)
            SIMULATION_COMMAND="HEADLESS=1 make px4_sitl gazebo"
            echo "Simulation Mode: Headless (Graphics Disabled)"
            ;;
        *)
            echo "Invalid simulation mode: $SIMULATION_MODE. Defaulting to headless mode."
            SIMULATION_COMMAND="HEADLESS=1 make px4_sitl gazebo"
            ;;
    esac

    echo "Simulation Command: $SIMULATION_COMMAND"
}

# Function to start SITL simulation
start_simulation() {
    echo "Starting SITL simulation..."
    cd "$PX4_DIR"

    # Export instance identifier
    export px4_instance="${HWID}-1"

    # Handle headless mode if applicable
    if [[ "$SIMULATION_COMMAND" == HEADLESS* ]]; then
        export HEADLESS=1
    fi

    # Execute the simulation command in the background
    $SIMULATION_COMMAND &
    simulation_pid=$!
    echo "SITL simulation started with PID: $simulation_pid"
}

# Function to manually run coordinator.py
run_coordinator_manually() {
    echo "Manually starting coordinator.py..."
    cd "$BASE_DIR"
    python3 "$BASE_DIR/coordinator.py" &
    coordinator_pid=$!
    echo "coordinator.py started with PID: $coordinator_pid"
}

# Function to enable and start coordinator.service
start_coordinator_service() {
    echo "Enabling and starting coordinator.service..."
    if ! systemctl enable coordinator.service; then
        echo "ERROR: Failed to enable coordinator.service."
        exit 1
    fi

    if ! systemctl start coordinator.service; then
        echo "ERROR: Failed to start coordinator.service."
        exit 1
    fi

    echo "coordinator.service is enabled and running."
}

# =============================================================================
# Main Script Execution
# =============================================================================

# Parse script arguments
parse_args "$@"

# Trap SIGINT and SIGTERM to execute cleanup
trap 'cleanup' INT TERM

echo "=============================================="
echo " Welcome to the SITL Startup Script!"
echo "=============================================="
echo ""
echo "Configuration:"
echo "  Git Remote: $GIT_REMOTE"
echo "  Git Branch: $GIT_BRANCH"
echo "  Use Global Python: $USE_GLOBAL_PYTHON"
echo "  Base Directory: $BASE_DIR"
echo "  Simulation Mode: ${SIMULATION_MODE:-h}"
echo "  Run Coordinator Manually: $RUN_MANUALLY"
echo ""

# Check for necessary dependencies
check_dependencies

# Wait for the .hwID file
wait_for_hwid

# Update the repository
update_repository

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

# Determine simulation mode from remaining arguments or default to headless
if [ "$#" -ge 0 ]; then
    # If simulation mode is provided as an argument after options
    SIMULATION_MODE="${SIMULATION_MODE:-h}"
else
    SIMULATION_MODE="h"  # Default to headless mode
fi

determine_simulation_command

# Start SITL simulation
start_simulation

# Start coordinator process based on the flag
if [ "$RUN_MANUALLY" = true ]; then
    run_coordinator_manually
else
    start_coordinator_service
fi

echo ""
echo "=============================================="
echo "All processes have been initialized."
if [ "$RUN_MANUALLY" = true ]; then
    echo "coordinator.py is running manually."
else
    echo "coordinator.service is running."
fi
echo "Press Ctrl+C to terminate the simulation."
echo "=============================================="
echo ""

# Wait for the simulation process to complete
wait "$simulation_pid"

# Keep the script running to maintain the environment
# The coordinator.service is managed by systemd, so no need to keep the script running
# However, if you want to keep the script alive when running manually, uncomment the following lines:
if [ "$RUN_MANUALLY" = true ]; then
    echo "Waiting for coordinator.py process to complete..."
    wait "$coordinator_pid"
fi

# Exit successfully
exit 0
