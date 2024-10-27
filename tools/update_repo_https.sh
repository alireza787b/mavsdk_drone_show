#!/bin/bash

# update_repo_https.sh
# Script to ensure the drone's software repository is up-to-date before operations using HTTPS for public repositories.
# This version assumes no authentication is required (i.e., the repository is public).
#
# Usage:
# This script can be run manually for troubleshooting or manual updates, or set up as a cron job or service.
#
# Configuration:
# - REPO_DIR: Directory of the local Git repository.
# - GIT_URL: URL to the Git repository (HTTPS only, assuming a public repository).
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
# ./update_repo_https.sh                   # Uses default branch (real-test-1)
# ./update_repo_https.sh --sitl            # Uses docker-sitl-2 branch
# ./update_repo_https.sh -b <branch_name>  # Uses the specified branch
#

set -euo pipefail

# Configuration variables
REPO_DIR="${HOME}/mavsdk_drone_show"  # Modify this path as needed
DEFAULT_BRANCH="real-test-1"          # Default branch to synchronize with
SITL_BRANCH="docker-sitl-2"           # SITL branch
GIT_URL="https://github.com/alireza787b/mavsdk_drone_show.git"  # HTTPS URL for the repo
LOG_FILE="${REPO_DIR}/update_repo.log"

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

# Ensure the repository directory exists
if [ ! -d "$REPO_DIR" ]; then
    log_error_and_exit "Repository directory does not exist: $REPO_DIR"
fi

# Navigate to the project directory
cd "$REPO_DIR" || log_error_and_exit "Failed to navigate to $REPO_DIR"

# Do a stash
git stash

# Check network connectivity
if ! ping -c 1 github.com >/dev/null 2>&1; then
    log_error_and_exit "No network connectivity. Cannot update repository."
fi

# Fetch the latest updates from all branches
if ! git fetch --all; then
    log_error_and_exit "Failed to fetch updates from $GIT_URL"
fi

# Checkout the specified branch
if ! git checkout "$BRANCH_NAME"; then
    log_error_and_exit "Failed to checkout branch $BRANCH_NAME"
fi

# Pull the latest updates
if ! git pull --rebase; then
    log_error_and_exit "Failed to pull the latest updates from $BRANCH_NAME"
else
    printf "$(date): Successfully updated code from $GIT_URL on branch $BRANCH_NAME\n" | tee -a "$LOG_FILE"
fi
