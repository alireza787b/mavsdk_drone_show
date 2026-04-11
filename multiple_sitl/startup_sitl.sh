#!/bin/bash

# =============================================================================
# Script Name: startup_sitl.sh
# Description: Initializes and manages the Docker SITL runtime for MAVSDK_Drone_Show.
#              The supported simulator path is PX4 SITL with Gazebo Harmonic
#              (`make px4_sitl gz_x500`) in headless mode.
# Author: Alireza Ghaderi
# Date: September 2024
# =============================================================================

# Exit immediately if a command exits with a non-zero status,
# if an undefined variable is used, or if any command in a pipeline fails
set -euo pipefail

# =============================================================================
# REPOSITORY CONFIGURATION: Environment Variable Support (MDS v3.1+)
# =============================================================================
# This script now supports environment variable override for advanced deployments
# while maintaining 100% backward compatibility for normal users.
#
# FOR NORMAL USERS (99%):
#   - No action required - defaults work identically to previous versions
#   - Uses: https://github.com/alireza787b/mavsdk_drone_show.git@main-candidate
#   - Simply run: bash create_dockers.sh <number_of_drones>
#
# FOR ADVANCED USERS (Custom Forks):
#   - Set environment variables on HOST before running create_dockers.sh:
#     export MDS_REPO_URL="https://github.com/yourcompany/your-fork.git"
#     export MDS_BRANCH="your-production-branch"
#   - Environment variables are automatically passed to containers
#   - All containers will use your custom repository configuration
#
# EXAMPLES:
#   # Use HTTPS URL (no SSH keys needed):
#   export MDS_REPO_URL="https://github.com/company/fork.git"
#   export MDS_BRANCH="production"
#   bash create_dockers.sh 5
#
#   # Use SSH URL only when the container has working SSH credentials.
#   # Public GitHub repos will retry over HTTPS automatically if SSH fails.
#   export MDS_REPO_URL="git@github.com:company/fork.git"
#   export MDS_BRANCH="main"
#   bash create_dockers.sh 10
#
# ENVIRONMENT VARIABLES SUPPORTED:
#   MDS_REPO_URL         - Git repository URL (SSH or HTTPS format)
#   MDS_BRANCH           - Git branch name to checkout and use
#   MDS_GIT_AUTH_TOKEN_FILE - Preferred path to an authenticated HTTPS token file for private GitHub repos
#   MDS_GIT_AUTH_TOKEN      - Legacy fallback authenticated HTTPS token for private GitHub repos
#   MDS_GIT_AUTH_USERNAME   - Optional HTTPS username for token auth (default: x-access-token)
#
# NOTE: These variables are checked at container startup time
# =============================================================================

# GitHub Repository Details (with environment variable override support)
DEFAULT_GIT_REMOTE="origin"
DEFAULT_GIT_BRANCH="${MDS_BRANCH:-main-candidate}"
GITHUB_REPO_URL="${MDS_REPO_URL:-https://github.com/alireza787b/mavsdk_drone_show.git}"
GIT_AUTH_TOKEN_FILE="${MDS_GIT_AUTH_TOKEN_FILE:-}"
GIT_AUTH_TOKEN="${MDS_GIT_AUTH_TOKEN:-}"
GIT_AUTH_USERNAME="${MDS_GIT_AUTH_USERNAME:-x-access-token}"

# Script Metadata and repository path detection
SCRIPT_NAME=$(basename "$0")
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_BASE_FROM_SCRIPT="$(cd "$SCRIPT_DIR/.." && pwd)"

# The launcher may copy this script outside the repo (for example to /tmp inside
# the container). Prefer an explicit MDS_BASE_DIR, otherwise fall back to the
# repo-relative location only when the script is still running from inside the repo.
if [ -d "$REPO_BASE_FROM_SCRIPT/.git" ]; then
    DEFAULT_BASE_DIR="$REPO_BASE_FROM_SCRIPT"
else
    DEFAULT_BASE_DIR="$HOME/mavsdk_drone_show"
fi

BASE_DIR="${MDS_BASE_DIR:-$DEFAULT_BASE_DIR}"

