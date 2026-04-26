#!/bin/bash
# =============================================================================
# MDS GCS Initialization Library: Common Utilities
# =============================================================================
# Version: Reads from VERSION file
# Description: GCS-specific constants and utilities (extends mds_init_lib/common.sh)
# Author: MDS Team
# =============================================================================

# Prevent double-sourcing
[[ -n "${_MDS_GCS_COMMON_LOADED:-}" ]] && return 0
_MDS_GCS_COMMON_LOADED=1

# =============================================================================
# SOURCE BASE COMMON LIBRARY
# =============================================================================

# Determine script directory
GCS_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MDS_INIT_LIB_DIR="${GCS_SCRIPT_DIR}/../mds_init_lib"

# Source base common.sh if available
if [[ -f "${MDS_INIT_LIB_DIR}/common.sh" ]]; then
    source "${MDS_INIT_LIB_DIR}/common.sh"
else
    echo "ERROR: Cannot find mds_init_lib/common.sh" >&2
    exit 1
fi

# =============================================================================
# GCS-SPECIFIC CONSTANTS (Override base constants)
# =============================================================================

GCS_REPO_ROOT="${GCS_REPO_ROOT:-$(cd "${GCS_SCRIPT_DIR}/../.." && pwd)}"
if [[ -f "${GCS_REPO_ROOT}/VERSION" ]]; then
    readonly GCS_VERSION="$(tr -d '[:space:]' < "${GCS_REPO_ROOT}/VERSION")"
else
    readonly GCS_VERSION="5.0"
fi
readonly GCS_STATE_FILE="${GCS_STATE_FILE:-${MDS_STATE_DIR}/gcs_init_state.json}"
readonly GCS_CONFIG_FILE="${GCS_CONFIG_FILE:-${MDS_CONFIG_DIR}/gcs.env}"
readonly GCS_LOG_FILE="${GCS_LOG_FILE:-${MDS_LOG_DIR}/mds_gcs_init.log}"

# GCS Phases
readonly -a GCS_PHASES=(
    "prereqs"
    "python"
    "nodejs"
    "repository"
    "firewall"
    "python_env"
    "nodejs_env"
    "env_config"
    "services"
    "verify"
)

# GCS Required Ports
declare -A GCS_PORTS=(
    ["22/tcp"]="SSH access"
    ["${MDS_DEFAULT_GCS_API_PORT:-5030}/tcp"]="GCS API Server (FastAPI)"
    ["${MDS_DEFAULT_DASHBOARD_PORT:-3030}/tcp"]="React Dashboard"
    ["14550/udp"]="GCS MAVLink (from drones)"
)

# Python requirements - critical packages to verify
readonly -a GCS_PYTHON_PACKAGES=(
    "fastapi"
    "uvicorn"
    "gunicorn"
    "aiohttp"
    "mavsdk"
)

# Node.js minimum version
readonly GCS_NODE_MIN_VERSION="18"
readonly GCS_NODE_TARGET_VERSION="22"

# Python minimum version
readonly GCS_PYTHON_MIN_VERSION="3.11"

# Default repository settings (git-tracked deployment profile)
readonly GCS_DEFAULT_REPO="${GCS_DEFAULT_REPO:-${MDS_DEFAULT_REPO_URL_HTTPS}}"
readonly GCS_DEFAULT_REPO_SSH="${GCS_DEFAULT_REPO_SSH:-${MDS_DEFAULT_REPO_URL_SSH}}"
readonly GCS_DEFAULT_BRANCH="${GCS_DEFAULT_BRANCH:-${MDS_DEFAULT_BRANCH}}"
readonly GCS_DEFAULT_REPO_OWNER="${GCS_DEFAULT_REPO_OWNER:-${MDS_DEFAULT_REPO_OWNER}}"

