#!/bin/bash

# update_repo.sh
# Script to ensure the drone's software repository is up-to-date before operations.
# Adjust the REPO_DIR variable to match the directory where your repository is located.
#
# Usage:
# This script is intended to be run automatically by the system service that
# starts the drone's operation software, ensuring all components are up-to-date.
# It can also be run manually for troubleshooting or manual updates.
#
# Configuration:
# - REPO_DIR: Directory of the local Git repository.
# - GIT_URL: URL to the Git repository (SSH by default, but HTTPS can be used as a fallback).
# - SITL_BRANCH: The default branch for SITL operations (docker-sitl-2).
# - REAL_BRANCH: The default branch for real operations (main-candidate).
# - User can select branches using --real or --sitl options.
# - Repo name and URL can be configured via command line parameters.
#
# Logging:
# The script logs all operations and their outcomes to a log file to aid in debugging
# and operational monitoring.
#
# Reliability Improvements:
# - Added retry mechanisms with exponential backoff for network operations (git fetch, git pull, and network connectivity check).
# - The script will attempt to retry failed network operations up to a specified number of times before exiting.
# - Enhanced error handling and logging for better troubleshooting.
#
# Example usage:
# ./update_repo.sh                            # Uses default branch (REAL_BRANCH)
# ./update_repo.sh --sitl                     # Uses SITL_BRANCH
# ./update_repo.sh --real                     # Uses REAL_BRANCH
# ./update_repo.sh -b <branch_name>           # Uses the specified branch
# ./update_repo.sh --repo-url <repo_url>      # Uses the specified repository URL
# ./update_repo.sh --repo-dir <directory>     # Uses the specified repository directory

set -euo pipefail

# Maximum number of retries for network operations
MAX_RETRIES=5
INITIAL_DELAY=5  # seconds

# Default branch names
SITL_BRANCH="docker-sitl-2"
REAL_BRANCH="main-candidate"

# Default repository directory
DEFAULT_REPO_DIR="${HOME}/mavsdk_drone_show"

# Default Git URLs (SSH and HTTPS)
DEFAULT_SSH_GIT_URL="git@github.com:alireza787b/mavsdk_drone_show.git"
DEFAULT_HTTPS_GIT_URL="https://github.com/alireza787b/mavsdk_drone_show.git"

# Function to log messages with timestamp
log() {
    local message="$1"
    printf "$(date '+%Y-%m-%d %H:%M:%S'): %s\n" "$message" | tee -a "$LOG_FILE"
}

# Function to log and exit with error
log_error_and_exit() {
    local message="$1"
    log "ERROR: $message"
    exit 1
}

# Function to retry a command up to N times with exponential backoff
retry() {
    local retries=$1
    local delay=$2
    shift 2
    local count=0

    until "$@"; do
        exit_code=$?
        count=$((count + 1))
        if [ $count -lt $retries ]; then
            wait=$((delay * 2 ** (count -1)))
            log "Command failed with exit code $exit_code. Attempt $count/$retries. Retrying in $wait seconds..."
            sleep $wait
        else
            log "Command failed after $count attempts."
            return $exit_code
        fi
    done
    return 0
}

# Function to check network connectivity with retries
check_network_connectivity() {
    local retries=$MAX_RETRIES
    local delay=$INITIAL_DELAY
    local count=0

    until ping -c 1 github.com >/dev/null 2>&1; do
        count=$((count + 1))
        if [ $count -lt $retries ]; then
            wait=$((delay * 2 ** (count -1)))
            log "Network check failed. Attempt $count/$retries. Retrying in $wait seconds..."
            sleep $wait
        else
            log_error_and_exit "No network connectivity after multiple attempts. Cannot update repository."
        fi
    done
    log "Network connectivity confirmed."
}

# Function to construct SSH URL from HTTPS URL
construct_ssh_url() {
    local https_url="$1"
    local ssh_url
    ssh_url="git@github.com:${https_url#https://github.com/}"
    ssh_url="${ssh_url%.git}.git"
    echo "$ssh_url"
}

# Function to construct HTTPS URL from SSH URL
construct_https_url() {
    local ssh_url="$1"
    local https_url
    https_url="https://github.com/${ssh_url#git@github.com:}"
    https_url="${https_url%.git}.git"
    echo "$https_url"
}

