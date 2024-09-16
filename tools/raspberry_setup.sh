#!/bin/bash

# =============================================================================
# raspberry_setup.sh
#
# A script to set up a drone within a Drone Swarm System. Supports both
# interactive and non-interactive modes, allowing users to provide inputs via
# command-line arguments or interactively through prompts. Specific setup steps
# can be skipped using appropriate flags.
#
# =============================================================================

# Enable strict error handling
set -euo pipefail
IFS=$'\n\t'

# =============================================================================
# Default Values
# =============================================================================
DEFAULT_BRANCH="real-test-1"
DEFAULT_MANAGEMENT_URL="https://nb1.joomtalk.ir"

# =============================================================================
# Flags to Skip Steps (default: false)
# =============================================================================
SKIP_NETBIRD=false
SKIP_MAVSDK=false
SKIP_GPIO=false
SKIP_SUDOERS=false

# =============================================================================
# Function: Display Help Message
# =============================================================================
usage() {
    cat << EOF
Usage: $(basename "$0") [OPTIONS]

Options:
  -b, --branch NAME           Specify Git branch name (default: real-test-1)
  -d, --drone-id ID           Specify Drone ID (e.g., 1, 2) [Required]
  -k, --netbird-key KEY       Specify Netbird Setup Key [Required unless --skip-netbird is used]
  -u, --management-url URL    Specify Netbird Management URL (default: https://nb1.joomtalk.ir)
      --skip-netbird          Skip Netbird setup steps
      --skip-mavsdk           Skip MAVSDK server setup
      --skip-gpio             Skip GPIO configuration
      --skip-sudoers          Skip sudoers configuration
  -h, --help                  Display this help and exit

Examples:
  # Interactive mode (prompts for all required inputs)
  ./raspberry_setup.sh

  # Non-interactive mode with all required arguments
  ./raspberry_setup.sh -b develop -d 1 -k myNetbirdKey123 -u https://custom.netbird.url

  # Non-interactive mode with default branch and management URL
  ./raspberry_setup.sh -d 2 -k anotherNetbirdKey456

  # Non-interactive mode with skipped Netbird setup
  ./raspberry_setup.sh -d 3 -b feature-branch --skip-netbird

  # Non-interactive mode with multiple steps skipped
  ./raspberry_setup.sh -d 4 --skip-netbird --skip-mavsdk --skip-gpio --skip-sudoers

  # Display help message
  ./raspberry_setup.sh -h
EOF
}

# =============================================================================
# Function: Parse Command-Line Arguments
# =============================================================================
parse_args() {
    # Use getopt for parsing both short and long options
    PARSED_ARGS=$(getopt -o b:d:k:u:h --long branch:,drone-id:,netbird-key:,management-url:,skip-netbird,skip-mavsdk,skip-gpio,skip-sudoers,help -- "$@")
    if [[ $? -ne 0 ]]; then
        usage
        exit 1
    fi

    eval set -- "$PARSED_ARGS"

    while true; do
        case "$1" in
            -b|--branch)
                BRANCH_NAME="$2"
                shift 2
                ;;
            -d|--drone-id)
                DRONE_ID="$2"
                shift 2
                ;;
            -k|--netbird-key)
                NETBIRD_KEY="$2"
                shift 2
                ;;
            -u|--management-url)
                MANAGEMENT_URL="$2"
                shift 2
                ;;
            --skip-netbird)
                SKIP_NETBIRD=true
                shift
                ;;
            --skip-mavsdk)
                SKIP_MAVSDK=true
                shift
                ;;
            --skip-gpio)
                SKIP_GPIO=true
                shift
                ;;
            --skip-sudoers)
                SKIP_SUDOERS=true
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            --)
                shift
                break
                ;;
            *)
                echo "Unexpected option: $1"
                usage
                exit 1
                ;;
        esac
    done
}

# =============================================================================
# Function: Prompt for Input if Variable is Empty
# =============================================================================
prompt_if_empty() {
    local var_name=$1
    local prompt_message=$2
    local hide_input=${3:-false}

    if [[ -z "${!var_name:-}" ]]; then
        if [[ "$hide_input" == true ]]; then
            read -s -p "$prompt_message: " input
            echo
        else
            read -p "$prompt_message: " input
        fi
        eval "$var_name=\$input"
    fi
}

