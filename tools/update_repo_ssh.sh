#!/bin/bash
#
# update_repo_ssh.sh - SSH-based Git Sync for MDS Drone Fleet
#
# This script ensures that the drone's software repository (MDS) is
# up-to-date before operations start. Enhanced for production swarm deployments.
#
# Author: MAVSDK Drone Show Team
# Date: 2025-07-14
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MDS_REPO_ROOT="${MDS_REPO_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
DEPLOYMENT_PROFILE_LOADER="${MDS_REPO_ROOT}/tools/load_deployment_profile.sh"
if [[ -f "${DEPLOYMENT_PROFILE_LOADER}" ]]; then
    # shellcheck disable=SC1090
    source "${DEPLOYMENT_PROFILE_LOADER}"
fi

# ----------------------------------
# Configuration and Default Settings (Built-in Defaults)
# ----------------------------------
readonly SCRIPT_VERSION="2.2.0"
readonly SCRIPT_NAME="git-sync"

# Use dynamic variables for user and home directory
RESOLVED_USER="${USER:-$(whoami 2>/dev/null || echo root)}"
RESOLVED_HOME="${HOME:-/root}"
REPO_USER="${REPO_USER:-$RESOLVED_USER}"
REPO_DIR="${REPO_DIR:-$RESOLVED_HOME/mavsdk_drone_show}"

# Default values - can be overridden by environment variables
MAX_RETRIES="${MAX_RETRIES:-10}"
INITIAL_DELAY="${INITIAL_DELAY:-1}"
MAX_DELAY="${MAX_DELAY:-60}"
REPAIR_TIMEOUT="${REPAIR_TIMEOUT:-120}"
FETCH_TIMEOUT="${FETCH_TIMEOUT:-300}"
NETWORK_TIMEOUT="${NETWORK_TIMEOUT:-30}"


# Branch configuration
SITL_BRANCH="${SITL_BRANCH:-docker-sitl-2}"
REAL_BRANCH="${REAL_BRANCH:-${MDS_DEFAULT_BRANCH:-main-candidate}}"
DEFAULT_BRANCH="${DEFAULT_BRANCH:-${MDS_DEFAULT_BRANCH:-main-candidate}}"

# Repository URLs
DEFAULT_SSH_GIT_URL="${DEFAULT_SSH_GIT_URL:-${MDS_DEFAULT_REPO_URL_SSH:-git@github.com:alireza787b/mavsdk_drone_show.git}}"
DEFAULT_HTTPS_GIT_URL="${DEFAULT_HTTPS_GIT_URL:-${MDS_DEFAULT_REPO_URL_HTTPS:-https://github.com/alireza787b/mavsdk_drone_show.git}}"
GIT_AUTH_TOKEN_FILE="${MDS_GIT_AUTH_TOKEN_FILE:-}"
GIT_AUTH_USERNAME="${MDS_GIT_AUTH_USERNAME:-x-access-token}"

# Recovery strategy: "graceful" or "aggressive"
RECOVERY_STRATEGY="${RECOVERY_STRATEGY:-graceful}"

# Swarm behavior settings
ENABLE_JITTER="${ENABLE_JITTER:-true}"
MAX_JITTER_SECONDS="${MAX_JITTER_SECONDS:-30}"
SWARM_OPERATION="${SWARM_OPERATION:-true}"

# Drone identification
DRONE_ID="${DRONE_ID:-$(hostname)}"
ENVIRONMENT="${ENVIRONMENT:-production}"

# Paths and commands
LED_CMD="${REPO_DIR}/venv/bin/python ${REPO_DIR}/led_indicator.py"
LOG_FILE="$RESOLVED_HOME/logs/drone_git_sync.log"
LOCK_FILE="/tmp/git_sync_${REPO_USER}.lock"
LOCAL_ENV_FILE="${MDS_LOCAL_ENV_FILE:-/etc/mds/local.env}"
USER_ENV_FILE="${MDS_USER_ENV_FILE:-$RESOLVED_HOME/.config/mds/env}"

# ----------------------------------
# Enhanced Logging System (FIXED - No variable corruption)
# ----------------------------------
log() {
    local level="$1"
    local component="$2"
    local message="$3"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    # Structured logging format - write to stderr to avoid variable corruption
    local log_entry="[$timestamp] [$level] [$SCRIPT_NAME] [$component] [drone:$DRONE_ID] $message"
    
    # Write to log file if possible, suppress errors to avoid corruption
    echo "$log_entry" >> "$LOG_FILE" 2>/dev/null || true
    
    # Write to stderr (not stdout) to avoid variable corruption
    echo "$log_entry" >&2
    
    # Send to syslog for centralized collection, suppress errors
    logger -t "$SCRIPT_NAME" -p "user.$level" "$component: $message" 2>/dev/null || true
}