# Function to parse command-line arguments
parse_arguments() {
    # Default values
    BRANCH_NAME=""
    REPO_URL=""
    REPO_DIR=""

    # Parse arguments
    PARSED_OPTIONS=$(getopt -n "$0" -o b: --long branch:,sitl,real,repo-url:,repo-dir: -- "$@")
    if [ $? -ne 0 ]; then
        echo "Error parsing options"
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

    # Set default branch if none specified
    if [ -z "${BRANCH_NAME}" ]; then
        BRANCH_NAME="$REAL_BRANCH"
    fi

    # Set default repository directory if none specified
    if [ -z "${REPO_DIR}" ]; then
        REPO_DIR="$DEFAULT_REPO_DIR"
    fi

    # Set default repository URL if none specified
    if [ -z "${REPO_URL}" ]; then
        REPO_URL="$DEFAULT_SSH_GIT_URL"
    fi
}

# Parse command-line arguments
parse_arguments "$@"

# Set the log file path
LOG_FILE="${REPO_DIR}/update_repo.log"

# Attempt to use SSH first if possible
GIT_URL="$REPO_URL"

if [[ "$REPO_URL" == git@* ]]; then
    # REPO_URL is SSH URL
    if git ls-remote "$REPO_URL" -q >/dev/null 2>&1; then
        log "Using SSH for Git operations"
    else
        log "Warning: SSH connection to $REPO_URL failed. Attempting to fallback to HTTPS."
        GIT_URL="$(construct_https_url "$REPO_URL")"
        log "Using HTTPS URL: $GIT_URL"
    fi
elif [[ "$REPO_URL" == https://* ]]; then
    # REPO_URL is HTTPS URL
    # Try to use SSH first
    SSH_URL="$(construct_ssh_url "$REPO_URL")"
    if git ls-remote "$SSH_URL" -q >/dev/null 2>&1; then
        GIT_URL="$SSH_URL"
        log "SSH connection successful. Using SSH URL: $GIT_URL"
    else
        GIT_URL="$REPO_URL"
        log "SSH connection failed. Using HTTPS URL: $GIT_URL"
    fi
else
    log_error_and_exit "Invalid REPO_URL: $REPO_URL"
fi

# Ensure the repository directory exists
if [ ! -d "$REPO_DIR" ]; then
    log_error_and_exit "Repository directory does not exist: $REPO_DIR"
fi

# Navigate to the project directory
cd "$REPO_DIR" || log_error_and_exit "Failed to navigate to $REPO_DIR"

# Check if the remote origin URL needs to be updated
current_remote_url=$(git remote get-url origin)
if [ "$current_remote_url" != "$GIT_URL" ]; then
    log "Setting remote URL to $GIT_URL"
    git remote set-url origin "$GIT_URL" || log_error_and_exit "Failed to set remote URL to $GIT_URL"
else
    log "Remote URL is already set to $GIT_URL"
fi

# Stash any local changes
if git status --porcelain | grep .; then
    log "Stashing local changes..."
    git stash --include-untracked || log_error_and_exit "Failed to stash local changes."
else
    log "No local changes to stash."
fi

# Check network connectivity
check_network_connectivity

# Fetch the latest updates from all branches with retries
if ! retry "$MAX_RETRIES" "$INITIAL_DELAY" git fetch --all; then
    log_error_and_exit "Failed to fetch updates from $GIT_URL after multiple attempts."
fi

# Determine the branch to operate on
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" != "$BRANCH_NAME" ]; then
    log "Switching to branch $BRANCH_NAME..."
    if ! git checkout "$BRANCH_NAME"; then
        log_error_and_exit "Failed to checkout branch $BRANCH_NAME"
    else
        log "Switched to branch $BRANCH_NAME"
    fi
else
    log "Already on branch $BRANCH_NAME"
fi

# Reset local changes to match the remote branch
log "Resetting local branch $BRANCH_NAME to match origin/$BRANCH_NAME..."
if ! retry "$MAX_RETRIES" "$INITIAL_DELAY" git reset --hard "origin/$BRANCH_NAME"; then
    log_error_and_exit "Failed to reset the branch $BRANCH_NAME"
fi

# Pull the latest updates with retries
log "Pulling the latest updates for branch $BRANCH_NAME..."
if ! retry "$MAX_RETRIES" "$INITIAL_DELAY" git pull; then
    log_error_and_exit "Failed to pull the latest updates from $BRANCH_NAME after multiple attempts."
else
    log "Successfully updated code from $GIT_URL on branch $BRANCH_NAME"
fi

exit 0