# =============================================================================
# Function: Validate Inputs
# =============================================================================
validate_inputs() {
    if [[ -z "$DRONE_ID" ]]; then
        echo "Error: Drone ID is required."
        usage
        exit 1
    fi

    if [[ "$SKIP_NETBIRD" == false && -z "${NETBIRD_KEY:-}" ]]; then
        echo "Error: Netbird Setup Key is required unless --skip-netbird is used."
        usage
        exit 1
    fi
}

# =============================================================================
# Function: Setup Git Repository
# =============================================================================
setup_git() {
    echo "Stashing any local changes and updating from Git repository..."
    git stash push --include-untracked
    git checkout "${BRANCH_NAME:-$DEFAULT_BRANCH}"
    git pull origin "${BRANCH_NAME:-$DEFAULT_BRANCH}"

    # Calculate new hash and check if script has changed
    new_hash=$(md5sum "$SCRIPT_PATH" | cut -d ' ' -f 1)
    if [[ "$INITIAL_HASH" != "$new_hash" ]]; then
        echo "Script has been updated. Restarting with the latest version..."
        exec bash "$SCRIPT_PATH" "$@"
    fi
}

# =============================================================================
# Function: Setup Netbird
# =============================================================================
setup_netbird() {
    echo "Disconnecting from Netbird..."
    netbird down

    echo "Clearing Netbird configurations..."
    sudo rm -rf /etc/netbird/
}

# =============================================================================
# Function: Configure Hostname
# =============================================================================
configure_hostname() {
    echo "Configuring hostname to 'drone$DRONE_ID'..."
    echo "drone$DRONE_ID" | sudo tee /etc/hostname > /dev/null
    sudo sed -i "s/.*127.0.1.1.*/127.0.1.1\tdrone$DRONE_ID/" /etc/hosts

    echo "Reloading hostname service to apply changes immediately..."
    sudo hostnamectl set-hostname "drone$DRONE_ID"
    sudo systemctl restart systemd-logind

    echo "Restarting avahi-daemon to apply hostname changes..."
    sudo systemctl restart avahi-daemon
}

# =============================================================================
# Function: Reconnect to Netbird
# =============================================================================
reconnect_netbird() {
    echo "Reconnecting to Netbird with new settings..."
    netbird up --management-url "$MANAGEMENT_URL" --setup-key "$NETBIRD_KEY"
    echo "Netbird reconnected with new hostname 'drone$DRONE_ID'."
    unset NETBIRD_KEY
}

# =============================================================================
# Function: Configure Sudoers
# =============================================================================
configure_sudoers() {
    sudoers_file="/etc/sudoers.d/mavsdk_sync_time"
    sync_time_script="$HOME/mavsdk_drone_show/tools/sync_time_linux.sh"
    sudoers_entry="droneshow ALL=(ALL) NOPASSWD: $sync_time_script"

    echo "Ensuring sudo permissions for time synchronization script..."
    if [[ ! -f "$sudoers_file" ]]; then
        echo "$sudoers_entry" | sudo tee "$sudoers_file" > /dev/null
        sudo chmod 440 "$sudoers_file"
        echo "Sudoers entry added for $sync_time_script."
    else
        echo "Sudoers entry already exists."
    fi
}

# =============================================================================
# Function: Configure GPIO Access
# =============================================================================
configure_gpio() {
    echo "Ensuring droneshow user has direct access to GPIO pins..."
    sudo usermod -aG gpio droneshow
}

# =============================================================================
# Function: Setup Coordinator Service
# =============================================================================
setup_coordinator_service() {
    echo "Setting up the Drone Swarm System Coordinator service..."
    sudo bash "$HOME/mavsdk_drone_show/tools/update_service.sh"
}

# =============================================================================
# Function: Check and Download MAVSDK Server
# =============================================================================
check_download_mavsdk() {
    echo "Checking for MAVSDK server binary..."
    if [[ ! -f "$HOME/mavsdk_drone_show/mavsdk_server" ]]; then
        echo "MAVSDK server binary not found, downloading..."
        if [[ -f "$HOME/mavsdk_drone_show/tools/download_mavsdk_server.sh" ]]; then
            sudo bash "$HOME/mavsdk_drone_show/tools/download_mavsdk_server.sh"
            echo "Note: You might need to manually update the download URL in the 'download_mavsdk_server.sh' script to match the latest MAVSDK server version."
        else
            echo "Error: MAVSDK server download script not found."
            exit 1
        fi
    else
        echo "MAVSDK server binary already present, no need to download."
    fi
}

