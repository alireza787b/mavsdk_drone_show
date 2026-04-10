#!/bin/bash
# =============================================================================
# MDS Initialization Library: Common Utilities
# =============================================================================
# Version: 4.5.0
# Description: Core utilities for mds_node_init.sh - colors, logging, state, branding
# Author: MDS Team
# =============================================================================

# Prevent double-sourcing
[[ -n "${_MDS_COMMON_LOADED:-}" ]] && return 0
_MDS_COMMON_LOADED=1

# =============================================================================
# CONSTANTS
# =============================================================================

readonly MDS_VERSION="4.5.0"
readonly MDS_STATE_DIR="/var/lib/mds"
readonly MDS_STATE_FILE="${MDS_STATE_DIR}/init_state.json"
readonly MDS_CONFIG_DIR="/etc/mds"
readonly MDS_LOCAL_ENV="${MDS_CONFIG_DIR}/local.env"
readonly MDS_NODE_IDENTITY_FILE="${MDS_CONFIG_DIR}/node_identity.json"
readonly MDS_INSTALL_DIR="/home/droneshow/mavsdk_drone_show"
readonly MDS_USER="droneshow"
readonly MDS_LOG_DIR="/var/log/mds"
readonly MDS_LOG_FILE="${MDS_LOG_DIR}/mds_init.log"

# =============================================================================
# TERMINAL COLORS
# =============================================================================

# Check if stdout is a terminal
if [[ -t 1 ]]; then
    readonly RED='\033[0;31m'
    readonly GREEN='\033[0;32m'
    readonly YELLOW='\033[1;33m'
    readonly BLUE='\033[0;34m'
    readonly MAGENTA='\033[0;35m'
    readonly CYAN='\033[0;36m'
    readonly WHITE='\033[1;37m'
    readonly BOLD='\033[1m'
    readonly DIM='\033[2m'
    readonly NC='\033[0m'  # No Color
    readonly CHECK="${GREEN}[✓]${NC}"
    readonly CROSS="${RED}[✗]${NC}"
    readonly ARROW="${CYAN}[→]${NC}"
    readonly WARN="${YELLOW}[!]${NC}"
    readonly INFO="${BLUE}[i]${NC}"
    readonly SPIN="${CYAN}[⋯]${NC}"
else
    readonly RED=''
    readonly GREEN=''
    readonly YELLOW=''
    readonly BLUE=''
    readonly MAGENTA=''
    readonly CYAN=''
    readonly WHITE=''
    readonly BOLD=''
    readonly DIM=''
    readonly NC=''
    readonly CHECK='[OK]'
    readonly CROSS='[FAIL]'
    readonly ARROW='[->]'
    readonly WARN='[!]'
    readonly INFO='[i]'
    readonly SPIN='[...]'
fi

# =============================================================================
# LOGGING FUNCTIONS
# =============================================================================

# Initialize logging
init_logging() {
    mkdir -p "${MDS_LOG_DIR}" 2>/dev/null || true
    touch "${MDS_LOG_FILE}" 2>/dev/null || true
    chmod 644 "${MDS_LOG_FILE}" 2>/dev/null || true
}

# Internal log function
_log() {
    local level="$1"
    local message="$2"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    # Always write to log file
    echo "[$timestamp] [$level] $message" >> "${MDS_LOG_FILE}" 2>/dev/null || true

    # Also write to syslog if available
    if command -v logger &>/dev/null; then
        logger -t "mds_init" -p "user.${level,,}" "$message" 2>/dev/null || true
    fi
}

# Public logging functions
log_info() {
    local message="$1"
    _log "INFO" "$message"
    if [[ "${VERBOSE:-false}" == "true" ]]; then
        echo -e "  ${INFO} ${message}"
    fi
    return 0
}

log_success() {
    local message="$1"
    _log "INFO" "$message"
    echo -e "  ${CHECK} ${message}"
}

log_warn() {
    local message="$1"
    _log "WARN" "$message"
    echo -e "  ${WARN} ${YELLOW}${message}${NC}"
}

log_error() {
    local message="$1"
    _log "ERROR" "$message"
    echo -e "  ${CROSS} ${RED}${message}${NC}"
}

log_debug() {
    local message="$1"
    _log "DEBUG" "$message"
    if [[ "${DEBUG:-false}" == "true" ]]; then
        echo -e "  ${DIM}[DEBUG] ${message}${NC}"
    fi
    return 0
}

log_step() {
    local message="$1"
    _log "INFO" "Step: $message"
    echo -e "  ${ARROW} ${message}"
}

# =============================================================================
# SHARED BANNER
# =============================================================================

# Source the shared banner file
_MDS_COMMON_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MDS_BANNER_PATH="${_MDS_COMMON_SCRIPT_DIR}/../mds_banner.sh"
if [[ -f "$MDS_BANNER_PATH" ]]; then
    source "$MDS_BANNER_PATH"
