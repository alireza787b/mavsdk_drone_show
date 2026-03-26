#!/bin/bash
# =============================================================================
# MDS GCS Bootstrap Installer
# =============================================================================
# Version: bootstrap wrapper (delegates to repo version after clone)
# Description: Bootstrap installer for remote GCS setup
#              Downloads and runs mds_gcs_init.sh
# Author: MDS Team
# License: MIT
# =============================================================================
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/alireza787b/mavsdk_drone_show/main-candidate/tools/install_gcs.sh | sudo bash
#
#   Or with options:
#   curl -fsSL ... | sudo bash -s -- --branch develop --https
#
# =============================================================================

set -euo pipefail

# =============================================================================
# CONFIGURATION
# =============================================================================

# Repository settings
REPO_URL="${MDS_REPO_URL:-https://github.com/alireza787b/mavsdk_drone_show.git}"
BRANCH="${MDS_BRANCH:-main-candidate}"

# Installation directory - defaults to user's home directory
# When running via sudo, SUDO_USER contains the original user
if [[ -n "${SUDO_USER:-}" ]]; then
    DEFAULT_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
else
    DEFAULT_HOME="$HOME"
fi
INSTALL_DIR="${MDS_INSTALL_DIR:-${DEFAULT_HOME}/mavsdk_drone_show}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# =============================================================================
# FUNCTIONS
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

print_banner() {
    # Source shared banner if available
    local script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [[ -f "${script_dir}/mds_banner.sh" ]]; then
        source "${script_dir}/mds_banner.sh"
        print_mds_banner "GCS Bootstrap" "" "$BRANCH" ""
    else
        # Fallback banner
        echo ""
        echo -e "${CYAN},--.   ,--.,------.   ,---.   ${NC}"
        echo -e "${CYAN}|   \`.'   ||  .-.  \\ '   .-'  ${NC}"
        echo -e "${CYAN}|  |'.'|  ||  |  \\  :\`.  \`-.  ${NC}"
        echo -e "${CYAN}|  |   |  ||  '--'  /.-'    | ${NC}"
        echo -e "${CYAN}\`--'   \`--'\`-------' \`-----'  ${NC}"
        echo ""
        echo -e "${GREEN}MAVSDK Drone Show - GCS Bootstrap${NC}"
        echo "================================================"
        echo "Branch:   $BRANCH"
        echo "================================================"
        echo ""
    fi
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root (use sudo)"
        exit 1
    fi
}

install_git() {
    if command -v git &>/dev/null; then
        log_success "git is already installed"
        return 0
    fi

    log_info "Installing git..."
    apt-get update -qq
    apt-get install -y -qq git
    log_success "git installed"
}

clone_repository() {
    log_info "Cloning repository..."
    log_info "  URL: $REPO_URL"
    log_info "  Branch: $BRANCH"
    log_info "  Directory: $INSTALL_DIR"

    if [[ -d "$INSTALL_DIR/.git" ]]; then
        log_info "Repository already exists, updating..."
        cd "$INSTALL_DIR"
        git fetch origin "$BRANCH"
        git checkout "$BRANCH"
        git pull origin "$BRANCH"
    else
        mkdir -p "$(dirname "$INSTALL_DIR")"
        git clone -b "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
    fi

    log_success "Repository ready"
}

run_init_script() {
    local init_script="${INSTALL_DIR}/tools/mds_gcs_init.sh"

    if [[ ! -f "$init_script" ]]; then
        log_error "Init script not found: $init_script"
        exit 1
    fi

    chmod +x "$init_script"

    log_info "Running GCS initialization script..."
    echo ""

    # Change to install directory and pass it explicitly
    cd "$INSTALL_DIR"

    # Pass install-dir and any extra arguments
    exec "$init_script" --install-dir "$INSTALL_DIR" "$@"
}

show_help() {
    cat << EOF
MDS GCS Bootstrap Installer

USAGE:
    curl -fsSL <url> | sudo bash
    curl -fsSL <url> | sudo bash -s -- [OPTIONS]

OPTIONS:
    --branch BRANCH     Git branch to use (default: main-candidate)
    --fork OWNER[/REPO] Use a GitHub fork or custom repo path
    --install-dir PATH  Installation directory (default: \$HOME/mavsdk_drone_show)
    -h, --help          Show this help message

    All other options are passed to mds_gcs_init.sh

ENVIRONMENT VARIABLES:
    MDS_REPO_URL        Git repository URL
    MDS_BRANCH          Git branch
    MDS_INSTALL_DIR     Installation directory

EXAMPLES:
    # Default installation (installs to ~/mavsdk_drone_show)
    curl -fsSL https://raw.githubusercontent.com/.../install_gcs.sh | sudo bash

    # Use your own fork
    curl -fsSL ... | sudo bash -s -- --fork myusername

    # Use a customer org/private repo path
    curl -fsSL ... | sudo bash -s -- --fork myorg/customer-mds

    # Custom branch
    curl -fsSL ... | sudo bash -s -- --branch develop

    # Non-interactive with fork
    curl -fsSL ... | sudo bash -s -- --fork myusername -y

    # Custom install directory
    curl -fsSL ... | sudo bash -s -- --install-dir /opt/mds

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
            --install-dir)
                INSTALL_DIR="$2"
                passthrough_args+=("--install-dir" "$2")
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

    log_info "Starting GCS bootstrap installation..."
    log_info "Date: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""

    check_root
    install_git
    clone_repository
    run_init_script "${passthrough_args[@]}"
}

main "$@"
