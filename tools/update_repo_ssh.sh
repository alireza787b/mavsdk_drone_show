#!/bin/bash
#
# update_repo_ssh.sh - Git Sync for MDS Repository (Automated Repair Version)
#
# This script ensures that the drone's software repository (MDS) is
# up-to-date before operations start. It performs the following steps:
#
# 1. Check network connectivity and GitHub accessibility (SSH/HTTPS).
# 2. Clean up any stale Git locks and stash local changes.
# 3. Attempt a normal git fetch (with retries). If it fails, assume there
#    may be repository corruption and run an integrity check.
# 4. Run 'git fsck' to identify any integrity issues (ignoring benign dangling
#    commits). If issues are found:
#      - If related to stash reflog, clear the stash.
#      - Otherwise, attempt to repair with git-repair (using a timeout).
#      - If repair fails (or if no corruption is found but fetch still fails),
#        reboot the system.
# 5. If the repository is healthy, switch to the desired branch, reset it to
#    match origin, and pull the latest changes.
#
# LED indicators (via led_indicator.py) are used to signal status:
#   - Blue: Git sync in progress.
#   - Yellow: Git repair in progress.
#   - Red: Failure.
#
# Usage:
#   ./update_repo_ssh.sh [--branch <branch>] [--sitl] [--real]
#                          [--repo-url <url>] [--repo-dir <dir>]
#
# Author: Alireza Ghaderi
# Date: 2025-03-02 (Revised: 2025-03-13, updated 2025-03-13 for automated repair on fetch failure)
#

set -euo pipefail

# ----------------------------------
# Configuration and Default Settings
# ----------------------------------
MAX_RETRIES=10
INITIAL_DELAY=1               # Delay (in seconds) between retries
REPAIR_TIMEOUT=120            # Timeout (in seconds) for git-repair (2 minutes)
SITL_BRANCH="docker-sitl-2"
REAL_BRANCH="aerohive-devv"

DEFAULT_REPO_DIR="${HOME}/UAV_sepehr"
DEFAULT_SSH_GIT_URL="git@github.com:AeroHive-community/UAV_sepehr"
DEFAULT_HTTPS_GIT_URL="https://github.com/AeroHive-community/UAV_sepehr.git"

# LED control command (assumes virtualenv Python path)
LED_CMD="/home/UAV_sepehr/venv/bin/python /home/UAV_sepehr/led_indicator.py"

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
    # Set LED to red to indicate failure
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
            log "Command failed after $count attempts."
            return $exit_code
        fi
    done
    return 0
}

# -------------------------------------------------
# Check Network Connectivity and GitHub Access
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
# Clean Up Stale Git Lock Files
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
# Check and Repair Repository Integrity
# -------------------------------------------------
check_and_repair_git_corruption() {
    log "Checking repository integrity..."
    fsck_output=$(git fsck --full 2>&1)
    filtered_output=$(echo "$fsck_output" | grep -v "dangling commit")
    
    if [ -n "$filtered_output" ]; then
        log "Integrity check reported issues:"
        echo "$filtered_output" | tee -a "$LOG_FILE"
        if echo "$filtered_output" | grep -q "refs/stash"; then
            log "Stash reflog errors detected. Clearing stash..."
            git stash clear || log "Warning: Failed to clear stash."
            if [ -f ".git/logs/refs/stash" ]; then
                rm -f ".git/logs/refs/stash"
                log "Removed corrupted stash reflog."
            fi
            # Re-run fsck after clearing stash
            fsck_output_after=$(git fsck --full 2>&1)
            filtered_output_after=$(echo "$fsck_output_after" | grep -v "dangling commit")
            if [ -n "$filtered_output_after" ]; then
                log "Repository still reports issues after clearing stash. Proceeding to repair..."
            else
                log "Repository issues resolved by clearing stash."
                return
            fi
        fi
        log "Attempting repair with git-repair (timeout ${REPAIR_TIMEOUT}s)..."
        $LED_CMD --color yellow || log "Warning: Unable to set LED to yellow."
        if timeout "$REPAIR_TIMEOUT" git-repair >> "$LOG_FILE" 2>&1; then
            log "Git repair completed successfully."
        else
            log "Git repair failed. Rebooting system..."
            sudo reboot || log_error_and_exit "Reboot command failed."
            exit 0
        fi
        if [ -f ".git/gc.log" ]; then
            rm -f ".git/gc.log"
            log "Removed .git/gc.log after repair."
        fi
        log "Repository repair complete. Rebooting system to ensure a clean state..."
        sudo reboot || log_error_and_exit "Reboot command failed."
        exit 0
    else
        log "No corruption detected in repository."
    fi
}

# -------------------------------------------------
# Main Workflow Execution
# -------------------------------------------------
# Set LED to blue to indicate Git sync is starting
$LED_CMD --color blue || log "Warning: Unable to set LED to blue."

log "==========================================="
log "Starting repository update script for MDS repository."
log "Branch: $BRANCH_NAME"
log "Repo URL: $REPO_URL"
log "Repo Dir: $REPO_DIR"
log "==========================================="

# Ensure repository directory exists
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

# Attempt to fetch all branches with retries.
log "Fetching latest commits from origin..."
if ! retry "$MAX_RETRIES" "$INITIAL_DELAY" git fetch --all; then
    log "Fetch failed. This may indicate repository corruption. Initiating repair sequence..."
    check_and_repair_git_corruption
    log "Retrying fetch after repair..."
    if ! retry "$MAX_RETRIES" "$INITIAL_DELAY" git fetch --all; then
        log_error_and_exit "Failed to fetch from $GIT_URL after repair. Rebooting..."
    fi
fi

# Clean up any residual lock files.
cleanup_lock_file

# Switch to the desired branch if not already on it.
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" != "$BRANCH_NAME" ]; then
    log "Switching from $CURRENT_BRANCH to $BRANCH_NAME..."
    git checkout "$BRANCH_NAME" || log_error_and_exit "Failed to checkout branch $BRANCH_NAME."
    log "Switched to branch $BRANCH_NAME"
fi

# Reset the branch to match origin.
log "Resetting $BRANCH_NAME to origin/$BRANCH_NAME..."
if ! retry "$MAX_RETRIES" "$INITIAL_DELAY" git reset --hard "origin/$BRANCH_NAME"; then
    log_error_and_exit "Failed git reset --hard on branch $BRANCH_NAME."
fi

# Pull the latest updates.
log "Pulling latest updates on $BRANCH_NAME..."
if ! retry "$MAX_RETRIES" "$INITIAL_DELAY" git pull; then
    log_error_and_exit "Failed git pull on branch $BRANCH_NAME."
fi

# Final cleanup of lock files.
cleanup_lock_file

log "Successfully updated code from $GIT_URL on branch $BRANCH_NAME."
exit 0
