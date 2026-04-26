#!/bin/bash
# =============================================================================
# MDS Companion Node Bootstrap Script
# =============================================================================
# Version: 4.5.0
# Description: Production-ready, enterprise-grade initialization for drone swarm nodes
# Author: MDS Team
# Repository: https://github.com/alireza787b/mavsdk_drone_show
#
# This script initializes a fresh Linux-based companion-computer node for use
# in the MDS drone swarm platform. It handles all aspects of setup including:
#   - Prerequisites and system validation
#   - mavlink-anywhere automated setup (NEW in v4.5)
#   - Repository cloning/updating with SSH key management
#   - Hardware identity configuration
#   - Firewall setup
#   - Python virtual environment
#   - MAVSDK binary installation
#   - Systemd service installation
#   - NTP time synchronization
#   - Optional: Netbird VPN, Static IP
#
# Usage: sudo ./mds_node_init.sh [OPTIONS]
#
# For detailed help: ./mds_node_init.sh --help
# =============================================================================

set -euo pipefail
IFS=$'\n\t'

# =============================================================================
# SCRIPT LOCATION
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/mds_init_lib"

# =============================================================================
# SOURCE LIBRARIES
# =============================================================================

source_library() {
    local lib="$1"
    local lib_path="${LIB_DIR}/${lib}"

    if [[ ! -f "$lib_path" ]]; then
        echo "Error: Library not found: $lib_path" >&2
        exit 1
    fi

    # shellcheck source=/dev/null
    source "$lib_path"
}

# Source all libraries
source_library "common.sh"
source_library "prereqs.sh"
source_library "mavlink_setup.sh"
source_library "repo.sh"
source_library "identity.sh"
source_library "firewall.sh"
source_library "python_env.sh"
source_library "mavsdk.sh"
source_library "services.sh"
source_library "network.sh"
source_library "connectivity.sh"
source_library "verify.sh"
source_library "announce.sh"

# =============================================================================
# GLOBAL VARIABLES
# =============================================================================

# Configuration (set via CLI or defaults)
DRONE_ID=""
REPO_URL="${MDS_REPO_URL:-}"
BRANCH="${MDS_BRANCH:-}"
USE_HTTPS="false"
GIT_AUTH_TOKEN_FILE="${MDS_GIT_AUTH_TOKEN_FILE:-}"
GIT_SSH_KEY_FILE="${MDS_GIT_SSH_KEY_FILE:-}"
NETBIRD_KEY=""
NETBIRD_URL=""
STATIC_IP=""
GATEWAY=""
GCS_IP=""
GCS_API_URL=""
MAVSDK_VERSION=""
MAVSDK_URL=""

# Flags
SKIP_FIREWALL="false"
SKIP_NETBIRD="false"
SKIP_NTP="false"
SKIP_SERVICES="false"
SKIP_MAVSDK="false"
SKIP_VENV="false"
NON_INTERACTIVE="false"
DRY_RUN="false"
RESUME="false"
FORCE="false"
VERBOSE="false"
DEBUG="false"
REPORT_JSON=""
ANNOUNCE_REPORT_JSON=""
ANNOUNCE_TIMEOUT_SEC="${DEFAULT_ANNOUNCE_TIMEOUT_SEC}"

