#!/bin/bash

# =============================================================================
# raspberry_setup.sh
#
# A script to set up a drone within a Drone Swarm System.
# Supports both interactive and non-interactive modes, allowing users to provide
# inputs via command-line arguments or interactively through prompts.
# Specific setup steps can be skipped using appropriate flags or during runtime prompts.
#
# =============================================================================

# Enable strict error handling
set -euo pipefail
IFS=$'\n\t'

# =============================================================================
# REPOSITORY CONFIGURATION: Environment Variable Support (MDS v3.1+)
# =============================================================================
# This hardware setup script now supports environment variable override for
# advanced deployments while maintaining 100% backward compatibility.
#
# FOR NORMAL USERS (99%):
#   - No action required - defaults work identically to previous versions
#   - Uses: git@github.com:alireza787b/mavsdk_drone_show.git@main-candidate
#   - Simply run: bash raspberry_setup.sh [options]
#
# FOR ADVANCED USERS (Custom Forks):
#   - Set environment variables before running this script:
#     export MDS_REPO_URL="git@github.com:yourcompany/your-fork.git"
#     export MDS_BRANCH="your-production-branch"
#   - Hardware will be deployed with your custom repository configuration
#
# EXAMPLES:
#   # Normal usage (no environment variables):
#   bash raspberry_setup.sh -d 1
#
#   # Advanced usage with custom repository:
#   export MDS_REPO_URL="git@github.com:company/fork.git"
#   export MDS_BRANCH="production"
#   bash raspberry_setup.sh -d 5 -k "your_netbird_key"
#
# ENVIRONMENT VARIABLES SUPPORTED:
#   MDS_REPO_URL  - Git repository URL (SSH or HTTPS format)
#   MDS_BRANCH    - Git branch name to checkout and use
#
# NOTE: Command line arguments --repo-url and --branch will override env vars
# =============================================================================

# Default Values (with environment variable override support)
DEFAULT_BRANCH="${MDS_BRANCH:-main}"
DEFAULT_MANAGEMENT_URL="https://nb1.joomtalk.ir"
DEFAULT_REPO_URL="${MDS_REPO_URL:-git@github.com:the-mak-00/mavsdk_drone_show.git}"
DEFAULT_SSH_KEY_PATH="$HOME/.ssh/id_rsa_git_deploy"
REPO_DIR="$HOME/mavsdk_drone_show"

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
  -b, --branch NAME           Specify Git branch name (default: main)
  -d, --drone-id ID           Specify Drone ID (e.g., 1, 2) [Required]
  -k, --netbird-key KEY       Specify Netbird Setup Key [Required unless --skip-netbird is used]
  -u, --management-url URL    Specify Netbird Management URL (default: https://nb1.joomtalk.ir)
      --repo-url URL          Specify Git repository URL (default: git@github.com:the-mak-00/mavsdk_drone_show.git)
      --ssh-key-path PATH     Specify SSH private key path for GitHub access (default: ~/.ssh/id_rsa_git_deploy)
      --skip-netbird          Skip Netbird setup steps
      --skip-mavsdk           Skip MAVSDK server setup
      --skip-gpio             Skip GPIO configuration
      --skip-sudoers          Skip sudoers configuration
  -h, --help                  Display this help and exit

Examples:
  # Interactive mode (prompts for all required inputs)
  ./raspberry_setup.sh

  # Non-interactive mode with all required arguments
  ./raspberry_setup.sh -b develop -d 1 -k myNetbirdKey123 -u https://custom.netbird.url --repo-url git@github.com:user/repo.git

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
    PARSED_ARGS=$(getopt -o b:d:k:u:h --long branch:,drone-id:,netbird-key:,management-url:,repo-url:,ssh-key-path:,skip-netbird,skip-mavsdk,skip-gpio,skip-sudoers,help -- "$@")
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
            --repo-url)
                REPO_URL="$2"
                shift 2
                ;;
            --ssh-key-path)
                SSH_KEY_PATH="$2"
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

    # Validate REPO_URL
    if [[ -z "${REPO_URL:-}" ]]; then
        REPO_URL="$DEFAULT_REPO_URL"
    fi

    # Validate SSH_KEY_PATH
    if [[ -z "${SSH_KEY_PATH:-}" ]]; then
        SSH_KEY_PATH="$DEFAULT_SSH_KEY_PATH"
    fi
}

# =============================================================================
# Function: Setup SSH Key for GitHub Access
# =============================================================================
setup_ssh_key_for_git() {
    echo "Setting up SSH key for GitHub access..."

    # Use provided SSH key path or default
    SSH_KEY_PATH="${SSH_KEY_PATH:-$DEFAULT_SSH_KEY_PATH}"

    # Check if SSH key already exists
    if [[ -f "$SSH_KEY_PATH" ]]; then
        echo "Using existing SSH key at $SSH_KEY_PATH"
    else
        # Generate a new SSH key pair without a passphrase
        echo "No SSH key found at $SSH_KEY_PATH"
        echo "Generating a new SSH key pair..."
        ssh-keygen -t rsa -b 4096 -f "$SSH_KEY_PATH" -N "" -C "drone$DRONE_ID@$(hostname)"
        echo "SSH key generated at $SSH_KEY_PATH"
    fi

    # Ensure correct permissions
    chmod 600 "$SSH_KEY_PATH"

    # Configure SSH to use the key for GitHub
    SSH_CONFIG_FILE="$HOME/.ssh/config"
    GITHUB_HOST="github.com"

    # Backup existing SSH config if it exists
    if [[ -f "$SSH_CONFIG_FILE" ]]; then
        cp "$SSH_CONFIG_FILE" "$SSH_CONFIG_FILE.bak"
        echo "Existing SSH config backed up to $SSH_CONFIG_FILE.bak"
    fi

    # Remove existing SSH config for GitHub to avoid conflicts
    sed -i '/Host github.com/,+5d' "$SSH_CONFIG_FILE" 2>/dev/null || true

    # Add new SSH config for GitHub
    mkdir -p "$(dirname "$SSH_CONFIG_FILE")"
    cat >> "$SSH_CONFIG_FILE" << EOF

Host github.com
    HostName github.com
    User git
    IdentityFile $SSH_KEY_PATH
    IdentitiesOnly yes
    StrictHostKeyChecking no
EOF
    echo "SSH configuration updated to use $SSH_KEY_PATH for $GITHUB_HOST"

    # Display public key and instruct user to add it to GitHub
    PUBLIC_KEY=$(cat "${SSH_KEY_PATH}.pub")
    echo
    echo "======================================================================="
    echo "Please add the following SSH public key as a deploy key to your GitHub repository:"
    echo
    echo "$PUBLIC_KEY"
    echo
    echo "Instructions:"
    echo "1. Copy the above SSH public key."
    echo "2. Go to your GitHub repository settings."
    echo "3. Navigate to 'Deploy keys' section."
    echo "4. Click 'Add deploy key'."
    echo "5. Paste the SSH public key, set a meaningful title (e.g., 'Drone $DRONE_ID Key'), and allow write access if necessary."
    echo "6. Save the deploy key."
    echo "======================================================================="
    echo

    # Wait for user confirmation
    read -p "Press Enter after you have added the SSH key to your GitHub repository..."

    # Test SSH connection to GitHub
    echo "Testing SSH connection to GitHub..."
    SSH_OUTPUT=$(ssh -T -i "$SSH_KEY_PATH" -o "StrictHostKeyChecking=no" -o "IdentitiesOnly=yes" git@github.com 2>&1 || true)

    if echo "$SSH_OUTPUT" | grep -q "successfully authenticated"; then
        echo "SSH connection to GitHub successful."
    elif echo "$SSH_OUTPUT" | grep -q "Hi"; then
        echo "SSH connection to GitHub successful."
    else
        echo "Error: SSH connection to GitHub failed. Please ensure your SSH key is added as a deploy key to your GitHub repository."
        echo "SSH Output:"
        echo "$SSH_OUTPUT"
        exit 1
    fi
}