log_info() { log "info" "$@"; }
log_warn() { log "warn" "$@"; }
log_error() { log "error" "$@"; }
log_debug() { [[ "${DEBUG:-0}" == "1" ]] && log "debug" "$@" || true; }

log_error_and_exit() {
    local component="$1"
    local message="$2"
    local exit_code="${3:-1}"

    log_error "$component" "$message"
    set_led_status "ERROR_CRITICAL"
    # Emit structured failure result for machine parsing (used by actions.py)
    local error_json
    error_json=$(echo "$message" | sed 's/\\/\\\\/g; s/"/\\"/g' | tr -d '\n\r')
    echo "GIT_SYNC_RESULT={\"success\":false,\"branch\":\"${BRANCH_NAME:-unknown}\",\"error\":\"$component\",\"message\":\"$error_json\"}"
    cleanup_on_exit
    exit "$exit_code"
}

# ----------------------------------
# Runtime Environment Loading
# ----------------------------------
load_runtime_env_files() {
    local env_file=""
    local loaded_files=()

    for env_file in "$LOCAL_ENV_FILE" "$USER_ENV_FILE"; do
        if [[ -f "$env_file" ]]; then
            log_debug "ENV" "Loading environment overrides from $env_file"
            set -a
            # shellcheck source=/dev/null
            source "$env_file"
            set +a
            loaded_files+=("$env_file")
        fi
    done

    if [[ ${#loaded_files[@]} -gt 0 ]]; then
        log_info "ENV" "Loaded environment overrides from ${loaded_files[*]}"
    else
        log_debug "ENV" "No runtime environment override files found"
    fi
}

# ----------------------------------
# Status and Notification Functions
# ----------------------------------
set_led_status() {
    local color_or_state="$1"
    if [[ "${LED_ENABLED:-true}" == "true" ]]; then
        # Try --state first (for semantic states), fallback to --color
        $LED_CMD --state "$color_or_state" 2>/dev/null || \
        $LED_CMD --color "$color_or_state" 2>/dev/null || true
    fi
}

# ----------------------------------
# Service Update Detection (runs after git pull)
# ----------------------------------
check_service_updates() {
    local component="SERVICE-UPDATE"
    local changed=false
    local services=("coordinator" "git_sync_mds" "led_indicator")
    local mds_user="${MDS_USER:-$(id -un)}"
    local mds_home="${MDS_HOME:-${HOME}}"
    local mds_install_dir="${MDS_INSTALL_DIR:-${REPO_DIR}}"

    log_info "$component" "Checking for service file changes..."

    for service in "${services[@]}"; do
        local src_file repo_file
        case $service in
            coordinator)
                src_file="/etc/systemd/system/coordinator.service"
                repo_file="$REPO_DIR/tools/coordinator.service"
                ;;
            git_sync_mds)
                src_file="/etc/systemd/system/git_sync_mds.service"
                repo_file="$REPO_DIR/tools/git_sync_mds/git_sync_mds.service"
                ;;
            led_indicator)
                src_file="/etc/systemd/system/led_indicator.service"
                repo_file="$REPO_DIR/tools/led_indicator/led_indicator.service"
                ;;
        esac

        # Atomic service file update (avoids TOCTOU race condition)
        if [[ -f "$repo_file" ]]; then
            local temp_file
            temp_file=$(mktemp) || continue
            sed \
                -e "s|__MDS_USER__|${mds_user}|g" \
                -e "s|__MDS_HOME__|${mds_home}|g" \
                -e "s|__MDS_INSTALL_DIR__|${mds_install_dir}|g" \
                "$repo_file" > "$temp_file" 2>/dev/null || { rm -f "$temp_file"; continue; }

            if ! cmp -s "$src_file" "$temp_file" 2>/dev/null; then
                log_info "$component" "Service file changed: $service"
                if sudo mv "$temp_file" "$src_file" 2>/dev/null; then
                    log_info "$component" "Updated $service service file"
                    changed=true
                else
                    log_warn "$component" "Failed to update $service service file (sudo may not be available)"
                    rm -f "$temp_file"
                fi
            else
                rm -f "$temp_file"
            fi
        fi
    done

    if $changed; then
        log_info "$component" "Reloading systemd daemon..."
        sudo systemctl daemon-reload 2>/dev/null || log_warn "$component" "Failed to reload systemd daemon"
    fi
}

