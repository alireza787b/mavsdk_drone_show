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
#   By default, it is set to `real-test-1`. However, the user can specify a branch via the script's arguments.
#   - If no branch argument is passed, the default branch will be used (`real-test-1`).
#   - Use `--sitl` to switch to `docker-sitl-2` branch.
#   - Use `-b <branch_name>` to specify a custom branch.
#
# Logging:
# The script logs all operations and their outcomes to a log file to aid in debugging
# and operational monitoring.

# Example usage:
# ./update_repo_ssh.sh                    # Uses default branch (real-test-1)
# ./update_repo_ssh.sh --sitl             # Uses docker-sitl-2 branch
# ./update_repo_ssh.sh -b <branch_name>   # Uses the specified branch
#

# Configuration variables
REPO_DIR="${HOME}/mavsdk_drone_show"  # Modify this path as needed
DEFAULT_BRANCH="real-test-1"          # Default branch to synchronize with
SITL_BRANCH="docker-sitl-2"           # SITL branch
LOG_FILE="${REPO_DIR}/update_repo.log"

# Default Git URL (SSH)
GIT_URL="git@github.com:alireza787b/mavsdk_drone_show.git"

# Function to determine branch based on user input
determine_branch() {
    local branch="$DEFAULT_BRANCH"  # Default value
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --sitl)
                branch="$SITL_BRANCH"
                shift
                ;;
            -b|--branch)
                branch="$2"
                shift 2
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
    printf "$(date): %s\n" "$message" | tee -a "$LOG_FILE" >&2
    exit 1
}

# Parse branch input
BRANCH_NAME=$(determine_branch "$@")

# Check if SSH key exists
if [ ! -f "${HOME}/.ssh/id_rsa" ]; then
    printf "$(date): No SSH key found. Falling back to HTTPS for Git operations.\n" | tee -a "$LOG_FILE"
    GIT_URL="https://github.com/alireza787b/mavsdk_drone_show.git"
fi

# Ensure the repository directory exists
if [ ! -d "$REPO_DIR" ]; then
    log_error_and_exit "Repository directory does not exist: $REPO_DIR"
fi

# Navigate to the project directory
cd "$REPO_DIR" || log_error_and_exit "Failed to navigate to $REPO_DIR"

# Do a stash
git stash

# Set the Git remote URL to the chosen protocol
git remote set-url origin "$GIT_URL"

# Fetch the latest updates from all branches
if ! git fetch --all; then
    log_error_and_exit "Failed to fetch updates from $GIT_URL"
fi

# Checkout the specified branch
if ! git checkout "$BRANCH_NAME"; then
    log_error_and_exit "Failed to checkout branch $BRANCH_NAME"
fi

# Reset local changes and ensure the branch is synced with the remote
if ! git reset --hard "origin/$BRANCH_NAME"; then
    log_error_and_exit "Failed to reset the branch $BRANCH_NAME"
fi

# Pull the latest updates
if ! git pull; then
    log_error_and_exit "Failed to pull the latest updates from $BRANCH_NAME"
else
    printf "$(date): Successfully updated code from $GIT_URL on branch $BRANCH_NAME\n" | tee -a "$LOG_FILE"
fi
