#!/bin/bash
#
# update_repo_ssh.sh - Enhanced Git Sync for MDS Repository (Swarm-Optimized)
#
# This script ensures that the drone's software repository (MDS) is
# up-to-date before operations start. Enhanced for production swarm deployments.
#
# Key Improvements:
# - Integrated logging with centralized system
# - Configurable recovery strategies (graceful vs aggressive)
# - Swarm-aware operations (jitter, rate limiting)
# - Better integration with service management
# - Enhanced error reporting and status notifications
# - Configurable timeouts and retry strategies
# - Lock contention handling for concurrent operations
#
# Author: Enhanced for Drone Swarm Project
# Date: 2025-07-14 (Based on original by Alireza Ghaderi)
#

set -euo pipefail

# ----------------------------------
# Configuration and Default Settings
# ----------------------------------
readonly SCRIPT_VERSION="2.0.0-swarm"
readonly SCRIPT_NAME="git-sync"

# Load configuration from environment or config file
REPO_USER="${REPO_USER:-droneshow}"
REPO_DIR="${REPO_DIR:-/home/${REPO_USER}/mavsdk_drone_show}"
CONFIG_FILE="${REPO_DIR}/config/drone_config.env"

# Default values (can be overridden by config)
MAX_RETRIES="${MAX_RETRIES:-10}"
INITIAL_DELAY="${INITIAL_DELAY:-1}"
MAX_DELAY="${MAX_DELAY:-60}"
REPAIR_TIMEOUT="${REPAIR_TIMEOUT:-120}"
FETCH_TIMEOUT="${FETCH_TIMEOUT:-300}"
NETWORK_TIMEOUT="${NETWORK_TIMEOUT:-30}"

# Branch configuration
SITL_BRANCH="${SITL_BRANCH:-docker-sitl-2}"
REAL_BRANCH="${REAL_BRANCH:-main-candidate}"
DEFAULT_BRANCH="${DEFAULT_BRANCH:-main-candidate}"

# Repository URLs
DEFAULT_SSH_GIT_URL="${DEFAULT_SSH_GIT_URL:-git@github.com:alireza787b/mavsdk_drone_show.git}"
DEFAULT_HTTPS_GIT_URL="${DEFAULT_HTTPS_GIT_URL:-https://github.com/alireza787b/mavsdk_drone_show.git}"

# Recovery strategy: "graceful" or "aggressive"
RECOVERY_STRATEGY="${RECOVERY_STRATEGY:-graceful}"

# Swarm behavior settings
ENABLE_JITTER="${ENABLE_JITTER:-true}"
MAX_JITTER_SECONDS="${MAX_JITTER_SECONDS:-30}"
SWARM_OPERATION="${SWARM_OPERATION:-true}"

# Paths and commands
LED_CMD="${REPO_DIR}/venv/bin/python ${REPO_DIR}/led_indicator.py"
LOG_FILE="${LOG_FILE:-/var/log/drone_git_sync.log}"
LOCK_FILE="/tmp/git_sync_${REPO_USER}.lock"

# ----------------------------------
# Load Configuration
# ----------------------------------
load_configuration() {
    if [[ -f "$CONFIG_FILE" ]]; then
        log_info "INIT" "Loading configuration from $CONFIG_FILE"
        # shellcheck source=/dev/null
        source "$CONFIG_FILE" || log_warn "INIT" "Failed to source config file"
        
        # Override defaults with config values
        DRONE_ID="${DRONE_ID:-$(hostname)}"
        ENVIRONMENT="${ENVIRONMENT:-production}"
        DRONE_BRANCH="${DRONE_BRANCH:-$DEFAULT_BRANCH}"
        
        # Update derived values
        if [[ "$ENVIRONMENT" == "sitl" ]]; then
            DEFAULT_BRANCH="$SITL_BRANCH"
        fi
    else
        log_warn "INIT" "Config file not found: $CONFIG_FILE"
        DRONE_ID="$(hostname)"
        ENVIRONMENT="production"
        DRONE_BRANCH="$DEFAULT_BRANCH"
    fi
}

# ----------------------------------
# Enhanced Logging System
# ----------------------------------
log() {
    local level="$1"
    local component="$2"
    local message="$3"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    local drone_id="${DRONE_ID:-unknown}"
    
    # Structured logging format
    local log_entry="[$timestamp] [$level] [$SCRIPT_NAME] [$component] [drone:$drone_id] $message"
    
    # Write to log file and console
    echo "$log_entry" | tee -a "$LOG_FILE"
    
    # Send to syslog for centralized collection
    logger -t "$SCRIPT_NAME" -p "user.$level" "$component: $message" || true
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
    set_led_status "red"
    send_status_notification "ERROR" "$component: $message"
    cleanup_on_exit
    exit "$exit_code"
}

# ----------------------------------
# Status and Notification Functions
# ----------------------------------
set_led_status() {
    local color="$1"
    if [[ "${LED_ENABLED:-true}" == "true" ]]; then
        $LED_CMD --color "$color" 2>/dev/null || log_debug "LED" "Failed to set LED to $color"
    fi
}