# MAVLink Configuration (NEW in v4.5)
MAVLINK_AUTO="false"
MAVLINK_SKIP="false"
MAVLINK_UART=""
MAVLINK_BAUD="57600"
MAVLINK_ENDPOINTS=""
MAVLINK_INPUT_TYPE="uart"
MAVLINK_INPUT_PORT="14550"
MAVLINK_MANAGEMENT_MODE="${MDS_MAVLINK_MANAGEMENT_MODE:-${MDS_DEFAULT_MAVLINK_MANAGEMENT_MODE:-managed}}"
MAVLINK_ANYWHERE_REPO_URL="${MDS_MAVLINK_ANYWHERE_REPO_URL:-${MDS_DEFAULT_MAVLINK_ANYWHERE_REPO_URL_HTTPS:-https://github.com/${MDS_DEFAULT_MAVLINK_ANYWHERE_REPO_SLUG:-alireza787b/mavlink-anywhere}.git}}"
MAVLINK_ANYWHERE_REF="${MDS_MAVLINK_ANYWHERE_REF:-${MDS_DEFAULT_MAVLINK_ANYWHERE_REF:-v3.0.8}}"
MAVLINK_ANYWHERE_INSTALL_DIR="${MDS_MAVLINK_ANYWHERE_INSTALL_DIR:-${MDS_DEFAULT_MAVLINK_ANYWHERE_INSTALL_DIR:-/opt/mavlink-anywhere}}"
MAVLINK_ANYWHERE_DASHBOARD_LISTEN="${MDS_MAVLINK_ANYWHERE_DASHBOARD_LISTEN:-${MDS_DEFAULT_MAVLINK_ANYWHERE_DASHBOARD_LISTEN:-127.0.0.1:9070}}"
MAVLINK_ANYWHERE_SKIP_DASHBOARD="${MDS_MAVLINK_ANYWHERE_SKIP_DASHBOARD:-false}"
MAVLINK_ANYWHERE_REPO_URL_EXPLICIT="false"
MAVLINK_ANYWHERE_REF_EXPLICIT="false"
MAVLINK_MANAGEMENT_SELECTION_EXPLICIT="false"
MDS_CONNECTIVITY_BACKEND="${MDS_CONNECTIVITY_BACKEND:-${MDS_DEFAULT_CONNECTIVITY_BACKEND:-none}}"
SMART_WIFI_MANAGER_MODE="${MDS_SMART_WIFI_MANAGER_MODE:-${MDS_DEFAULT_SMART_WIFI_MANAGER_MODE:-observe}}"
SMART_WIFI_MANAGER_IMPORT_MODE="${MDS_SMART_WIFI_MANAGER_IMPORT_MODE:-${MDS_DEFAULT_SMART_WIFI_MANAGER_IMPORT_MODE:-replace}}"
SMART_WIFI_MANAGER_PROFILE_SOURCE="${MDS_SMART_WIFI_MANAGER_PROFILE_SOURCE:-}"
SMART_WIFI_MANAGER_CONFIG_FILE="${MDS_SMART_WIFI_MANAGER_CONFIG_FILE:-}"
SMART_WIFI_MANAGER_INSTALL_DIR="${MDS_SMART_WIFI_MANAGER_INSTALL_DIR:-${MDS_DEFAULT_SMART_WIFI_MANAGER_INSTALL_DIR:-/opt/smart-wifi-manager}}"
SMART_WIFI_MANAGER_DASHBOARD_LISTEN="${MDS_SMART_WIFI_MANAGER_DASHBOARD_LISTEN:-${MDS_DEFAULT_SMART_WIFI_MANAGER_DASHBOARD_LISTEN:-127.0.0.1:9080}}"
SMART_WIFI_MANAGER_SKIP_DASHBOARD="${MDS_SMART_WIFI_MANAGER_SKIP_DASHBOARD:-false}"
CONNECTIVITY_SELECTION_EXPLICIT="false"

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

enable_non_interactive_without_tty() {
    if [[ "${NON_INTERACTIVE}" != "true" ]] && ! { [[ -t 0 || -t 1 || -t 2 ]] && : </dev/tty >/dev/null 2>&1; }; then
        NON_INTERACTIVE="true"
    fi
    export NON_INTERACTIVE
}

# =============================================================================
# HELP TEXT
# =============================================================================