# =============================================================================
# Main Script Execution
# =============================================================================

# Parse command-line arguments
parse_args "$@"

# Prompt for inputs if not provided via arguments
prompt_if_empty DRONE_ID "Enter Drone ID (e.g., 1, 2)"
echo "You entered Drone ID: $DRONE_ID"

if [[ "$SKIP_NETBIRD" == false ]]; then
    prompt_if_empty NETBIRD_KEY "Enter Netbird Setup Key" true
fi

if [[ -z "${BRANCH_NAME:-}" ]]; then
    read -p "Enter the Git branch name you want to use ($DEFAULT_BRANCH by default): " user_branch
    BRANCH_NAME="${user_branch:-$DEFAULT_BRANCH}"
fi

if [[ -z "${MANAGEMENT_URL:-}" && "$SKIP_NETBIRD" == false ]]; then
    read -p "Enter Netbird Management URL (Press enter for default: $DEFAULT_MANAGEMENT_URL): " user_url
    MANAGEMENT_URL="${user_url:-$DEFAULT_MANAGEMENT_URL}"
fi

# Display summary of inputs
echo
echo "Configuration Summary:"
echo "  Git Branch Name        : ${BRANCH_NAME:-$DEFAULT_BRANCH}"
echo "  Drone ID               : $DRONE_ID"
if [[ "$SKIP_NETBIRD" == false ]]; then
    echo "  Netbird Setup Key      : [HIDDEN]"
    echo "  Netbird Management URL : ${MANAGEMENT_URL:-$DEFAULT_MANAGEMENT_URL}"
fi
echo "  Skip Netbird Setup     : $SKIP_NETBIRD"
echo "  Skip MAVSDK Setup      : $SKIP_MAVSDK"
echo "  Skip GPIO Configuration: $SKIP_GPIO"
echo "  Skip Sudoers Config    : $SKIP_SUDOERS"
echo

# Validate inputs
validate_inputs

# Define the script path
SCRIPT_PATH="$HOME/mavsdk_drone_show/tools/raspberry_setup.sh"

# Get absolute path to avoid issues with 'cd' commands later
SCRIPT_PATH=$(realpath "$SCRIPT_PATH")

# Calculate initial hash of the script
INITIAL_HASH=$(md5sum "$SCRIPT_PATH" | cut -d ' ' -f 1)

# Navigate to the repository directory
cd "$(dirname "$SCRIPT_PATH")"

# Setup Git Repository
setup_git "$@"

echo "Starting setup for the Drone Swarm System..."
echo "NOTE: If this Drone ID has been used before, running this setup might create a duplicate entry in Netbird."

# Proceed with Netbird setup unless skipped
if [[ "$SKIP_NETBIRD" == false ]]; then
    setup_netbird
fi

# Handle Hardware ID (HWID) File
hwid_file="$HOME/mavsdk_drone_show/${DRONE_ID}.hwID"
if [[ -f "$hwid_file" ]]; then
    echo "HWID file exists - updating..."
    rm "$hwid_file"
fi
touch "$hwid_file"
echo "Hardware ID file created/updated at: $hwid_file"

# Configure Hostname
configure_hostname

# Reconnect to Netbird unless skipped
if [[ "$SKIP_NETBIRD" == false ]]; then
    reconnect_netbird
fi

# Configure Sudoers unless skipped
if [[ "$SKIP_SUDOERS" == false ]]; then
    configure_sudoers
fi

# Configure GPIO Access unless skipped
if [[ "$SKIP_GPIO" == false ]]; then
    configure_gpio
fi

# Setup Coordinator Service
setup_coordinator_service

# Check and Download MAVSDK Server unless skipped
if [[ "$SKIP_MAVSDK" == false ]]; then
    check_download_mavsdk
fi

echo "Setup complete! The system is now configured for Drone ID $DRONE_ID."