send_status_notification() {
    local status="$1"
    local message="$2"
    local drone_id="${DRONE_ID:-unknown}"
    
    log_info "STATUS" "Drone $drone_id: $status - $message"
    
    # Integration point for central monitoring system
    if [[ -n "${COORDINATOR_ENDPOINT:-}" ]] && command -v curl >/dev/null; then
        local payload="{\"drone_id\":\"$drone_id\",\"service\":\"git-sync\",\"status\":\"$status\",\"message\":\"$message\",\"timestamp\":\"$(date -Iseconds)\"}"
        curl -s -m 5 -X POST "${COORDINATOR_ENDPOINT}/drone-status" \
             -H "Content-Type: application/json" \
             -d "$payload" || log_debug "STATUS" "Failed to send status notification"
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
                local jitter=$((RANDOM % 5))
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
check_network_connectivity() {
    local component="NETWORK"
    log_info "$component" "Checking network connectivity..."
    
    # Add jitter for swarm operations to prevent simultaneous network tests
    if [[ "$SWARM_OPERATION" == "true" && "$ENABLE_JITTER" == "true" ]]; then
        local jitter=$((RANDOM % MAX_JITTER_SECONDS))
        log_debug "$component" "Adding ${jitter}s jitter for swarm operation"
        sleep "$jitter"
    fi
    
    # Test multiple endpoints for redundancy
    local endpoints=("github.com" "8.8.8.8" "1.1.1.1")
    local success=false
    
    for endpoint in "${endpoints[@]}"; do
        if ping -c 1 -W "$NETWORK_TIMEOUT" "$endpoint" >/dev/null 2>&1; then
            log_info "$component" "Network connectivity confirmed via $endpoint"
            success=true
            break
        fi
    done
    
    if [[ "$success" != "true" ]]; then
        log_error_and_exit "$component" "No network connectivity to any endpoint after testing: ${endpoints[*]}"
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
        for lock_file in $repo_dir/$pattern; do
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
    set_led_status "yellow"
    
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
            log_warn "$component" "Aggressive recovery: rebooting system..."
            send_status_notification "CRITICAL" "Repository corruption detected, system rebooting"
            sudo reboot || log_error_and_exit "$component" "Reboot command failed"
            exit 0
            ;;
        "graceful")
            log_error "$component" "Repository corruption could not be repaired"
            send_status_notification "DEGRADED" "Repository corruption detected, continuing with existing code"
            return 1
            ;;
        *)
            log_error_and_exit "$component" "Unknown recovery strategy: $RECOVERY_STRATEGY"
            ;;
    esac
}

# ----------------------------------
# Git Operations with Enhanced Error Handling
# ----------------------------------
perform_git_fetch() {
    local component="GIT-FETCH"
    local git_url="$1"
    
    log_info "$component" "Fetching updates from $git_url..."
    
    # Set git configuration for better network handling
    git config http.timeout "$FETCH_TIMEOUT"
    git config http.lowSpeedLimit 1000
    git config http.lowSpeedTime 30
    
    if retry_with_backoff "$MAX_RETRIES" "$component" timeout "$FETCH_TIMEOUT" git fetch --all --prune; then
        log_info "$component" "Fetch completed successfully"
        return 0
    else
        log_error "$component" "Fetch failed after retries"
        
        # Check for repository corruption
        if ! check_git_integrity; then
            log_warn "$component" "Repository corruption detected during fetch failure"
            handle_repository_corruption
            return $?
        fi
        
        return 1
    fi
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
    
    # Set values with precedence: CLI args > config > defaults
    BRANCH_NAME="${branch_name:-${DRONE_BRANCH:-$DEFAULT_BRANCH}}"
    REPO_URL="${repo_url:-$DEFAULT_SSH_GIT_URL}"
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
    RECOVERY_STRATEGY       'graceful' or 'aggressive' (default: graceful)
    ENABLE_JITTER          Add random delays for swarm operations (default: true)
    MAX_RETRIES            Maximum retry attempts (default: 10)
    DRONE_ID               Unique drone identifier
    
CONFIGURATION:
    Configuration is loaded from: $CONFIG_FILE
    
EXAMPLES:
    $0                      # Use default branch from config
    $0 --sitl               # Use SITL branch
    $0 --branch develop     # Use specific branch
    $0 --debug              # Enable debug output

EOF
}