check_connectivity_updates() {
    local component="CONNECTIVITY"
    local backend="${MDS_CONNECTIVITY_BACKEND:-none}"
    local reconcile_script="${REPO_DIR}/tools/reconcile_connectivity.sh"

    case "$backend" in
        smart-wifi-manager|smart_wifi_manager|smartwifi|wifi)
            ;;
        *)
            log_debug "$component" "Connectivity backend is '${backend}', nothing to reconcile"
            return 0
            ;;
    esac

    if [[ ! -x "${reconcile_script}" ]]; then
        log_warn "$component" "Connectivity reconcile helper is missing: ${reconcile_script}"
        return 0
    fi

    log_info "$component" "Reapplying connectivity backend configuration..."
    if sudo "${reconcile_script}" apply --quiet; then
        log_info "$component" "Connectivity backend reconciled"
    else
        log_warn "$component" "Connectivity reconcile did not complete cleanly"
    fi
}

# ----------------------------------
# Requirements Update Check (runs after git pull)
# ----------------------------------
check_requirements_update() {
    local component="PIP-UPDATE"
    local mds_dir="${HOME}/.mds"
    local req_hash_file="${mds_dir}/requirements.sha256"

    # Ensure .mds directory exists
    mkdir -p "$mds_dir" 2>/dev/null || true

    if [[ ! -f "$REPO_DIR/requirements.txt" ]]; then
        log_debug "$component" "No requirements.txt found, skipping"
        return 0
    fi

    local current_hash
    current_hash=$(sha256sum "$REPO_DIR/requirements.txt" 2>/dev/null | cut -d' ' -f1)

    if [[ -f "$req_hash_file" ]]; then
        local stored_hash
        stored_hash=$(cat "$req_hash_file" 2>/dev/null)

        if [[ "$current_hash" != "$stored_hash" ]]; then
            log_info "$component" "requirements.txt changed, updating venv..."
            set_led_status "SERVICES_UPDATING"

            if [[ -x "$REPO_DIR/venv/bin/pip" ]]; then
                if "$REPO_DIR/venv/bin/pip" install -r "$REPO_DIR/requirements.txt" --quiet 2>/dev/null; then
                    log_info "$component" "Python requirements updated successfully"
                    echo "$current_hash" > "$req_hash_file"
                else
                    log_warn "$component" "Failed to update Python requirements"
                fi
            else
                log_warn "$component" "venv pip not found at $REPO_DIR/venv/bin/pip"
            fi
        else
            log_debug "$component" "requirements.txt unchanged"
        fi
    else
        # First run - store current hash
        log_info "$component" "Storing initial requirements hash"
        echo "$current_hash" > "$req_hash_file"
    fi
}

# ----------------------------------
# Lock Management for Concurrent Operations
# ----------------------------------
acquire_lock() {
    local timeout="${1:-60}"
    local count=0
    
    while ! (set -C; echo $$ > "$LOCK_FILE") 2>/dev/null; do
        if [[ -f "$LOCK_FILE" ]]; then
            local lock_pid=$(cat "$LOCK_FILE" 2>/dev/null || echo "unknown")
            if ! kill -0 "$lock_pid" 2>/dev/null; then
                log_warn "LOCK" "Removing stale lock file (PID $lock_pid no longer exists)"
                rm -f "$LOCK_FILE"
                continue
            fi
        fi
        
        count=$((count + 1))
        if [[ $count -ge $timeout ]]; then
            log_error_and_exit "LOCK" "Failed to acquire lock after ${timeout}s"
        fi
        
        log_info "LOCK" "Waiting for lock... (attempt $count/$timeout)"
        sleep 1
    done
    
    log_debug "LOCK" "Lock acquired (PID $$)"
}

release_lock() {
    if [[ -f "$LOCK_FILE" ]]; then
        rm -f "$LOCK_FILE"
        log_debug "LOCK" "Lock released"
    fi
}

git_https_auth_enabled() {
    [[ -n "${MDS_GIT_AUTH_TOKEN_FILE:-}" && -r "${MDS_GIT_AUTH_TOKEN_FILE}" ]] || [[ -n "${MDS_GIT_AUTH_TOKEN:-}" ]]
}

git_runtime_home() {
    printf '%s\n' "${HOME:-/root}"
}