show_help() {
    cat << 'EOF'
MDS Companion Node Bootstrap Script v4.5.0

USAGE:
    sudo ./mds_node_init.sh [OPTIONS]

DESCRIPTION:
    Initialize a Linux-based companion-computer node for the MDS drone swarm
    platform. Handles all aspects of setup from a fresh Debian-family host to a
    production-ready node.

REQUIRED (interactive prompts if missing):
    -d, --drone-id ID           Hardware ID for this drone (1-999)

REPOSITORY OPTIONS:
    -r, --repo-url URL          Git repository URL
                                Default: git@github.com:alireza787b/mavsdk_drone_show.git
    -b, --branch BRANCH         Git branch to use
                                Default: main
    --fork OWNER[/REPO]         Use GitHub fork or custom repo path
    --https                     Use HTTPS instead of SSH for git operations
    --git-auth-token-file PATH  Preferred private HTTPS Git auth token file
    --git-ssh-key-file PATH     Existing SSH private key file for private GitHub SSH access

OPTIONAL COMPONENTS:
    --netbird-key KEY           Netbird VPN setup key
    --netbird-url URL           Netbird management URL
    --static-ip IP/CIDR         Static IP address (e.g., 192.168.1.42/24)
    --gateway IP                Gateway for static IP
    --gcs-ip IP                 Override GCS IP address
    --gcs-api-url URL           Override GCS API base URL for candidate announce
    --connectivity-backend NAME Connectivity backend: none|smart-wifi-manager
    --smart-wifi-mode MODE      Smart Wi-Fi Manager mode: manage|observe|disabled
    --smart-wifi-config PATH    Smart Wi-Fi Manager JSON profile to import
    --smart-wifi-import-mode M  Smart Wi-Fi import mode: replace|merge
    --smart-wifi-dashboard ADDR Smart Wi-Fi dashboard listen address
    --skip-smart-wifi-dashboard Install Smart Wi-Fi Manager without dashboard

MAVSDK OPTIONS:
    --mavsdk-version VERSION    Specific MAVSDK version (e.g., v3.15.0)
                                Default: auto-detect latest
    --mavsdk-url URL            Direct URL to MAVSDK binary (overrides version)

MAVLINK-ROUTER OPTIONS (NEW in v4.5):
    --mavlink-auto              Auto-configure mavlink-router with recommended defaults
    --mavlink-skip              Skip mavlink-router setup entirely
    --mavlink-uart DEVICE       UART device (e.g., /dev/ttyS0)
    --mavlink-baud RATE         Baud rate (default: 57600)
    --mavlink-endpoints LIST    Comma-separated endpoints
    --mavlink-input TYPE        Input type: uart (default) or udp
    --mavlink-input-port PORT   UDP input port (default: 14550)
    --mavlink-repo-url URL      Managed mavlink-anywhere repo URL override
    --mavlink-ref REF           Managed mavlink-anywhere git ref/tag override
    --mavlink-install-dir DIR   Managed mavlink-anywhere install directory
    --mavlink-dashboard ADDR    Dashboard listen address (default: 127.0.0.1:9070)
    --skip-mavlink-dashboard    Keep router managed but do not install/update dashboard

SKIP FLAGS:
    --skip-firewall             Skip UFW firewall configuration
    --skip-netbird              Skip Netbird VPN setup
    --skip-ntp                  Skip NTP time synchronization
    --skip-services             Skip systemd service installation
    --skip-mavsdk               Skip MAVSDK binary download
    --skip-venv                 Skip Python virtual environment setup

CONTROL OPTIONS:
    -y, --yes                   Non-interactive mode (use defaults)
    --dry-run                   Show what would be done without making changes
    --report-json PATH          Write machine-readable bootstrap report
                                Use '-' to print the report JSON to stdout
    --announce-report-json PATH Write candidate-announce report JSON
                                Use '-' to print the report JSON to stdout
    --announce-timeout SEC      Candidate-announce HTTP timeout (default: 15)
    --resume                    Resume from last checkpoint
    --force                     Force re-run all phases (ignore state)
    -v, --verbose               Verbose output
    --debug                     Debug output (very verbose)
    -h, --help                  Show this help message

EXAMPLES:
    # Interactive setup
    sudo ./mds_node_init.sh

    # Non-interactive with drone ID
    sudo ./mds_node_init.sh -d 42 -y

    # Custom fork with HTTPS (using --fork shorthand)
    sudo ./mds_node_init.sh -d 1 --fork myuser --branch main

    # Custom org/private repo path (using --fork shorthand)
    sudo ./mds_node_init.sh -d 1 --fork myorg/customer-mds --branch main

    # Or with full URL
    sudo ./mds_node_init.sh -d 1 --https -r https://github.com/myuser/myfork.git -b main

    # Full setup with VPN and static IP
    sudo ./mds_node_init.sh -d 5 --netbird-key "XXXXX" --static-ip 192.168.1.105/24 --gateway 192.168.1.1

    # Explicit GCS API URL for candidate announce
    sudo ./mds_node_init.sh -d 5 --gcs-api-url https://gcs.example/api -y

    # Install Smart Wi-Fi Manager in observe mode
    sudo ./mds_node_init.sh -d 5 --connectivity-backend smart-wifi-manager --smart-wifi-mode observe -y

    # Install Smart Wi-Fi Manager and import a local profile
    sudo ./mds_node_init.sh -d 5 --connectivity-backend smart-wifi-manager --smart-wifi-config /tmp/profile.json -y

    # Auto-configure mavlink-router with GCS IP (NEW)
    sudo ./mds_node_init.sh -d 1 -y --mavlink-auto --gcs-ip 100.96.32.75

    # Headless UART mavlink configuration
    sudo ./mds_node_init.sh -d 1 -y --mavlink-uart /dev/ttyS0 --mavlink-endpoints "127.0.0.1:14540,127.0.0.1:14569"

    # Pin managed mavlink-anywhere to a specific release tag
    sudo ./mds_node_init.sh -d 1 -y --mavlink-auto --mavlink-ref v3.0.8

    # Headless UDP-input mavlink configuration
    sudo ./mds_node_init.sh -d 1 -y --mavlink-input udp --mavlink-input-port 14550 --mavlink-endpoints "127.0.0.1:14540,127.0.0.1:14569,127.0.0.1:12550"

    # Dry run to see what would happen
    sudo ./mds_node_init.sh -d 1 --dry-run

    # Resume interrupted installation
    sudo ./mds_node_init.sh --resume

ENVIRONMENT VARIABLES:
    MDS_REPO_URL                Override repository URL
    MDS_BRANCH                  Override git branch
    MDS_GIT_AUTH_TOKEN_FILE     Preferred private HTTPS Git token file
    MDS_GIT_SSH_KEY_FILE        Existing SSH private key file for private GitHub SSH access
    MDS_GCS_IP                  Override GCS IP address
    MDS_GCS_API_BASE_URL        Override candidate-announce API base URL
    MDS_MAVLINK_MANAGEMENT_MODE Managed or manual mavlink-anywhere ownership
    MDS_MAVLINK_ANYWHERE_REPO_URL Managed mavlink-anywhere repo URL override
    MDS_MAVLINK_ANYWHERE_REF    Managed mavlink-anywhere ref/tag override
    MDS_MAVLINK_ANYWHERE_INSTALL_DIR Managed mavlink-anywhere install directory
    MDS_MAVLINK_ANYWHERE_DASHBOARD_LISTEN Managed dashboard listen address
    MDS_MAVLINK_ANYWHERE_SKIP_DASHBOARD Skip dashboard installation/update

STATE FILE:
    /var/lib/mds/init_state.json    Persistent state tracking

CONFIG FILE:
    /etc/mds/local.env              Per-node runtime overrides
    /etc/mds/node_identity.json     Structured node identity manifest

For more information, see: https://github.com/alireza787b/mavsdk_drone_show
EOF
}