# =============================================================================
# PROGRESS SPINNER (UX feedback for long operations)
# =============================================================================
# Usage:
#   start_progress "Installing packages" "may take 1-2 min"
#   apt-get install -y foo >/dev/null 2>&1
#   stop_progress $?
#
# The spinner runs in background writing to /dev/tty so it doesn't
# interfere with command output capture. Shows elapsed time so the
# user always knows the system is alive.

_PROGRESS_PID=""
_PROGRESS_START=""

start_progress() {
    local message="$1"
    local hint="${2:-}"

    # Don't start if not a terminal or already running
    [[ ! -t 1 ]] && return 0
    [[ -n "$_PROGRESS_PID" ]] && stop_progress 0

    _PROGRESS_START=$(date +%s)

    # Subshell inherits parent variables — use them directly
    (
        local _sp_chars='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
        local _sp_i=0
        local _sp_start="$_PROGRESS_START"
        local _sp_msg="$message"
        local _sp_hint="$hint"
        while true; do
            local _sp_now=$(date +%s)
            local _sp_elapsed=$(( _sp_now - _sp_start ))
            local _sp_c="${_sp_chars:_sp_i%10:1}"
            local _sp_time="${_sp_elapsed}s"
            if [[ $_sp_elapsed -ge 60 ]]; then
                _sp_time="$((_sp_elapsed/60))m$((_sp_elapsed%60))s"
            fi
            if [[ -n "$_sp_hint" ]]; then
                printf "\r  \033[0;36m[%s]\033[0m %s \033[2m(%s, %s)\033[0m " "$_sp_c" "$_sp_msg" "$_sp_hint" "$_sp_time" >/dev/tty 2>/dev/null
            else
                printf "\r  \033[0;36m[%s]\033[0m %s \033[2m%s\033[0m " "$_sp_c" "$_sp_msg" "$_sp_time" >/dev/tty 2>/dev/null
            fi
            ((_sp_i++))
            sleep 0.3
        done
    ) &
    _PROGRESS_PID=$!
    disown "$_PROGRESS_PID" 2>/dev/null
}

stop_progress() {
    local exit_code="${1:-0}"

    if [[ -n "$_PROGRESS_PID" ]]; then
        kill "$_PROGRESS_PID" 2>/dev/null
        wait "$_PROGRESS_PID" 2>/dev/null
        _PROGRESS_PID=""
        # Clear the spinner line
        printf "\r%-80s\r" "" >/dev/tty 2>/dev/null || true
    fi

    return "$exit_code"
}

# Cleanup spinner on script exit (prevents orphan spinner processes)
_cleanup_progress() {
    if [[ -n "$_PROGRESS_PID" ]]; then
        kill "$_PROGRESS_PID" 2>/dev/null
        wait "$_PROGRESS_PID" 2>/dev/null
        _PROGRESS_PID=""
    fi
}
trap '_cleanup_progress' EXIT

# =============================================================================
# GCS-SPECIFIC LOGGING
# =============================================================================

# Initialize GCS logging (uses GCS_LOG_FILE)
gcs_init_logging() {
    mkdir -p "${MDS_LOG_DIR}" 2>/dev/null || true
    touch "${GCS_LOG_FILE}" 2>/dev/null || true
    chmod 644 "${GCS_LOG_FILE}" 2>/dev/null || true
}

# GCS-specific internal log function (logs to GCS log file)
_gcs_log() {
    local level="$1"
    local message="$2"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    # Write to GCS log file
    echo "[$timestamp] [$level] $message" >> "${GCS_LOG_FILE}" 2>/dev/null || true

    # Also write to syslog if available
    if command -v logger &>/dev/null; then
        logger -t "mds_gcs_init" -p "user.${level,,}" "$message" 2>/dev/null || true
    fi
}

# Override logging functions to use GCS log file
log_info() {
    local message="$1"
    _gcs_log "INFO" "$message"
    if [[ "${VERBOSE:-false}" == "true" ]]; then
        echo -e "  ${INFO} ${message}"
    fi
    return 0
}

