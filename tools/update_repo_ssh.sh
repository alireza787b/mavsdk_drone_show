#!/bin/bash
#
# update_repo_ssh.sh - Git Sync for MDS Repository
#
# This script ensures that the drone's software repository (MDS) is
# up-to-date before operations start. It checks network connectivity,
# cleans up any stale Git locks, stashes local changes, and performs
# a Git fetch, reset, and pull on the desired branch.
#
# LED indicators (via led_indicator.py) are used for visual status:
#   - Blue: Git sync in progress.
#   - Yellow: Git sync failed after retries.
#
# Usage:
#   ./update_repo_ssh.sh [--branch <branch>] [--sitl] [--real] [--repo-url <url>] [--repo-dir <dir>]
#
# Author: Alireza Ghaderi
# Date: 2025-03-02

set -euo pipefail

# ----------------------------------
# Configuration and Default Settings
# ----------------------------------
MAX_RETRIES=10
INITIAL_DELAY=1  # Fixed delay (in seconds) between retries
SITL_BRANCH="docker-sitl-2"
REAL_BRANCH="main-candidate"

DEFAULT_REPO_DIR="${HOME}/mavsdk_drone_show"
DEFAULT_SSH_GIT_URL="git@github.com:alireza787b/mavsdk_drone_show.git"
DEFAULT_HTTPS_GIT_URL="https://github.com/alireza787b/mavsdk_drone_show.git"

# LED control command (assumes virtualenv Python path)
LED_CMD="/home/droneshow/mavsdk_drone_show/venv/bin/python /home/droneshow/mavsdk_drone_show/led_indicator.py"

# -------------------------------------------------
# Logging Setup - logs are written to /tmp/update_repo.log
# -------------------------------------------------
LOG_FILE="/tmp/update_repo.log"

log() {
    local message="$1"
    printf "%s: %s\n" "$(date '+%Y-%m-%d %H:%M:%S')" "$message" | tee -a "$LOG_FILE"
}

log_error_and_exit() {
    log "ERROR: $1"
    # Set LED to yellow to indicate failure
    $LED_CMD --color red || true
    exit 1
}

# -------------------------------------------------
# Retry Function with Fixed Delay
# -------------------------------------------------
retry() {
    local retries="$1"
    local delay="$2"
    shift 2
    local count=0

    until "$@"; do
        exit_code=$?
        count=$((count + 1))
        if [ $count -lt $retries ]; then
            log "Command failed with exit code $exit_code (attempt $count/$retries). Retrying in $delay seconds..."
            sleep "$delay"
        else
            log "Command failed after $count attempts. Exiting."
            return $exit_code
        fi
    done
    return 0
}

# -------------------------------------------------
# Network Connectivity Check
# -------------------------------------------------
check_network_connectivity() {
    local retries="$MAX_RETRIES"
    local delay="$INITIAL_DELAY"
    local count=0

    until ping -c 1 github.com >/dev/null 2>&1; do
        count=$((count + 1))
        if [ $count -lt $retries ]; then
            log "Network check failed (attempt $count/$retries). Retrying in $delay seconds..."
            sleep "$delay"
        else
            log_error_and_exit "No network connectivity after multiple attempts."
        fi
    done
    log "Network connectivity confirmed."
}

# -------------------------------------------------
# URL Construction Helpers
# -------------------------------------------------
construct_ssh_url() {
    local https_url="$1"
    local ssh_url="git@github.com:${https_url#https://github.com/}"
    ssh_url="${ssh_url%.git}.git"
    echo "$ssh_url"
}

construct_https_url() {
    local ssh_url="$1"
    local https_url="https://github.com/${ssh_url#git@github.com:}"
    https_url="${https_url%.git}.git"
    echo "$https_url"
}

# -------------------------------------------------
# Parse Command-Line Arguments
# -------------------------------------------------
parse_arguments() {
    BRANCH_NAME=""
    REPO_URL=""
    REPO_DIR=""

    PARSED_OPTIONS=$(getopt -n "$0" -o b: --long branch:,sitl,real,repo-url:,repo-dir: -- "$@")
    if [ $? -ne 0 ]; then
        echo "Error parsing options."
        exit 1
    fi

    eval set -- "$PARSED_OPTIONS"
    while true; do
        case "$1" in
            -b|--branch)
                BRANCH_NAME="$2"
                shift 2
                ;;
            --sitl)
                BRANCH_NAME="$SITL_BRANCH"
                shift
                ;;
            --real)
                BRANCH_NAME="$REAL_BRANCH"
                shift
                ;;
            --repo-url)
                REPO_URL="$2"
                shift 2
                ;;
            --repo-dir)
                REPO_DIR="$2"
                shift 2
                ;;
            --)
                shift
                break
                ;;
            *)
                echo "Unknown option: $1"
                exit 1
                ;;
        esac
    done

    # Set defaults if not specified
    [ -z "$BRANCH_NAME" ] && BRANCH_NAME="$REAL_BRANCH"
    [ -z "$REPO_DIR" ] && REPO_DIR="$DEFAULT_REPO_DIR"
    [ -z "$REPO_URL" ] && REPO_URL="$DEFAULT_SSH_GIT_URL"

    export BRANCH_NAME REPO_URL REPO_DIR
}