# =============================================================================
# ARGUMENT PARSING
# =============================================================================

parse_args() {
    # Use getopt for proper argument parsing
    local PARSED_ARGS
    PARSED_ARGS=$(getopt -o d:r:b:yvh \
        --long drone-id:,repo-url:,branch:,fork:,https,git-auth-token-file:,git-ssh-key-file:,netbird-key:,netbird-url:,static-ip:,gateway:,gcs-ip:,gcs-api-url:,connectivity-backend:,smart-wifi-mode:,smart-wifi-config:,smart-wifi-import-mode:,smart-wifi-dashboard:,skip-smart-wifi-dashboard,mavsdk-version:,mavsdk-url:,mavlink-auto,mavlink-skip,mavlink-uart:,mavlink-baud:,mavlink-endpoints:,mavlink-input:,mavlink-input-port:,mavlink-repo-url:,mavlink-ref:,mavlink-install-dir:,mavlink-dashboard:,skip-mavlink-dashboard,skip-firewall,skip-netbird,skip-ntp,skip-services,skip-mavsdk,skip-venv,yes,dry-run,report-json:,announce-report-json:,announce-timeout:,resume,force,verbose,debug,help \
        -n 'mds_node_init.sh' -- "$@") || {
        echo "Error: Invalid arguments. Use --help for usage." >&2
        exit 1
    }

    eval set -- "$PARSED_ARGS"

    while true; do
        case "$1" in
            -d|--drone-id)
                DRONE_ID="$2"
                shift 2
                ;;
            -r|--repo-url)
                REPO_URL="$2"
                shift 2
                ;;
            -b|--branch)
                BRANCH="$2"
                shift 2
                ;;
            --fork)
                local repo_path
                repo_path=$(normalize_github_repo_path "$2") || {
                    echo "Error: Invalid --fork value '$2'" >&2
                    exit 1
                }
                # Use SSH by default for writable hardware deployments.
                REPO_URL="git@github.com:${repo_path}.git"
                shift 2
                ;;
            --https)
                USE_HTTPS="true"
                shift
                ;;
            --git-auth-token-file)
                GIT_AUTH_TOKEN_FILE="$2"
                shift 2
                ;;
            --git-ssh-key-file)
                GIT_SSH_KEY_FILE="$2"
                MDS_GIT_SSH_KEY_FILE="$2"
                if declare -F sync_node_ssh_key_path >/dev/null 2>&1; then
                    sync_node_ssh_key_path
                fi
                shift 2
                ;;
            --netbird-key)
                NETBIRD_KEY="$2"
                shift 2
                ;;
            --netbird-url)
                NETBIRD_URL="$2"
                shift 2
                ;;
            --static-ip)
                STATIC_IP="$2"
                shift 2
                ;;
            --gateway)
                GATEWAY="$2"
                shift 2
                ;;
            --gcs-ip)
                GCS_IP="$2"
                shift 2
                ;;
            --gcs-api-url)
                GCS_API_URL="$2"
                shift 2
                ;;
            --connectivity-backend)
                MDS_CONNECTIVITY_BACKEND="$2"
                CONNECTIVITY_SELECTION_EXPLICIT="true"
                shift 2
                ;;
            --smart-wifi-mode)
                SMART_WIFI_MANAGER_MODE="$2"
                CONNECTIVITY_SELECTION_EXPLICIT="true"
                shift 2
                ;;
            --smart-wifi-config)
                SMART_WIFI_MANAGER_CONFIG_FILE="$2"
                SMART_WIFI_MANAGER_PROFILE_SOURCE="file:$2"
                MDS_CONNECTIVITY_BACKEND="smart-wifi-manager"
                CONNECTIVITY_SELECTION_EXPLICIT="true"
                shift 2
                ;;
            --smart-wifi-import-mode)
                SMART_WIFI_MANAGER_IMPORT_MODE="$2"
                CONNECTIVITY_SELECTION_EXPLICIT="true"
                shift 2
                ;;
            --smart-wifi-dashboard)
                SMART_WIFI_MANAGER_DASHBOARD_LISTEN="$2"
                MDS_CONNECTIVITY_BACKEND="smart-wifi-manager"
                CONNECTIVITY_SELECTION_EXPLICIT="true"
                shift 2
                ;;
            --skip-smart-wifi-dashboard)
                SMART_WIFI_MANAGER_SKIP_DASHBOARD="true"
                MDS_CONNECTIVITY_BACKEND="smart-wifi-manager"
                CONNECTIVITY_SELECTION_EXPLICIT="true"
                shift
                ;;
            --mavsdk-version)
                MAVSDK_VERSION="$2"
                shift 2
                ;;
            --mavsdk-url)
                MAVSDK_URL="$2"
                shift 2
                ;;
            --skip-firewall)
                SKIP_FIREWALL="true"
                shift
                ;;
            --skip-netbird)
                SKIP_NETBIRD="true"
                shift
                ;;
            --skip-ntp)
                SKIP_NTP="true"
                shift
                ;;
            --skip-services)
                SKIP_SERVICES="true"
                shift
                ;;
            --skip-mavsdk)
                SKIP_MAVSDK="true"
                shift
                ;;
            --skip-venv)
                SKIP_VENV="true"
                shift
                ;;
            --mavlink-auto)
                MAVLINK_AUTO="true"
                shift
                ;;
            --mavlink-skip)
                MAVLINK_SKIP="true"
                shift
                ;;
            --mavlink-uart)
                MAVLINK_UART="$2"
                shift 2
                ;;
            --mavlink-baud)
                MAVLINK_BAUD="$2"
                shift 2
                ;;
            --mavlink-endpoints)
                MAVLINK_ENDPOINTS="$2"
                shift 2
                ;;
            --mavlink-input)
                MAVLINK_INPUT_TYPE="$2"
                shift 2
                ;;
            --mavlink-input-port)
                MAVLINK_INPUT_PORT="$2"
                shift 2
                ;;
            --mavlink-repo-url)
                MAVLINK_ANYWHERE_REPO_URL="$2"
                MAVLINK_ANYWHERE_REPO_URL_EXPLICIT="true"
                MAVLINK_MANAGEMENT_MODE="managed"
                MAVLINK_MANAGEMENT_SELECTION_EXPLICIT="true"
                shift 2
                ;;
            --mavlink-ref)
                MAVLINK_ANYWHERE_REF="$2"
                MAVLINK_ANYWHERE_REF_EXPLICIT="true"
                MAVLINK_MANAGEMENT_MODE="managed"
                MAVLINK_MANAGEMENT_SELECTION_EXPLICIT="true"
                shift 2
                ;;
            --mavlink-install-dir)
                MAVLINK_ANYWHERE_INSTALL_DIR="$2"
                MAVLINK_MANAGEMENT_MODE="managed"
                MAVLINK_MANAGEMENT_SELECTION_EXPLICIT="true"
                shift 2
                ;;
            --mavlink-dashboard)
                MAVLINK_ANYWHERE_DASHBOARD_LISTEN="$2"
                MAVLINK_MANAGEMENT_MODE="managed"
                MAVLINK_MANAGEMENT_SELECTION_EXPLICIT="true"
                shift 2
                ;;
            --skip-mavlink-dashboard)
                MAVLINK_ANYWHERE_SKIP_DASHBOARD="true"
                MAVLINK_MANAGEMENT_MODE="managed"
                MAVLINK_MANAGEMENT_SELECTION_EXPLICIT="true"
                shift
                ;;
            -y|--yes)
                NON_INTERACTIVE="true"
                shift
                ;;
            --dry-run)
                DRY_RUN="true"
                shift
                ;;
            --report-json)
                REPORT_JSON="$2"
                shift 2
                ;;
            --announce-report-json)
                ANNOUNCE_REPORT_JSON="$2"
                shift 2
                ;;
            --announce-timeout)
                ANNOUNCE_TIMEOUT_SEC="$2"
                shift 2
                ;;
            --resume)
                RESUME="true"
                shift
                ;;
            --force)
                FORCE="true"
                shift
                ;;
            -v|--verbose)
                VERBOSE="true"
                shift
                ;;
            --debug)
                DEBUG="true"
                VERBOSE="true"
                shift
                ;;
            -h|--help)
                show_help
                exit 0
                ;;
            --)
                shift
                break
                ;;
            *)
                echo "Error: Unknown option: $1" >&2
                exit 1
                ;;
        esac
    done

    # Export all configuration for use by libraries
    export DRONE_ID REPO_URL BRANCH USE_HTTPS GIT_AUTH_TOKEN_FILE GIT_SSH_KEY_FILE
    export NETBIRD_KEY NETBIRD_URL STATIC_IP GATEWAY GCS_IP GCS_API_URL
    export MDS_CONNECTIVITY_BACKEND SMART_WIFI_MANAGER_MODE SMART_WIFI_MANAGER_IMPORT_MODE
    export SMART_WIFI_MANAGER_PROFILE_SOURCE SMART_WIFI_MANAGER_CONFIG_FILE
    export SMART_WIFI_MANAGER_INSTALL_DIR SMART_WIFI_MANAGER_DASHBOARD_LISTEN
    export SMART_WIFI_MANAGER_SKIP_DASHBOARD CONNECTIVITY_SELECTION_EXPLICIT
    export MAVSDK_VERSION MAVSDK_URL
    export MAVLINK_AUTO MAVLINK_SKIP MAVLINK_UART MAVLINK_BAUD MAVLINK_ENDPOINTS
    export MAVLINK_INPUT_TYPE MAVLINK_INPUT_PORT
    export MAVLINK_MANAGEMENT_MODE MAVLINK_ANYWHERE_REPO_URL MAVLINK_ANYWHERE_REF
    export MAVLINK_ANYWHERE_INSTALL_DIR MAVLINK_ANYWHERE_DASHBOARD_LISTEN MAVLINK_ANYWHERE_SKIP_DASHBOARD
    export MAVLINK_ANYWHERE_REPO_URL_EXPLICIT MAVLINK_ANYWHERE_REF_EXPLICIT MAVLINK_MANAGEMENT_SELECTION_EXPLICIT
    export SKIP_FIREWALL SKIP_NETBIRD SKIP_NTP SKIP_SERVICES SKIP_MAVSDK SKIP_VENV
    export NON_INTERACTIVE DRY_RUN REPORT_JSON ANNOUNCE_REPORT_JSON ANNOUNCE_TIMEOUT_SEC RESUME FORCE VERBOSE DEBUG
}