git_askpass_path() {
    local runtime_home
    runtime_home="$(git_runtime_home)"
    printf '%s\n' "${runtime_home}/.cache/mds-runtime/mds_git_sync_askpass.sh"
}

prepare_git_askpass() {
    local askpass_path
    local askpass_dir
    askpass_path="$(git_askpass_path)"
    askpass_dir="$(dirname "$askpass_path")"

    if [[ -x "$askpass_path" ]]; then
        return 0
    fi

    mkdir -p "$askpass_dir"
    chmod 700 "$(dirname "$askpass_dir")" "$askpass_dir" 2>/dev/null || true

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

run_git_command() {
    local repo_url="${1:-}"
    shift

    if [[ "$repo_url" == https://* ]] && git_https_auth_enabled; then
        prepare_git_askpass
        env \
            GIT_TERMINAL_PROMPT=0 \
            GIT_ASKPASS_REQUIRE=force \
            GIT_ASKPASS="$(git_askpass_path)" \
            MDS_GIT_AUTH_USERNAME="${MDS_GIT_AUTH_USERNAME:-$GIT_AUTH_USERNAME}" \
            MDS_GIT_AUTH_TOKEN_FILE="${MDS_GIT_AUTH_TOKEN_FILE:-}" \
            MDS_GIT_AUTH_TOKEN="${MDS_GIT_AUTH_TOKEN:-}" \
            git -c credential.username="${MDS_GIT_AUTH_USERNAME:-$GIT_AUTH_USERNAME}" "$@"
    else
        git "$@"
    fi
}

# ----------------------------------
# Cleanup and Signal Handling
# ----------------------------------
cleanup_on_exit() {
    local exit_code=$?
    release_lock
    
    if [[ $exit_code -ne 0 ]]; then
        log_error "CLEANUP" "Script exiting with code $exit_code"
    fi
    
    return $exit_code
}

# Set up signal handlers
trap cleanup_on_exit EXIT
trap 'log_warn "SIGNAL" "Received interrupt signal"; exit 130' INT TERM

# ----------------------------------
# Enhanced Retry Function with Exponential Backoff
# ----------------------------------
retry_with_backoff() {
    local retries="$1"
    local component="$2"
    shift 2
    local count=0
    local delay="$INITIAL_DELAY"
    
    until "$@"; do
        local exit_code=$?
        count=$((count + 1))
        
        if [[ $count -lt $retries ]]; then
            log_warn "$component" "Command failed with exit code $exit_code (attempt $count/$retries). Retrying in ${delay}s..."
            sleep "$delay"
            
            # Exponential backoff with jitter
            delay=$((delay * 2))
            if [[ $delay -gt $MAX_DELAY ]]; then
                delay=$MAX_DELAY
            fi
            
            # Add jitter to prevent thundering herd in swarm operations
            if [[ "$ENABLE_JITTER" == "true" ]]; then
                # Use /dev/urandom for better randomness across 1000s of drones
                local jitter=$(( $(od -An -N2 -tu2 /dev/urandom 2>/dev/null || echo $RANDOM) % MAX_JITTER_SECONDS ))
                delay=$((delay + jitter))
            fi
        else
            log_error "$component" "Command failed after $count attempts"
            return $exit_code
        fi
    done
    
    if [[ $count -gt 1 ]]; then
        log_info "$component" "Command succeeded after $count attempts"
    fi
    return 0
}

# ----------------------------------
# Network Connectivity Check with Swarm Awareness
# ----------------------------------
probe_network_endpoint() {
    local endpoint="$1"
    local port="${2:-443}"

    if command -v ping >/dev/null 2>&1; then
        if ping -c 1 -W "$NETWORK_TIMEOUT" "$endpoint" >/dev/null 2>&1; then
            return 0
        fi
    fi

    if command -v timeout >/dev/null 2>&1 && command -v bash >/dev/null 2>&1; then
        if timeout "$NETWORK_TIMEOUT" bash -lc "</dev/tcp/${endpoint}/${port}" >/dev/null 2>&1; then
            return 0
        fi
    fi

    return 1
}

check_network_connectivity() {
    local component="NETWORK"
    log_info "$component" "Checking network connectivity..."
    
    # Add jitter for swarm operations to prevent simultaneous network tests
    if [[ "$SWARM_OPERATION" == "true" && "$ENABLE_JITTER" == "true" ]]; then
        # Use /dev/urandom for better randomness across 1000s of drones
        local jitter=$(( $(od -An -N2 -tu2 /dev/urandom 2>/dev/null || echo $RANDOM) % MAX_JITTER_SECONDS ))
        log_debug "$component" "Adding ${jitter}s jitter for swarm operation"
        sleep "$jitter"
    fi
    
    # Test multiple endpoints for redundancy. This is advisory only; the
    # subsequent git fetch is the authoritative connectivity test.
    local endpoints=("github.com:443" "github.com:22" "8.8.8.8:443" "1.1.1.1:443")
    local success=false
    
    for endpoint_spec in "${endpoints[@]}"; do
        local endpoint="${endpoint_spec%%:*}"
        local port="${endpoint_spec##*:}"
        if probe_network_endpoint "$endpoint" "$port"; then
            log_info "$component" "Network connectivity confirmed via ${endpoint}:${port}"
            success=true
            break
        fi
    done
    
    if [[ "$success" != "true" ]]; then
        log_warn "$component" "Connectivity probe failed (${endpoints[*]}). Proceeding to git fetch for definitive verification."
    fi
}

# ----------------------------------
# Git Repository Operations
# ----------------------------------
cleanup_git_locks() {
    local component="GIT-LOCK"
    local repo_dir="$1"
    local lock_files=(".git/index.lock" ".git/refs/heads/*.lock" ".git/packed-refs.lock")
    
    for pattern in "${lock_files[@]}"; do
        # Note: glob expansion needs unquoted pattern but quoted base path
        for lock_file in "$repo_dir"/$pattern; do
            if [[ -f "$lock_file" ]]; then
                # Check if any git processes are running
                if pgrep -f "git" >/dev/null 2>&1; then
                    log_warn "$component" "Git process detected, waiting 5s before removing lock: $lock_file"
                    sleep 5
                fi
                
                if [[ -f "$lock_file" ]]; then
                    log_info "$component" "Removing stale git lock: $lock_file"
                    rm -f "$lock_file"
                fi
            fi
        done
    done
}

check_git_integrity() {
    local component="GIT-INTEGRITY"
    log_info "$component" "Performing repository integrity check..."
    
    local fsck_output
    if ! fsck_output=$(timeout 60 git fsck --full 2>&1); then
        log_error "$component" "Git fsck command failed or timed out"
        return 1
    fi
    
    # Filter out benign warnings
    local filtered_output
    filtered_output=$(echo "$fsck_output" | grep -v -E "(dangling commit|dangling blob|dangling tree)" || true)
    
    if [[ -n "$filtered_output" ]]; then
        log_warn "$component" "Repository integrity issues detected:"
        echo "$filtered_output" | while read -r line; do
            log_warn "$component" "  $line"
        done
        return 1
    fi
    
    log_info "$component" "Repository integrity check passed"
    return 0
}

repair_git_repository() {
    local component="GIT-REPAIR"
    log_warn "$component" "Attempting repository repair..."
    set_led_status "ERROR_RECOVERABLE"
    
    # First, try to fix common issues
    if git stash clear 2>/dev/null; then
        log_info "$component" "Cleared git stash"
    fi
    
    if [[ -f ".git/logs/refs/stash" ]]; then
        rm -f ".git/logs/refs/stash"
        log_info "$component" "Removed corrupted stash reflog"
    fi
    
    # Run git-repair if available
    if command -v git-repair >/dev/null; then
        log_info "$component" "Running git-repair (timeout: ${REPAIR_TIMEOUT}s)..."
        if timeout "$REPAIR_TIMEOUT" git-repair >> "$LOG_FILE" 2>&1; then
            log_info "$component" "Git repair completed successfully"
            
            # Clean up repair artifacts
            [[ -f ".git/gc.log" ]] && rm -f ".git/gc.log"
            
            return 0
        else
            log_error "$component" "Git repair failed or timed out"
        fi
    else
        log_warn "$component" "git-repair not available, trying alternative repair..."
        
        # Alternative repair approach
        if git reflog expire --expire=now --all && git gc --prune=now; then
            log_info "$component" "Alternative repair completed"
            return 0
        fi
    fi
    
    return 1
}

handle_repository_corruption() {
    local component="GIT-CORRUPTION"
    
    if repair_git_repository; then
        log_info "$component" "Repository repair successful"
        return 0
    fi
    
    # Apply recovery strategy
    case "$RECOVERY_STRATEGY" in
        "aggressive")
            # WARNING: Aggressive strategy removed for fleet safety
            # Rebooting 1000s of drones due to git issues could be catastrophic
            # Instead, we log the error and continue with cached code
            log_error "$component" "Repository corruption could not be repaired"
            log_warn "$component" "Aggressive reboot disabled for fleet safety - continuing with cached code"
            log_warn "$component" "Manual intervention may be required on this drone"
            set_led_status "ERROR_RECOVERABLE"
            return 1
            ;;
        "graceful")
            log_error "$component" "Repository corruption could not be repaired"
            log_warn "$component" "Continuing with cached code - manual intervention may be required"
            return 1
            ;;
        *)
            log_error_and_exit "$component" "Unknown recovery strategy: $RECOVERY_STRATEGY"
            ;;
    esac
}