fi

# =============================================================================
# BRANDING AND DISPLAY
# =============================================================================

print_banner() {
    local branch="${1:-}"
    local commit="${2:-}"

    # Use shared banner if available
    if type print_mds_banner &>/dev/null; then
        print_mds_banner "Companion Node" "${MDS_VERSION}" "${branch}" "${commit}"
    else
        # Fallback to inline banner
        echo -e "${CYAN}"
        echo ",--.   ,--.,------.   ,---.   "
        echo "|   \`.'   ||  .-.  \\ '   .-'  "
        echo "|  |'.'|  ||  |  \\  :\`.  \`-.  "
        echo "|  |   |  ||  '--'  /.-'    | "
        echo "\`--'   \`--'\`-------' \`-----'  "
        echo -e "${NC}"
        echo -e "${WHITE}MAVSDK Drone Show - Companion Node${NC}"
        echo "================================================"
        echo -e "Version:  ${WHITE}${MDS_VERSION}${NC}"
        [[ -n "$branch" ]] && echo -e "Branch:   ${WHITE}$branch${NC}"
        [[ -n "$commit" ]] && echo -e "Commit:   ${WHITE}$commit${NC}"
        echo "================================================"
        echo ""
    fi
    echo -e "${DIM}                   Enterprise Drone Swarm Platform${NC}"
    echo ""
}

print_phase_header() {
    local phase_num="$1"
    local phase_name="$2"
    local total_phases="${3:-13}"

    echo ""
    echo -e "${CYAN}+==============================================================================+${NC}"
    echo -e "${CYAN}|${NC}  ${WHITE}PHASE ${phase_num}/${total_phases}: ${phase_name}${NC}"
    echo -e "${CYAN}+==============================================================================+${NC}"
    echo ""
}

print_section() {
    local title="$1"
    echo ""
    echo -e "  ${BOLD}${title}${NC}"
    echo -e "  ${DIM}$(printf '%.0s─' {1..60})${NC}"
}

print_box() {
    local content="$1"
    local width=78

    echo -e "${CYAN}┌$(printf '%.0s─' $(seq 1 $width))┐${NC}"
    while IFS= read -r line; do
        printf "${CYAN}│${NC} %-$((width-2))s ${CYAN}│${NC}\n" "$line"
    done <<< "$content"
    echo -e "${CYAN}└$(printf '%.0s─' $(seq 1 $width))┘${NC}"
}

print_progress() {
    local current="$1"
    local total="$2"
    local width=40
    local percent=$((current * 100 / total))
    local filled=$((current * width / total))
    local empty=$((width - filled))

    printf "\r  Progress: ${GREEN}"
    printf '%0.s█' $(seq 1 $filled)
    printf "${DIM}"
    printf '%0.s░' $(seq 1 $empty)
    printf "${NC} %3d%%" "$percent"
}

# =============================================================================
# STATE MANAGEMENT
# =============================================================================

# Initialize state file
state_init() {
    mkdir -p "${MDS_STATE_DIR}" 2>/dev/null || true

    # Check if state file exists and validate JSON
    if [[ -f "${MDS_STATE_FILE}" ]] && [[ "${FORCE:-false}" != "true" ]]; then
        if command -v jq &>/dev/null; then
            if jq empty "${MDS_STATE_FILE}" 2>/dev/null; then
                # Valid JSON - keep existing state file
                log_debug "State file valid: ${MDS_STATE_FILE}"
                return 0
            else
                # Invalid JSON - backup corrupted file and recreate
                local backup="${MDS_STATE_FILE}.corrupt.$(date +%Y%m%d_%H%M%S)"
                mv "${MDS_STATE_FILE}" "$backup"
                log_warn "State file was corrupt, backed up to: $backup"
            fi
        fi
    fi

    # Create new state file if needed
    if [[ ! -f "${MDS_STATE_FILE}" ]] || [[ "${FORCE:-false}" == "true" ]]; then
        cat > "${MDS_STATE_FILE}" << EOF
{
  "version": "${MDS_VERSION}",
  "started_at": "$(date -Iseconds)",
  "drone_id": null,
  "phases": {},
  "values": {}
}
EOF
        chmod 644 "${MDS_STATE_FILE}"
        log_debug "Initialized state file: ${MDS_STATE_FILE}"
    fi
}

# Get phase status from state
state_get_phase() {
    local phase="$1"
    if [[ -f "${MDS_STATE_FILE}" ]] && command -v jq &>/dev/null; then
        jq -r ".phases.${phase}.status // \"pending\"" "${MDS_STATE_FILE}" 2>/dev/null || echo "pending"
    else
        echo "pending"
    fi
}

