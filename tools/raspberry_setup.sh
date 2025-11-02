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

# Error trap handler for better error reporting
error_handler() {
    local line_num=$1
    local last_command="$BASH_COMMAND"

    echo ""
    echo "╔════════════════════════════════════════════════════════════════════════════╗"
    echo "║  ✗ SETUP FAILED                                                            ║"
    echo "╚════════════════════════════════════════════════════════════════════════════╝"
    echo ""
    echo "Error Details:"
    echo "  Line Number: $line_num"
    echo "  Command: $last_command"
    if [[ -n "${CURRENT_STEP:-}" && -n "${TOTAL_STEPS:-}" ]]; then
        echo "  Failed at Step: $CURRENT_STEP/$TOTAL_STEPS"
    fi
    echo ""
    if [[ -n "${LOG_FILE:-}" ]]; then
        echo "Log File: $LOG_FILE"
    fi
    echo ""
    echo "Troubleshooting:"
    echo "  1. Review the error message above"
    echo "  2. Check Python compatibility: docs/PYTHON_COMPATIBILITY.md"
    echo "  3. Try skipping problematic steps:"
    echo "       --skip-netbird    Skip Netbird VPN setup"
    echo "       --skip-mavsdk     Skip MAVSDK download"
    echo "       --skip-gpio       Skip GPIO configuration"
    echo "  4. Run with verbose output: bash -x raspberry_setup.sh [options]"
    echo ""
    echo "Get Help:"
    echo "  • GitHub: https://github.com/alireza787b/mavsdk_drone_show/issues"
    echo "  • Email: p30planets@gmail.com"
    echo ""

    exit 1
}

