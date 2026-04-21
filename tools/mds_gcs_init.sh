#!/bin/bash
# =============================================================================
# MDS GCS Initialization Script
# =============================================================================
# Version: Reads from VERSION file
# Description: Enterprise GCS (Ground Control Station) initialization script
#              Configures VPS/Ubuntu systems for MDS GCS operation
# Author: MDS Team
# License: MIT
# =============================================================================
#
# Usage:
#   sudo ./mds_gcs_init.sh [options]
#
# Examples:
#   sudo ./mds_gcs_init.sh                     # Interactive configuration
#   sudo ./mds_gcs_init.sh -y                  # Non-interactive with defaults
#   sudo ./mds_gcs_init.sh --run               # Run mode (start services)
#   sudo ./mds_gcs_init.sh --dry-run -y        # Show what would be done
#   sudo ./mds_gcs_init.sh --resume            # Resume from last checkpoint
#
# =============================================================================

set -euo pipefail

# =============================================================================
# SCRIPT INITIALIZATION
# =============================================================================

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GCS_LIB_DIR="${SCRIPT_DIR}/mds_gcs_init_lib"

# Source common library first
if [[ -f "${GCS_LIB_DIR}/gcs_common.sh" ]]; then
    source "${GCS_LIB_DIR}/gcs_common.sh"
else
    echo "ERROR: Cannot find GCS library at: ${GCS_LIB_DIR}/gcs_common.sh" >&2
    exit 1
fi

# Source all GCS library modules
for lib in "${GCS_LIB_DIR}"/gcs_*.sh; do
    if [[ -f "$lib" ]] && [[ "$lib" != *"gcs_common.sh" ]]; then
        source "$lib" || {
            echo "ERROR: Failed to source library: $lib" >&2
            exit 1
        }
    fi
done

# =============================================================================
# GLOBAL VARIABLES
# =============================================================================

# Mode selection
MODE="configure"  # configure or run

# Repository options
REPO_URL="${MDS_REPO_URL:-}"
BRANCH="${MDS_BRANCH:-}"
USE_HTTPS="false"
GIT_AUTH_TOKEN_FILE="${MDS_GIT_AUTH_TOKEN_FILE:-}"
GIT_SSH_KEY_FILE="${MDS_GIT_SSH_KEY_FILE:-}"

# Installation options
GCS_INSTALL_DIR=""

# Skip flags
SKIP_PREREQS="false"
SKIP_PYTHON="false"
SKIP_NODEJS="false"
SKIP_REPO="false"
SKIP_FIREWALL="false"
SKIP_PYTHON_ENV="false"
SKIP_NODEJS_ENV="false"
SKIP_ENV_CONFIG="false"

# Control options
NON_INTERACTIVE="false"
DRY_RUN="false"
RESUME="false"
FORCE="false"
VERBOSE="false"
DEBUG="false"

# Export all for libraries
export MODE REPO_URL BRANCH USE_HTTPS GIT_AUTH_TOKEN_FILE GIT_SSH_KEY_FILE GCS_INSTALL_DIR
export SKIP_PREREQS SKIP_PYTHON SKIP_NODEJS SKIP_REPO SKIP_FIREWALL
export SKIP_PYTHON_ENV SKIP_NODEJS_ENV SKIP_ENV_CONFIG
export NON_INTERACTIVE DRY_RUN RESUME FORCE VERBOSE DEBUG

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
    cat << EOF
MDS GCS Initialization Script v${GCS_VERSION}

USAGE:
    sudo ./mds_gcs_init.sh [OPTIONS]

DESCRIPTION:
    Configures a fresh VPS or Ubuntu system for MDS Ground Control Station
    operation. Handles Python, Node.js, repository, firewall, and environment
    setup.

MODE SELECTION:
    --configure         Configure mode (default) - full setup
    --run               Run mode - guide to startup script

REPOSITORY OPTIONS:
    -r, --repo-url URL  Git repository URL
    -b, --branch BRANCH Git branch (default: main-candidate)
    --https             Use HTTPS instead of SSH for git
    --git-auth-token-file PATH
                        Preferred private HTTPS Git auth token file
    --git-ssh-key-file PATH
                        Existing SSH private key file for private GitHub SSH access

INSTALLATION OPTIONS:
    --install-dir PATH  Installation directory (default: current directory)