# ----------------------------------
# URL Construction and Detection
# ----------------------------------
determine_git_url() {
    local component="GIT-URL"
    local repo_url="$1"
    local git_url=""
    
    if [[ "$repo_url" == git@* ]]; then
        # Try SSH first
        if git ls-remote "$repo_url" -q >/dev/null 2>&1; then
            log_info "$component" "SSH connection successful"
            git_url="$repo_url"
        else
            log_warn "$component" "SSH connection failed, falling back to HTTPS"
            git_url="https://github.com/${repo_url#git@github.com:}"
            git_url="${git_url%.git}.git"
        fi
    elif [[ "$repo_url" == https://* ]]; then
        # Try SSH first if available
        local ssh_url="git@github.com:${repo_url#https://github.com/}"
        ssh_url="${ssh_url%.git}.git"
        
        if git ls-remote "$ssh_url" -q >/dev/null 2>&1; then
            log_info "$component" "SSH connection available, using SSH"
            git_url="$ssh_url"
        else
            log_info "$component" "Using HTTPS connection"
            git_url="$repo_url"
        fi
    else
        log_error_and_exit "$component" "Invalid repository URL format: $repo_url"
    fi
    
    echo "$git_url"
}

# ----------------------------------
# Main Execution Function
# ----------------------------------
main() {
    local start_time=$(date +%s)
    
    # Initialize logging
    sudo mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
    sudo touch "$LOG_FILE" 2>/dev/null || true
    sudo chown "${REPO_USER}:${REPO_USER}" "$LOG_FILE" 2>/dev/null || true
    
    log_info "INIT" "=========================================="
    log_info "INIT" "Git Sync Script Starting (v$SCRIPT_VERSION)"
    log_info "INIT" "Hostname: $(hostname)"
    log_info "INIT" "User: $(whoami)"
    log_info "INIT" "PID: $$"
    log_info "INIT" "=========================================="
    
    # Load configuration and parse arguments
    load_configuration
    parse_arguments "$@"
    
    log_info "CONFIG" "Branch: $BRANCH_NAME"
    log_info "CONFIG" "Repository: $REPO_URL"
    log_info "CONFIG" "Directory: $REPO_DIR"
    log_info "CONFIG" "Recovery Strategy: $RECOVERY_STRATEGY"
    log_info "CONFIG" "Environment: $ENVIRONMENT"
    
    # Acquire exclusive lock
    acquire_lock 60
    
    # Set initial status
    set_led_status "blue"
    send_status_notification "SYNCING" "Git synchronization started"
    
    # Validate repository directory
    if [[ ! -d "$REPO_DIR" ]]; then
        log_error_and_exit "VALIDATION" "Repository directory does not exist: $REPO_DIR"
    fi
    
    if [[ ! -d "$REPO_DIR/.git" ]]; then
        log_error_and_exit "VALIDATION" "Not a git repository: $REPO_DIR"
    fi
    
    cd "$REPO_DIR" || log_error_and_exit "VALIDATION" "Failed to cd into $REPO_DIR"
    
    # Clean up any stale git locks
    cleanup_git_locks "$REPO_DIR"
    
    # Check network connectivity
    check_network_connectivity
    
    # Determine optimal git URL
    local git_url
    git_url=$(determine_git_url "$REPO_URL")
    
    # Update remote origin if necessary
    local current_remote_url
    current_remote_url=$(git remote get-url origin 2>/dev/null || echo "")
    if [[ "$current_remote_url" != "$git_url" ]]; then
        log_info "GIT-REMOTE" "Updating remote URL from '$current_remote_url' to '$git_url'"
        git remote set-url origin "$git_url" || log_error_and_exit "GIT-REMOTE" "Failed to set remote URL"
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
            send_status_notification "DEGRADED" "Git fetch failed, using existing code"
            set_led_status "yellow"
            exit 0
        else
            log_error_and_exit "GIT-FETCH" "Git fetch failed and recovery strategy is aggressive"
        fi
    fi
    
    # Clean up any locks that might have been created during fetch
    cleanup_git_locks "$REPO_DIR"
    
    # Switch to target branch
    local current_branch
    current_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
    if [[ "$current_branch" != "$BRANCH_NAME" ]]; then
        log_info "GIT-BRANCH" "Switching from '$current_branch' to '$BRANCH_NAME'"
        if ! git checkout "$BRANCH_NAME"; then
            log_error_and_exit "GIT-BRANCH" "Failed to checkout branch '$BRANCH_NAME'"
        fi
    fi
    
    # Reset to match origin
    log_info "GIT-RESET" "Resetting $BRANCH_NAME to origin/$BRANCH_NAME"
    if ! retry_with_backoff "$MAX_RETRIES" "GIT-RESET" git reset --hard "origin/$BRANCH_NAME"; then
        log_error_and_exit "GIT-RESET" "Failed to reset branch $BRANCH_NAME"
    fi
    
    # Final pull to ensure we're up to date
    log_info "GIT-PULL" "Performing final pull on $BRANCH_NAME"
    if ! retry_with_backoff "$MAX_RETRIES" "GIT-PULL" git pull; then
        log_error_and_exit "GIT-PULL" "Failed to pull latest changes"
    fi
    
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
    
    set_led_status "green"
    send_status_notification "SYNCED" "Git sync completed: $commit_hash on $BRANCH_NAME"
    
    exit 0
}

# Execute main function if script is run directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi