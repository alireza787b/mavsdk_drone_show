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
# - GIT_URL: URL to the Git repository.
# - BRANCH_NAME: The branch to which the repository should be set.
#
# Logging:
# The script logs all operations and their outcomes to a log file to aid in debugging
# and operational monitoring.

# Configuration variables
REPO_DIR="${HOME}/mavsdk_drone_show"  # Modify this path as needed
GIT_URL="git@github.com:alireza787b/mavsdk_drone_show.git"  # Repository URL
BRANCH_NAME="real-test-1"  # Branch to synchronize with

# Ensure the repository directory exists
if [ ! -d "$REPO_DIR" ]; then
    echo "Repository directory does not exist: $REPO_DIR"
    exit 1
fi

# Navigate to the project directory
cd "$REPO_DIR" || exit

# Fetch the latest updates from all branches
git fetch --all

# Checkout the specified branch
git checkout $BRANCH_NAME

# Reset local changes and ensure the branch is synced with the remote
git reset --hard origin/$BRANCH_NAME

# Pull the latest updates
git pull

# Check if Git operations were successful and log the result
if [ $? -ne 0 ]; then
    echo "$(date): Failed to update code from Git repository" >> "${REPO_DIR}/logs/git_operations.log"
    # Optionally, you can perform additional error handling here, such as retrying the operation.
else
    echo "$(date): Successfully updated code from Git repository" >> "${REPO_DIR}/logs/git_operations.log"
fi