# =============================================================================
# PHASE MANAGEMENT
# =============================================================================

# Phase definitions
declare -a PHASES=(
    "prereqs"
    "mavlink_setup"
    "repository"
    "identity"
    "environment"
    "firewall"
    "python_env"
    "mavsdk"
    "services"
    "ntp"
    "netbird"
    "static_ip"
    "connectivity"
    "verify"
    "candidate_announce"
)

MDS_TOTAL_PHASES="${#PHASES[@]}"

# Run a specific phase
run_phase() {
    local phase="$1"

    # Check if phase should be skipped (resume mode)
    if [[ "$RESUME" == "true" ]]; then
        local status
        status=$(state_get_phase "$phase")

        if [[ "$status" == "completed" ]]; then
            log_info "Skipping ${phase} (already completed)"
            return 0
        fi
    fi

    # Mark phase as in progress
    state_set_phase "$phase" "in_progress"

    # Run the phase
    local result=0
    case "$phase" in
        prereqs)
            run_prereqs_phase || result=$?
            ;;
        mavlink_setup)
            run_mavlink_setup_phase || result=$?
            ;;
        repository)
            run_repository_phase || result=$?
            ;;
        identity)
            run_identity_phase || result=$?
            ;;
        environment)
            # Environment is handled within identity phase
            log_info "Environment configured in identity phase"
            ;;
        firewall)
            run_firewall_phase || result=$?
            ;;
        python_env)
            run_python_env_phase || result=$?
            ;;
        mavsdk)
            run_mavsdk_phase || result=$?
            ;;
        services)
            run_services_phase || result=$?
            ;;
        ntp)
            run_ntp_phase || result=$?
            ;;
        netbird)
            run_netbird_phase || result=$?
            ;;
        static_ip)
            run_static_ip_phase || result=$?
            ;;
        connectivity)
            run_connectivity_phase || result=$?
            ;;
        verify)
            run_verify_phase || result=$?
            ;;
        candidate_announce)
            run_candidate_announce_phase || result=$?
            ;;
        *)
            log_error "Unknown phase: $phase"
            result=1
            ;;
    esac

    # Mark phase status
    if [[ $result -eq 0 ]]; then
        state_set_phase "$phase" "completed"
    else
        state_set_phase "$phase" "failed"
    fi

    return $result
}