load_stock_sitl_origin_defaults() {
    local default_origin_file="$BASE_DIR/data/origin.sitl.default.json"
    local origin_values

    if [[ ! -f "$default_origin_file" ]]; then
        return 0
    fi

    if ! origin_values="$(python3 - "$default_origin_file" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, 'r', encoding='utf-8') as handle:
    data = json.load(handle)

print(data['lat'])
print(data['lon'])
print(data.get('alt', 0))
PY
)"; then
        echo "[WARN] Failed to load stock SITL origin defaults from $default_origin_file" >&2
        return 0
    fi

    mapfile -t _origin_lines <<<"$origin_values"
    if [[ ${#_origin_lines[@]} -ge 3 ]]; then
        DEFAULT_LAT="${_origin_lines[0]}"
        DEFAULT_LON="${_origin_lines[1]}"
        DEFAULT_ALT="${_origin_lines[2]}"
    fi
}

# Option to use global Python
USE_GLOBAL_PYTHON=false  # Set to true to use global Python instead of venv

# Default geographic position: Azadi Stadium
DEFAULT_LAT=35.724435686078365
DEFAULT_LON=51.275581311948706
DEFAULT_ALT=1278
load_stock_sitl_origin_defaults

# Directory Paths
HWID_DIR="${MDS_HWID_DIR:-$BASE_DIR}"
VENV_DIR="$BASE_DIR/venv"
CONFIG_FILE="$BASE_DIR/config_sitl.json"
PX4_DIR="${MDS_PX4_DIR:-$HOME/PX4-Autopilot}"
PX4_RCS_PATH="$PX4_DIR/build/px4_sitl_default/etc/init.d-posix/rcS"
PX4_BUILD_PREP_LOG="$BASE_DIR/logs/px4_build_prepare.log"
MAVSDK_BINARY_PATH="$BASE_DIR/mavsdk_server"
MAVSDK_DOWNLOAD_SCRIPT="$BASE_DIR/tools/download_mavsdk_server.sh"
MAVLINK2REST_LOG="$BASE_DIR/logs/mavlink2rest.log"

# MAVLink Router for SITL (external routing - replaces internal MavlinkManager)
MAVLINK_ROUTER_SCRIPT="$BASE_DIR/tools/run_mavlink_router.sh"
MAVLINK_ROUTER_LOG="$BASE_DIR/logs/mavlink_router.log"
PX4_MAVLINK_PORT_DETECTOR="$BASE_DIR/multiple_sitl/detect_px4_mavlink_port.py"

# Supported Docker SITL standard:
#   - PX4 Gazebo Harmonic target: gz_x500
#   - Headless mode only
#   - Unique Gazebo transport partition per drone by default
DEFAULT_PX4_GZ_TARGET="gz_x500"
DEFAULT_QT_QPA_PLATFORM="offscreen"
DEFAULT_GZ_PARTITION_PREFIX="px4_sim"
DEFAULT_SITL_LOG_TAIL_LINES=40
DEFAULT_SITL_GIT_SYNC="true"
DEFAULT_SITL_REQUIREMENTS_SYNC="true"
DEFAULT_SITL_FILE_LOG_MODE="bounded"
DEFAULT_SITL_FILE_LOG_MAX_BYTES=$((5 * 1024 * 1024))
DEFAULT_SITL_FILE_LOG_BACKUP_COUNT=1
DEFAULT_SITL_STRIP_PXH_PROMPTS="true"
DEFAULT_SITL_PARAM_OVERRIDES=(
    "COM_RC_IN_MODE=4"
    "NAV_RCL_ACT=0"
    "NAV_DLL_ACT=0"
    "COM_DL_LOSS_T=0"
    "CBRK_SUPPLY_CHK=894281"
    "SDLOG_MODE=0"
)

# Runtime configuration (can be overridden with MDS_* environment variables)
PX4_GZ_TARGET="${MDS_PX4_GZ_TARGET:-$DEFAULT_PX4_GZ_TARGET}"
QT_QPA_PLATFORM_VALUE="${MDS_QT_QPA_PLATFORM:-$DEFAULT_QT_QPA_PLATFORM}"
GZ_PARTITION_PREFIX="${MDS_GZ_PARTITION_PREFIX:-$DEFAULT_GZ_PARTITION_PREFIX}"
GZ_PARTITION_OVERRIDE="${MDS_GZ_PARTITION:-}"
SITL_LOG_TAIL_LINES="${MDS_SITL_LOG_TAIL_LINES:-$DEFAULT_SITL_LOG_TAIL_LINES}"
KILL_STALE_SIM_PROCESSES="${MDS_SITL_KILL_STALE_PROCESSES:-true}"
SHELL_TRACE_ENABLED="${MDS_SITL_TRACE:-0}"
SITL_GIT_SYNC="${MDS_SITL_GIT_SYNC:-$DEFAULT_SITL_GIT_SYNC}"
SITL_REQUIREMENTS_SYNC="${MDS_SITL_REQUIREMENTS_SYNC:-$DEFAULT_SITL_REQUIREMENTS_SYNC}"
SITL_FILE_LOG_MODE="${MDS_SITL_FILE_LOG_MODE:-$DEFAULT_SITL_FILE_LOG_MODE}"
SITL_FILE_LOG_MAX_BYTES="${MDS_SITL_FILE_LOG_MAX_BYTES:-$DEFAULT_SITL_FILE_LOG_MAX_BYTES}"
SITL_FILE_LOG_BACKUP_COUNT="${MDS_SITL_FILE_LOG_BACKUP_COUNT:-$DEFAULT_SITL_FILE_LOG_BACKUP_COUNT}"
SITL_STRIP_PXH_PROMPTS="${MDS_SITL_STRIP_PXH_PROMPTS:-$DEFAULT_SITL_STRIP_PXH_PROMPTS}"
VENV_REQUIREMENTS_MARKER="$VENV_DIR/.mds_requirements_state"
LOG_POLICY_RUNNER="$BASE_DIR/tools/run_with_log_policy.py"
IMAGE_BUILD_METADATA_FILE="$BASE_DIR/.mds_sitl_image_build.env"
PX4_PROVENANCE_FILE="$BASE_DIR/.mds_px4_source_provenance.env"
PX4_SUBMODULE_STATUS_FILE="$BASE_DIR/.mds_px4_submodules.txt"

# Backward-compatible legacy option parsing: the launcher now always forces
# headless Gazebo Harmonic, but older invocations may still pass `-s`.
REQUESTED_SIMULATION_MODE="h"

# Initialize Git variables
GIT_REMOTE="$DEFAULT_GIT_REMOTE"
GIT_BRANCH="$DEFAULT_GIT_BRANCH"

# Verbose Mode Flag
VERBOSE_MODE=false
ACTIVE_SITL_PARAM_OVERRIDES=()
PX4_PARAM_ENV_VARS=()
SIMULATION_ENV_VARS=()
SIMULATION_COMMAND=()
MAVLINK2REST_ARGS=(-c "udpin:127.0.0.1:14569" -s "0.0.0.0:8088")
LAUNCH_WITH_LOG_POLICY_LAST_PID=""

if [ "$SHELL_TRACE_ENABLED" = "1" ]; then
    set -x
fi

# =============================================================================
# Function Definitions
# =============================================================================

# Function to display usage information
usage() {
    cat << EOF
Usage: $SCRIPT_NAME [options]

Options:
  -r <git_remote>       Specify the GitHub repository remote name (default: $DEFAULT_GIT_REMOTE)
  -b <git_branch>       Specify the GitHub repository branch name (default: $DEFAULT_GIT_BRANCH)
  -s <simulation_mode>  Deprecated compatibility flag. Docker SITL now always runs headless PX4 Gazebo Harmonic (gz_x500)
  -v, --verbose         Run coordinator.py in verbose mode (foreground with output to screen)
  -h, --help            Display this help message

Examples:
  $SCRIPT_NAME
  $SCRIPT_NAME -r upstream -b develop
  $SCRIPT_NAME --verbose
EOF
    exit 1
}

# Function to log messages to the terminal with timestamps
log_message() {
    local message="$1"
    echo "$(date +"%Y-%m-%d %H:%M:%S") - $message"
}

load_git_auth_token() {
    if [[ -n "$GIT_AUTH_TOKEN_FILE" ]]; then
        if [[ ! -r "$GIT_AUTH_TOKEN_FILE" ]]; then
            log_message "ERROR: MDS_GIT_AUTH_TOKEN_FILE is not readable: $GIT_AUTH_TOKEN_FILE"
            exit 1
        fi

        GIT_AUTH_TOKEN="$(tr -d '\r\n' < "$GIT_AUTH_TOKEN_FILE")"
    fi
}

# Function to handle script termination and cleanup
cleanup() {
    echo ""
    log_message "Received interrupt signal. Terminating background processes..."

    if [[ -n "${simulation_pid:-}" ]]; then
        kill "$simulation_pid" 2>/dev/null || true
        log_message "Terminated SITL simulation with PID: $simulation_pid"
    fi

    if [ "$VERBOSE_MODE" = false ]; then
        if [[ -n "${coordinator_pid:-}" ]]; then
            kill "$coordinator_pid" 2>/dev/null || true
            log_message "Terminated coordinator.py with PID: $coordinator_pid"
        fi
    else
        log_message "Coordinator.py running in foreground, should receive SIGINT."
    fi

    if [[ -n "${mavlink2rest_pid:-}" ]]; then
        kill "$mavlink2rest_pid" 2>/dev/null || true
        log_message "Terminated mavlink2rest with PID: $mavlink2rest_pid"
    fi

    if [[ -n "${mavlink_router_pid:-}" ]]; then
        kill "$mavlink_router_pid" 2>/dev/null || true
        log_message "Terminated MAVLink router with PID: $mavlink_router_pid"
    fi

    if [ "${USE_GLOBAL_PYTHON:-false}" = false ]; then
        deactivate 2>/dev/null || true
        log_message "Deactivated Python virtual environment."
    fi

    exit 0
}

# Function to install 'bc' if not present
install_bc() {
    log_message "'bc' is not installed. Installing 'bc'..."
    if ! sudo apt-get update || ! sudo apt-get install -y bc; then
        log_message "ERROR: Failed to install 'bc'. Please install it manually."
        exit 1
    fi
    log_message "'bc' installed successfully."
}

# Function to parse script arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -r)
                if [[ -n "${2:-}" && ! $2 =~ ^- ]]; then
                    GIT_REMOTE="$2"
                    shift 2
                else
                    log_message "ERROR: -r requires a non-empty option argument."
                    usage
                fi
                ;;
            -b)
                if [[ -n "${2:-}" && ! $2 =~ ^- ]]; then
                    GIT_BRANCH="$2"
                    shift 2
                else
                    log_message "ERROR: -b requires a non-empty option argument."
                    usage
                fi
                ;;
            -s)
                if [[ -n "${2:-}" && ! $2 =~ ^- ]]; then
                    REQUESTED_SIMULATION_MODE="$2"
                    shift 2
                else
                    log_message "ERROR: -s requires a non-empty option argument."
                    usage
                fi
                ;;
            -v|--verbose)
                VERBOSE_MODE=true
                shift
                ;;
            -h|--help)
                usage
                ;;
            *)
                log_message "ERROR: Unknown option: $1"
                usage
                ;;
        esac
    done
}

# Function to check and install dependencies
check_dependencies() {
    if ! command -v bc &> /dev/null; then
        install_bc
    else
        log_message "'bc' is already installed."
    fi
    if ! command -v git &> /dev/null; then
        log_message "'git' is not installed. Installing 'git'..."
        if ! sudo apt-get update || ! sudo apt-get install -y git; then
            log_message "ERROR: Failed to install 'git'. Please install it manually."
            exit 1
        fi
        log_message "'git' installed successfully."
    else
        log_message "'git' is already installed."
    fi
    if ! command -v jq &> /dev/null; then
        log_message "'jq' is not installed. Installing 'jq'..."
        if ! sudo apt-get update || ! sudo apt-get install -y jq; then
            log_message "ERROR: Failed to install 'jq'. Please install it manually."
            exit 1
        fi
        log_message "'jq' installed successfully."
    else
        log_message "'jq' is already installed."
    fi
}