# =============================================================================
# Function: Setup Git Repository
# =============================================================================
setup_git() {
    echo "Setting up Git repository..."

    # Clone the repository if it doesn't exist
    if [[ ! -d "$REPO_DIR/.git" ]]; then
        echo "Repository directory $REPO_DIR does not exist or is not a git repository. Cloning repository..."
        rm -rf "$REPO_DIR"
        git clone "$REPO_URL" "$REPO_DIR"
    fi

    # Navigate to the repository directory
    cd "$REPO_DIR"

    # Ensure the git remote uses SSH and points to the correct repository
    git remote set-url origin "$REPO_URL"
    echo "Git remote URL set to: $REPO_URL"

    # Proceed with git operations
    echo "Stashing any local changes..."
    git stash push --include-untracked || true

    echo "Checking out branch ${BRANCH_NAME:-$DEFAULT_BRANCH}..."
    git fetch origin
    git checkout "${BRANCH_NAME:-$DEFAULT_BRANCH}"
    git pull origin "${BRANCH_NAME:-$DEFAULT_BRANCH}"

    # Calculate new hash and check if script has changed
    SCRIPT_PATH="$REPO_DIR/tools/$(basename "$0")"
    new_hash=$(md5sum "$SCRIPT_PATH" | cut -d ' ' -f 1)
    if [[ "$INITIAL_HASH" != "$new_hash" ]]; then
        echo "Script has been updated. Restarting with the latest version..."
        exec bash "$SCRIPT_PATH" "$@"
    fi
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
# Function: Configure Sudoers
# =============================================================================
configure_sudoers() {
    sudoers_file="/etc/sudoers.d/mavsdk_sync_time"
    sync_time_script="$REPO_DIR/tools/sync_time_linux.sh"
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
# Function: Ensure Polkit Rule for Reboot Exists
# =============================================================================
configure_polkit_for_reboot() {
    local polkit_rule_path="/etc/polkit-1/rules.d/50-droneshow-reboot.rules"
    local expected_rule_content="polkit.addRule(function(action, subject) {
    if ((action.id == \"org.freedesktop.login1.reboot\" ||
         action.id == \"org.freedesktop.login1.power-off\" ||
         action.id == \"org.freedesktop.login1.hibernate\" ||
         action.id == \"org.freedesktop.login1.suspend\") &&
        subject.isInGroup(\"droneshow\")) {
        return polkit.Result.YES;
    }
});"

    # Check if the Polkit rule file exists
    if [[ -f "$polkit_rule_path" ]]; then
        echo "Polkit rule file exists at $polkit_rule_path. Checking contents..."

        # Check if the rule for the 'droneshow' user exists in the file
        if grep -q "subject.isInGroup(\"droneshow\")" "$polkit_rule_path"; then
            echo "Polkit rule for 'droneshow' reboot already exists. No changes needed."
        else
            echo "Polkit rule file exists, but the 'droneshow' rule is missing. Updating the rule..."
            add_polkit_reboot_rule "$polkit_rule_path" "$expected_rule_content"
        fi
    else
        echo "Polkit rule file does not exist. Creating it with the necessary reboot rule for 'droneshow'..."
        add_polkit_reboot_rule "$polkit_rule_path" "$expected_rule_content"
    fi
}

# =============================================================================
# Function: Add or Update Polkit Rule for Reboot
# =============================================================================
add_polkit_reboot_rule() {
    local polkit_rule_path="$1"
    local rule_content="$2"

    # Create or update the Polkit rule file with the expected content
    sudo tee "$polkit_rule_path" > /dev/null << EOF
$rule_content
EOF

    # Set correct permissions
    sudo chmod 644 "$polkit_rule_path"
    echo "Polkit rule added or updated successfully at $polkit_rule_path."
}

# =============================================================================
# Function: Configure GPIO Access
# =============================================================================
configure_gpio() {
    echo "Ensuring droneshow user has direct access to GPIO pins..."
    sudo usermod -aG gpio droneshow
}


# =============================================================================
# Function: Setup led_indicator Service
# =============================================================================
setup_led_indicator_service() {
    echo "Setting up the led_indicator System Coordinator service..."
    sudo bash "$REPO_DIR/tools/led_indicator/install_led_indicator.sh"
}

# =============================================================================
# Function: Setup git_sync_mds Service
# =============================================================================
setup_git_sync_mds_service() {
    echo "Setting up the git_sync_mds System Coordinator service..."
    sudo bash "$REPO_DIR/tools/git_sync_mds/install_git_sync_mds.sh"
}

# =============================================================================
# Function: Setup Wifi-Manager Service
# =============================================================================
setup_wifi_manager_service() {
    echo "Setting up the Wifi-Manager System Coordinator service..."
    sudo bash "$REPO_DIR/tools/wifi-manager/update_wifi-manager_service.sh"
}

# =============================================================================
# Function: Setup Coordinator Service
# =============================================================================
setup_coordinator_service() {
    echo "Setting up the Drone Swarm System Coordinator service..."
    sudo bash "$REPO_DIR/tools/update_service.sh"
}

# =============================================================================
# Function: Check and Download MAVSDK Server
# =============================================================================
check_download_mavsdk() {
    echo "Checking for MAVSDK server binary..."
    if [[ ! -f "$REPO_DIR/mavsdk_server" ]]; then
        echo "MAVSDK server binary not found, downloading..."
        if [[ -f "$REPO_DIR/tools/download_mavsdk_server.sh" ]]; then
            sudo bash "$REPO_DIR/tools/download_mavsdk_server.sh"
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
# Function: Setup Netbird (At the End)
# =============================================================================
setup_netbird() {
    echo
    echo "Netbird setup will proceed now."
    echo "Warning: This step may disrupt your network connection, including SSH."
    echo "It's recommended to run this script directly from the device or ensure you have alternative access methods."
    read -p "Do you want to proceed with Netbird setup? (y/n): " proceed_netbird
    if [[ "$proceed_netbird" != "y" && "$proceed_netbird" != "Y" ]]; then
        echo "Skipping Netbird setup as per your choice."
        SKIP_NETBIRD=true
        return
    fi

    echo "Proceeding with Netbird setup..."

    echo "Disconnecting from Netbird..."
    netbird down || true  # Ignore errors if Netbird is not running

    echo "Clearing Netbird configurations..."
    sudo rm -rf /etc/netbird/

    echo "Reconnecting to Netbird with new settings..."
    netbird up --management-url "$MANAGEMENT_URL" --setup-key "$NETBIRD_KEY"
    echo "Netbird reconnected with new hostname 'drone$DRONE_ID'."
    unset NETBIRD_KEY

    echo "Netbird setup complete."
}

# =============================================================================
# NEW FUNCTION: Setup Python Virtual Environment
# =============================================================================
setup_python_venv() {
    echo
    echo "------------------------------------------------------"
    echo "Setting up Python virtual environment in $REPO_DIR..."
    echo "------------------------------------------------------"

    # Check if python3 is available
    if ! command -v python3 &> /dev/null; then
        echo "Python3 not found. Installing python3..."
        sudo apt-get update
        sudo apt-get install -y python3
    fi

    # Check if python3-venv is installed
    if ! dpkg -s python3-venv &> /dev/null; then
        echo "python3-venv not installed. Installing it..."
        sudo apt-get update
        sudo apt-get install -y python3-venv
    fi
    # Check if python3-pip is installed
    if ! dpkg -s python3-pip &> /dev/null; then
        echo "python3-pip not installed. Installing it..."
        sudo apt-get update
        sudo apt-get install -y python3-pip
    fi

    # Check if git-repair is installed
    if ! dpkg -s git-repair &> /dev/null; then
        echo "git-repair not installed. Installing it..."
        sudo apt-get update
        sudo apt-get install -y git-repair
    fi

    # Move to repository directory (already cloned by setup_git)
    cd "$REPO_DIR"

    # Check if venv folder exists
    if [[ -d "venv" ]]; then
        echo "Existing virtual environment detected. Activating..."
    else
        echo "No existing 'venv' found. Creating a new virtual environment..."
        python3 -m venv venv
    fi

    echo "Activating the virtual environment..."
    # shellcheck disable=SC1091
    source venv/bin/activate

    echo "Upgrading pip and installing required packages..."
    pip install --upgrade pip

    #temporary disable hash check so if restore from backup wont fail...

    if [[ -f "requirements.txt" ]]; then
        echo "Installing from requirements.txt..."
        pip install --no-deps -r requirements.txt
    else
        echo "requirements.txt not found. Skipping pip install from file."
    fi

    echo "Deactivating virtual environment to avoid conflicts with the rest of the script."
    deactivate

    echo "Python virtual environment setup is complete."
    echo
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
echo "  Repository URL         : ${REPO_URL:-$DEFAULT_REPO_URL}"
echo "  SSH Key Path           : ${SSH_KEY_PATH:-$DEFAULT_SSH_KEY_PATH}"
echo "  Skip Netbird Setup     : $SKIP_NETBIRD"
echo "  Skip MAVSDK Setup      : $SKIP_MAVSDK"
echo "  Skip GPIO Configuration: $SKIP_GPIO"
echo "  Skip Sudoers Config    : $SKIP_SUDOERS"
echo

# Validate inputs
validate_inputs

# Calculate initial hash of the script
SCRIPT_PATH="$(realpath "$0")"
INITIAL_HASH=$(md5sum "$SCRIPT_PATH" | cut -d ' ' -f 1)

echo "Starting setup for the Drone Swarm System..."

# Handle Hardware ID (HWID) File and real.mode

# Define the directory containing HWID and real.mode files
hwid_dir="$REPO_DIR"

# Define the HWID file path based on Drone ID
hwid_file="$hwid_dir/${DRONE_ID}.hwID"

# Define the real.mode file path
real_mode_file="$hwid_dir/real.mode"

# Remove any existing HWID files for this drone
find "$hwid_dir" -name "*.hwID" -type f -exec rm -f {} \;

# Create the new HWID file
touch "$hwid_file"
echo "Hardware ID file created/updated at: $hwid_file"

# Check if real.mode exists; if not, create an empty real.mode file
if [[ ! -f "$real_mode_file" ]]; then
    touch "$real_mode_file"
    echo "real.mode file did not exist and has been created at: $real_mode_file"
else
    echo "real.mode file already exists at: $real_mode_file"
fi

# Configure Hostname
configure_hostname

# Configure Sudoers unless skipped
if [[ "$SKIP_SUDOERS" == false ]]; then
    configure_sudoers
fi

# Configure GPIO Access unless skipped
if [[ "$SKIP_GPIO" == false ]]; then
    configure_gpio
fi

# Add the polkit rule for reboot if it doesn't exist
configure_polkit_for_reboot

# Set up SSH key for GitHub access
setup_ssh_key_for_git

# Set GIT_SSH_COMMAND to ensure the correct SSH key is used
export GIT_SSH_COMMAND="ssh -i $SSH_KEY_PATH -o IdentitiesOnly=yes"

# Setup Git Repository
setup_git "$@"

echo
echo "Git repository setup complete."
echo

# ----------------------------------------------------------------------
# CALL OUR NEW VIRTUAL ENV SETUP FUNCTION (if desired, no skip flag for it)
# ----------------------------------------------------------------------
setup_python_venv

# Setup led_indicator Service
setup_led_indicator_service

# Setup Wifi-Manager Service
setup_wifi_manager_service

# Setup git_sync_msc Service
setup_git_sync_mds_service

# Setup Coordinator Service
setup_coordinator_service

# Check and Download MAVSDK Server unless skipped
if [[ "$SKIP_MAVSDK" == false ]]; then
    check_download_mavsdk
fi

# Proceed with Netbird setup unless skipped
if [[ "$SKIP_NETBIRD" == false ]]; then
    setup_netbird
fi

echo "Setup Finished..."
echo "Initiating Reboot..."
sudo reboot


echo
echo "Setup complete! The system is now configured for Drone ID $DRONE_ID."