log_success() {
    local message="$1"
    _gcs_log "INFO" "$message"
    echo -e "  ${CHECK} ${message}"
}

log_warn() {
    local message="$1"
    _gcs_log "WARN" "$message"
    echo -e "  ${WARN} ${YELLOW}${message}${NC}"
}

log_error() {
    local message="$1"
    _gcs_log "ERROR" "$message"
    echo -e "  ${CROSS} ${RED}${message}${NC}"
}

log_debug() {
    local message="$1"
    _gcs_log "DEBUG" "$message"
    if [[ "${DEBUG:-false}" == "true" ]]; then
        echo -e "  ${DIM}[DEBUG] ${message}${NC}"
    fi
    return 0
}

log_step() {
    local message="$1"
    _gcs_log "INFO" "Step: $message"
    echo -e "  ${ARROW} ${message}"
}

# =============================================================================
# GCS BRANDING
# =============================================================================

# Source the shared banner file
MDS_BANNER_PATH="${GCS_SCRIPT_DIR}/../mds_banner.sh"
if [[ -f "$MDS_BANNER_PATH" ]]; then
    source "$MDS_BANNER_PATH"
fi

print_gcs_banner() {
    local branch="${1:-}"
    local commit="${2:-}"

    # Use shared banner if available
    if type print_mds_banner &>/dev/null; then
        print_mds_banner "Ground Control Station" "${GCS_VERSION}" "${branch}" "${commit}"
    else
        # Fallback to inline banner
        echo -e "${CYAN}"
        echo ",--.   ,--.,------.   ,---.   "
        echo "|   \`.'   ||  .-.  \\ '   .-'  "
        echo "|  |'.'|  ||  |  \\  :\`.  \`-.  "
        echo "|  |   |  ||  '--'  /.-'    | "
        echo "\`--'   \`--'\`-------' \`-----'  "
        echo -e "${NC}"
        echo -e "${WHITE}MAVSDK Drone Show - Ground Control Station${NC}"
        echo "================================================"
        echo -e "Version:  ${WHITE}${GCS_VERSION}${NC}"
        [[ -n "$branch" ]] && echo -e "Branch:   ${WHITE}$branch${NC}"
        [[ -n "$commit" ]] && echo -e "Commit:   ${WHITE}$commit${NC}"
        echo "================================================"
        echo ""
    fi
    echo -e "${DIM}              Enterprise Drone Swarm Platform${NC}"
    echo ""
}

# =============================================================================
# GCS STATE MANAGEMENT
# =============================================================================

# Initialize GCS state file
gcs_state_init() {
    mkdir -p "${MDS_STATE_DIR}" 2>/dev/null || true

    # Check if state file exists and validate JSON
    if [[ -f "${GCS_STATE_FILE}" ]] && [[ "${FORCE:-false}" != "true" ]]; then
        if command -v jq &>/dev/null; then
            if jq empty "${GCS_STATE_FILE}" 2>/dev/null; then
                log_debug "GCS state file valid: ${GCS_STATE_FILE}"
                return 0
            else
                local backup="${GCS_STATE_FILE}.corrupt.$(date +%Y%m%d_%H%M%S)"
                mv "${GCS_STATE_FILE}" "$backup"
                log_warn "GCS state file was corrupt, backed up to: $backup"
            fi
        fi
    fi

    # Create new state file if needed
    if [[ ! -f "${GCS_STATE_FILE}" ]] || [[ "${FORCE:-false}" == "true" ]]; then
        cat > "${GCS_STATE_FILE}" << EOF
{
  "version": "${GCS_VERSION}",
  "mode": "gcs",
  "started_at": "$(date -Iseconds)",
  "install_dir": "${GCS_INSTALL_DIR:-$(pwd)}",
  "user": "$(whoami)",
  "phases": {},
  "values": {}
}
EOF
        chmod 600 "${GCS_STATE_FILE}"  # Owner-only for security
        log_debug "Initialized GCS state file: ${GCS_STATE_FILE}"
    fi
}