# Function to wait for the .hwID file
wait_for_hwid() {
    log_message "Waiting for .hwID file in $HWID_DIR..."
    while true; do
        HWID_FILE=$(ls "$HWID_DIR"/*.hwID 2>/dev/null | head -n 1 || true)
        if [[ -n "$HWID_FILE" ]]; then
            HWID=$(basename "$HWID_FILE" .hwID)
            log_message "Found .hwID file: $HWID.hwID"
            break
        else
            log_message "  - .hwID file not found. Retrying in 1 second..."
            sleep 1
        fi
    done

    # Validate that HWID is a positive integer
    if ! [[ "$HWID" =~ ^[1-9][0-9]*$ ]]; then
        log_message "ERROR: Extracted HWID '$HWID' is not a positive integer."
        exit 1
    fi
}

ensure_runtime_paths() {
    if [ ! -d "$BASE_DIR" ]; then
        log_message "ERROR: Base directory not found: $BASE_DIR"
        exit 1
    fi

    if [ ! -d "$PX4_DIR" ]; then
        log_message "ERROR: PX4 directory not found: $PX4_DIR"
        exit 1
    fi

    mkdir -p "$BASE_DIR/logs"
}

validate_runtime_configuration() {
    if [[ ! "$PX4_GZ_TARGET" =~ ^gz_ ]]; then
        log_message "ERROR: PX4 Gazebo target must start with 'gz_' (got '$PX4_GZ_TARGET')."
        exit 1
    fi

    if [[ ! "$SITL_LOG_TAIL_LINES" =~ ^[1-9][0-9]*$ ]]; then
        log_message "ERROR: MDS_SITL_LOG_TAIL_LINES must be a positive integer (got '$SITL_LOG_TAIL_LINES')."
        exit 1
    fi

    case "$KILL_STALE_SIM_PROCESSES" in
        true|false) ;;
        *)
            log_message "ERROR: MDS_SITL_KILL_STALE_PROCESSES must be 'true' or 'false' (got '$KILL_STALE_SIM_PROCESSES')."
            exit 1
            ;;
    esac

    case "$SITL_GIT_SYNC" in
        true|false) ;;
        *)
            log_message "ERROR: MDS_SITL_GIT_SYNC must be 'true' or 'false' (got '$SITL_GIT_SYNC')."
            exit 1
            ;;
    esac

    case "$SITL_REQUIREMENTS_SYNC" in
        true|false) ;;
        *)
            log_message "ERROR: MDS_SITL_REQUIREMENTS_SYNC must be 'true' or 'false' (got '$SITL_REQUIREMENTS_SYNC')."
            exit 1
            ;;
    esac

    case "$SITL_FILE_LOG_MODE" in
        bounded|full|discard) ;;
        *)
            log_message "ERROR: MDS_SITL_FILE_LOG_MODE must be one of: bounded, full, discard (got '$SITL_FILE_LOG_MODE')."
            exit 1
            ;;
    esac

    if [[ ! "$SITL_FILE_LOG_MAX_BYTES" =~ ^[1-9][0-9]*$ ]]; then
        log_message "ERROR: MDS_SITL_FILE_LOG_MAX_BYTES must be a positive integer (got '$SITL_FILE_LOG_MAX_BYTES')."
        exit 1
    fi

    if [[ ! "$SITL_FILE_LOG_BACKUP_COUNT" =~ ^[0-9]+$ ]]; then
        log_message "ERROR: MDS_SITL_FILE_LOG_BACKUP_COUNT must be zero or greater (got '$SITL_FILE_LOG_BACKUP_COUNT')."
        exit 1
    fi

    case "$SITL_STRIP_PXH_PROMPTS" in
        true|false) ;;
        *)
            log_message "ERROR: MDS_SITL_STRIP_PXH_PROMPTS must be 'true' or 'false' (got '$SITL_STRIP_PXH_PROMPTS')."
            exit 1
            ;;
    esac
}

log_px4_source_state() {
    if git -C "$PX4_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        local px4_branch
        local px4_commit
        px4_branch=$(git -C "$PX4_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
        px4_commit=$(git -C "$PX4_DIR" rev-parse --short HEAD 2>/dev/null || echo "unknown")
        log_message "PX4 Source: $PX4_DIR ($px4_branch @ $px4_commit)"
    else
        log_message "PX4 Source: $PX4_DIR"
    fi
}

resolve_gz_partition() {
    if [ -n "$GZ_PARTITION_OVERRIDE" ]; then
        GZ_PARTITION_VALUE="$GZ_PARTITION_OVERRIDE"
        log_message "Using Gazebo transport partition override: $GZ_PARTITION_VALUE"
    else
        GZ_PARTITION_VALUE="${GZ_PARTITION_PREFIX}_${HWID}"
        log_message "Using per-drone Gazebo transport partition: $GZ_PARTITION_VALUE"
    fi
}

trim_whitespace() {
    local value="$1"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    printf "%s" "$value"
}

build_sitl_param_overrides() {
    ACTIVE_SITL_PARAM_OVERRIDES=()
    PX4_PARAM_ENV_VARS=()

    if [ -n "${MDS_SITL_PARAM_OVERRIDES:-}" ]; then
        case "${MDS_SITL_PARAM_OVERRIDES,,}" in
            none|off|false)
                return 0
                ;;
        esac

        local normalized_overrides
        normalized_overrides="${MDS_SITL_PARAM_OVERRIDES//$'\n'/,}"

        local raw_items=()
        IFS=',' read -r -a raw_items <<< "$normalized_overrides"

        local item trimmed_item
        for item in "${raw_items[@]}"; do
            trimmed_item=$(trim_whitespace "$item")
            if [ -n "$trimmed_item" ]; then
                ACTIVE_SITL_PARAM_OVERRIDES+=("$trimmed_item")
            fi
        done
    else
        ACTIVE_SITL_PARAM_OVERRIDES=("${DEFAULT_SITL_PARAM_OVERRIDES[@]}")
    fi

    local override name value
    for override in "${ACTIVE_SITL_PARAM_OVERRIDES[@]}"; do
        name="${override%%=*}"
        value="${override#*=}"
        PX4_PARAM_ENV_VARS+=("PX4_PARAM_${name}=${value}")
    done
}

format_sitl_param_overrides() {
    if [ ${#ACTIVE_SITL_PARAM_OVERRIDES[@]} -eq 0 ]; then
        printf "none"
        return
    fi

    local formatted=""
    local override
    for override in "${ACTIVE_SITL_PARAM_OVERRIDES[@]}"; do
        if [ -n "$formatted" ]; then
            formatted+=", "
        fi
        formatted+="$override"
    done
    printf "%s" "$formatted"
}

log_startup_configuration() {
    local requested_mode_note="$REQUESTED_SIMULATION_MODE"
    if [ "$REQUESTED_SIMULATION_MODE" != "h" ]; then
        requested_mode_note="$REQUESTED_SIMULATION_MODE (legacy request; forced to headless ${PX4_GZ_TARGET})"
    fi

    log_message "Configuration:"
    log_message "  Git Remote: $GIT_REMOTE"
    log_message "  Git Branch: $GIT_BRANCH"
    log_message "  Base Directory: $BASE_DIR"
    log_message "  HWID Directory: $HWID_DIR"
    log_message "  Use Global Python: $USE_GLOBAL_PYTHON"
    log_message "  Requested Legacy Sim Mode: $requested_mode_note"
    log_message "  PX4 Gazebo Target: $PX4_GZ_TARGET"
    log_message "  Headless Mode: true"
    log_message "  QT_QPA_PLATFORM: $QT_QPA_PLATFORM_VALUE"
    log_message "  GZ Partition Prefix: $GZ_PARTITION_PREFIX"
    log_message "  Kill Stale PX4/GZ Processes: $KILL_STALE_SIM_PROCESSES"
    log_message "  Git Sync on Startup: $SITL_GIT_SYNC"
    log_message "  Requirements Sync on Startup: $SITL_REQUIREMENTS_SYNC"
    log_message "  File Log Mode: $SITL_FILE_LOG_MODE"
    log_message "  File Log Max Bytes: $SITL_FILE_LOG_MAX_BYTES"
    log_message "  File Log Backup Count: $SITL_FILE_LOG_BACKUP_COUNT"
    log_message "  Strip PX4 Prompt Noise: $SITL_STRIP_PXH_PROMPTS"
    log_message "  Verbose Mode: $VERBOSE_MODE"
    log_px4_source_state
}

log_runtime_identity() {
    log_message "Runtime Identity:"
    log_message "  HWID / MAV_SYS_ID: $HWID"
    log_message "  Gazebo Transport Partition: $GZ_PARTITION_VALUE"
    log_message "  SITL PX4 Parameter Overrides: $(format_sitl_param_overrides)"
}

kill_exact_processes() {
    local label="$1"
    local process_name="$2"

    if ! pgrep -x "$process_name" >/dev/null 2>&1; then
        return 0
    fi

    log_message "Stopping stale $label processes ('$process_name')..."
    pkill -TERM -x "$process_name" || true
    sleep 2

    if pgrep -x "$process_name" >/dev/null 2>&1; then
        log_message "Escalating stale $label processes ('$process_name') to SIGKILL..."
        pkill -KILL -x "$process_name" || true
        sleep 1
    fi
}

kill_command_processes() {
    local label="$1"
    local command_pattern="$2"

    if ! pgrep -f "$command_pattern" >/dev/null 2>&1; then
        return 0
    fi

    log_message "Stopping stale $label commands matching '$command_pattern'..."
    pkill -TERM -f "$command_pattern" || true
    sleep 2

    if pgrep -f "$command_pattern" >/dev/null 2>&1; then
        log_message "Escalating stale $label commands matching '$command_pattern' to SIGKILL..."
        pkill -KILL -f "$command_pattern" || true
        sleep 1
    fi
}

cleanup_stale_simulation_processes() {
    if [ "$KILL_STALE_SIM_PROCESSES" != "true" ]; then
        log_message "Skipping stale PX4/Gazebo cleanup (MDS_SITL_KILL_STALE_PROCESSES=false)."
        return
    fi

    kill_exact_processes "PX4" "px4"
    kill_exact_processes "Gazebo Transport" "gz"
    kill_command_processes "Gazebo Sim" "gz sim"
}

tail_log_file() {
    local file_path="$1"
    if [ -f "$file_path" ] && [ "$file_path" != "/dev/null" ]; then
        while IFS= read -r line; do
            log_message "  $line"
        done < <(tail -n "$SITL_LOG_TAIL_LINES" "$file_path")
    fi
}

describe_log_policy_target() {
    local file_path="$1"
    case "$SITL_FILE_LOG_MODE" in
        discard)
            printf "discarded"
            ;;
        bounded)
            printf "%s (bounded to %s bytes, %s backup)" "$file_path" "$SITL_FILE_LOG_MAX_BYTES" "$SITL_FILE_LOG_BACKUP_COUNT"
            ;;
        full)
            printf "%s" "$file_path"
            ;;
    esac
}

launch_with_log_policy() {
    local log_file="$1"
    shift
    local extra_runner_args=()

    if [ ! -f "$LOG_POLICY_RUNNER" ]; then
        log_message "WARNING: Log policy runner not found at $LOG_POLICY_RUNNER. Falling back to direct file redirection."
        if [ "$SITL_FILE_LOG_MODE" = "discard" ]; then
            "$@" </dev/null >/dev/null 2>&1 &
        else
            "$@" </dev/null &> "$log_file" &
        fi
        LAUNCH_WITH_LOG_POLICY_LAST_PID="$!"
        return 0
    fi

    if [ "$SITL_STRIP_PXH_PROMPTS" = "true" ] && [ "$log_file" = "$BASE_DIR/logs/sitl_simulation.log" ]; then
        extra_runner_args+=(--strip-pxh-prompts)
    fi

    python3 "$LOG_POLICY_RUNNER" \
        --mode "$SITL_FILE_LOG_MODE" \
        --log-file "$log_file" \
        --max-bytes "$SITL_FILE_LOG_MAX_BYTES" \
        --backup-count "$SITL_FILE_LOG_BACKUP_COUNT" \
        "${extra_runner_args[@]}" \
        -- \
        "$@" </dev/null >/dev/null 2>&1 &
    LAUNCH_WITH_LOG_POLICY_LAST_PID="$!"
}

# Retry helper for SITL git operations (matches update_repo_ssh.sh pattern)
sitl_retry() {
    local max_retries="${1:-3}"
    local label="$2"
    shift 2
    local attempt=0
    local delay=2
    while [ $attempt -lt "$max_retries" ]; do
        if "$@"; then
            return 0
        fi
        attempt=$((attempt + 1))
        if [ $attempt -lt "$max_retries" ]; then
            # Add jitter (0-2s) to avoid thundering herd with multiple SITL containers
            local jitter=$((RANDOM % 3))
            local wait=$((delay + jitter))
            log_message "[$label] Attempt $attempt/$max_retries failed. Retrying in ${wait}s..."
            sleep "$wait"
            delay=$((delay * 2))
        fi
    done
    log_message "ERROR: [$label] Failed after $max_retries attempts."
    return 1
}

github_https_fallback_url() {
    local repo_url="$1"
    if [[ "$repo_url" =~ ^git@github\.com:(.+)$ ]]; then
        echo "https://github.com/${BASH_REMATCH[1]}"
        return 0
    fi
    return 1
}

urlencode_value() {
    python3 - "$1" <<'PY'
import sys
from urllib.parse import quote

print(quote(sys.argv[1], safe=''))
PY
}

github_repo_path() {
    local repo_url="$1"
    local repo_path=""

    if [[ "$repo_url" =~ ^git@github\.com:(.+)$ ]]; then
        repo_path="${BASH_REMATCH[1]}"
    elif [[ "$repo_url" =~ ^https://github\.com/(.+)$ ]]; then
        repo_path="${BASH_REMATCH[1]}"
    else
        return 1
    fi

    repo_path="${repo_path%.git}"
    printf '%s.git\n' "$repo_path"
}

github_authenticated_https_url() {
    local repo_url="$1"
    local repo_path=""

    [[ -n "$GIT_AUTH_TOKEN" ]] || return 1
    repo_path=$(github_repo_path "$repo_url") || return 1

    local encoded_username encoded_token
    encoded_username=$(urlencode_value "$GIT_AUTH_USERNAME")
    encoded_token=$(urlencode_value "$GIT_AUTH_TOKEN")
    printf 'https://%s:%s@github.com/%s\n' "$encoded_username" "$encoded_token" "$repo_path"
}

requirements_state_value() {
    local requirements_file="$BASE_DIR/requirements.txt"
    if [ ! -f "$requirements_file" ]; then
        log_message "ERROR: Requirements file not found: $requirements_file"
        exit 1
    fi

    local requirements_hash
    local python_version
    requirements_hash=$(sha256sum "$requirements_file" | awk '{print $1}')
    python_version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')
    printf "%s|python=%s\n" "$requirements_hash" "$python_version"
}

load_image_build_metadata() {
    if [ -f "$IMAGE_BUILD_METADATA_FILE" ]; then
        # shellcheck disable=SC1090
        source "$IMAGE_BUILD_METADATA_FILE"
    fi

    if [ -f "$PX4_PROVENANCE_FILE" ]; then
        # shellcheck disable=SC1090
        source "$PX4_PROVENANCE_FILE"
    fi
}

bootstrap_repository_checkout() {
    local repo_url="$1"
    local fallback_repo_url="$2"
    local authenticated_repo_url=""
    local effective_repo_url="$repo_url"
    local clone_parent
    clone_parent=$(mktemp -d)
    local clone_dir="$clone_parent/repo"
    local preserve_dir
    preserve_dir=$(mktemp -d)
    local runtime_item

    log_message "Bootstrapping repository checkout into $BASE_DIR..."

    if [ -d "$BASE_DIR/venv" ]; then
        mv "$BASE_DIR/venv" "$preserve_dir/venv"
    fi

    if [ -d "$BASE_DIR/logs" ]; then
        mv "$BASE_DIR/logs" "$preserve_dir/logs"
    fi

    shopt -s nullglob
    for runtime_item in "$BASE_DIR"/*.hwID; do
        mv "$runtime_item" "$preserve_dir/"
    done
    shopt -u nullglob

    if [ -f "$BASE_DIR/mavsdk_server" ]; then
        mv "$BASE_DIR/mavsdk_server" "$preserve_dir/mavsdk_server"
    fi

    if [ -f "$BASE_DIR/config_sitl.json" ]; then
        cp "$BASE_DIR/config_sitl.json" "$preserve_dir/config_sitl.json"
    fi

    if [ -f "$IMAGE_BUILD_METADATA_FILE" ]; then
        cp "$IMAGE_BUILD_METADATA_FILE" "$preserve_dir/.mds_sitl_image_build.env"
    fi

    if [ -f "$PX4_PROVENANCE_FILE" ]; then
        cp "$PX4_PROVENANCE_FILE" "$preserve_dir/.mds_px4_source_provenance.env"
    fi

    if [ -f "$PX4_SUBMODULE_STATUS_FILE" ]; then
        cp "$PX4_SUBMODULE_STATUS_FILE" "$preserve_dir/.mds_px4_submodules.txt"
    fi

    if authenticated_repo_url=$(github_authenticated_https_url "$repo_url"); then
        effective_repo_url="$authenticated_repo_url"
        fallback_repo_url=""
    fi

    if ! git clone --depth 1 --branch "$GIT_BRANCH" "$effective_repo_url" "$clone_dir"; then
        if [ -n "$fallback_repo_url" ] && [ "$fallback_repo_url" != "$repo_url" ]; then
            log_message "Clone via SSH failed. Retrying with HTTPS fallback: $fallback_repo_url"
            git clone --depth 1 --branch "$GIT_BRANCH" "$fallback_repo_url" "$clone_dir"
        else
            log_message "ERROR: Failed to clone $repo_url@$GIT_BRANCH"
            exit 1
        fi
    fi

    rm -rf "$BASE_DIR"
    mv "$clone_dir" "$BASE_DIR"
    rm -rf "$clone_parent"

    if [ -d "$preserve_dir/venv" ]; then
        mv "$preserve_dir/venv" "$BASE_DIR/venv"
    fi

    if [ -d "$preserve_dir/logs" ]; then
        mv "$preserve_dir/logs" "$BASE_DIR/logs"
    else
        mkdir -p "$BASE_DIR/logs"
    fi

    shopt -s nullglob
    for runtime_item in "$preserve_dir"/*.hwID; do
        mv "$runtime_item" "$BASE_DIR/"
    done
    shopt -u nullglob

    if [ -f "$preserve_dir/mavsdk_server" ] && [ ! -f "$BASE_DIR/mavsdk_server" ]; then
        mv "$preserve_dir/mavsdk_server" "$BASE_DIR/mavsdk_server"
    fi

    if [ -f "$preserve_dir/config_sitl.json" ] && [ ! -f "$BASE_DIR/config_sitl.json" ]; then
        mv "$preserve_dir/config_sitl.json" "$BASE_DIR/config_sitl.json"
    fi

    if [ -f "$preserve_dir/.mds_sitl_image_build.env" ] && [ ! -f "$IMAGE_BUILD_METADATA_FILE" ]; then
        mv "$preserve_dir/.mds_sitl_image_build.env" "$IMAGE_BUILD_METADATA_FILE"
    fi

    if [ -f "$preserve_dir/.mds_px4_source_provenance.env" ] && [ ! -f "$PX4_PROVENANCE_FILE" ]; then
        mv "$preserve_dir/.mds_px4_source_provenance.env" "$PX4_PROVENANCE_FILE"
    fi

    if [ -f "$preserve_dir/.mds_px4_submodules.txt" ] && [ ! -f "$PX4_SUBMODULE_STATUS_FILE" ]; then
        mv "$preserve_dir/.mds_px4_submodules.txt" "$PX4_SUBMODULE_STATUS_FILE"
    fi

    rm -rf "$preserve_dir"
}

# Function to update the repository
update_repository() {
    local start_time
    start_time=$(date +%s)

    if [ "$SITL_GIT_SYNC" != "true" ]; then
        log_message "Skipping repository sync (MDS_SITL_GIT_SYNC=false)."
        echo "GIT_SYNC_RESULT={\"success\":true,\"branch\":\"$GIT_BRANCH\",\"skipped\":true}"
        return 0
    fi

    local authenticated_repo_url=""
    local fallback_repo_url=""
    local effective_repo_url="$GITHUB_REPO_URL"
    if authenticated_repo_url=$(github_authenticated_https_url "$GITHUB_REPO_URL"); then
        effective_repo_url="$authenticated_repo_url"
        fallback_repo_url=""
    elif fallback_repo_url=$(github_https_fallback_url "$GITHUB_REPO_URL"); then
        :
    else
        fallback_repo_url=""
    fi

    if ! git -C "$BASE_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        bootstrap_repository_checkout "$effective_repo_url" "$fallback_repo_url"
    fi

    log_message "Navigating to $BASE_DIR..."
    cd "$BASE_DIR"

    log_message "Setting Git remote to $GIT_REMOTE..."
    if git remote get-url "$GIT_REMOTE" >/dev/null 2>&1; then
        git remote set-url "$GIT_REMOTE" "$effective_repo_url"
    else
        git remote add "$GIT_REMOTE" "$effective_repo_url"
    fi

    local remote_tracking_ref="refs/remotes/$GIT_REMOTE/$GIT_BRANCH"
    local fetch_refspec="+refs/heads/$GIT_BRANCH:$remote_tracking_ref"

    log_message "Fetching latest changes from $GIT_REMOTE/$GIT_BRANCH..."
    if ! sitl_retry 3 "GIT-FETCH" git fetch --depth 1 "$GIT_REMOTE" "$fetch_refspec"; then
        if [ -n "$fallback_repo_url" ] && [ "$fallback_repo_url" != "$effective_repo_url" ]; then
            log_message "SSH fetch failed. Retrying with HTTPS fallback: $fallback_repo_url"
            git remote set-url "$GIT_REMOTE" "$fallback_repo_url" || true
            if ! sitl_retry 3 "GIT-FETCH-HTTPS" git fetch --depth 1 "$GIT_REMOTE" "$fetch_refspec"; then
                log_message "ERROR: Failed to fetch from $GIT_REMOTE/$GIT_BRANCH even after HTTPS fallback."
                echo "GIT_SYNC_RESULT={\"success\":false,\"branch\":\"$GIT_BRANCH\",\"error\":\"fetch_failed\"}"
                exit 1
            fi
        else
            log_message "ERROR: Failed to fetch from $GIT_REMOTE/$GIT_BRANCH."
            echo "GIT_SYNC_RESULT={\"success\":false,\"branch\":\"$GIT_BRANCH\",\"error\":\"fetch_failed\"}"
            exit 1
        fi
    fi

    log_message "Checking out branch $GIT_BRANCH..."
    if ! git checkout -B "$GIT_BRANCH" "$remote_tracking_ref"; then
        log_message "ERROR: Failed to checkout branch $GIT_BRANCH."
        echo "GIT_SYNC_RESULT={\"success\":false,\"branch\":\"$GIT_BRANCH\",\"error\":\"checkout_failed\"}"
        exit 1
    fi

    log_message "Resetting worktree to $GIT_REMOTE/$GIT_BRANCH..."
    if ! git reset --hard "$remote_tracking_ref"; then
        log_message "ERROR: Failed to reset to $GIT_REMOTE/$GIT_BRANCH."
        echo "GIT_SYNC_RESULT={\"success\":false,\"branch\":\"$GIT_BRANCH\",\"error\":\"reset_failed\"}"
        exit 1
    fi

    log_message "Cleaning untracked repository files while preserving runtime state..."
    if ! git clean -ffd \
        -e venv/ \
        -e logs/ \
        -e '*.hwID' \
        -e mavsdk_server \
        -e .mds_sitl_image_build.env \
        -e .mds_px4_source_provenance.env \
        -e .mds_px4_submodules.txt; then
        log_message "ERROR: Failed to clean untracked files in $BASE_DIR."
        echo "GIT_SYNC_RESULT={\"success\":false,\"branch\":\"$GIT_BRANCH\",\"error\":\"clean_failed\"}"
        exit 1
    fi

    local commit_hash
    commit_hash=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    local commit_message
    commit_message=$(git log -1 --pretty=format:"%s" 2>/dev/null || echo "unknown")
    local end_time
    end_time=$(date +%s)
    local duration=$((end_time - start_time))

    log_message "Repository updated successfully."
    # Escape quotes/backslashes in commit message for valid JSON
    local commit_message_json
    commit_message_json=$(echo "$commit_message" | sed 's/\\/\\\\/g; s/"/\\"/g' | tr -d '\n\r')
    echo "GIT_SYNC_RESULT={\"success\":true,\"branch\":\"$GIT_BRANCH\",\"commit\":\"$commit_hash\",\"message\":\"$commit_message_json\",\"duration\":$duration}"
}

log_image_runtime_mode() {
    load_image_build_metadata

    local current_commit
    current_commit=$(git -C "$BASE_DIR" rev-parse --short HEAD 2>/dev/null || echo "unknown")

    if [ -f "$IMAGE_BUILD_METADATA_FILE" ]; then
        log_message "Image Build Metadata:"
        log_message "  Prepared At UTC: ${MDS_IMAGE_PREPARED_AT_UTC:-unknown}"
        log_message "  Baked Repo Branch: ${MDS_IMAGE_BRANCH:-unknown}"
        log_message "  Baked Repo Commit: ${MDS_IMAGE_COMMIT:-unknown}"
        log_message "  Runtime Repo Commit: ${current_commit}"
        log_message "  Sync Mode: ${MDS_IMAGE_SYNC_MODE:-unknown}"
        if [ -n "${MDS_IMAGE_PX4_COMMIT:-}" ]; then
            log_message "  Baked PX4: ${MDS_IMAGE_PX4_DESCRIBE:-unknown} (${MDS_IMAGE_PX4_COMMIT})"
        fi
    fi

    if [ "$SITL_GIT_SYNC" != "true" ]; then
        log_message "Repository sync is disabled. Runtime stays on the baked repo commit."
        return
    fi

    if [ -f "$IMAGE_BUILD_METADATA_FILE" ] && [ -n "${MDS_IMAGE_COMMIT:-}" ] && [ "$current_commit" != "${MDS_IMAGE_COMMIT}" ]; then
        log_message "WARNING: Repository auto-sync moved runtime MDS code from baked commit ${MDS_IMAGE_COMMIT} to ${current_commit}."
        log_message "WARNING: This container is running in mutable latest-on-boot mode."
        log_message "WARNING: PX4 and mavsdk_server stay pinned in the image. Rebuild the SITL image after validation for a reproducible release."
    fi
}

# Function to run MAVLink router for SITL (external routing)
# This replaces the internal MavlinkManager and provides MAVLink routing
# from PX4's detected GCS UDP port to mavlink2rest (14569),
# LocalMavlinkController (12550), and remote GCS (24550)
run_mavlink_router() {
    log_message "Starting MAVLink router for SITL..."

    # Ensure the logs directory exists
    mkdir -p "$(dirname "$MAVLINK_ROUTER_LOG")"

    # Export GCS_IP for mavlink router (reads from params via Python)
    # Falls back to Docker gateway if params not available
    cd "$BASE_DIR"
    export GCS_IP=$(python3 -c "from src.params import Params; print(Params.GCS_IP)" 2>/dev/null || ip route show default 2>/dev/null | awk '/default/ {print $3; exit}')
    if [ -z "${GCS_IP:-}" ]; then
        export GCS_IP="172.18.0.1"
    fi
    log_message "GCS IP for MAVLink routing: $GCS_IP"

    # Check if mavlink-routerd is installed
    if ! command -v mavlink-routerd &> /dev/null; then
        log_message "WARNING: mavlink-routerd not installed. MAVLink routing cannot start."
        log_message "To install: git clone https://github.com/alireza787b/mavlink-anywhere && cd mavlink-anywhere && sudo ./install_mavlink_router.sh"
        return 1
    fi

    # Run mavlink router in the background
    if [ -x "$MAVLINK_ROUTER_SCRIPT" ]; then
        local router_input_port="${PX4_GCS_MAVLINK_PORT:-14550}"
        log_message "MAVLink router input port: $router_input_port"
        launch_with_log_policy "$MAVLINK_ROUTER_LOG" "$MAVLINK_ROUTER_SCRIPT" "$router_input_port"
        mavlink_router_pid="$LAUNCH_WITH_LOG_POLICY_LAST_PID"
        log_message "MAVLink router started with PID: $mavlink_router_pid. Output: $(describe_log_policy_target "$MAVLINK_ROUTER_LOG")"
        sleep 2  # Wait for router to initialize before starting other services
        if ! kill -0 "$mavlink_router_pid" 2>/dev/null; then
            log_message "ERROR: MAVLink router exited during startup. Recent log lines:"
            tail_log_file "$MAVLINK_ROUTER_LOG"
            return 1
        fi
    else
        log_message "WARNING: MAVLink router script not found or not executable: $MAVLINK_ROUTER_SCRIPT"
        return 1
    fi
}

# Detect PX4's live MAVLink GCS output port so the router matches the image's
# actual runtime behavior instead of relying on a single hardcoded assumption.
detect_px4_mavlink_port() {
    local expected_port=14550
    local default_port="${MDS_PX4_GCS_PORT:-$expected_port}"
    local detection_log="$BASE_DIR/logs/mavlink_port_detection.log"

    if [ -n "${MDS_PX4_GCS_PORT:-}" ]; then
        PX4_GCS_MAVLINK_PORT="$MDS_PX4_GCS_PORT"
        log_message "Using PX4 MAVLink port override from MDS_PX4_GCS_PORT: $PX4_GCS_MAVLINK_PORT"
        return 0
    fi

    if [ ! -f "$PX4_MAVLINK_PORT_DETECTOR" ]; then
        PX4_GCS_MAVLINK_PORT="$default_port"
        log_message "WARNING: MAVLink port detector not found. Falling back to port $PX4_GCS_MAVLINK_PORT"
        return 0
    fi

    mkdir -p "$(dirname "$detection_log")"
    PX4_GCS_MAVLINK_PORT=$(python3 "$PX4_MAVLINK_PORT_DETECTOR" \
        --default-port "$default_port" \
        --timeout 12 \
        --poll-interval 0.5 \
        --sitl-log "$BASE_DIR/logs/sitl_simulation.log" \
        --exclude-port 12550 \
        --exclude-port 14540 \
        --exclude-port 14569 \
        --exclude-port 24550 \
        2>>"$detection_log")

    if [[ ! "$PX4_GCS_MAVLINK_PORT" =~ ^[0-9]+$ ]]; then
        PX4_GCS_MAVLINK_PORT="$default_port"
        log_message "WARNING: Invalid detected PX4 MAVLink port. Falling back to $PX4_GCS_MAVLINK_PORT"
    fi

    if [ "$PX4_GCS_MAVLINK_PORT" -eq "$expected_port" ]; then
        log_message "PX4 MAVLink GCS port confirmed at $PX4_GCS_MAVLINK_PORT."
    else
        log_message "WARNING: PX4 MAVLink GCS port detected at $PX4_GCS_MAVLINK_PORT instead of expected $expected_port."
        log_message "WARNING: Using detected port to preserve telemetry. This suggests a legacy or modified SITL image/startup configuration."
    fi
}

# Function to run mavlink2rest in the background
run_mavlink2rest() {
    log_message "Starting mavlink2rest in the background..."

    # Ensure the logs directory exists
    mkdir -p "$(dirname "$MAVLINK2REST_LOG")"

    launch_with_log_policy "$MAVLINK2REST_LOG" mavlink2rest "${MAVLINK2REST_ARGS[@]}"
    mavlink2rest_pid="$LAUNCH_WITH_LOG_POLICY_LAST_PID"
    log_message "mavlink2rest started with PID: $mavlink2rest_pid. Output: $(describe_log_policy_target "$MAVLINK2REST_LOG")"
}

# Function to set up Python environment
setup_python_env() {
    if [ "$USE_GLOBAL_PYTHON" = false ]; then
        if [ ! -d "$VENV_DIR" ]; then
            log_message "Creating a Python virtual environment at $VENV_DIR..."
            python3 -m venv "$VENV_DIR"
            log_message "Virtual environment created successfully."
        else
            log_message "Python virtual environment already exists at $VENV_DIR."
        fi

        log_message "Activating the virtual environment..."
        source "$VENV_DIR/bin/activate"

        local desired_state
        local current_state=""
        desired_state=$(requirements_state_value)

        if [ -f "$VENV_REQUIREMENTS_MARKER" ]; then
            current_state=$(cat "$VENV_REQUIREMENTS_MARKER")
        fi

        if [ "$SITL_REQUIREMENTS_SYNC" != "true" ] && [ -n "$current_state" ]; then
            log_message "Skipping Python requirements sync (MDS_SITL_REQUIREMENTS_SYNC=false)."
            return
        fi

        if [ "$desired_state" = "$current_state" ]; then
            log_message "Python requirements already match requirements.txt."
            return
        fi

        log_message "Synchronizing Python requirements..."
        local pip_log="$BASE_DIR/logs/pip_install.log"
        if PIP_NO_CACHE_DIR=1 python3 -m pip install --upgrade pip -q &>"$pip_log" && \
            PIP_NO_CACHE_DIR=1 python3 -m pip install -q -r "$BASE_DIR/requirements.txt" &>>"$pip_log"; then
            printf "%s\n" "$desired_state" > "$VENV_REQUIREMENTS_MARKER"
            rm -f "$pip_log"
            log_message "Python requirements synchronized successfully."
        else
            log_message "ERROR: Failed to install Python requirements. See $pip_log for details."
            exit 1
        fi
    else
        log_message "Using global Python installation."
    fi
}

ensure_mavsdk_server() {
    mkdir -p "$BASE_DIR/logs"
    local force_refresh="false"

    if [ -n "${MDS_MAVSDK_VERSION:-}" ] || [ -n "${MDS_MAVSDK_URL:-}" ]; then
        force_refresh="true"
    fi

    if [ -f "$MAVSDK_BINARY_PATH" ] && [ ! -x "$MAVSDK_BINARY_PATH" ]; then
        chmod +x "$MAVSDK_BINARY_PATH"
    fi

    if [ "$force_refresh" != "true" ] && [ -x "$MAVSDK_BINARY_PATH" ]; then
        log_message "MAVSDK server binary ready: $MAVSDK_BINARY_PATH"
        return
    fi

    if [ ! -f "$MAVSDK_DOWNLOAD_SCRIPT" ]; then
        log_message "ERROR: MAVSDK server binary missing and download script not found: $MAVSDK_DOWNLOAD_SCRIPT"
        exit 1
    fi

    if ! command -v curl &>/dev/null; then
        log_message "ERROR: curl is required to download mavsdk_server but is not installed."
        exit 1
    fi

    local mavsdk_log="$BASE_DIR/logs/mavsdk_download.log"
    if [ "$force_refresh" = "true" ]; then
        log_message "Refreshing mavsdk_server because MDS_MAVSDK_VERSION or MDS_MAVSDK_URL was set."
        rm -f "$MAVSDK_BINARY_PATH"
    else
        log_message "MAVSDK server binary missing. Downloading it into $BASE_DIR..."
    fi

    if MDS_INSTALL_DIR="$BASE_DIR" bash "$MAVSDK_DOWNLOAD_SCRIPT" &>"$mavsdk_log"; then
        if [ -f "$MAVSDK_BINARY_PATH" ] && [ ! -x "$MAVSDK_BINARY_PATH" ]; then
            chmod +x "$MAVSDK_BINARY_PATH"
        fi

        if [ -x "$MAVSDK_BINARY_PATH" ]; then
            rm -f "$mavsdk_log"
            log_message "MAVSDK server binary installed successfully."
            return
        fi
    fi

    log_message "ERROR: Failed to provision mavsdk_server. Recent log lines:"
    tail_log_file "$mavsdk_log"
    exit 1
}

# Prepare PX4 build artifacts if the generated rcS file is not available yet.
prepare_px4_build_artifacts() {
    if [ -f "$PX4_RCS_PATH" ]; then
        log_message "PX4 rcS file found: $PX4_RCS_PATH"
        return
    fi

    log_message "PX4 rcS file not found. Preparing px4_sitl_default build artifacts..."
    cd "$PX4_DIR"
    if make px4_sitl_default &> "$PX4_BUILD_PREP_LOG"; then
        rm -f "$PX4_BUILD_PREP_LOG"
        log_message "PX4 build artifacts prepared successfully."
    else
        log_message "ERROR: Failed to prepare PX4 build artifacts. Recent log lines:"
        tail_log_file "$PX4_BUILD_PREP_LOG"
        exit 1
    fi

    if [ ! -f "$PX4_RCS_PATH" ]; then
        log_message "ERROR: PX4 rcS file still missing after build preparation: $PX4_RCS_PATH"
        exit 1
    fi
}

# Prepare SITL-only PX4 parameter overrides using the native PX4_PARAM_* env
# mechanism. PX4 applies these after the airframe defaults load, which is more
# reliable than mutating the generated build rcS file.
configure_px4_sitl_rcs() {
    log_message "Preparing PX4 SITL parameter overrides..."

    build_sitl_param_overrides

    if [ ${#PX4_PARAM_ENV_VARS[@]} -eq 0 ]; then
        log_message "No PX4 SITL parameter overrides requested."
    else
        log_message "Using PX4_PARAM_* environment overrides at launch time."
    fi
}

# Function to read offsets from trajectory CSV
# Note: x,y positions now come from trajectory CSV files (single source of truth), not config.json
read_offsets() {
    log_message "Reading offsets from trajectory CSV for HWID: $HWID..."

    OFFSET_X=0
    OFFSET_Y=0

    if [ ! -f "$CONFIG_FILE" ]; then
        log_message "WARNING: Configuration file $CONFIG_FILE does not exist. Using default offsets (0,0)."
        return
    fi

    # Read config.json to get pos_id for this hw_id
    if ! command -v jq &>/dev/null; then
        log_message "ERROR: jq is required. Install with: apt-get install -y jq"
        exit 1
    fi

    local drone_entry
    drone_entry=$(jq -c ".drones[] | select(.hw_id == $HWID)" "$CONFIG_FILE" 2>/dev/null)

    local POS_ID=""
    if [[ -z "$drone_entry" || "$drone_entry" == "null" ]]; then
        log_message "WARNING: HWID $HWID not found in $CONFIG_FILE. Using default offsets (0,0)."
        return
    else
        POS_ID=$(echo "$drone_entry" | jq -r '.pos_id')
        log_message "Found pos_id=$POS_ID for hw_id=$HWID"
    fi

    # Read trajectory CSV to get initial position (px, py from first row)
    TRAJECTORY_FILE="$BASE_DIR/shapes_sitl/swarm/processed/Drone ${POS_ID}.csv"

    if [ ! -f "$TRAJECTORY_FILE" ]; then
        log_message "WARNING: Trajectory file not found: $TRAJECTORY_FILE"
        log_message "Falling back to row spawning with fixed spacing for drone $HWID"
        # Spawn in row with 10m spacing
        OFFSET_X=0
        OFFSET_Y=$((($HWID - 1) * 10))
        log_message "Using fallback offsets - X: $OFFSET_X, Y: $OFFSET_Y (row formation)"
        return
    fi

    # Read the first waypoint and resolve px/py by header name so the parser
    # stays correct if processed trajectories include an idx column.
    local header
    local px_col
    local py_col
    header=$(head -1 "$TRAJECTORY_FILE")
    px_col=$(echo "$header" | tr ',' '\n' | grep -n '^px$' | cut -d: -f1)
    py_col=$(echo "$header" | tr ',' '\n' | grep -n '^py$' | cut -d: -f1)

    if [[ -z "$px_col" || -z "$py_col" ]]; then
        log_message "WARNING: Could not locate px/py columns in $TRAJECTORY_FILE. Using default offsets (0,0)."
        return
    fi

    OFFSET_X=$(awk -v col="$px_col" -F "," 'NR==2 {print $col}' "$TRAJECTORY_FILE")
    OFFSET_Y=$(awk -v col="$py_col" -F "," 'NR==2 {print $col}' "$TRAJECTORY_FILE")

    if [[ -n "$OFFSET_X" && -n "$OFFSET_Y" ]]; then
        log_message "Found trajectory offsets from $TRAJECTORY_FILE - X: $OFFSET_X, Y: $OFFSET_Y"
        return
    fi

    log_message "WARNING: Could not read trajectory data from $TRAJECTORY_FILE. Using default offsets (0,0)."
}

# Function to calculate new geographic coordinates
calculate_new_coordinates() {
    log_message "Calculating new geographic coordinates based on offsets..."

    local coord_helper="$BASE_DIR/multiple_sitl/calculate_spawn_coordinates.py"
    local coord_output

    if [[ ! -f "$coord_helper" ]]; then
        log_message "ERROR: Coordinate helper missing: $coord_helper"
        exit 1
    fi

    if ! coord_output=$(python3 "$coord_helper" \
        --lat="$DEFAULT_LAT" \
        --lon="$DEFAULT_LON" \
        --offset-north="$OFFSET_X" \
        --offset-east="$OFFSET_Y" 2>&1); then
        log_message "ERROR: Failed to calculate spawn coordinates: $coord_output"
        exit 1
    fi

    NEW_LAT=$(echo "$coord_output" | awk -F= '/^NEW_LAT=/{print $2}')
    NEW_LON=$(echo "$coord_output" | awk -F= '/^NEW_LON=/{print $2}')

    if [[ -z "$NEW_LAT" || -z "$NEW_LON" ]]; then
        log_message "ERROR: Coordinate helper returned incomplete output: $coord_output"
        exit 1
    fi

    log_message "New Coordinates - Latitude: $NEW_LAT, Longitude: $NEW_LON"
}

# Function to export environment variables for PX4 SITL
export_env_vars() {
    log_message "Exporting environment variables for PX4 SITL..."
    export PX4_HOME_LAT="$NEW_LAT"
    export PX4_HOME_LON="$NEW_LON"
    export PX4_HOME_ALT="$DEFAULT_ALT"
    export MAV_SYS_ID="$HWID"
    export MDS_HW_ID="$HWID"
    log_message "Environment variables set: PX4_HOME_LAT=$PX4_HOME_LAT, PX4_HOME_LON=$PX4_HOME_LON, PX4_HOME_ALT=$PX4_HOME_ALT, MAV_SYS_ID=$MAV_SYS_ID, MDS_HW_ID=$MDS_HW_ID"
}

# Function to determine the simulation command
determine_simulation_command() {
    if [ "$REQUESTED_SIMULATION_MODE" != "h" ]; then
        log_message "WARNING: Legacy simulation mode '$REQUESTED_SIMULATION_MODE' requested."
        log_message "WARNING: Docker SITL now always uses headless PX4 Gazebo Harmonic (${PX4_GZ_TARGET})."
    fi

    SIMULATION_ENV_VARS=(
        "HEADLESS=1"
        "QT_QPA_PLATFORM=$QT_QPA_PLATFORM_VALUE"
        "GZ_PARTITION=$GZ_PARTITION_VALUE"
    )
    if [ ${#PX4_PARAM_ENV_VARS[@]} -gt 0 ]; then
        SIMULATION_ENV_VARS+=("${PX4_PARAM_ENV_VARS[@]}")
    fi
    SIMULATION_COMMAND=(make px4_sitl "$PX4_GZ_TARGET")

    log_message "Simulation Runtime: PX4 Gazebo Harmonic (${PX4_GZ_TARGET}) in headless mode"
    log_message "Simulation Environment: ${SIMULATION_ENV_VARS[*]}"
    log_message "Simulation Command: ${SIMULATION_COMMAND[*]}"
}

# Function to start SITL simulation
start_simulation() {
    log_message "Starting SITL simulation..."
    cd "$PX4_DIR"

    # Export instance identifier
    export px4_instance="${HWID}-1"

    # Execute the simulation command in the background
    launch_with_log_policy "$BASE_DIR/logs/sitl_simulation.log" env "${SIMULATION_ENV_VARS[@]}" "${SIMULATION_COMMAND[@]}"
    simulation_pid="$LAUNCH_WITH_LOG_POLICY_LAST_PID"
    log_message "SITL simulation started with PID: $simulation_pid. Output: $(describe_log_policy_target "$BASE_DIR/logs/sitl_simulation.log")"
}

validate_simulation_startup() {
    log_message "Validating PX4 SITL startup..."
    sleep 2

    if ! kill -0 "$simulation_pid" 2>/dev/null; then
        log_message "ERROR: SITL simulation exited during startup. Recent log lines:"
        tail_log_file "$BASE_DIR/logs/sitl_simulation.log"
        exit 1
    fi

    log_message "PX4 SITL process is running (PID: $simulation_pid)."
    log_message "Expected PX4 MAVLink UDP ports: offboard=14540, gcs=14550"
}

# Function to run coordinator.py
run_coordinator() {
    log_message "Starting coordinator.py..."
    cd "$BASE_DIR"
    if [ "$USE_GLOBAL_PYTHON" = false ]; then
        source "$VENV_DIR/bin/activate"
    fi

    if [ "$VERBOSE_MODE" = true ]; then
        export MDS_LOG_LEVEL="${MDS_LOG_LEVEL:-DEBUG}"
    else
        export MDS_LOG_LEVEL="${MDS_LOG_LEVEL:-INFO}"
    fi
    export MDS_LOG_FILE_LEVEL="${MDS_LOG_FILE_LEVEL:-DEBUG}"

    if [ "$VERBOSE_MODE" = true ]; then
        log_message "Running coordinator.py in verbose mode (foreground)."
        python3 "$BASE_DIR/coordinator.py"
        # Script will wait here until coordinator.py exits
    else
        launch_with_log_policy "$BASE_DIR/logs/coordinator.log" python3 "$BASE_DIR/coordinator.py"
        coordinator_pid="$LAUNCH_WITH_LOG_POLICY_LAST_PID"
        log_message "coordinator.py started with PID: $coordinator_pid. Output: $(describe_log_policy_target "$BASE_DIR/logs/coordinator.log")"
    fi
}

# =============================================================================
# Main Script Execution
# =============================================================================

# Parse script arguments
parse_args "$@"
load_git_auth_token

# Trap SIGINT and SIGTERM to execute cleanup
trap 'cleanup' INT TERM

log_message "=============================================="
log_message " Welcome to the SITL Startup Script!"
log_message "=============================================="
log_message ""

ensure_runtime_paths
validate_runtime_configuration
log_startup_configuration
log_message ""

# Check for necessary dependencies
check_dependencies

# Wait for the .hwID file
wait_for_hwid

# Resolve per-drone runtime values once HWID is known
resolve_gz_partition
build_sitl_param_overrides
log_runtime_identity

# Update the repository
update_repository
log_image_runtime_mode

# Run MAVLink2rest in the background
#run_mavlink2rest

# Set up Python environment
setup_python_env
ensure_mavsdk_server

# Clean up any stale simulator processes before launching a fresh instance.
cleanup_stale_simulation_processes

# Ensure PX4 build artifacts exist and prepare PX4 launch-time parameter overrides.
prepare_px4_build_artifacts
configure_px4_sitl_rcs

# Read offsets from config.json
read_offsets

# Calculate new geographic coordinates
calculate_new_coordinates

# Export environment variables
export_env_vars

# Determine simulation mode
determine_simulation_command

# Start SITL simulation
start_simulation

# Validate PX4 process health and expected default port assumptions early.
validate_simulation_startup

# Detect PX4's actual MAVLink output port before routing.
detect_px4_mavlink_port

# Start MAVLink router for external routing (replaces internal MavlinkManager)
# This routes MAVLink from the detected PX4 GCS port to local consumers and remote GCS.
if ! run_mavlink_router; then
    log_message "ERROR: Failed to start MAVLink router."
    exit 1
fi

# Start coordinator.py
run_coordinator

log_message ""
log_message "=============================================="
log_message "All processes have been initialized."
log_message "coordinator.py is running."
log_message "Press Ctrl+C to terminate the simulation."
log_message "=============================================="
log_message ""

# Wait for the simulation process to complete
wait "$simulation_pid"

if [ "$VERBOSE_MODE" = false ]; then
    # Wait for coordinator.py process to complete
    log_message "Waiting for coordinator.py process to complete..."
    wait "$coordinator_pid"
fi

# Wait for mavlink2rest process to complete (if it was started)
if [ -n "${mavlink2rest_pid:-}" ]; then
    log_message "Waiting for mavlink2rest process to complete..."
    wait "$mavlink2rest_pid" 2>/dev/null || true
fi

# Wait for mavlink router process to complete (if it was started)
if [ -n "${mavlink_router_pid:-}" ]; then
    log_message "Waiting for mavlink router process to complete..."
    wait "$mavlink_router_pid" 2>/dev/null || true
fi

# Exit successfully
exit 0