SKIP FLAGS:
    --skip-prereqs      Skip prerequisites check
    --skip-python       Skip Python installation
    --skip-nodejs       Skip Node.js installation
    --skip-repo         Skip repository setup
    --skip-firewall     Skip firewall configuration
    --skip-python-env   Skip Python venv setup
    --skip-nodejs-env   Skip dashboard npm dependency install
    --skip-env-config   Skip .env configuration

CONTROL OPTIONS:
    -y, --yes           Non-interactive mode (accept defaults)
    --dry-run           Show what would be done without making changes
    --resume            Resume from last checkpoint
    --force             Force re-run all phases (ignore state)
    -v, --verbose       Verbose output
    --debug             Debug output (very verbose)
    -h, --help          Show this help message

EXAMPLES:
    # Interactive configuration (recommended for first run)
    sudo ./mds_gcs_init.sh

    # Non-interactive with defaults
    sudo ./mds_gcs_init.sh -y

    # Custom repository and branch
    sudo ./mds_gcs_init.sh -r git@github.com:user/repo.git -b develop

    # Use HTTPS (no SSH key required, but no git sync)
    sudo ./mds_gcs_init.sh --https -y

    # Skip specific phases
    sudo ./mds_gcs_init.sh --skip-firewall --skip-nodejs-env

    # Dry run to see what would happen
    sudo ./mds_gcs_init.sh --dry-run -y

    # Resume after interruption
    sudo ./mds_gcs_init.sh --resume

    # Run mode (after configuration)
    sudo ./mds_gcs_init.sh --run

PHASES:
    1. prereqs      - System validation, base packages
    2. python       - Python 3.11+ installation
    3. nodejs       - Node.js 22.x LTS installation
    4. repository   - Clone/update repository with SSH key
    5. firewall     - UFW with GCS ports
    6. python_env   - venv + requirements.txt
    7. nodejs_env   - npm ci for dashboard
    8. env_config   - .env file configuration
    9. verify       - Final verification

For more information, see: docs/guides/gcs-setup.md
EOF
}

# =============================================================================
# ARGUMENT PARSING
# =============================================================================

parse_arguments() {
    # Use getopt for robust argument parsing
    local PARSED_ARGS
    PARSED_ARGS=$(getopt -o r:b:yvh \
        --long configure,run \
        --long repo-url:,branch:,https,git-auth-token-file:,git-ssh-key-file: \
        --long install-dir: \
        --long skip-prereqs,skip-python,skip-nodejs,skip-repo,skip-firewall \
        --long skip-python-env,skip-nodejs-env,skip-env-config \
        --long yes,dry-run,resume,force,verbose,debug,help \
        -n 'mds_gcs_init.sh' -- "$@") || {
            echo "Error parsing arguments. Use --help for usage." >&2
            exit 1
        }

    eval set -- "$PARSED_ARGS"

    while true; do
        case "$1" in
            # Mode selection
            --configure)
                MODE="configure"
                shift
                ;;
            --run)
                MODE="run"
                shift
                ;;

            # Repository options
            -r|--repo-url)
                REPO_URL="$2"
                shift 2
                ;;
            -b|--branch)
                BRANCH="$2"
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
                if declare -F sync_gcs_ssh_key_paths >/dev/null 2>&1; then
                    sync_gcs_ssh_key_paths
                fi
                shift 2
                ;;

            # Installation options
            --install-dir)
                GCS_INSTALL_DIR="$2"
                shift 2
                ;;

            # Skip flags
            --skip-prereqs)
                SKIP_PREREQS="true"
                shift
                ;;
            --skip-python)
                SKIP_PYTHON="true"
                shift
                ;;
            --skip-nodejs)
                SKIP_NODEJS="true"
                shift
                ;;
            --skip-repo)
                SKIP_REPO="true"
                shift
                ;;
            --skip-firewall)
                SKIP_FIREWALL="true"
                shift
                ;;
            --skip-python-env)
                SKIP_PYTHON_ENV="true"
                shift
                ;;
            --skip-nodejs-env)
                SKIP_NODEJS_ENV="true"
                shift
                ;;
            --skip-env-config)
                SKIP_ENV_CONFIG="true"
                shift
                ;;

            # Control options
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
                echo "Unknown option: $1" >&2
                exit 1
                ;;
        esac
    done

    # Set defaults
    [[ -z "$BRANCH" ]] && BRANCH="$GCS_DEFAULT_BRANCH"
    [[ -z "$GCS_INSTALL_DIR" ]] && GCS_INSTALL_DIR="$(pwd)"

    # Export updated values
    export MODE REPO_URL BRANCH USE_HTTPS GIT_AUTH_TOKEN_FILE GIT_SSH_KEY_FILE GCS_INSTALL_DIR
    export SKIP_PREREQS SKIP_PYTHON SKIP_NODEJS SKIP_REPO SKIP_FIREWALL
    export SKIP_PYTHON_ENV SKIP_NODEJS_ENV SKIP_ENV_CONFIG
    export NON_INTERACTIVE DRY_RUN RESUME FORCE VERBOSE DEBUG
}