# Get phase status from GCS state
gcs_state_get_phase() {
    local phase="$1"
    if [[ -f "${GCS_STATE_FILE}" ]] && command -v jq &>/dev/null; then
        jq -r ".phases.${phase}.status // \"pending\"" "${GCS_STATE_FILE}" 2>/dev/null || echo "pending"
    else
        echo "pending"
    fi
}

# Update phase status in GCS state
gcs_state_set_phase() {
    local phase="$1"
    local status="$2"

    if [[ -f "${GCS_STATE_FILE}" ]] && command -v jq &>/dev/null; then
        local timestamp
        timestamp=$(date -Iseconds)
        local tmp_file="${GCS_STATE_FILE}.tmp"

        jq ".phases.${phase} = {\"status\": \"${status}\", \"timestamp\": \"${timestamp}\"}" \
            "${GCS_STATE_FILE}" > "${tmp_file}" && mv "${tmp_file}" "${GCS_STATE_FILE}"

        log_debug "GCS State: ${phase} -> ${status}"
    fi
}

# Store a value in GCS state
gcs_state_set_value() {
    local key="$1"
    local value="$2"

    if [[ -f "${GCS_STATE_FILE}" ]] && command -v jq &>/dev/null; then
        local tmp_file="${GCS_STATE_FILE}.tmp"
        jq ".values.${key} = \"${value}\"" "${GCS_STATE_FILE}" > "${tmp_file}" && \
            mv "${tmp_file}" "${GCS_STATE_FILE}"
    fi
}

# Get a value from GCS state
gcs_state_get_value() {
    local key="$1"
    local default="${2:-}"

    if [[ -f "${GCS_STATE_FILE}" ]] && command -v jq &>/dev/null; then
        local value
        value=$(jq -r ".values.${key} // \"\"" "${GCS_STATE_FILE}" 2>/dev/null)
        [[ -n "$value" ]] && echo "$value" || echo "$default"
    else
        echo "$default"
    fi
}

# Reset GCS state for fresh start
gcs_state_reset() {
    rm -f "${GCS_STATE_FILE}"
    gcs_state_init
    log_info "GCS state reset complete"
}

# =============================================================================
# GCS UTILITY FUNCTIONS
# =============================================================================

# Check OS version and distribution
get_os_info() {
    if [[ -f /etc/os-release ]]; then
        source /etc/os-release
        echo "${ID}:${VERSION_ID}"
    else
        echo "unknown:unknown"
    fi
}

# Get Ubuntu version number
get_ubuntu_version() {
    if [[ -f /etc/os-release ]]; then
        source /etc/os-release
        if [[ "$ID" == "ubuntu" ]]; then
            echo "${VERSION_ID}"
            return 0
        fi
    fi
    echo ""
}

# Check minimum disk space (in GB)
check_disk_space() {
    local required_gb="${1:-5}"
    local path="${2:-/}"
    local available_mb
    available_mb=$(get_disk_space_mb "$path")
    local required_mb=$((required_gb * 1024))

    [[ $available_mb -ge $required_mb ]]
}

# Get Python version
get_python_version() {
    local python_cmd="${1:-python3}"
    if command_exists "$python_cmd"; then
        "$python_cmd" --version 2>&1 | grep -oP '\d+\.\d+\.\d+' || echo ""
    else
        echo ""
    fi
}

# Compare version strings (returns 0 if $1 >= $2)
version_gte() {
    local version1="$1"
    local version2="$2"

    printf '%s\n%s\n' "$version2" "$version1" | sort -V -C
}

# =============================================================================
# NODE.JS DISCOVERY (sudo/nvm-aware)
# =============================================================================

# Discover Node.js binary across common install locations.
# When running as sudo, the user's nvm/volta/fnm paths are not in root's PATH.
# This function searches all common locations and adds the best one to PATH.
# Sets: _MDS_NODE_DIR (the directory containing node/npm)
_MDS_NODE_DIR=""

