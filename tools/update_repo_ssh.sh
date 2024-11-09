#!/bin/bash

# update_repo_ssh.sh
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
# - BRANCH_NAME: The branch to synchronize with.
#   By default, no branch is specified, and the current branch will be used.
#   - If `--real` is passed, the script will switch to the `real-test-1` branch.
#   - If `--sitl` is passed, the script will switch to the `docker-sitl-2` branch.
#   - If `-b <branch_name>` is passed, the script will switch to the specified branch.
#
# Logging:
# The script logs all operations and their outcomes to a log file to aid in debugging
# and operational monitoring.
#
# Reliability Improvements:
# - Added retry mechanisms with exponential backoff for network operations (`git fetch`, `git pull`, and network connectivity check).
# - The script will attempt to retry failed network operations up to a specified number of times before exiting.
# - Enhanced error handling and logging for better troubleshooting.
#
# Example usage:
# ./update_repo_ssh.sh                    # Stays on current branch
# ./update_repo_ssh.sh --real             # Uses real-test-1 branch
# ./update_repo_ssh.sh --sitl             # Uses docker-sitl-2 branch
# ./update_repo_ssh.sh -b <branch_name>   # Uses the specified branch
#

set -euo pipefail

# Configuration variables
REPO_DIR="${HOME}/mavsdk_drone_show"  # Modify this path as needed
DEFAULT_BRANCH="real-test-1"          # Default branch to use with --real
SITL_BRANCH="docker-sitl-2"           # SITL branch
LOG_FILE="${REPO_DIR}/update_repo.log"

# Default Git URL (SSH)
GIT_URL="git@github.com:alireza787b/mavsdk_drone_show.git"

# Function to determine branch based on user input
determine_branch() {
    local branch=""  # Start with empty branch
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --real)
                branch="$DEFAULT_BRANCH"
                shift
                ;;
            --sitl)
                branch="$SITL_BRANCH"
                shift
                ;;
            -b|--branch)
                if [[ -n "${2-}" ]]; then
                    branch="$2"
                    shift 2
                else
                    echo "Error: --branch requires a non-empty option argument." >&2
                    exit 1
                fi
                ;;
            *)
                shift  # Skip other arguments
                ;;
        esac
    done
    printf "%s" "$branch"
}

# Function to log and exit with error
log_error_and_exit() {
    local message="$1"
    printf "$(date): ERROR: %s\n" "$message" | tee -a "$LOG_FILE" >&2
    exit 1
}

# Function to retry a command up to N times with exponential backoff
retry() {
    local retries=$1      # Number of retries
    local delay=$2        # Initial delay between retries in seconds
    shift 2               # Shift the arguments to get the command
    local count=0

    until "$@"; do
        exit_code=$?
        count=$((count + 1))
        if [ $count -lt $retries ]; then
            wait=$((delay * 2 ** (count -1)))
            echo "$(date): Command failed with exit code $exit_code. Attempt $count/$retries. Retrying in $wait seconds..." | tee -a "$LOG_FILE"
            sleep $wait
        else
            echo "$(date): Command failed after $count attempts." | tee -a "$LOG_FILE"
            return $exit_code
        fi
    done
    return 0
}

# Function to check network connectivity with retries
check_network_connectivity() {
    local retries=5       # Number of retries
    local delay=5         # Initial delay between retries in seconds
    local count=0

    until ping -c 1 github.com >/dev/null 2>&1; do
        count=$((count + 1))
        if [ $count -lt $retries ]; then
            wait=$((delay * 2 ** (count -1)))
            echo "$(date): Network check failed. Attempt $count/$retries. Retrying in $wait seconds..." | tee -a "$LOG_FILE"
            sleep $wait
        else
            log_error_and_exit "No network connectivity after multiple attempts. Cannot update repository."
        fi
    done
    echo "$(date): Network connectivity confirmed." | tee -a "$LOG_FILE"
}

# Parse branch input
BRANCH_NAME=$(determine_branch "$@")

# Check if SSH key exists
if [ ! -f "${HOME}/.ssh/id_rsa" ]; then
    echo "$(date): No SSH key found. Falling back to HTTPS for Git operations." | tee -a "$LOG_FILE"
    GIT_URL="https://github.com/alireza787b/mavsdk_drone_show.git"
fi

# Ensure the repository directory exists
if [ ! -d "$REPO_DIR" ]; then
    log_error_and_exit "Repository directory does not exist: $REPO_DIR"
fi

# Navigate to the project directory
cd "$REPO_DIR" || log_error_and_exit "Failed to navigate to $REPO_DIR"

# Stash any local changes
if git status --porcelain | grep .; then
    echo "$(date): Stashing local changes..." | tee -a "$LOG_FILE"
    git stash --include-untracked
else
    echo "$(date): No local changes to stash." | tee -a "$LOG_FILE"
fi

# Set the Git remote URL to the chosen protocol
git remote set-url origin "$GIT_URL"

# Check network connectivity
check_network_connectivity

# Fetch the latest updates from all branches with retries
if ! retry 5 5 git fetch --all; then
    log_error_and_exit "Failed to fetch updates from $GIT_URL after multiple attempts."
fi

# If a branch name was specified, checkout that branch
if [ -n "$BRANCH_NAME" ]; then
    if ! git checkout "$BRANCH_NAME"; then
        log_error_and_exit "Failed to checkout branch $BRANCH_NAME"
    else
        echo "$(date): Switched to branch $BRANCH_NAME" | tee -a "$LOG_FILE"
    fi
else
    # No branch specified, stay on current branch
    BRANCH_NAME=$(git rev-parse --abbrev-ref HEAD)
    echo "$(date): No branch specified, staying on current branch $BRANCH_NAME" | tee -a "$LOG_FILE"
fi

# Reset local changes and ensure the branch is synced with the remote
if ! retry 5 5 git reset --hard "origin/$BRANCH_NAME"; then
    log_error_and_exit "Failed to reset the branch $BRANCH_NAME"
fi

# Pull the latest updates with retries
if ! retry 5 5 git pull; then
    log_error_and_exit "Failed to pull the latest updates from $BRANCH_NAME after multiple attempts."
else
    echo "$(date): Successfully updated code from $GIT_URL on branch $BRANCH_NAME" | tee -a "$LOG_FILE"
fi

# Optional: Apply stashed changes if any... not needed now.
# if git stash list | grep -q 'stash@{0}'; then
#     echo "$(date): Applying stashed changes..." | tee -a "$LOG_FILE"
#     git stash pop
# fi
