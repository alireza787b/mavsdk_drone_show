#!/bin/bash
# =============================================================================
# MDS Raspberry Pi Bootstrap Installer
# =============================================================================
# Version: 4.4.0
# Description: Bootstrap installer for fresh Raspberry Pi setup
#              Downloads and runs mds_init.sh
# Author: MDS Team
# =============================================================================
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/alireza787b/mavsdk_drone_show/main-candidate/tools/install_rpi.sh | sudo bash
#
#   Or with options:
#   curl -fsSL ... | sudo bash -s -- -d 1 --fork myuser
#   curl -fsSL ... | sudo bash -s -- -d 1 --branch develop -y
#
# =============================================================================

set -euo pipefail

# =============================================================================
# CONFIGURATION
# =============================================================================

# Repository settings
REPO_URL="${MDS_REPO_URL:-https://github.com/alireza787b/mavsdk_drone_show.git}"
BRANCH="${MDS_BRANCH:-main-candidate}"

# User and installation settings
MDS_USER="droneshow"
INSTALL_DIR="/home/${MDS_USER}/mavsdk_drone_show"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# =============================================================================
# LOGGING FUNCTIONS
# =============================================================================

log_info() {
    echo -e "${CYAN}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

normalize_github_repo_path() {
    local spec="${1:-}"

    spec="${spec#https://github.com/}"
    spec="${spec#git@github.com:}"
    spec="${spec#github.com/}"
    spec="${spec%.git}"
    spec="${spec#/}"

    if [[ -z "$spec" ]]; then
        return 1
    fi

    if [[ "$spec" != */* ]]; then
        spec="${spec}/mavsdk_drone_show"
    fi

    printf '%s\n' "$spec"
}

# =============================================================================
# BANNER
# =============================================================================

print_banner() {
    echo ""
    echo -e "${CYAN},--.   ,--.,------.   ,---.   ${NC}"
    echo -e "${CYAN}|   \`.'   ||  .-.  \\ '   .-'  ${NC}"
    echo -e "${CYAN}|  |'.'|  ||  |  \\  :\`.  \`-.  ${NC}"
    echo -e "${CYAN}|  |   |  ||  '--'  /.-'    | ${NC}"
    echo -e "${CYAN}\`--'   \`--'\`-------' \`-----'  ${NC}"
    echo ""
    echo -e "${WHITE}MAVSDK Drone Show - Raspberry Pi Bootstrap${NC}"
    echo "================================================================"
    echo -e "Version:  ${WHITE}4.4.0${NC}"
    echo -e "Branch:   ${WHITE}$BRANCH${NC}"
    echo "================================================================"
    echo -e "${DIM}           Enterprise Drone Swarm Platform${NC}"
    echo ""
}

# =============================================================================
# SYSTEM CHECKS
# =============================================================================

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root (use sudo)"
        echo ""
        echo "Usage:"
        echo "  curl -fsSL <url> | sudo bash"
        exit 1
    fi
}

check_os() {
    log_info "Checking operating system..."

    if [[ ! -f /etc/os-release ]]; then
        log_error "Cannot detect operating system"
        exit 1
    fi

    source /etc/os-release

    case "${ID:-unknown}" in
        raspbian|debian)
            log_success "Detected: ${PRETTY_NAME:-$ID}"
            ;;
        ubuntu)
            log_warn "Ubuntu detected - not officially supported but may work"
            ;;
        *)
            log_error "Unsupported OS: ${ID:-unknown}. Raspberry Pi OS or Debian required."
            exit 1
            ;;
    esac
}

check_architecture() {
    log_info "Checking architecture..."

    local arch=$(uname -m)
    case "$arch" in
        aarch64|arm64)
            log_success "Architecture: ARM64 (64-bit)"
            ;;
        armv7l)
            log_warn "Architecture: ARM32 (32-bit) - 64-bit recommended"
            ;;
        x86_64)
            log_warn "Architecture: x86_64 - SITL/development mode"
            ;;
        *)
            log_error "Unsupported architecture: $arch"
            exit 1
            ;;
    esac
}

# =============================================================================
# USER MANAGEMENT
# =============================================================================

create_droneshow_user() {
    log_info "Checking for '${MDS_USER}' user..."

    if id "${MDS_USER}" &>/dev/null; then
        log_success "User '${MDS_USER}' already exists"
        return 0
    fi

    log_info "Creating '${MDS_USER}' user..."

    # Create user with home directory
    useradd -m -s /bin/bash "${MDS_USER}" || {
        log_error "Failed to create user '${MDS_USER}'"
        exit 1
    }

    # Add to necessary groups
    local groups=("gpio" "dialout" "video" "audio" "sudo")
    for group in "${groups[@]}"; do
        if getent group "$group" &>/dev/null; then
            usermod -aG "$group" "${MDS_USER}" 2>/dev/null || true
        fi
    done

    log_success "User '${MDS_USER}' created and added to groups"
}

# =============================================================================
# PREREQUISITES
# =============================================================================

install_prerequisites() {
    log_info "Installing prerequisites..."

    apt-get update -qq

    # Essential packages for bootstrap
    local packages=("git" "curl" "jq")
    local missing=()

    for pkg in "${packages[@]}"; do
        if ! dpkg -l "$pkg" 2>/dev/null | grep -q "^ii"; then
            missing+=("$pkg")
        fi
    done

    if [[ ${#missing[@]} -eq 0 ]]; then
        log_success "All prerequisites already installed"
        return 0
    fi

    log_info "Installing: ${missing[*]}"
    apt-get install -y -qq "${missing[@]}" || {
        log_error "Failed to install prerequisites"
        exit 1
    }

    log_success "Prerequisites installed"
}

# =============================================================================
# REPOSITORY
# =============================================================================

clone_repository() {
    log_info "Cloning repository..."
    log_info "  URL: $REPO_URL"
    log_info "  Branch: $BRANCH"
    log_info "  Directory: $INSTALL_DIR"

    # Ensure parent directory exists
    mkdir -p "$(dirname "$INSTALL_DIR")"
    chown "${MDS_USER}:${MDS_USER}" "$(dirname "$INSTALL_DIR")"

    if [[ -d "$INSTALL_DIR/.git" ]]; then
        log_info "Repository already exists, updating..."
        cd "$INSTALL_DIR"

        # Update as the droneshow user
        sudo -u "${MDS_USER}" git fetch origin "$BRANCH" || {
            log_error "Failed to fetch repository"
            exit 1
        }
        sudo -u "${MDS_USER}" git checkout "$BRANCH" 2>/dev/null || \
            sudo -u "${MDS_USER}" git checkout -b "$BRANCH" "origin/$BRANCH"
        sudo -u "${MDS_USER}" git reset --hard "origin/$BRANCH"
    else
        # Clone as the droneshow user
        sudo -u "${MDS_USER}" git clone -b "$BRANCH" "$REPO_URL" "$INSTALL_DIR" || {
            log_error "Failed to clone repository"
            exit 1
        }
    fi

    log_success "Repository ready"
}

# =============================================================================
# RUN INIT SCRIPT
# =============================================================================

run_init_script() {
    local init_script="${INSTALL_DIR}/tools/mds_init.sh"

    if [[ ! -f "$init_script" ]]; then
        log_error "Init script not found: $init_script"
        exit 1
    fi

    chmod +x "$init_script"

    log_info "Running MDS initialization script..."
    echo ""
    echo -e "${CYAN}================================================================${NC}"
    echo -e "${WHITE}Handing off to mds_init.sh...${NC}"
    echo -e "${CYAN}================================================================${NC}"
    echo ""

    # Change to install directory and run init script
    cd "$INSTALL_DIR"

    # Pass through all remaining arguments
    exec "$init_script" "$@"
}

# =============================================================================
# HELP
# =============================================================================

show_help() {
    cat << 'EOF'
MDS Raspberry Pi Bootstrap Installer (v4.4.0)

USAGE:
    curl -fsSL <url> | sudo bash
    curl -fsSL <url> | sudo bash -s -- [OPTIONS]

BOOTSTRAP OPTIONS:
    --branch BRANCH     Git branch to use (default: main-candidate)
    --fork OWNER[/REPO] Use a GitHub fork or custom repo path
    -h, --help          Show this help message

    All other options are passed to mds_init.sh

PASSTHROUGH OPTIONS (to mds_init.sh):
    -d, --drone-id ID   Hardware ID for this drone (1-999)
    -y, --yes           Non-interactive mode
    --https             Use HTTPS for git operations
    --netbird-key KEY   Netbird VPN setup key
    --static-ip IP      Static IP address (CIDR format)
    --dry-run           Show what would be done

    See mds_init.sh --help for all options

ENVIRONMENT VARIABLES:
    MDS_REPO_URL        Git repository URL
    MDS_BRANCH          Git branch

EXAMPLES:
    # Basic installation (interactive)
    curl -fsSL https://raw.githubusercontent.com/alireza787b/mavsdk_drone_show/main-candidate/tools/install_rpi.sh | sudo bash

    # With drone ID (non-interactive)
    curl -fsSL ... | sudo bash -s -- -d 1 -y

    # Use your own fork
    curl -fsSL ... | sudo bash -s -- --fork myusername -d 1 -y

    # Use a customer org/private repo path
    curl -fsSL ... | sudo bash -s -- --fork myorg/customer-mds -d 1 -y

    # Custom branch
    curl -fsSL ... | sudo bash -s -- --branch develop -d 1 -y

    # Full setup with VPN
    curl -fsSL ... | sudo bash -s -- -d 5 --netbird-key "XXXXX" -y

WHAT THIS SCRIPT DOES:
    1. Creates 'droneshow' user if needed
    2. Installs git, curl, jq prerequisites
    3. Clones the MDS repository
    4. Runs the full mds_init.sh initialization

For more information: https://github.com/alireza787b/mavsdk_drone_show
EOF
}

# =============================================================================
# MAIN
# =============================================================================

main() {
    # Parse bootstrap-specific arguments
    local passthrough_args=()

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --branch)
                BRANCH="$2"
                shift 2
                ;;
            --fork)
                local repo_path
                repo_path=$(normalize_github_repo_path "$2") || {
                    log_error "Invalid --fork value: $2"
                    exit 1
                }
                REPO_URL="https://github.com/${repo_path}.git"
                export MDS_REPO_URL="$REPO_URL"
                log_info "Using GitHub repository: ${repo_path}"
                shift 2
                ;;
            -h|--help)
                show_help
                exit 0
                ;;
            *)
                passthrough_args+=("$1")
                shift
                ;;
        esac
    done

    print_banner

    log_info "Starting Raspberry Pi bootstrap installation..."
    log_info "Date: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""

    # System checks
    check_root
    check_os
    check_architecture

    echo ""

    # Setup
    create_droneshow_user
    install_prerequisites
    clone_repository

    echo ""

    # Run init script with passthrough args
    run_init_script "${passthrough_args[@]}"
}

main "$@"