trap 'error_handler $LINENO' ERR

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
DEFAULT_BRANCH="${MDS_BRANCH:-main-candidate}"
DEFAULT_MANAGEMENT_URL="https://nb1.joomtalk.ir"
DEFAULT_REPO_URL="${MDS_REPO_URL:-git@github.com:alireza787b/mavsdk_drone_show.git}"
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
  -b, --branch NAME           Specify Git branch name (default: main-candidate)
  -d, --drone-id ID           Specify Drone ID (e.g., 1, 2) [Required]
  -k, --netbird-key KEY       Specify Netbird Setup Key [Required unless --skip-netbird is used]
  -u, --management-url URL    Specify Netbird Management URL (default: https://nb1.joomtalk.ir)
      --repo-url URL          Specify Git repository URL (default: git@github.com:alireza787b/mavsdk_drone_show.git)
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
# PROFESSIONAL UX: Progress Tracking & Logging Functions (MDS v3.5.1+)
# =============================================================================

# Global variables for progress tracking
TOTAL_STEPS=16
CURRENT_STEP=0

# Function: Log step with progress indicator
log_step() {
    ((CURRENT_STEP++))
    echo ""
    echo "╔════════════════════════════════════════════════════════════╗"
    printf "║  Step %2d/%-2d: %-45s║\n" "$CURRENT_STEP" "$TOTAL_STEPS" "$1"
    echo "╚════════════════════════════════════════════════════════════╝"
}

# Function: Log progress within a step
log_progress() {
    echo "  → $1"
}

# Function: Log success
log_success() {
    echo "  ✓ $1"
}

# Function: Log warning
log_warn() {
    echo "  ⚠ WARNING: $1"
}

# Function: Log error message
log_error() {
    echo "  ✗ ERROR: $1"
}

# =============================================================================
# HEALTH CHECKS: Pre-flight System Validation
# =============================================================================
run_health_checks() {
    log_step "Running pre-flight system health checks"

    local warnings=0
    local errors=0

    # Check 1: Disk Space
    log_progress "Checking disk space..."
    local free_gb=$(df -BG / | awk 'NR==2 {print $4}' | sed 's/G//')
    if [[ $free_gb -lt 1 ]]; then
        log_error "Insufficient disk space: ${free_gb}GB (need at least 1GB)"
        ((errors++))
    elif [[ $free_gb -lt 2 ]]; then
        log_warn "Low disk space: ${free_gb}GB (recommend >2GB)"
        ((warnings++))
    else
        log_success "Disk space: ${free_gb}GB available"
    fi

    # Check 2: Internet Connectivity
    log_progress "Checking internet connectivity..."
    if ping -c 1 -W 2 8.8.8.8 &>/dev/null; then
        log_success "Internet: Connected"
    else
        log_error "No internet connectivity (required for installation)"
        ((errors++))
    fi

    # Check 3: DNS Resolution
    log_progress "Checking DNS resolution..."
    if ping -c 1 -W 2 github.com &>/dev/null; then
        log_success "DNS: Working"
    else
        log_warn "DNS resolution issues detected"
        ((warnings++))
    fi

    # Check 4: User permissions
    log_progress "Checking user permissions..."
    if [[ "$USER" == "root" ]]; then
        log_warn "Running as root (not recommended)"
        ((warnings++))
    else
        log_success "Running as user: $USER"
    fi

    # Check 5: Sudo access
    log_progress "Checking sudo access..."
    if sudo -n true 2>/dev/null; then
        log_success "Sudo: Available (passwordless)"
    elif sudo true 2>/dev/null; then
        log_success "Sudo: Available"
    else
        log_error "Sudo access required but not available"
        ((errors++))
    fi

    # Summary
    echo ""
    if [[ $errors -gt 0 ]]; then
        echo "  ✗ Health check FAILED: $errors error(s), $warnings warning(s)"
        echo ""
        read -p "  Continue anyway? (not recommended) [y/N]: " continue_anyway
        if [[ "$continue_anyway" != "y" && "$continue_anyway" != "Y" ]]; then
            echo "  Setup cancelled by user."
            exit 1
        fi
    elif [[ $warnings -gt 0 ]]; then
        echo "  ⚠ Health check passed with $warnings warning(s)"
        read -p "  Continue? [Y/n]: " continue_with_warnings
        if [[ "$continue_with_warnings" == "n" || "$continue_with_warnings" == "N" ]]; then
            echo "  Setup cancelled by user."
            exit 1
        fi
    else
        log_success "All health checks passed"
    fi
    echo ""
}

# =============================================================================
# MAVLINK ROUTER: Installation Function
# =============================================================================
install_mavlink_router() {
    log_step "Checking MAVLink Router installation"

    if command -v mavlink-routerd &> /dev/null; then
        log_success "MAVLink Router already installed"
        log_progress "Version: $(mavlink-routerd --version 2>&1 | head -1)"
        return 0
    fi

    log_warn "MAVLink Router not found - installing..."

    local MAVLINK_DIR="$HOME/mavlink-anywhere"

    # Clone repository
    if [[ ! -d "$MAVLINK_DIR" ]]; then
        log_progress "Cloning mavlink-anywhere repository..."
        if git clone https://github.com/alireza787b/mavlink-anywhere.git "$MAVLINK_DIR"; then
            log_success "Repository cloned"
        else
            log_error "Failed to clone mavlink-anywhere repository"
            return 1
        fi
    else
        log_progress "Repository exists, updating..."
        cd "$MAVLINK_DIR"
        git pull origin main || log_warn "Could not update repository"
    fi

    # Run installation script
    if [[ -f "$MAVLINK_DIR/install_mavlink_router.sh" ]]; then
        log_progress "Running installation script..."
        cd "$MAVLINK_DIR"
        if sudo bash install_mavlink_router.sh; then
            log_success "Installation script completed"
        else
            log_error "Installation script failed"
            return 1
        fi
    else
        log_error "Installation script not found: $MAVLINK_DIR/install_mavlink_router.sh"
        return 1
    fi

    # Verify installation
    if command -v mavlink-routerd &> /dev/null; then
        log_success "MAVLink Router installed successfully"
        log_progress "Version: $(mavlink-routerd --version 2>&1 | head -1)"
    else
        log_error "MAVLink Router installation verification failed"
        return 1
    fi

    cd "$REPO_DIR"
}

# =============================================================================
# SERVICE MANAGEMENT: Enhanced Setup with Verification
# =============================================================================
setup_and_enable_service() {
    local service_name="$1"
    local install_script="$2"
    local service_file="$3"

    log_progress "Setting up $service_name..."

    # Run installation script
    if [[ -f "$install_script" ]]; then
        if sudo bash "$install_script" &>/dev/null; then
            log_success "Installation script completed"
        else
            log_warn "Installation script had issues: $install_script"
            return 1
        fi
    else
        log_error "Installation script not found: $install_script"
        return 1
    fi

    # Reload systemd
    sudo systemctl daemon-reload

    # Enable service
    if sudo systemctl enable "$service_file" &>/dev/null; then
        log_success "$service_name enabled for boot"
    else
        log_warn "Could not enable $service_file"
    fi
}

# =============================================================================
# NETWORK INFORMATION: Gathering Functions for Final Report
# =============================================================================

# Get all network interfaces and IPs
get_network_info() {
    local output=""
    local iface_list=""
    local ip_list=""

    # Get all active interfaces (except lo)
    while IFS= read -r line; do
        local iface=$(echo "$line" | awk '{print $2}' | tr -d ':')
        if [[ "$iface" != "lo" ]]; then
            local ip=$(ip -4 addr show "$iface" 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | head -1)
            if [[ -n "$ip" ]]; then
                iface_list="${iface_list}${iface} "
                ip_list="${ip_list}${ip} "
            fi
        fi
    done < <(ip -o link show | grep -v "lo:")

    echo "${iface_list}|${ip_list}"
}

# Get Netbird VPN IP and interface
get_netbird_ip() {
    if command -v netbird &>/dev/null && netbird status &>/dev/null; then
        # Netbird interface is usually 'wt0' or similar
        local netbird_iface=$(ip -o link show | grep -E "wt[0-9]|nb[0-9]" | awk '{print $2}' | tr -d ':' | head -1)
        if [[ -n "$netbird_iface" ]]; then
            local netbird_ip=$(ip -4 addr show "$netbird_iface" 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | head -1)
            if [[ -n "$netbird_ip" ]]; then
                echo "$netbird_ip|$netbird_iface"
                return 0
            fi
        fi
    fi
    echo "|"
}

# Get hostname information
get_hostname_info() {
    local hostname=$(hostname)
    local fqdn=$(hostname -f 2>/dev/null || echo "$hostname")
    local mdns="${hostname}.local"
    echo "$hostname|$fqdn|$mdns"
}

# =============================================================================
# NETWORK REPORT: Critical Information Before Reboot
# =============================================================================
print_network_connection_info() {
    echo ""
    echo "╔════════════════════════════════════════════════════════════════════════════╗"
    echo "║                   NETWORK CONNECTION INFORMATION                           ║"
    echo "║                      >> SAVE THIS BEFORE REBOOT <<                         ║"
    echo "╚════════════════════════════════════════════════════════════════════════════╝"
    echo ""

    # Get hostname information
    IFS='|' read -r hostname fqdn mdns <<< "$(get_hostname_info)"
    echo "Device Identity:"
    echo "  • Hostname: $hostname"
    echo "  • FQDN: $fqdn"
    echo "  • mDNS: $mdns"
    echo ""

    # Get network interfaces
    echo "Network Interfaces:"
    IFS='|' read -r iface_list ip_list <<< "$(get_network_info)"

    if [[ -n "$iface_list" ]]; then
        IFS=' ' read -ra ifaces <<< "$iface_list"
        IFS=' ' read -ra ips <<< "$ip_list"

        for i in "${!ifaces[@]}"; do
            local iface="${ifaces[$i]}"
            local ip="${ips[$i]}"

            # Determine interface type
            local type="Unknown"
            case "$iface" in
                eth*|enp*|eno*) type="Ethernet" ;;
                wlan*|wlp*) type="WiFi" ;;
                usb*) type="USB" ;;
            esac

            echo "  • $iface ($type): $ip"
        done
    else
        echo "  ⚠ No network interfaces detected"
    fi
    echo ""

    # Get Netbird information
    if [[ "$SKIP_NETBIRD" == false ]]; then
        IFS='|' read -r netbird_ip netbird_iface <<< "$(get_netbird_ip)"
        if [[ -n "$netbird_ip" ]]; then
            echo "Netbird VPN:"
            echo "  • Interface: $netbird_iface"
            echo "  • VPN IP: $netbird_ip"
            echo "  • Management: ${MANAGEMENT_URL:-Not set}"
            local netbird_status=$(netbird status 2>/dev/null | head -1 || echo "Unknown")
            echo "  • Status: $netbird_status"
        else
            echo "Netbird VPN:"
            echo "  ⚠ Netbird configured but VPN IP not detected yet"
            echo "  ⚠ Will be available after reboot and service start"
        fi
        echo ""
    fi

    # Connection recommendations
    echo "How to Reconnect After Reboot:"
    echo ""

    if [[ "$SKIP_NETBIRD" == false ]]; then
        if [[ -n "$netbird_ip" ]]; then
            echo "  🔹 RECOMMENDED: Use Netbird VPN IP"
            echo "     ssh droneshow@$netbird_ip"
            echo "     or"
            echo "     ssh droneshow@$hostname  (via Netbird DNS if configured)"
        else
            echo "  🔹 RECOMMENDED: Use Netbird (will be active after reboot)"
            echo "     Check Netbird admin panel for VPN IP"
            echo "     or use hostname: ssh droneshow@$hostname"
        fi
        echo ""
    fi

    if [[ -n "$iface_list" ]]; then
        echo "  🔸 ALTERNATIVE: Use Local Network"
        IFS=' ' read -ra ips <<< "$ip_list"
        for ip in "${ips[@]}"; do
            echo "     ssh droneshow@$ip"
        done
        echo "     or"
        echo "     ssh droneshow@$mdns"
        echo ""
    fi

    echo "  USERNAME: droneshow"
    echo "  DRONE ID: $DRONE_ID"
    echo ""

    # Warning about SSH disruption
    if [[ -n "$SSH_CLIENT" || -n "$SSH_CONNECTION" ]]; then
        echo "⚠ IMPORTANT: You are connected via SSH"
        echo "  • Your current session WILL disconnect during reboot"
        echo "  • Wait 60-90 seconds for system to fully restart"
        echo "  • All services will auto-start after boot"
        echo "  • Use the connection information above to reconnect"
        echo ""
    fi

    # Save to file for reference
    local info_file="$HOME/mds_network_info.txt"
    {
        echo "MDS Setup - Network Connection Information"
        echo "Generated: $(date)"
        echo "=========================================="
        echo ""
        echo "Hostname: $hostname"
        echo "mDNS: $mdns"
        echo "Drone ID: $DRONE_ID"
        echo ""
        echo "Network Interfaces:"
        if [[ -n "$iface_list" ]]; then
            IFS=' ' read -ra ifaces <<< "$iface_list"
            IFS=' ' read -ra ips <<< "$ip_list"
            for i in "${!ifaces[@]}"; do
                echo "  ${ifaces[$i]}: ${ips[$i]}"
            done
        fi
        echo ""
        if [[ "$SKIP_NETBIRD" == false ]]; then
            if [[ -n "$netbird_ip" ]]; then
                echo "Netbird VPN: $netbird_ip ($netbird_iface)"
            else
                echo "Netbird VPN: Configured (IP will be available after reboot)"
            fi
            echo "Management: ${MANAGEMENT_URL:-Not set}"
        fi
        echo ""
        echo "SSH Connection Commands:"
        if [[ "$SKIP_NETBIRD" == false && -n "$netbird_ip" ]]; then
            echo "  ssh droneshow@$netbird_ip  # Via Netbird VPN"
        fi
        if [[ -n "$iface_list" ]]; then
            IFS=' ' read -ra ips <<< "$ip_list"
            for ip in "${ips[@]}"; do
                echo "  ssh droneshow@$ip  # Via local network"
            done
            echo "  ssh droneshow@$mdns  # Via mDNS"
        fi
    } > "$info_file"

    echo "📋 Network info saved to: $info_file"
    echo ""
}