# ----------------------------------
# FIXED: Git URL Determination (No variable corruption)
# ----------------------------------
determine_git_url() {
    local repo_url="$1"
    local git_url=""
    
    # FIXED: Capture output properly without mixing with logs
    if [[ "$repo_url" == git@* ]]; then
        # Try SSH first - capture result in variable without logging interference
        if run_git_command "$repo_url" ls-remote "$repo_url" -q >/dev/null 2>&1; then
            log_info "GIT-URL" "SSH connection successful"
            git_url="$repo_url"
        else
            log_warn "GIT-URL" "SSH connection failed, falling back to HTTPS"
            git_url="https://github.com/${repo_url#git@github.com:}"
            git_url="${git_url%.git}.git"
        fi
    elif [[ "$repo_url" == https://* ]]; then
        if git_https_auth_enabled; then
            log_info "GIT-URL" "Using authenticated HTTPS connection"
            git_url="$repo_url"
        else
            log_info "GIT-URL" "Using HTTPS connection"
            git_url="$repo_url"
        fi
    else
        log_error_and_exit "GIT-URL" "Invalid repository URL format: $repo_url"
    fi
    
    # FIXED: Return the URL cleanly without any logging interference
    echo "$git_url"
}

# ----------------------------------
# Git Operations with Enhanced Error Handling
# ----------------------------------
perform_git_fetch() {
    local component="GIT-FETCH"
    local git_url="$1"
    
    log_info "$component" "Fetching updates from $git_url..."
    
    # Set git configuration for better network handling
    run_git_command "$git_url" config http.timeout "$FETCH_TIMEOUT"
    run_git_command "$git_url" config http.lowSpeedLimit 1000
    run_git_command "$git_url" config http.lowSpeedTime 30
    
    if [[ "$git_url" == https://* ]] && git_https_auth_enabled; then
        prepare_git_askpass
        if retry_with_backoff \
            "$MAX_RETRIES" \
            "$component" \
            env \
                GIT_TERMINAL_PROMPT=0 \
                GIT_ASKPASS_REQUIRE=force \
                GIT_ASKPASS="$(git_askpass_path)" \
                MDS_GIT_AUTH_USERNAME="${MDS_GIT_AUTH_USERNAME:-$GIT_AUTH_USERNAME}" \
                MDS_GIT_AUTH_TOKEN_FILE="${MDS_GIT_AUTH_TOKEN_FILE:-}" \
                MDS_GIT_AUTH_TOKEN="${MDS_GIT_AUTH_TOKEN:-}" \
                timeout "$FETCH_TIMEOUT" \
                git -c credential.username="${MDS_GIT_AUTH_USERNAME:-$GIT_AUTH_USERNAME}" fetch --all --prune; then
            log_info "$component" "Fetch completed successfully"
            return 0
        fi
    elif retry_with_backoff "$MAX_RETRIES" "$component" timeout "$FETCH_TIMEOUT" git fetch --all --prune; then
        log_info "$component" "Fetch completed successfully"
        return 0
    fi

    log_error "$component" "Fetch failed after retries"

    # Check for repository corruption
    if ! check_git_integrity; then
        log_warn "$component" "Repository corruption detected during fetch failure"
        handle_repository_corruption
        return $?
    fi

    return 1
}

# ----------------------------------
# Argument Parsing
# ----------------------------------
parse_arguments() {
    local branch_name=""
    local repo_url=""
    local repo_dir=""
    
    local parsed_options
    if ! parsed_options=$(getopt -n "$0" -o b:hvd --long branch:,sitl,real,repo-url:,repo-dir:,help,version,debug -- "$@"); then
        echo "Error parsing options." >&2
        exit 1
    fi
    
    eval set -- "$parsed_options"
    while true; do
        case "$1" in
            -b|--branch)
                branch_name="$2"
                shift 2
                ;;
            --sitl)
                branch_name="$SITL_BRANCH"
                shift
                ;;
            --real)
                branch_name="$REAL_BRANCH"
                shift
                ;;
            --repo-url)
                repo_url="$2"
                shift 2
                ;;
            --repo-dir)
                repo_dir="$2"
                shift 2
                ;;
            -d|--debug)
                DEBUG=1
                shift
                ;;
            -v|--version)
                echo "Git Sync Script version $SCRIPT_VERSION"
                exit 0
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
    
    # Set values with precedence: CLI args > modern env vars > legacy env vars > defaults
    BRANCH_NAME="${branch_name:-${MDS_BRANCH:-${DRONE_BRANCH:-$DEFAULT_BRANCH}}}"
    REPO_URL="${repo_url:-${MDS_REPO_URL:-$DEFAULT_SSH_GIT_URL}}"
    REPO_DIR="${repo_dir:-$REPO_DIR}"
    
    export BRANCH_NAME REPO_URL REPO_DIR
}