# Run all phases
run_all_phases() {
    local failed=0

    for phase in "${PHASES[@]}"; do
        if ! run_phase "$phase"; then
            log_error "Phase failed: $phase"

            # Critical phases should stop execution
            case "$phase" in
                prereqs|repository)
                    log_error "Critical phase failed. Cannot continue."
                    return 1
                    ;;
                *)
                    ((failed++))
                    if [[ "${NON_INTERACTIVE:-false}" != "true" ]]; then
                        if ! confirm "Continue despite failure?" "y"; then
                            return 1
                        fi
                    fi
                    ;;
            esac
        fi
    done

    return $failed
}

# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

main() {
    # Parse command line arguments
    parse_args "$@"
    enable_non_interactive_without_tty

    # Initialize logging
    init_logging

    # Setup signal handlers
    trap 'error_handler $LINENO' ERR
    trap cleanup_handler EXIT

    # Check root access
    if ! check_root; then
        echo "Error: This script must be run as root (use sudo)" >&2
        exit 1
    fi

    # Initialize state
    state_init

    # Get git info if available
    local git_info branch commit git_date
    if [[ -d "${SCRIPT_DIR}/../.git" ]]; then
        git_info=$(get_git_info "${SCRIPT_DIR}/.." 2>/dev/null || echo "unknown|unknown|unknown")
        IFS='|' read -r branch commit git_date <<< "$git_info"
    fi

    # Show banner with version info
    print_banner "${branch:-main}" "${commit:-pending}"

    log_info "Initialization started: $(date '+%Y-%m-%d %H:%M:%S')"
    log_info "Script version: ${MDS_VERSION}"

    # Show mode indicators
    echo ""
    [[ "$DRY_RUN" == "true" ]] && echo -e "  ${YELLOW}[DRY-RUN MODE]${NC} No changes will be made"
    [[ "$RESUME" == "true" ]] && echo -e "  ${CYAN}[RESUME MODE]${NC} Continuing from last checkpoint"
    [[ "$NON_INTERACTIVE" == "true" ]] && echo -e "  ${CYAN}[NON-INTERACTIVE]${NC} Using defaults for all prompts"
    [[ "$VERBOSE" == "true" ]] && echo -e "  ${CYAN}[VERBOSE]${NC} Extended output enabled"
    echo ""

    # Log start
    log_info "MDS initialization started"
    log_info "Script version: ${MDS_VERSION}"
    log_info "Arguments: $*"

    # Run all phases
    local exit_code=0
    if ! run_all_phases; then
        exit_code=1
        set_led_state "ERROR_GENERAL"
    fi

    # Final status
    echo ""
    if [[ $exit_code -eq 0 ]]; then
        write_node_identity_manifest "${DRONE_ID:-$(state_get_value hw_id "")}" "completed" || true
    else
        write_node_identity_manifest "${DRONE_ID:-$(state_get_value hw_id "")}" "completed_with_errors" || true
    fi
    write_bootstrap_report "$exit_code" || true

    if [[ $exit_code -eq 0 ]]; then
        log_success "MDS initialization completed successfully!"
        set_led_state "STARTUP_COMPLETE"
    else
        log_error "MDS initialization completed with errors"
    fi

    exit $exit_code
}

# =============================================================================
# RUN MAIN
# =============================================================================

main "$@"