# =============================================================================
# PHASE EXECUTION
# =============================================================================

# Run a single phase with state tracking
run_phase() {
    local phase="$1"
    local phase_num="$2"

    # Check resume mode - skip completed phases
    if [[ "$RESUME" == "true" ]]; then
        local status
        status=$(gcs_state_get_phase "$phase")
        if [[ "$status" == "completed" ]]; then
            log_info "Skipping ${phase} (already completed)"
            return 0
        fi
    fi

    # Mark in progress
    gcs_state_set_phase "$phase" "in_progress"

    # Execute phase
    local result=0
    case "$phase" in
        prereqs)
            run_prereqs_phase || result=$?
            ;;
        python)
            run_python_phase || result=$?
            ;;
        nodejs)
            run_nodejs_phase || result=$?
            ;;
        repository)
            run_repository_phase || result=$?
            ;;
        firewall)
            run_firewall_phase || result=$?
            ;;
        python_env)
            run_python_env_phase || result=$?
            ;;
        nodejs_env)
            run_nodejs_env_phase || result=$?
            ;;
        env_config)
            run_env_config_phase || result=$?
            ;;
        verify)
            run_verify_phase || result=$?
            ;;
        *)
            log_error "Unknown phase: $phase"
            result=1
            ;;
    esac

    # Mark completion
    if [[ $result -eq 0 ]]; then
        gcs_state_set_phase "$phase" "completed"
    else
        gcs_state_set_phase "$phase" "failed"
    fi

    return $result
}

# Run all phases in order
run_all_phases() {
    local failed=0
    local phase_num=1
    local total_phases=${#GCS_PHASES[@]}

    for phase in "${GCS_PHASES[@]}"; do
        if ! run_phase "$phase" "$phase_num"; then
            log_error "Phase failed: $phase"

            # Critical phases stop execution
            case "$phase" in
                prereqs|python|nodejs|repository)
                    log_error "Critical phase failed. Cannot continue."
                    return 1
                    ;;
                *)
                    ((failed++))
                    if [[ "${NON_INTERACTIVE}" != "true" ]]; then
                        if ! confirm "Continue despite failure?" "y"; then
                            return 1
                        fi
                    fi
                    ;;
            esac
        fi
        ((phase_num++))
    done

    return $failed
}

# =============================================================================
# RUN MODE
# =============================================================================

run_mode() {
    print_gcs_banner

    echo -e "${WHITE}GCS Run Mode${NC}"
    echo ""

    # Check if configuration was completed
    local verified
    verified=$(gcs_state_get_value "verified" "false")

    if [[ "$verified" != "true" ]] && [[ "$verified" != "partial" ]]; then
        log_warn "GCS has not been configured yet"
        echo ""
        echo -e "  Please run configuration first:"
        echo -e "  ${GREEN}sudo ./mds_gcs_init.sh${NC}"
        echo ""
        return 1
    fi

    local install_dir
    install_dir=$(gcs_state_get_value "install_dir" "$(pwd)")

    echo -e "  ${CHECK} GCS configuration found"
    echo -e "  ${WHITE}Install directory:${NC} $install_dir"
    echo ""

    # Check for startup script
    local startup_script="${install_dir}/app/linux_dashboard_start.sh"

    if [[ ! -f "$startup_script" ]]; then
        log_error "Startup script not found: $startup_script"
        return 1
    fi

    echo -e "${CYAN}+------------------------------------------------------------------------------+${NC}"
    echo -e "${CYAN}|${NC}  ${WHITE}LAUNCH OPTIONS${NC}"
    echo -e "${CYAN}+------------------------------------------------------------------------------+${NC}"
    echo ""
    echo -e "  ${WHITE}1.${NC} Start with tmux (recommended)"
    echo -e "     ${GREEN}${startup_script}${NC}"
    echo ""
    echo -e "  ${WHITE}2.${NC} Start in foreground"
    echo -e "     ${GREEN}${startup_script} -n${NC}"
    echo ""
    echo -e "  ${WHITE}3.${NC} Start in background"
    echo -e "     ${GREEN}${startup_script} &${NC}"
    echo ""
    echo -e "${CYAN}+------------------------------------------------------------------------------+${NC}"
    echo ""

    if [[ "${NON_INTERACTIVE}" != "true" ]]; then
        if confirm "Start GCS now with tmux?" "y"; then
            exec "$startup_script"
        fi
    fi

    return 0
}

