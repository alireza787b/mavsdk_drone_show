#!/bin/bash
# =============================================================================
# MDS Raspberry Pi Initialization Script
# =============================================================================
# Version: 4.5.0
# Description: Production-ready, enterprise-grade initialization for drone swarm nodes
# Author: MDS Team
# Repository: https://github.com/alireza787b/mavsdk_drone_show
#
# This script initializes a fresh Raspberry Pi for use in the MDS drone swarm
# platform. It handles all aspects of setup including:
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
# Usage: sudo ./mds_init.sh [OPTIONS]
#
# For detailed help: ./mds_init.sh --help
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
source_library "verify.sh"

# =============================================================================
# GLOBAL VARIABLES
# =============================================================================

# Configuration (set via CLI or defaults)
DRONE_ID=""
REPO_URL="${MDS_REPO_URL:-}"
BRANCH="${MDS_BRANCH:-}"
USE_HTTPS="false"
NETBIRD_KEY=""
NETBIRD_URL=""
STATIC_IP=""
GATEWAY=""
GCS_IP=""
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

# MAVLink Configuration (NEW in v4.5)
MAVLINK_AUTO="false"
MAVLINK_SKIP="false"
MAVLINK_UART=""
MAVLINK_BAUD="57600"
MAVLINK_ENDPOINTS=""
MAVLINK_INPUT_TYPE="uart"
MAVLINK_INPUT_PORT="14550"

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
MDS Raspberry Pi Initialization Script v4.5.0

USAGE:
    sudo ./mds_init.sh [OPTIONS]

DESCRIPTION:
    Initialize a Raspberry Pi for the MDS drone swarm platform.
    Handles all aspects of setup from fresh Raspbian OS to production-ready node.

REQUIRED (interactive prompts if missing):
    -d, --drone-id ID           Hardware ID for this drone (1-999)

REPOSITORY OPTIONS:
    -r, --repo-url URL          Git repository URL
                                Default: git@github.com:alireza787b/mavsdk_drone_show.git
    -b, --branch BRANCH         Git branch to use
                                Default: main-candidate
    --fork OWNER[/REPO]         Use GitHub fork or custom repo path
    --https                     Use HTTPS instead of SSH for git operations

OPTIONAL COMPONENTS:
    --netbird-key KEY           Netbird VPN setup key
    --netbird-url URL           Netbird management URL
    --static-ip IP/CIDR         Static IP address (e.g., 192.168.1.42/24)
    --gateway IP                Gateway for static IP
    --gcs-ip IP                 Override GCS IP address

MAVSDK OPTIONS:
    --mavsdk-version VERSION    Specific MAVSDK version (e.g., v3.15.0)
                                Default: auto-detect latest
    --mavsdk-url URL            Direct URL to MAVSDK binary (overrides version)

MAVLINK-ROUTER OPTIONS (NEW in v4.5):
    --mavlink-auto              Auto-configure mavlink-router (recommended)
    --mavlink-skip              Skip mavlink-router setup entirely
    --mavlink-uart DEVICE       UART device (e.g., /dev/ttyS0)
    --mavlink-baud RATE         Baud rate (default: 57600)
    --mavlink-endpoints LIST    Comma-separated endpoints
    --mavlink-input TYPE        Input type: uart (default) or udp
    --mavlink-input-port PORT   UDP input port (default: 14550)

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
    --resume                    Resume from last checkpoint
    --force                     Force re-run all phases (ignore state)
    -v, --verbose               Verbose output
    --debug                     Debug output (very verbose)
    -h, --help                  Show this help message

EXAMPLES:
    # Interactive setup
    sudo ./mds_init.sh

    # Non-interactive with drone ID
    sudo ./mds_init.sh -d 42 -y

    # Custom fork with HTTPS (using --fork shorthand)
    sudo ./mds_init.sh -d 1 --fork myuser --branch main

    # Custom org/private repo path (using --fork shorthand)
    sudo ./mds_init.sh -d 1 --fork myorg/customer-mds --branch main-candidate

    # Or with full URL
    sudo ./mds_init.sh -d 1 --https -r https://github.com/myuser/myfork.git -b main

    # Full setup with VPN and static IP
    sudo ./mds_init.sh -d 5 --netbird-key "XXXXX" --static-ip 192.168.1.105/24 --gateway 192.168.1.1

    # Auto-configure mavlink-router with GCS IP (NEW)
    sudo ./mds_init.sh -d 1 -y --mavlink-auto --gcs-ip 100.96.32.75

    # Headless mavlink configuration
    sudo ./mds_init.sh -d 1 -y --mavlink-uart /dev/ttyS0 --mavlink-endpoints "127.0.0.1:14540,127.0.0.1:14569"

    # Dry run to see what would happen
    sudo ./mds_init.sh -d 1 --dry-run

    # Resume interrupted installation
    sudo ./mds_init.sh --resume

ENVIRONMENT VARIABLES:
    MDS_REPO_URL                Override repository URL
    MDS_BRANCH                  Override git branch
    MDS_GCS_IP                  Override GCS IP address

STATE FILE:
    /var/lib/mds/init_state.json    Persistent state tracking

CONFIG FILE:
    /etc/mds/local.env              Per-drone configuration

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
        --long drone-id:,repo-url:,branch:,fork:,https,netbird-key:,netbird-url:,static-ip:,gateway:,gcs-ip:,mavsdk-version:,mavsdk-url:,mavlink-auto,mavlink-skip,mavlink-uart:,mavlink-baud:,mavlink-endpoints:,mavlink-input:,mavlink-input-port:,skip-firewall,skip-netbird,skip-ntp,skip-services,skip-mavsdk,skip-venv,yes,dry-run,resume,force,verbose,debug,help \
        -n 'mds_init.sh' -- "$@") || {
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
            -y|--yes)
                NON_INTERACTIVE="true"
                shift
                ;;
            --dry-run)
                DRY_RUN="true"
                shift
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
    export DRONE_ID REPO_URL BRANCH USE_HTTPS
    export NETBIRD_KEY NETBIRD_URL STATIC_IP GATEWAY GCS_IP
    export MAVSDK_VERSION MAVSDK_URL
    export MAVLINK_AUTO MAVLINK_SKIP MAVLINK_UART MAVLINK_BAUD MAVLINK_ENDPOINTS
    export MAVLINK_INPUT_TYPE MAVLINK_INPUT_PORT
    export SKIP_FIREWALL SKIP_NETBIRD SKIP_NTP SKIP_SERVICES SKIP_MAVSDK SKIP_VENV
    export NON_INTERACTIVE DRY_RUN RESUME FORCE VERBOSE DEBUG
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
    "verify"
)

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
        verify)
            run_verify_phase || result=$?
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
    print_banner "${branch:-main-candidate}" "${commit:-pending}"

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