discover_nodejs() {
    # Already discovered and in PATH
    if [[ -n "$_MDS_NODE_DIR" ]] && command -v node &>/dev/null; then
        return 0
    fi

    local search_paths=()
    local invoking_user="${SUDO_USER:-$(whoami)}"
    local invoking_home
    invoking_home=$(eval echo "~${invoking_user}" 2>/dev/null)

    # 1. nvm (most common for developers)
    #    Check invoking user's nvm first, then root's
    if [[ -n "$invoking_home" ]] && [[ -d "${invoking_home}/.nvm/versions/node" ]]; then
        # Find latest nvm-installed version (highest version number)
        local nvm_latest
        nvm_latest=$(ls -d "${invoking_home}/.nvm/versions/node"/v* 2>/dev/null | sort -V | tail -1)
        [[ -n "$nvm_latest" ]] && search_paths+=("${nvm_latest}/bin")
    fi
    if [[ -d "/root/.nvm/versions/node" ]]; then
        local nvm_root_latest
        nvm_root_latest=$(ls -d /root/.nvm/versions/node/v* 2>/dev/null | sort -V | tail -1)
        [[ -n "$nvm_root_latest" ]] && search_paths+=("${nvm_root_latest}/bin")
    fi

    # 2. Official Node.js binary installer (/usr/local/bin)
    search_paths+=("/usr/local/bin")

    # 3. volta
    [[ -n "$invoking_home" ]] && search_paths+=("${invoking_home}/.volta/bin")

    # 4. fnm
    [[ -n "$invoking_home" ]] && search_paths+=("${invoking_home}/.local/share/fnm/aliases/default/bin")

    # 5. snap
    search_paths+=("/snap/bin")

    # 6. System apt (last resort)
    search_paths+=("/usr/bin")

    # Search each path for a working node binary
    for dir in "${search_paths[@]}"; do
        if [[ -x "${dir}/node" ]]; then
            local ver
            ver=$("${dir}/node" --version 2>/dev/null | grep -oP '\d+\.\d+\.\d+')
            if [[ -n "$ver" ]]; then
                local major="${ver%%.*}"
                if [[ "$major" -ge "$GCS_NODE_MIN_VERSION" ]]; then
                    _MDS_NODE_DIR="$dir"
                    # Add to PATH if not already there
                    if [[ ":$PATH:" != *":${dir}:"* ]]; then
                        export PATH="${dir}:${PATH}"
                    fi
                    log_debug "Discovered Node.js v${ver} at ${dir}/node"
                    return 0
                else
                    log_debug "Found Node.js v${ver} at ${dir}/node (too old, need >= ${GCS_NODE_MIN_VERSION})"
                fi
            fi
        fi
    done

    return 1
}

# Get Node.js version (calls discover_nodejs first)
get_node_version() {
    discover_nodejs &>/dev/null
    if command -v node &>/dev/null; then
        node --version 2>&1 | grep -oP '\d+\.\d+\.\d+' || echo ""
    else
        echo ""
    fi
}

# Get npm version (calls discover_nodejs first)
get_npm_version() {
    discover_nodejs &>/dev/null
    if command -v npm &>/dev/null; then
        npm --version 2>&1 | grep -oP '\d+\.\d+\.\d+' || echo ""
    else
        echo ""
    fi
}

# =============================================================================
# EXPORT FOR SUBSHELLS
# =============================================================================

export GCS_VERSION GCS_STATE_FILE GCS_CONFIG_FILE GCS_LOG_FILE
export GCS_DEFAULT_REPO GCS_DEFAULT_REPO_SSH GCS_DEFAULT_BRANCH GCS_DEFAULT_REPO_OWNER
export GCS_NODE_MIN_VERSION GCS_NODE_TARGET_VERSION GCS_PYTHON_MIN_VERSION
