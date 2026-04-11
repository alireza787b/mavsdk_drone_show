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
GCS_SSH_KEY_PATH="${HOME}/.ssh/mds_gcs_deploy_key"

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

is_github_ssh_repo_url() {
    [[ "${1:-}" == git@github.com:* ]]
}

gcs_git_ssh_command() {
    printf 'ssh -i %q -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new' "$GCS_SSH_KEY_PATH"
}

wrapper_non_interactive() {
    [[ "${WRAPPER_NON_INTERACTIVE:-false}" == "true" ]]
}

resolve_target_repo_url() {
    local explicit_repo_url="${1:-}"
    local selected_repo_path="${2:-}"
    local use_https_mode="${3:-false}"

    if [[ -n "$explicit_repo_url" ]]; then
        printf '%s\n' "$explicit_repo_url"
        return 0
    fi

    if [[ -n "$selected_repo_path" ]]; then
        if [[ "$use_https_mode" == "true" ]]; then
            printf 'https://github.com/%s.git\n' "$selected_repo_path"
        else
            printf 'git@github.com:%s.git\n' "$selected_repo_path"
        fi
        return 0
    fi

    printf '%s\n' "$REPO_URL"
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

prepare_wrapper_repo_ssh_runtime() {
    mkdir -p "${HOME}/.ssh"
    chmod 700 "${HOME}/.ssh"

    if [[ -f "$GCS_SSH_KEY_PATH" ]]; then
        chmod 600 "$GCS_SSH_KEY_PATH"
    fi

    if [[ -f "${GCS_SSH_KEY_PATH}.pub" ]]; then
        chmod 644 "${GCS_SSH_KEY_PATH}.pub"
    fi

    if ! grep -q "github.com" "${HOME}/.ssh/known_hosts" 2>/dev/null; then
        ssh-keyscan -t ed25519 github.com >> "${HOME}/.ssh/known_hosts" 2>/dev/null || true
    fi
}

wrapper_ssh_key_exists() {
    [[ -f "$GCS_SSH_KEY_PATH" ]]
}

generate_wrapper_deploy_key() {
    log_info "Preparing GCS SSH deploy key for bootstrap..."

    if wrapper_ssh_key_exists; then
        log_success "Bootstrap SSH key already exists"
        return 0
    fi

    prepare_wrapper_repo_ssh_runtime

    if ssh-keygen -t ed25519 -f "$GCS_SSH_KEY_PATH" -N "" -C "mds-gcs@$(hostname)" >/dev/null 2>&1; then
        chmod 600 "$GCS_SSH_KEY_PATH"
        chmod 644 "${GCS_SSH_KEY_PATH}.pub"
        log_success "Bootstrap SSH deploy key generated"
    else
        log_error "Failed to generate bootstrap SSH deploy key"
        exit 1
    fi
}

display_wrapper_deploy_key_instructions() {
    local repo_url="$1"

    echo ""
    echo -e "${CYAN}================================================${NC}"
    echo -e "${WHITE}GitHub deploy key authorization is required before the first private GCS clone.${NC}"
    echo -e "${CYAN}================================================${NC}"
    echo ""
    echo -e "${WHITE}Repository:${NC} ${repo_url}"
    echo -e "${WHITE}Key path:${NC} ${GCS_SSH_KEY_PATH}.pub"
    echo ""
    if [[ -f "${GCS_SSH_KEY_PATH}.pub" ]]; then
        cat "${GCS_SSH_KEY_PATH}.pub"
        echo ""
    fi
    echo "GitHub path: Settings -> Deploy keys -> Add deploy key"
    echo "Title: MDS GCS - $(hostname)"
    echo "Allow write access: required if this GCS will commit/push."
    echo ""
}

test_wrapper_ssh_connection() {
    local result

    prepare_wrapper_repo_ssh_runtime
    result=$(ssh \
        -T \
        -o BatchMode=yes \
        -o ConnectTimeout=10 \
        -o IdentitiesOnly=yes \
        -o StrictHostKeyChecking=accept-new \
        -i "${GCS_SSH_KEY_PATH}" \
        git@github.com 2>&1) || true

    echo "$result" | grep -qi "successfully authenticated"
}

ensure_wrapper_repo_access() {
    local repo_url="$1"

    if ! is_github_ssh_repo_url "$repo_url"; then
        return 0
    fi

    prepare_wrapper_repo_ssh_runtime
    generate_wrapper_deploy_key

    if test_wrapper_ssh_connection; then
        log_success "Bootstrap SSH access to GitHub verified"
        return 0
    fi

    display_wrapper_deploy_key_instructions "$repo_url"

    if wrapper_non_interactive; then
        log_error "Non-interactive bootstrap cannot continue until the GCS deploy key is authorized on GitHub"
        log_info "Authorize ${GCS_SSH_KEY_PATH}.pub on the target repository, then rerun the same bootstrap command"
        exit 1
    fi

    while true; do
        local answer=""
        read -r -p "Add the deploy key, then press Enter to retry SSH auth (or type 'https' to switch to HTTPS): " answer </dev/tty || true
        if [[ "${answer}" == "https" ]]; then
            REPO_URL="$(printf '%s\n' "$repo_url" | sed 's|git@github.com:|https://github.com/|')"
            log_warn "Switching bootstrap clone to HTTPS"
            return 0
        fi
        if test_wrapper_ssh_connection; then
            log_success "Bootstrap SSH access to GitHub verified"
            return 0
        fi
        log_warn "SSH authentication still failed. Verify the deploy key was added to the correct repository."
    done
}

run_git_as_root() {
    local repo_url="$1"
    shift

    if is_github_ssh_repo_url "$repo_url"; then
        env GIT_SSH_COMMAND="$(gcs_git_ssh_command)" git "$@"
    else
        git "$@"
    fi
}

clone_repository() {
    log_info "Cloning repository..."
    log_info "  URL: $REPO_URL"
    log_info "  Branch: $BRANCH"
    log_info "  Directory: $INSTALL_DIR"

    if [[ -d "$INSTALL_DIR/.git" ]]; then
        log_info "Repository already exists, updating..."
        cd "$INSTALL_DIR"
        local current_remote
        current_remote=$(git -C "$INSTALL_DIR" remote get-url origin 2>/dev/null || echo "")
        if [[ -n "$current_remote" && "$current_remote" != "$REPO_URL" ]]; then
            log_info "Updating repository remote to requested bootstrap target"
            run_git_as_root "$REPO_URL" -C "$INSTALL_DIR" remote set-url origin "$REPO_URL"
        fi

        if is_github_ssh_repo_url "$REPO_URL"; then
            run_git_as_root "$REPO_URL" -C "$INSTALL_DIR" config core.sshCommand "$(gcs_git_ssh_command)" || true
        else
            git -C "$INSTALL_DIR" config --unset-all core.sshCommand >/dev/null 2>&1 || true
        fi

        run_git_as_root "$REPO_URL" -C "$INSTALL_DIR" fetch origin "$BRANCH"
        run_git_as_root "$REPO_URL" -C "$INSTALL_DIR" checkout "$BRANCH"
        run_git_as_root "$REPO_URL" -C "$INSTALL_DIR" pull origin "$BRANCH"
    else
        mkdir -p "$(dirname "$INSTALL_DIR")"
        run_git_as_root "$REPO_URL" clone -b "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
        if is_github_ssh_repo_url "$REPO_URL"; then
            run_git_as_root "$REPO_URL" -C "$INSTALL_DIR" config core.sshCommand "$(gcs_git_ssh_command)" || true
        fi
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
    --repo-url URL      Use an explicit repository URL for bootstrap and init
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

    # Use an explicit repository URL
    curl -fsSL ... | sudo bash -s -- --repo-url https://github.com/myorg/customer-mds.git --branch customer-demo

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
    local explicit_branch=""
    local explicit_repo_url=""
    local selected_repo_path=""
    local config_repo_url=""
    local use_https_mode="false"
    WRAPPER_NON_INTERACTIVE="false"

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --branch)
                BRANCH="$2"
                explicit_branch="$2"
                shift 2
                ;;
            --repo-url)
                REPO_URL="$2"
                explicit_repo_url="$2"
                shift 2
                ;;
            --fork)
                local repo_path
                repo_path=$(normalize_github_repo_path "$2") || {
                    log_error "Invalid --fork value: $2"
                    exit 1
                }
                selected_repo_path="$repo_path"
                REPO_URL="https://github.com/${repo_path}.git"
                log_info "Using GitHub repository: ${repo_path}"
                shift 2
                ;;
            --https)
                use_https_mode="true"
                passthrough_args+=("$1")
                shift
                ;;
            -y|--yes)
                WRAPPER_NON_INTERACTIVE="true"
                passthrough_args+=("$1")
                shift
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

    config_repo_url="$(resolve_target_repo_url "$explicit_repo_url" "$selected_repo_path" "$use_https_mode")"
    REPO_URL="$config_repo_url"

    if [[ -n "$explicit_branch" ]]; then
        export MDS_BRANCH="$explicit_branch"
        passthrough_args+=("--branch" "$explicit_branch")
    fi

    export MDS_REPO_URL="$config_repo_url"
    passthrough_args+=("--repo-url" "$config_repo_url")

    print_banner

    log_info "Starting GCS bootstrap installation..."
    log_info "Date: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""

    check_root
    install_git
    ensure_wrapper_repo_access "$REPO_URL"
    clone_repository
    run_init_script "${passthrough_args[@]}"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
