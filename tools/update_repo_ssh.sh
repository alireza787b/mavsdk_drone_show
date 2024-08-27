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
#
# Logging:
# The script logs all operations and their outcomes to a log file to aid in debugging
# and operational monitoring.

# Configuration variables
REPO_DIR="${HOME}/mavsdk_drone_show"  # Modify this path as needed
BRANCH_NAME="real-test-1"  # Branch to synchronize with
LOG_FILE="${REPO_DIR}/update_repo.log"

# Default Git URL (SSH)
GIT_URL="git@github.com:alireza787b/mavsdk_drone_show.git"

# Check if SSH key exists
if [ ! -f "${HOME}/.ssh/id_rsa" ]; then
    echo "$(date): No SSH key found. Falling back to HTTPS for Git operations." | tee -a "$LOG_FILE"
    GIT_URL="https://github.com/alireza787b/mavsdk_drone_show.git"
fi

# Ensure the repository directory exists
if [ ! -d "$REPO_DIR" ]; then
    echo "$(date): Repository directory does not exist: $REPO_DIR" | tee -a "$LOG_FILE"
    exit 1
fi

# Navigate to the project directory
cd "$REPO_DIR" || { echo "$(date): Failed to navigate to $REPO_DIR" | tee -a "$LOG_FILE"; exit 1; }

# Set the Git remote URL to the chosen protocol
git remote set-url origin $GIT_URL

# Fetch the latest updates from all branches
if ! git fetch --all; then
    echo "$(date): Failed to fetch updates from $GIT_URL" | tee -a "$LOG_FILE"
    exit 1
fi

# Checkout the specified branch
if ! git checkout $BRANCH_NAME; then
    echo "$(date): Failed to checkout branch $BRANCH_NAME" | tee -a "$LOG_FILE"
    exit 1
fi

# Reset local changes and ensure the branch is synced with the remote
if ! git reset --hard origin/$BRANCH_NAME; then
    echo "$(date): Failed to reset the branch $BRANCH_NAME" | tee -a "$LOG_FILE"
    exit 1
fi

# Pull the latest updates
if ! git pull; then
    echo "$(date): Failed to pull the latest updates from $BRANCH_NAME" | tee -a "$LOG_FILE"
    exit 1
else
    echo "$(date): Successfully updated code from $GIT_URL on branch $BRANCH_NAME" | tee -a "$LOG_FILE"
fi