parse_arguments "$@"

# -------------------------------------------------
# Lock-File Cleanup (Handles .git/index.lock)
# -------------------------------------------------
cleanup_lock_file() {
    local lock_file="$REPO_DIR/.git/index.lock"
    local tries=0
    local max_tries=3

    while [ -f "$lock_file" ] && [ $tries -lt $max_tries ]; do
        if pgrep -f "git" >/dev/null 2>&1; then
            log "Detected .git/index.lock while another Git process might be running. Waiting 3 seconds..."
            sleep 3
        else
            log "Stale .git/index.lock found. Attempting removal..."
            rm -f "$lock_file"
        fi
        tries=$((tries+1))
    done

    if [ -f "$lock_file" ]; then
        log "WARNING: .git/index.lock still present after $max_tries tries. Forcibly removing it."
        rm -f "$lock_file"
    fi
}

# -------------------------------------------------
# Check Git Repository Integrity
# -------------------------------------------------
check_git_repository_integrity() {
    log "Checking repository integrity..."
    if ! git fsck --full; then
        log_error_and_exit "Git repository integrity check failed. Corruption detected."
    fi
}

# -------------------------------------------------
# Main Script Execution
# -------------------------------------------------
# Set LED to blue indicating Git sync is starting
$LED_CMD --color blue || log "Warning: Unable to set LED to blue."

log "==========================================="
log "Starting repository update script for MDS repository."
log "Branch: $BRANCH_NAME"
log "Repo URL: $REPO_URL"
log "Repo Dir: $REPO_DIR"
log "==========================================="

# Ensure REPO_DIR exists
if [ ! -d "$REPO_DIR" ]; then
    log_error_and_exit "Repository directory does not exist: $REPO_DIR"
fi

cd "$REPO_DIR" || log_error_and_exit "Failed to cd into $REPO_DIR"

# Clean up any existing Git lock files
cleanup_lock_file

# Determine if SSH or HTTPS is viable
if [[ "$REPO_URL" == git@* ]]; then
    if git ls-remote "$REPO_URL" -q >/dev/null 2>&1; then
        log "Using SSH for Git operations."
        GIT_URL="$REPO_URL"
    else
        log "SSH connection failed. Falling back to HTTPS."
        GIT_URL="$(construct_https_url "$REPO_URL")"
    fi
elif [[ "$REPO_URL" == https://* ]]; then
    local_ssh_url="$(construct_ssh_url "$REPO_URL")"
    if git ls-remote "$local_ssh_url" -q >/dev/null 2>&1; then
        log "SSH connection successful. Using SSH URL: $local_ssh_url"
        GIT_URL="$local_ssh_url"
    else
        log "SSH connection failed. Using HTTPS URL: $REPO_URL"
        GIT_URL="$REPO_URL"
    fi
else
    log_error_and_exit "Invalid REPO_URL: $REPO_URL"
fi

# Update remote origin if necessary
current_remote_url=$(git remote get-url origin)
if [ "$current_remote_url" != "$GIT_URL" ]; then
    log "Setting remote URL to $GIT_URL"
    git remote set-url origin "$GIT_URL" || log_error_and_exit "Failed to set remote URL."
else
    log "Remote URL is already set to $GIT_URL"
fi

# Stash any local changes to avoid conflicts
if git status --porcelain | grep -q .; then
    log "Stashing local changes..."
    git stash --include-untracked || log_error_and_exit "Failed to stash changes."
else
    log "No local changes to stash."
fi

# Check network connectivity
check_network_connectivity

# Fetch all branches with retries
log "Fetching latest commits from origin..."
if ! retry "$MAX_RETRIES" "$INITIAL_DELAY" git fetch --all; then
    log_error_and_exit "Failed to fetch from $GIT_URL."
fi

# Check repository integrity
#check_git_repository_integrity

# Re-check lock file
cleanup_lock_file

# Switch to the desired branch if not already on it
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" != "$BRANCH_NAME" ]; then
    log "Switching from $CURRENT_BRANCH to $BRANCH_NAME..."
    git checkout "$BRANCH_NAME" || log_error_and_exit "Failed to checkout branch $BRANCH_NAME."
    log "Switched to branch $BRANCH_NAME"
fi

# Reset local branch to match origin
log "Resetting $BRANCH_NAME to origin/$BRANCH_NAME..."
if ! retry "$MAX_RETRIES" "$INITIAL_DELAY" git reset --hard "origin/$BRANCH_NAME"; then
    log_error_and_exit "Failed git reset --hard on branch $BRANCH_NAME."
fi

# Pull latest changes
log "Pulling latest updates on $BRANCH_NAME..."
if ! retry "$MAX_RETRIES" "$INITIAL_DELAY" git pull; then
    log_error_and_exit "Failed git pull on branch $BRANCH_NAME."
fi

# Final cleanup
cleanup_lock_file

log "Successfully updated code from $GIT_URL on branch $BRANCH_NAME."

# Optionally, set LED to indicate success; leave it to coordinator to update later if desired.
# $LED_CMD --color blue || log "Warning: Unable to update LED after Git sync." 

exit 0