show_help() {
    cat << EOF
Git Sync Script for Drone Swarm - Version $SCRIPT_VERSION

Usage: $0 [OPTIONS]

OPTIONS:
    -b, --branch BRANCH     Use specific branch
    --sitl                  Use SITL branch ($SITL_BRANCH)
    --real                  Use production branch ($REAL_BRANCH)
    --repo-url URL          Override repository URL
    --repo-dir DIR          Override repository directory
    -d, --debug             Enable debug logging
    -v, --version           Show version information
    -h, --help              Show this help message

ENVIRONMENT VARIABLES:
    MDS_REPO_URL           Repository URL override (preferred single source of truth)
    MDS_BRANCH             Branch override (preferred single source of truth)
    MDS_LOCAL_ENV_FILE     Alternate /etc/mds/local.env path for testing
    MDS_USER_ENV_FILE      Alternate user env path for testing
    DRONE_BRANCH           Legacy branch override (fallback)
    DEFAULT_SSH_GIT_URL    Legacy repository URL fallback
    RECOVERY_STRATEGY       'graceful' or 'aggressive' (default: graceful)
    ENABLE_JITTER          Add random delays for swarm operations (default: true)
    MAX_RETRIES            Maximum retry attempts (default: 10)
    DRONE_ID               Unique drone identifier (default: hostname)
    
EXAMPLES:
    $0                      # Use default branch
    $0 --sitl               # Use SITL branch
    $0 --branch develop     # Use specific branch
    $0 --debug              # Enable debug output

EOF
}