# Update phase status in state
state_set_phase() {
    local phase="$1"
    local status="$2"

    if [[ -f "${MDS_STATE_FILE}" ]] && command -v jq &>/dev/null; then
        local timestamp
        timestamp=$(date -Iseconds)
        local tmp_file="${MDS_STATE_FILE}.tmp"

        jq ".phases.${phase} = {\"status\": \"${status}\", \"timestamp\": \"${timestamp}\"}" \
            "${MDS_STATE_FILE}" > "${tmp_file}" && mv "${tmp_file}" "${MDS_STATE_FILE}"

        log_debug "State: ${phase} -> ${status}"
    fi
}

# Store a value in state
state_set_value() {
    local key="$1"
    local value="$2"

    if [[ -f "${MDS_STATE_FILE}" ]] && command -v jq &>/dev/null; then
        local tmp_file="${MDS_STATE_FILE}.tmp"

        jq ".values.${key} = \"${value}\"" "${MDS_STATE_FILE}" > "${tmp_file}" && \
            mv "${tmp_file}" "${MDS_STATE_FILE}"
    fi
}

# Get a value from state
state_get_value() {
    local key="$1"
    local default="${2:-}"

    if [[ -f "${MDS_STATE_FILE}" ]] && command -v jq &>/dev/null; then
        local value
        value=$(jq -r ".values.${key} // \"\"" "${MDS_STATE_FILE}" 2>/dev/null)
        [[ -n "$value" ]] && echo "$value" || echo "$default"
    else
        echo "$default"
    fi
}

# Set drone ID in state
state_set_drone_id() {
    local drone_id="$1"

    if [[ -f "${MDS_STATE_FILE}" ]] && command -v jq &>/dev/null; then
        local tmp_file="${MDS_STATE_FILE}.tmp"
        jq ".drone_id = ${drone_id}" "${MDS_STATE_FILE}" > "${tmp_file}" && \
            mv "${tmp_file}" "${MDS_STATE_FILE}"
    fi
}

# Reset state for fresh start
state_reset() {
    rm -f "${MDS_STATE_FILE}"
    state_init
    log_info "State reset complete"
}

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

# Check if running as root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        return 1
    fi
    return 0
}

# Check if a command exists
command_exists() {
    command -v "$1" &>/dev/null
}

# Check if running on Raspberry Pi
is_raspberry_pi() {
    [[ -f /proc/device-tree/model ]] && grep -qi "raspberry" /proc/device-tree/model 2>/dev/null
}

# Get system architecture
get_architecture() {
    local arch
    arch=$(uname -m)
    case "$arch" in
        aarch64|arm64) echo "arm64" ;;
        armv7l|armhf) echo "armhf" ;;
        x86_64) echo "x86_64" ;;
        *) echo "$arch" ;;
    esac
}

# Returns success when interactive prompting is safe.
can_prompt() {
    [[ "${NON_INTERACTIVE:-false}" != "true" ]] && [[ -t 0 || -t 1 || -t 2 ]] && : </dev/tty >/dev/null 2>&1
}

# Prompt for input with default value
# Uses /dev/tty to work correctly when script is piped (curl | bash)
prompt_input() {
    local prompt="$1"
    local default="$2"
    local var_name="$3"
    local is_password="${4:-false}"

    if ! can_prompt; then
        eval "$var_name=\"$default\""
        return 0
    fi

    local input
    if [[ "$is_password" == "true" ]]; then
        read -s -p "  $prompt [$default]: " input </dev/tty
        echo ""
    else
        read -p "  $prompt [$default]: " input </dev/tty
    fi

    eval "$var_name=\"${input:-$default}\""
}

# Prompt for yes/no confirmation
# Uses /dev/tty to work correctly when script is piped (curl | bash)
confirm() {
    local prompt="$1"
    local default="${2:-y}"

    if ! can_prompt; then
        return 0
    fi

    local yn
    if [[ "$default" == "y" ]]; then
        read -p "  $prompt [Y/n]: " yn </dev/tty
        yn=${yn:-y}
    else
        read -p "  $prompt [y/N]: " yn </dev/tty
        yn=${yn:-n}
    fi

    [[ "${yn,,}" == "y" || "${yn,,}" == "yes" ]]
}

# Wait for user to press any key
# Uses /dev/tty to work correctly when script is piped (curl | bash)
wait_for_keypress() {
    local prompt="${1:-Press any key to continue...}"

    if ! can_prompt; then
        return 0
    fi

    echo ""
    read -n 1 -s -r -p "  $prompt" </dev/tty
    echo ""
}

# Wait with countdown
wait_countdown() {
    local seconds="$1"
    local message="${2:-Continuing in}"

    for ((i=seconds; i>0; i--)); do
        printf "\r  ${message} %d seconds... " "$i"
        sleep 1
    done
    printf "\r%-50s\r" ""
}

