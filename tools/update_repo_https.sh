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
#   - If -b <branch_name> is passed, the script will switch to the specified branch.
#   - If no branch argument is passed, the script will stay on the current branch.
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
# ./update_repo_https.sh                    # Stays on current branch
# ./update_repo_https.sh -b <branch_name>   # Uses the specified branch

set -euo pipefail

# =============================================================================
# REPOSITORY CONFIGURATION: Environment Variable Support (MDS v3.1+)
# =============================================================================
# This HTTPS git update script now supports environment variable override for
# advanced deployments while maintaining 100% backward compatibility.
#
# FOR NORMAL USERS (99%):
#   - No action required - defaults work identically to previous versions
#   - Uses: https://github.com/alireza787b/mavsdk_drone_show.git
#   - Simply run: bash update_repo_https.sh [branch]
#
# FOR ADVANCED USERS (Custom Forks):
#   - Set environment variable before running this script:
#     export MDS_REPO_URL="https://github.com/yourcompany/your-fork.git"
#   - The script will use your custom repository URL
#   - Note: Only HTTPS URLs work with this script (no SSH keys needed)
#
# EXAMPLES:
#   # Normal usage (no environment variables):
#   bash update_repo_https.sh main-candidate
#
#   # Advanced usage with custom repository:
#   export MDS_REPO_URL="https://github.com/company/fork.git"
#   bash update_repo_https.sh production
#
# ENVIRONMENT VARIABLES SUPPORTED:
#   MDS_REPO_URL  - Git repository URL (HTTPS format only for this script)
# =============================================================================

# Configuration variables (with environment variable override support)
REPO_DIR="${HOME}/mavsdk_drone_show"        # Modify this path as needed
GIT_URL="${MDS_REPO_URL:-https://github.com/the-mak-00/mavsdk_drone_show.git}"  # HTTPS URL for the repo
LOG_FILE="${REPO_DIR}/update_repo.log"

# Maximum number of retries for network operations
MAX_RETRIES=5
INITIAL_DELAY=5  # seconds

# Function to determine branch based on user input
determine_branch() {
    local branch=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -b|--branch)
                if [[ -n "${2-}" ]]; then
                    branch="$2"
                    shift 2
                else
                    echo "Error: --branch requires a non-empty option argument." >&2
                    echo "Usage: $0 [-b <branch_name>]" >&2
                    exit 1
                fi
                ;;
            *)
                echo "Unknown option: $1" >&2
                echo "Usage: $0 [-b <branch_name>]" >&2
                exit 1
                ;;
        esac
    done
    printf "%s" "$branch"
}

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

# Parse branch input
BRANCH_NAME=$(determine_branch "$@")

# Ensure the repository directory exists
if [ ! -d "$REPO_DIR" ]; then
    log_error_and_exit "Repository directory does not exist: $REPO_DIR"
fi

# Navigate to the project directory
cd "$REPO_DIR" || log_error_and_exit "Failed to navigate to $REPO_DIR"

# Stash any local changes
if git status --porcelain | grep .; then
    log "Stashing local changes..."
    git stash --include-untracked || log_error_and_exit "Failed to stash local changes."
else
    log "No local changes to stash."
fi

# Set the Git remote URL to HTTPS
git remote set-url origin "$GIT_URL" || log_error_and_exit "Failed to set remote URL to $GIT_URL"

# Check network connectivity
check_network_connectivity

# Fetch the latest updates from all branches with retries
if ! retry "$MAX_RETRIES" "$INITIAL_DELAY" git fetch --all; then
    log_error_and_exit "Failed to fetch updates from $GIT_URL after multiple attempts."
fi

# Determine the branch to operate on
if [ -n "$BRANCH_NAME" ]; then
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
else
    # No branch specified, use current branch
    BRANCH_NAME=$(git rev-parse --abbrev-ref HEAD)
    log "No branch specified. Using current branch: $BRANCH_NAME"
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

# Optional: Apply stashed changes if any (currently not needed)
# if git stash list | grep -q 'stash@{0}'; then
#     log "Applying stashed changes..."
#     git stash pop || log_error_and_exit "Failed to apply stashed changes."
# fi

exit 0