# ----------------------------------
# Main Execution Function
# ----------------------------------
main() {
    local start_time=$(date +%s)
    
    # Initialize logging
    mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
    touch "$LOG_FILE" 2>/dev/null || true
    
    log_info "INIT" "=========================================="
    log_info "INIT" "Git Sync Script Starting (v$SCRIPT_VERSION)"
    log_info "INIT" "Hostname: $(hostname)"
    log_info "INIT" "User: $(whoami)"
    log_info "INIT" "PID: $$"
    log_info "INIT" "=========================================="

    load_runtime_env_files
    
    # Parse arguments
    parse_arguments "$@"
    
    log_info "CONFIG" "Branch: $BRANCH_NAME"
    log_info "CONFIG" "Repository: $REPO_URL"
    log_info "CONFIG" "Directory: $REPO_DIR"
    log_info "CONFIG" "Recovery Strategy: $RECOVERY_STRATEGY"
    log_info "CONFIG" "Environment: $ENVIRONMENT"
    
    # Acquire exclusive lock
    acquire_lock 60
    
    # Set initial status - GIT_SYNCING (cyan)
    set_led_status "GIT_SYNCING"
    
    # Validate repository directory
    if [[ ! -d "$REPO_DIR" ]]; then
        log_error_and_exit "VALIDATION" "Repository directory does not exist: $REPO_DIR"
    fi
    
    if ! git -C "$REPO_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        log_error_and_exit "VALIDATION" "Not a git repository: $REPO_DIR"
    fi
    
    cd "$REPO_DIR" || log_error_and_exit "VALIDATION" "Failed to cd into $REPO_DIR"
    
    # Clean up any stale git locks
    cleanup_git_locks "$REPO_DIR"
    
    # Check network connectivity
    check_network_connectivity
    
    # FIXED: Determine optimal git URL without variable corruption
    local git_url
    git_url=$(determine_git_url "$REPO_URL")
    
    # Update remote origin if necessary
    local current_remote_url
    current_remote_url=$(git remote get-url origin 2>/dev/null || echo "")
    if [[ "$current_remote_url" != "$git_url" ]]; then
        log_info "GIT-REMOTE" "Updating remote URL from '$current_remote_url' to '$git_url'"
        run_git_command "$git_url" remote set-url origin "$git_url" || log_error_and_exit "GIT-REMOTE" "Failed to set remote URL"
    fi
    
    # Stash local changes
    if git status --porcelain | grep -q .; then
        log_info "GIT-STASH" "Stashing local changes..."
        git stash push --include-untracked -m "Auto-stash before sync at $(date)" || \
            log_error_and_exit "GIT-STASH" "Failed to stash local changes"
    fi
    
    # Perform git fetch with retry logic
    if ! perform_git_fetch "$git_url"; then
        if [[ "$RECOVERY_STRATEGY" == "graceful" ]]; then
            log_warn "GIT-FETCH" "Fetch failed, continuing with existing repository state"
            set_led_status "GIT_FAILED_CONTINUING"  # Yellow - indicates cached code being used
            echo "GIT_SYNC_RESULT={\"success\":false,\"branch\":\"$BRANCH_NAME\",\"error\":\"fetch_failed_graceful\",\"message\":\"Fetch failed, using cached code\"}"
            exit 0
        else
            log_error_and_exit "GIT-FETCH" "Git fetch failed and recovery strategy is aggressive"
        fi
    fi
    
    # Clean up any locks that might have been created during fetch
    cleanup_git_locks "$REPO_DIR"
    
    # Switch to target branch
    local current_branch
    local detached_target=false
    current_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
    if [[ "$current_branch" != "$BRANCH_NAME" ]]; then
        log_info "GIT-BRANCH" "Switching from '$current_branch' to '$BRANCH_NAME'"
        if ! git checkout "$BRANCH_NAME"; then
            log_warn "GIT-BRANCH" "Local branch checkout failed; attempting detached origin/$BRANCH_NAME checkout (worktree-safe)"
            if git checkout --detach "origin/$BRANCH_NAME"; then
                detached_target=true
            else
                log_error_and_exit "GIT-BRANCH" "Failed to checkout branch '$BRANCH_NAME'"
            fi
        fi
    fi
    
    # Reset to match origin
    log_info "GIT-RESET" "Resetting $BRANCH_NAME to origin/$BRANCH_NAME"
    if ! retry_with_backoff "$MAX_RETRIES" "GIT-RESET" git reset --hard "origin/$BRANCH_NAME"; then
        log_error_and_exit "GIT-RESET" "Failed to reset branch $BRANCH_NAME"
    fi
    
    # No final `git pull` is needed here.
    # The runtime already fetched origin/$BRANCH_NAME and hard-reset to that exact tip.
    # Skipping pull avoids false failures on custom branches without a configured upstream.
    log_info "GIT-PULL" "Skipping final git pull; fetch + reset already pinned runtime to origin/$BRANCH_NAME"

    # Post-sync checks: service files and requirements
    set_led_status "GIT_SUCCESS"
    check_service_updates
    check_connectivity_updates
    check_requirements_update

    # Get commit information for logging
    local commit_hash
    local commit_message
    commit_hash=$(git rev-parse --short HEAD)
    commit_message=$(git log -1 --pretty=format:"%s" 2>/dev/null || echo "unknown")
    
    # Calculate execution time
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    
    # Final cleanup
    cleanup_git_locks "$REPO_DIR"
    
    log_info "SUCCESS" "=========================================="
    log_info "SUCCESS" "Git synchronization completed successfully"
    log_info "SUCCESS" "Repository: $git_url"
    log_info "SUCCESS" "Branch: $BRANCH_NAME"
    log_info "SUCCESS" "Commit: $commit_hash - $commit_message"
    log_info "SUCCESS" "Duration: ${duration}s"
    log_info "SUCCESS" "=========================================="

    # Structured result for machine parsing (used by actions.py)
    # Escape quotes/backslashes in commit message for valid JSON
    local commit_message_json
    commit_message_json=$(echo "$commit_message" | sed 's/\\/\\\\/g; s/"/\\"/g' | tr -d '\n\r')
    echo "GIT_SYNC_RESULT={\"success\":true,\"branch\":\"$BRANCH_NAME\",\"commit\":\"$commit_hash\",\"message\":\"$commit_message_json\",\"duration\":$duration}"

    # Final LED state: Startup complete (white flash), then coordinator will take over
    set_led_status "STARTUP_COMPLETE"

    exit 0
}

# Execute main function if script is run directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