# =============================================================================
# FINAL SUMMARY: Complete Status Report Before Reboot
# =============================================================================
print_setup_summary() {
    echo ""
    echo "╔════════════════════════════════════════════════════════════════════════════╗"
    echo "║                      SETUP COMPLETE - FINAL REPORT                         ║"
    echo "╚════════════════════════════════════════════════════════════════════════════╝"
    echo ""

    # System Configuration
    echo "System Configuration:"
    echo "  • Drone ID: $DRONE_ID"
    echo "  • Hostname: drone$DRONE_ID"
    echo "  • Repository: $REPO_URL"
    echo "  • Branch: $BRANCH_NAME"
    echo "  • Python: $(python3 --version 2>&1 | awk '{print $2}')"
    echo ""

    # Services Status
    echo "Services Configured (will auto-start on boot):"
    local services=(
        "coordinator.service"
        "led_indicator.service"
        "wifi-manager.service"
        "git_sync_mds.service"
    )

    for service in "${services[@]}"; do
        if systemctl is-enabled "$service" &>/dev/null; then
            echo "  ✓ $service"
        else
            echo "  ⚠ $service (not enabled)"
        fi
    done
    echo ""

    # Components Installed
    echo "Components Installed:"
    echo "  • Python venv: $REPO_DIR/venv"

    if command -v mavlink-routerd &>/dev/null; then
        local version=$(mavlink-routerd --version 2>&1 | head -1 || echo "unknown")
        echo "  ✓ MAVLink Router: $version"
    else
        echo "  ⚠ MAVLink Router: Not installed"
    fi

    if [[ "$SKIP_MAVSDK" == false ]]; then
        if [[ -f "$REPO_DIR/mavsdk_server" ]]; then
            echo "  ✓ MAVSDK Server: Installed"
        else
            echo "  ⚠ MAVSDK Server: Not found"
        fi
    fi

    if [[ "$SKIP_NETBIRD" == false ]]; then
        if command -v netbird &>/dev/null; then
            local version=$(netbird version 2>&1 | head -1 || echo "unknown")
            echo "  ✓ Netbird VPN: $version"
        else
            echo "  ⚠ Netbird: Not detected"
        fi
    fi
    echo ""

    # Log file location
    if [[ -n "${LOG_FILE:-}" ]]; then
        echo "Setup Log: $LOG_FILE"
    fi
    echo "Network Info: $HOME/mds_network_info.txt"
    echo ""

    # Now show detailed network information
    print_network_connection_info

    # Verification steps
    echo "After Reboot - Verification Steps:"
    echo "  1. Wait 60-90 seconds for full system boot"
    echo "  2. Reconnect via SSH (see connection info above)"
    echo "  3. Check coordinator status:"
    echo "       systemctl status coordinator.service"
    echo "  4. View coordinator logs:"
    echo "       journalctl -u coordinator.service -f"
    echo "  5. Check all services:"
    echo "       systemctl status led_indicator wifi-manager git_sync_mds"
    echo ""

    # Final countdown
    echo "╔════════════════════════════════════════════════════════════════════════════╗"
    echo "║  System will reboot in 15 seconds...                                      ║"
    echo "║  Press Ctrl+C now to cancel reboot and review settings                    ║"
    echo "╚════════════════════════════════════════════════════════════════════════════╝"
    echo ""

    for i in {15..1}; do
        printf "  Rebooting in %2d seconds...  \r" $i
        sleep 1
    done
    echo ""
}

