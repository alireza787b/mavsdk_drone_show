#!/bin/bash
# =============================================================================
# MDS Companion Node Bootstrap Installer
# =============================================================================
# Version: 4.5.0
# Description: Bootstrap installer for a fresh companion-computer setup
#              Downloads and runs mds_node_init.sh
# Author: MDS Team
# =============================================================================
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/alireza787b/mavsdk_drone_show/main-candidate/tools/install_companion.sh | sudo bash
#   # compatibility alias:
#   curl -fsSL https://raw.githubusercontent.com/alireza787b/mavsdk_drone_show/main-candidate/tools/install_mds_node.sh | sudo bash
#
#   Or with options:
#   curl -fsSL ... | sudo bash -s -- -d 1 --fork myuser
#   curl -fsSL ... | sudo bash -s -- -d 1 --branch develop -y
#
# =============================================================================

set -euo pipefail

# Load the git-tracked deployment profile when running from a local checkout.
# When this wrapper is fetched remotely or piped, it falls back to the embedded
# official defaults below so the bootstrap remains self-contained.
SCRIPT_DIR=""
if [[ -n "${BASH_SOURCE[0]:-}" && "${BASH_SOURCE[0]}" != "bash" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
if [[ -n "$SCRIPT_DIR" && -f "${SCRIPT_DIR}/load_deployment_profile.sh" ]]; then
    MDS_REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
    # shellcheck disable=SC1090
    source "${SCRIPT_DIR}/load_deployment_profile.sh"
fi

DEFAULT_REPO_SLUG="${MDS_DEFAULT_REPO_SLUG:-alireza787b/mavsdk_drone_show}"
DEFAULT_REPO_URL_HTTPS="${MDS_DEFAULT_REPO_URL_HTTPS:-https://github.com/${DEFAULT_REPO_SLUG}.git}"
DEFAULT_BRANCH="${MDS_DEFAULT_BRANCH:-main-candidate}"
DEFAULT_PROJECT_NAME="${DEFAULT_REPO_SLUG##*/}"
DEFAULT_REPO_WEB_URL="https://github.com/${DEFAULT_REPO_SLUG}"
DEFAULT_INSTALL_COMPANION_URL="https://raw.githubusercontent.com/${DEFAULT_REPO_SLUG}/${DEFAULT_BRANCH}/tools/install_companion.sh"
DEFAULT_INSTALL_NODE_URL="https://raw.githubusercontent.com/${DEFAULT_REPO_SLUG}/${DEFAULT_BRANCH}/tools/install_mds_node.sh"

# =============================================================================
# CONFIGURATION
# =============================================================================

# Repository settings
REPO_URL="${MDS_REPO_URL:-${DEFAULT_REPO_URL_HTTPS}}"
BRANCH="${MDS_BRANCH:-${DEFAULT_BRANCH}}"

# User and installation settings
MDS_USER="${MDS_USER:-droneshow}"
INSTALL_DIR="${MDS_INSTALL_DIR:-/home/${MDS_USER}/${DEFAULT_PROJECT_NAME}}"
GIT_AUTH_TOKEN_FILE="${MDS_GIT_AUTH_TOKEN_FILE:-}"
GIT_AUTH_TOKEN="${MDS_GIT_AUTH_TOKEN:-}"
GIT_AUTH_USERNAME="${MDS_GIT_AUTH_USERNAME:-x-access-token}"
GIT_SSH_KEY_FILE="${MDS_GIT_SSH_KEY_FILE:-}"
DEFAULT_SSH_KEY_PATH="/home/${MDS_USER}/.ssh/id_rsa_git_deploy"
SSH_KEY_PATH="${DEFAULT_SSH_KEY_PATH}"

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

set_wrapper_ssh_key_path() {
    if [[ -n "${GIT_SSH_KEY_FILE:-}" ]]; then
        SSH_KEY_PATH="${GIT_SSH_KEY_FILE}"
    else
        SSH_KEY_PATH="${DEFAULT_SSH_KEY_PATH}"
    fi
}

wrapper_ssh_key_is_explicit() {
    [[ -n "${GIT_SSH_KEY_FILE:-}" ]]
}

set_wrapper_ssh_key_path

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
        spec="${spec}/${DEFAULT_PROJECT_NAME}"
    fi

    printf '%s\n' "$spec"
}

is_github_ssh_repo_url() {
    [[ "${1:-}" == git@github.com:* ]]
}

is_github_https_repo_url() {
    [[ "${1:-}" == https://github.com/* ]]
}

wrapper_git_auth_enabled() {
    [[ -n "${GIT_AUTH_TOKEN_FILE:-}" && -r "${GIT_AUTH_TOKEN_FILE}" ]] || [[ -n "${GIT_AUTH_TOKEN:-}" ]]
}

wrapper_git_askpass_path() {
    printf '%s\n' "/tmp/mds_node_git_askpass.sh"
}

prepare_wrapper_git_askpass() {
    local askpass_path
    askpass_path="$(wrapper_git_askpass_path)"

    if [[ -x "$askpass_path" ]]; then
        return 0
    fi

    cat >"$askpass_path" <<'EOF'
#!/bin/sh
prompt="${1:-}"
if printf '%s' "$prompt" | grep -qi 'username'; then
    printf '%s\n' "${MDS_GIT_AUTH_USERNAME:-x-access-token}"
    exit 0
fi
if [ -n "${MDS_GIT_AUTH_TOKEN_FILE:-}" ] && [ -r "${MDS_GIT_AUTH_TOKEN_FILE}" ]; then
    tr -d '\r\n' < "${MDS_GIT_AUTH_TOKEN_FILE}"
    exit 0
fi
printf '%s\n' "${MDS_GIT_AUTH_TOKEN:-}"
EOF

    chmod 700 "$askpass_path"
}

mds_git_ssh_command() {
    printf 'ssh -i %q -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new' "$SSH_KEY_PATH"
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
    echo -e "${WHITE}MAVSDK Drone Show - Companion Node Bootstrap${NC}"
    echo "================================================================"
    echo -e "Version:  ${WHITE}4.5.0${NC}"
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
            log_error "Unsupported OS: ${ID:-unknown}. Debian-family Linux required."
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

create_runtime_user() {
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

prepare_wrapper_repo_ssh_runtime() {
    local ssh_dir="/home/${MDS_USER}/.ssh"

    mkdir -p "$ssh_dir"
    chown "${MDS_USER}:${MDS_USER}" "$ssh_dir"
    chmod 700 "$ssh_dir"

    if [[ -f "$SSH_KEY_PATH" ]]; then
        chmod 600 "$SSH_KEY_PATH"
        chown "${MDS_USER}:${MDS_USER}" "$SSH_KEY_PATH"
    fi

    if [[ -f "${SSH_KEY_PATH}.pub" ]]; then
        chmod 644 "${SSH_KEY_PATH}.pub"
        chown "${MDS_USER}:${MDS_USER}" "${SSH_KEY_PATH}.pub"
    fi

    sudo -u "${MDS_USER}" bash -lc 'if ! grep -q "github.com" "$HOME/.ssh/known_hosts" 2>/dev/null; then ssh-keyscan -t ed25519 github.com >> "$HOME/.ssh/known_hosts" 2>/dev/null || true; fi'
}

wrapper_ssh_key_exists() {
    [[ -f "$SSH_KEY_PATH" ]]
}

generate_wrapper_deploy_key() {
    log_info "Preparing SSH deploy key for bootstrap..."

    if wrapper_ssh_key_exists; then
        log_success "Bootstrap SSH key already exists"
        return 0
    fi

    if wrapper_ssh_key_is_explicit; then
        log_error "Configured --git-ssh-key-file is not readable: ${SSH_KEY_PATH}"
        log_info "Provide an existing SSH private key file or omit --git-ssh-key-file to let the installer manage ${DEFAULT_SSH_KEY_PATH}"
        exit 1
    fi

    prepare_wrapper_repo_ssh_runtime

    sudo -u "${MDS_USER}" ssh-keygen -t rsa -b 4096 \
        -f "${SSH_KEY_PATH}" \
        -N "" \
        -C "mds-drone-deploy-$(hostname)" >/dev/null || {
        log_error "Failed to generate bootstrap SSH deploy key"
        exit 1
    }

    chmod 600 "${SSH_KEY_PATH}"
    chmod 644 "${SSH_KEY_PATH}.pub"
    chown "${MDS_USER}:${MDS_USER}" "${SSH_KEY_PATH}" "${SSH_KEY_PATH}.pub"
    log_success "Bootstrap SSH deploy key generated"
}

display_wrapper_deploy_key_instructions() {
    local repo_url="$1"

    echo ""
    echo -e "${CYAN}================================================================${NC}"
    echo -e "${WHITE}GitHub deploy key authorization is required before the first private clone.${NC}"
    echo -e "${CYAN}================================================================${NC}"
    echo ""
    echo -e "${WHITE}Repository:${NC} ${repo_url}"
    echo -e "${WHITE}Key path:${NC} ${SSH_KEY_PATH}.pub"
    echo ""
    if [[ -f "${SSH_KEY_PATH}.pub" ]]; then
        cat "${SSH_KEY_PATH}.pub"
        echo ""
    fi
    echo "GitHub path: Settings -> Deploy keys -> Add deploy key"
    echo "Title: mds-drone-$(hostname)"
    echo "Allow write access: enable only if this node must push."
    echo ""
}

test_wrapper_ssh_connection() {
    local output

    prepare_wrapper_repo_ssh_runtime
    output=$(sudo -u "${MDS_USER}" ssh -T \
        -o StrictHostKeyChecking=accept-new \
        -o BatchMode=yes \
        -o ConnectTimeout=10 \
        -o IdentitiesOnly=yes \
        -i "${SSH_KEY_PATH}" git@github.com 2>&1) || true

    echo "$output" | grep -qi "successfully authenticated"
}

ensure_wrapper_repo_access() {
    local repo_url="$1"

    if is_github_https_repo_url "$repo_url"; then
        if wrapper_git_auth_enabled; then
            prepare_wrapper_git_askpass
            log_success "Bootstrap HTTPS git auth configured"
        else
            log_warn "No git auth token configured. Public HTTPS repos will work, but private HTTPS repos require MDS_GIT_AUTH_TOKEN_FILE or MDS_GIT_AUTH_TOKEN."
        fi
        return 0
    fi

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
        log_error "Non-interactive bootstrap cannot continue until the deploy key is authorized on GitHub"
        log_info "Authorize ${SSH_KEY_PATH}.pub on the target repository, then rerun the same bootstrap command"
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

run_git_as_mds_user() {
    local repo_url="$1"
    shift

    if is_github_ssh_repo_url "$repo_url"; then
        sudo -u "${MDS_USER}" env GIT_SSH_COMMAND="$(mds_git_ssh_command)" git "$@"
    elif is_github_https_repo_url "$repo_url" && wrapper_git_auth_enabled; then
        prepare_wrapper_git_askpass
        sudo -u "${MDS_USER}" env \
            GIT_TERMINAL_PROMPT=0 \
            GIT_ASKPASS_REQUIRE=force \
            GIT_ASKPASS="$(wrapper_git_askpass_path)" \
            MDS_GIT_AUTH_USERNAME="${GIT_AUTH_USERNAME}" \
            MDS_GIT_AUTH_TOKEN_FILE="${GIT_AUTH_TOKEN_FILE:-}" \
            MDS_GIT_AUTH_TOKEN="${GIT_AUTH_TOKEN:-}" \
            git -c credential.username="${GIT_AUTH_USERNAME}" "$@"
    else
        sudo -u "${MDS_USER}" git "$@"
    fi
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

        local current_remote
        current_remote=$(sudo -u "${MDS_USER}" git -C "$INSTALL_DIR" remote get-url origin 2>/dev/null || echo "")
        if [[ -n "$current_remote" && "$current_remote" != "$REPO_URL" ]]; then
            log_info "Updating repository remote to requested bootstrap target"
            run_git_as_mds_user "$REPO_URL" -C "$INSTALL_DIR" remote set-url origin "$REPO_URL" || {
                log_error "Failed to update repository remote"
                exit 1
            }
        fi

        if is_github_ssh_repo_url "$REPO_URL"; then
            run_git_as_mds_user "$REPO_URL" -C "$INSTALL_DIR" config core.sshCommand "$(mds_git_ssh_command)" || true
        else
            sudo -u "${MDS_USER}" git -C "$INSTALL_DIR" config --unset-all core.sshCommand >/dev/null 2>&1 || true
        fi

        run_git_as_mds_user "$REPO_URL" -C "$INSTALL_DIR" fetch origin "$BRANCH" || {
            log_error "Failed to fetch repository"
            exit 1
        }
        run_git_as_mds_user "$REPO_URL" -C "$INSTALL_DIR" checkout "$BRANCH" 2>/dev/null || \
            run_git_as_mds_user "$REPO_URL" -C "$INSTALL_DIR" checkout -b "$BRANCH" "origin/$BRANCH"
        run_git_as_mds_user "$REPO_URL" -C "$INSTALL_DIR" reset --hard "origin/$BRANCH"
    else
        # Clone as the runtime MDS user
        run_git_as_mds_user "$REPO_URL" clone -b "$BRANCH" "$REPO_URL" "$INSTALL_DIR" || {
            log_error "Failed to clone repository"
            exit 1
        }
        if is_github_ssh_repo_url "$REPO_URL"; then
            run_git_as_mds_user "$REPO_URL" -C "$INSTALL_DIR" config core.sshCommand "$(mds_git_ssh_command)" || true
        fi
    fi

    log_success "Repository ready"
}

# =============================================================================
# RUN INIT SCRIPT
# =============================================================================

run_init_script() {
    local init_script="${INSTALL_DIR}/tools/mds_node_init.sh"

    if [[ ! -f "$init_script" ]]; then
        log_error "Init script not found: $init_script"
        exit 1
    fi

    chmod +x "$init_script"

    log_info "Running MDS initialization script..."
    echo ""
    echo -e "${CYAN}================================================================${NC}"
    echo -e "${WHITE}Handing off to mds_node_init.sh...${NC}"
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
    cat <<EOF
MDS Companion Node Bootstrap Installer (v4.5.0)

USAGE:
    curl -fsSL <url> | sudo bash
    curl -fsSL <url> | sudo bash -s -- [OPTIONS]

BOOTSTRAP OPTIONS:
    --branch BRANCH     Git branch to use (default: ${BRANCH})
    --repo-url URL      Use an explicit repository URL for bootstrap and init
    --fork OWNER[/REPO] Use a GitHub fork or custom repo path
    --git-auth-token-file PATH
                        Read private HTTPS Git auth token from PATH
    --git-ssh-key-file PATH
                        Use an existing SSH private key file for private GitHub SSH access
    -h, --help          Show this help message

    All other options are passed to mds_node_init.sh

PASSTHROUGH OPTIONS (to mds_node_init.sh):
    -d, --drone-id ID   Hardware ID for this drone (1-999)
    -y, --yes           Non-interactive mode
    --https             Use HTTPS for git operations
    --netbird-key KEY   Netbird VPN setup key
    --static-ip IP      Static IP address (CIDR format)
    --gcs-api-url URL   Explicit GCS API base URL for candidate announce
    --connectivity-backend NAME
                        Connectivity backend: none|smart-wifi-manager
    --smart-wifi-mode MODE
                        Smart Wi-Fi Manager mode: manage|observe|disabled
    --smart-wifi-config PATH
                        Smart Wi-Fi Manager JSON profile to import
    --report-json PATH  Write machine-readable bootstrap report to PATH ('-' = stdout)
    --announce-report-json PATH  Write candidate-announce report to PATH ('-' = stdout)
    --dry-run           Show what would be done

    See mds_node_init.sh --help for all options

ENVIRONMENT VARIABLES:
    MDS_REPO_URL        Git repository URL
    MDS_BRANCH          Git branch
    MDS_USER            Runtime user created for the companion node (default: ${MDS_USER})
    MDS_INSTALL_DIR     Installation directory for the repo checkout (default: ${INSTALL_DIR})
    MDS_GIT_AUTH_TOKEN_FILE
                        Preferred private HTTPS Git token file
    MDS_GIT_SSH_KEY_FILE
                        Existing SSH private key file for private GitHub SSH access

EXAMPLES:
    # Basic installation (interactive)
    curl -fsSL ${DEFAULT_INSTALL_COMPANION_URL} | sudo bash

    # Compatibility alias
    curl -fsSL ${DEFAULT_INSTALL_NODE_URL} | sudo bash

    # With drone ID (non-interactive)
    curl -fsSL ... | sudo bash -s -- -d 1 -y

    # Use your own fork
    curl -fsSL ... | sudo bash -s -- --fork myusername -d 1 -y

    # Use a customer org/private repo path
    curl -fsSL ... | sudo bash -s -- --fork myorg/customer-mds -d 1 -y

    # Use an explicit repository URL
    curl -fsSL ... | sudo bash -s -- --repo-url https://github.com/myorg/customer-mds.git --branch customer-demo -d 1 -y

    # Private HTTPS with token file
    curl -fsSL ... | sudo bash -s -- --repo-url https://github.com/myorg/customer-mds.git --branch customer-demo --git-auth-token-file /home/${MDS_USER}/.mds_git_read_token -d 1 -y

    # Private SSH with an existing read-only deploy or machine-user key
    curl -fsSL ... | sudo bash -s -- --repo-url git@github.com:myorg/customer-mds.git --branch customer-demo --git-ssh-key-file /home/${MDS_USER}/.ssh/customer_git_read_key -d 1 -y

    # Custom runtime user and install directory
    curl -fsSL ... | sudo env MDS_USER=companion MDS_INSTALL_DIR=/srv/${DEFAULT_PROJECT_NAME} bash -s -- -d 1 -y

    # Custom branch
    curl -fsSL ... | sudo bash -s -- --branch develop -d 1 -y

    # Full setup with VPN
    curl -fsSL ... | sudo bash -s -- -d 5 --netbird-key "XXXXX" -y

    # Explicit GCS API URL for enrollment announce
    curl -fsSL ... | sudo bash -s -- -d 5 --gcs-api-url https://gcs.example/api -y

WHAT THIS SCRIPT DOES:
    1. Creates '${MDS_USER}' user if needed
    2. Installs git, curl, jq prerequisites
    3. Clones the MDS repository
    4. Runs the full mds_node_init.sh initialization

For more information: ${DEFAULT_REPO_WEB_URL}
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
            --git-auth-token-file)
                GIT_AUTH_TOKEN_FILE="$2"
                passthrough_args+=("--git-auth-token-file" "$2")
                shift 2
                ;;
            --git-ssh-key-file)
                GIT_SSH_KEY_FILE="$2"
                set_wrapper_ssh_key_path
                passthrough_args+=("--git-ssh-key-file" "$2")
                shift 2
                ;;
            -y|--yes)
                WRAPPER_NON_INTERACTIVE="true"
                passthrough_args+=("$1")
                shift
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
        BRANCH="$explicit_branch"
    fi

    export MDS_BRANCH="$BRANCH"
    passthrough_args+=("--branch" "$BRANCH")

    export MDS_REPO_URL="$config_repo_url"
    passthrough_args+=("--repo-url" "$config_repo_url")
    if [[ -n "${GIT_AUTH_TOKEN_FILE:-}" ]]; then
        export MDS_GIT_AUTH_TOKEN_FILE="$GIT_AUTH_TOKEN_FILE"
    fi
    if [[ -n "${GIT_AUTH_TOKEN:-}" ]]; then
        export MDS_GIT_AUTH_TOKEN="$GIT_AUTH_TOKEN"
    fi
    if [[ -n "${GIT_SSH_KEY_FILE:-}" ]]; then
        export MDS_GIT_SSH_KEY_FILE="$GIT_SSH_KEY_FILE"
    fi
    export MDS_GIT_AUTH_USERNAME="$GIT_AUTH_USERNAME"

    print_banner

    log_info "Starting companion-node bootstrap installation..."
    log_info "Date: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""

    # System checks
    check_root
    check_os
    check_architecture

    echo ""

    # Setup
    create_runtime_user
    install_prerequisites
    ensure_wrapper_repo_access "$REPO_URL"
    clone_repository

    echo ""

    # Run init script with passthrough args
    run_init_script "${passthrough_args[@]}"
}

if [[ "${BASH_SOURCE[0]-$0}" == "$0" ]]; then
    main "$@"
fi