# Run command with retry
run_with_retry() {
    local cmd="$1"
    local max_retries="${2:-3}"
    local delay="${3:-5}"
    local description="${4:-command}"

    local attempt=1
    while [[ $attempt -le $max_retries ]]; do
        log_debug "Attempt $attempt/$max_retries: $description"

        if eval "$cmd"; then
            return 0
        fi

        if [[ $attempt -lt $max_retries ]]; then
            log_warn "Attempt $attempt failed, retrying in ${delay}s..."
            sleep "$delay"
            delay=$((delay * 2))  # Exponential backoff
        fi

        ((attempt++))
    done

    log_error "Failed after $max_retries attempts: $description"
    return 1
}

# Validate drone ID (1-999)
validate_drone_id() {
    local id="$1"

    if [[ ! "$id" =~ ^[0-9]+$ ]]; then
        return 1
    fi

    if [[ "$id" -lt 1 || "$id" -gt 999 ]]; then
        return 1
    fi

    return 0
}

# Validate IP address
validate_ip() {
    local ip="$1"
    local regex='^([0-9]{1,3}\.){3}[0-9]{1,3}$'

    if [[ ! "$ip" =~ $regex ]]; then
        return 1
    fi

    IFS='.' read -ra octets <<< "$ip"
    for octet in "${octets[@]}"; do
        if [[ "$octet" -gt 255 ]]; then
            return 1
        fi
    done

    return 0
}

# Validate CIDR notation
validate_cidr() {
    local cidr="$1"
    local regex='^([0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]{1,2}$'

    if [[ ! "$cidr" =~ $regex ]]; then
        return 1
    fi

    local ip="${cidr%/*}"
    local prefix="${cidr#*/}"

    validate_ip "$ip" && [[ "$prefix" -ge 0 && "$prefix" -le 32 ]]
}

# Get available disk space in MB
get_disk_space_mb() {
    local path="${1:-/}"
    df -BM "$path" | awk 'NR==2 {gsub(/M/, "", $4); print $4}'
}

# Set LED state via led_indicator.py if available
set_led_state() {
    local state="$1"
    local led_script="${MDS_INSTALL_DIR}/tools/led_indicator/led_indicator.py"

    if [[ -f "$led_script" ]]; then
        if command_exists python3; then
            python3 "$led_script" --state "$state" 2>/dev/null || true
        fi
    fi

    log_debug "LED state: $state"
}

# Check if droneshow user exists
user_exists() {
    local username="${1:-$MDS_USER}"
    id "$username" &>/dev/null
}

# Check if a service is active
service_is_active() {
    local service="$1"
    systemctl is-active --quiet "$service" 2>/dev/null
}

# Check if a service is enabled
service_is_enabled() {
    local service="$1"
    systemctl is-enabled --quiet "$service" 2>/dev/null
}

# Backup a file with timestamp
backup_file() {
    local file="$1"
    if [[ -f "$file" ]]; then
        local backup="${file}.bak.$(date +%Y%m%d_%H%M%S)"
        cp "$file" "$backup"
        log_debug "Backed up: $file -> $backup"
        echo "$backup"
    fi
}

# Create directory with proper permissions
ensure_dir() {
    local dir="$1"
    local owner="${2:-root:root}"
    local mode="${3:-755}"

    if [[ ! -d "$dir" ]]; then
        mkdir -p "$dir"
        chown "$owner" "$dir"
        chmod "$mode" "$dir"
        log_debug "Created directory: $dir"
    fi
}

# Check if we're in dry-run mode
is_dry_run() {
    [[ "${DRY_RUN:-false}" == "true" ]]
}

# Execute or show what would be done
run_or_dry() {
    local cmd="$1"
    local description="${2:-$cmd}"

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would execute: ${cmd}${NC}"
        return 0
    fi

    eval "$cmd"
}

# =============================================================================
# ERROR HANDLING
# =============================================================================

# Error handler for trap
error_handler() {
    local exit_code=$?
    local line_no=$1

    if [[ $exit_code -ne 0 ]]; then
        log_error "Script failed at line ${line_no} with exit code ${exit_code}"
        set_led_state "ERROR_GENERAL"
    fi
}

# Cleanup handler
cleanup_handler() {
    # Reset terminal colors
    echo -e "${NC}"

    # Log completion status
    if [[ "${_MDS_COMPLETED:-false}" == "true" ]]; then
        log_info "MDS initialization completed successfully"
    else
        log_warn "MDS initialization interrupted or failed"
    fi
}

# =============================================================================
# EXPORT FOR SUBSHELLS
# =============================================================================

export MDS_VERSION MDS_STATE_DIR MDS_STATE_FILE MDS_CONFIG_DIR MDS_LOCAL_ENV MDS_NODE_IDENTITY_FILE
export MDS_INSTALL_DIR MDS_USER MDS_LOG_DIR MDS_LOG_FILE