# =============================================================================
# NEW FUNCTION: Setup Python Virtual Environment
# =============================================================================
setup_python_venv() {
    log_step "Setting up Python virtual environment"

    # Check if python3 is available
    if ! command -v python3 &> /dev/null; then
        log_warn "Python3 not found - installing..."
        sudo apt-get update
        sudo apt-get install -y python3
    fi

    # Check Python version (MDS requires Python 3.11-3.13)
    log_progress "Checking Python version compatibility..."
    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
    PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

    log_progress "Detected Python version: $PYTHON_VERSION"

    if [[ $PYTHON_MAJOR -lt 3 ]] || [[ $PYTHON_MAJOR -eq 3 && $PYTHON_MINOR -lt 11 ]]; then
        echo ""
        log_error "Incompatible Python Version"
        echo ""
        echo "MAVSDK Drone Show requires Python 3.11 or newer."
        echo "You have Python $PYTHON_VERSION"
        echo ""
        echo "Solutions:"
        echo "  1. Upgrade to latest Raspberry Pi OS (includes Python 3.13)"
        echo "  2. Install Python 3.11+ manually"
        echo ""
        echo "For support, see: docs/PYTHON_COMPATIBILITY.md"
        exit 1
    elif [[ $PYTHON_MAJOR -eq 3 && $PYTHON_MINOR -gt 13 ]]; then
        log_warn "Untested Python Version: $PYTHON_VERSION"
        echo "  MDS has been tested with Python 3.11-3.13."
        echo "  Python 3.14+ may work but is not officially supported yet."
        read -p "  Continue anyway? (y/n): " continue_install
        if [[ "$continue_install" != "y" && "$continue_install" != "Y" ]]; then
            echo "Installation cancelled."
            exit 1
        fi
    fi

    log_success "Python $PYTHON_VERSION - Compatible"

    # Check if python3-venv is installed
    if ! dpkg -s python3-venv &> /dev/null; then
        log_progress "Installing python3-venv..."
        sudo apt-get update &>/dev/null
        sudo apt-get install -y python3-venv &>/dev/null
    fi

    # Check if python3-pip is installed
    if ! dpkg -s python3-pip &> /dev/null; then
        log_progress "Installing python3-pip..."
        sudo apt-get update &>/dev/null
        sudo apt-get install -y python3-pip &>/dev/null
    fi

    # Install system dependencies required for Python scientific packages
    log_progress "Installing system dependencies for Python packages..."
    sudo apt-get update &>/dev/null
    sudo apt-get install -y \
        python3-dev \
        build-essential \
        libgfortran5 \
        libopenblas-dev \
        libatlas-base-dev \
        libxml2-dev \
        libxslt-dev \
        liblapack-dev \
        gfortran &>/dev/null
    log_success "System dependencies installed"

    # Check if git-repair is installed
    if ! dpkg -s git-repair &> /dev/null; then
        log_progress "Installing git-repair..."
        sudo apt-get install -y git-repair &>/dev/null
    fi

    # Move to repository directory (already cloned by setup_git)
    cd "$REPO_DIR"

    # Check if venv folder exists
    if [[ -d "venv" ]]; then
        log_progress "Using existing virtual environment"
    else
        log_progress "Creating new virtual environment..."
        python3 -m venv venv
        log_success "Virtual environment created"
    fi

    log_progress "Activating virtual environment..."
    # shellcheck disable=SC1091
    source venv/bin/activate

    log_progress "Upgrading pip..."
    pip install --upgrade pip &>/dev/null

    if [[ -f "requirements.txt" ]]; then
        log_progress "Installing Python packages (this may take 5-10 minutes)..."
        # Use --no-cache-dir to avoid cache issues during backup/restore
        # but DO install dependencies (removed dangerous --no-deps flag)
        if pip install --no-cache-dir -r requirements.txt; then
            log_success "All Python packages installed successfully"
        else
            log_error "Some packages failed to install"
            log_warn "Check the log for details"
        fi
    else
        log_warn "requirements.txt not found - skipping pip install"
    fi

    log_progress "Deactivating virtual environment..."
    deactivate

    log_success "Python environment setup complete"
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

echo ""
echo "╔════════════════════════════════════════════════════════════════════════════╗"
echo "║            MAVSDK Drone Show - Hardware Setup Script v3.5.1               ║"
echo "╚════════════════════════════════════════════════════════════════════════════╝"
echo ""

# Run pre-flight health checks
# TEMPORARILY DISABLED: Causing script to exit on some systems
# run_health_checks

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

# Setup Python Virtual Environment
setup_python_venv

# Install MAVLink Router
install_mavlink_router || log_warn "MAVLink Router installation had issues (non-critical)"

# Setup Services with Verification and Enable for Boot
log_step "Installing and enabling system services"

setup_and_enable_service "LED Indicator" \
    "$REPO_DIR/tools/led_indicator/install_led_indicator.sh" \
    "led_indicator.service"

setup_and_enable_service "Wifi Manager" \
    "$REPO_DIR/tools/wifi-manager/update_wifi-manager_service.sh" \
    "wifi-manager.service"

setup_and_enable_service "Git Sync MDS" \
    "$REPO_DIR/tools/git_sync_mds/install_git_sync_mds.sh" \
    "git_sync_mds.service"

setup_and_enable_service "Coordinator" \
    "$REPO_DIR/tools/update_service.sh" \
    "coordinator.service"

echo ""

# Check and Download MAVSDK Server unless skipped
if [[ "$SKIP_MAVSDK" == false ]]; then
    log_step "Checking MAVSDK Server"
    if [[ ! -f "$REPO_DIR/mavsdk_server" ]]; then
        log_progress "MAVSDK server not found, downloading..."
        if [[ -f "$REPO_DIR/tools/download_mavsdk_server.sh" ]]; then
            sudo bash "$REPO_DIR/tools/download_mavsdk_server.sh"
            log_success "MAVSDK server downloaded"
        else
            log_error "Download script not found"
        fi
    else
        log_success "MAVSDK server already present"
    fi
fi

# Proceed with Netbird setup unless skipped
if [[ "$SKIP_NETBIRD" == false ]]; then
    setup_netbird
fi

# Print comprehensive final summary with network information
print_setup_summary

# Reboot
sudo reboot