# =============================================================================
# SIGNAL HANDLERS
# =============================================================================

# Error handler
gcs_error_handler() {
    local exit_code=$?
    local line_no=$1

    if [[ $exit_code -ne 0 ]]; then
        log_error "Script failed at line ${line_no} with exit code ${exit_code}"
    fi
}

# Cleanup handler
gcs_cleanup_handler() {
    # Reset terminal colors
    echo -e "${NC}"

    # Log completion status
    if [[ "${_GCS_COMPLETED:-false}" == "true" ]]; then
        log_info "GCS initialization completed successfully"
    else
        log_warn "GCS initialization interrupted or failed"
    fi
}

# =============================================================================
# MAIN
# =============================================================================

main() {
    # Parse command line arguments
    parse_arguments "$@"
    enable_non_interactive_without_tty

    # Setup signal handlers
    trap 'gcs_error_handler $LINENO' ERR
    trap gcs_cleanup_handler EXIT

    # Initialize logging
    gcs_init_logging

    # Handle run mode
    if [[ "$MODE" == "run" ]]; then
        run_mode
        exit $?
    fi

    # Configure mode
    # Get git info if available
    local git_info branch commit git_date
    if [[ -d "${GCS_INSTALL_DIR}/.git" ]]; then
        git_info=$(get_git_info "${GCS_INSTALL_DIR}" 2>/dev/null || echo "unknown|unknown|unknown")
        IFS='|' read -r branch commit git_date <<< "$git_info"
    fi

    print_gcs_banner "${branch:-$GCS_DEFAULT_BRANCH}" "${commit:-pending}"

    log_info "Installation started: $(date '+%Y-%m-%d %H:%M:%S')"
    log_info "Script version: ${GCS_VERSION}"

    # Display mode indicators
    if [[ "$DRY_RUN" == "true" ]]; then
        echo -e "  ${WARN} ${YELLOW}DRY-RUN MODE - No changes will be made${NC}"
        echo ""
    fi

    if [[ "$RESUME" == "true" ]]; then
        echo -e "  ${INFO} Resuming from last checkpoint..."
        echo ""
    fi

    if [[ "$NON_INTERACTIVE" == "true" ]]; then
        echo -e "  ${INFO} Non-interactive mode enabled"
        echo ""
    fi

    # Check root (except for dry-run)
    if [[ "$DRY_RUN" != "true" ]]; then
        if ! check_root; then
            log_error "This script must be run as root (use sudo)"
            exit 1
        fi
    fi

    # Initialize state
    gcs_state_init

    # Store initial values
    gcs_state_set_value "install_dir" "$GCS_INSTALL_DIR"

    # Display minimal configuration (details will be asked in Phase 4)
    echo -e "  ${WHITE}Install directory:${NC} ${GCS_INSTALL_DIR}"
    echo ""

    # Confirm before proceeding (interactive mode)
    if [[ "${NON_INTERACTIVE}" != "true" ]] && [[ "$DRY_RUN" != "true" ]]; then
        if ! confirm "Proceed with GCS initialization?" "y"; then
            echo "Aborted by user."
            exit 0
        fi
        echo ""
    fi

    # Run all phases
    if run_all_phases; then
        _GCS_COMPLETED="true"
        exit 0
    else
        exit 1
    fi
}

# Run main function
main "$@"
