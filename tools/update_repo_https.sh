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
#
# Logging:
# The script logs all operations and their outcomes to a log file to aid in debugging
# and operational monitoring.

# Configuration variables
#!/bin/bash

# update_repo_https.sh
# Ensure the drone's software repository is up-to-date before operations.
# Adjust the REPO_DIR variable to match the directory where your repository is located.

REPO_DIR="${HOME}/mavsdk_drone_show"
BRANCH_NAME="real-test-1"
GIT_URL="https://github.com/alireza787b/mavsdk_drone_show.git"
LOG_FILE="${REPO_DIR}/update_repo.log"

# Ensure the repository directory exists
if [ ! -d "$REPO_DIR" ]; then
    echo "Repository directory does not exist: $REPO_DIR" | tee -a "$LOG_FILE"
    exit 1
fi

# Navigate to the project directory
cd "$REPO_DIR" || { echo "Failed to navigate to $REPO_DIR"; exit 1; }

# Stash any local changes to avoid conflicts
if ! git stash; then
    echo "Failed to stash local changes" | tee -a "$LOG_FILE"
    exit 1
fi

# Fetch the latest updates from the remote repository
if ! git fetch --all; then
    echo "Failed to fetch updates from $GIT_URL" | tee -a "$LOG_FILE"
    exit 1
fi

# Checkout the specified branch
if ! git checkout "$BRANCH_NAME"; then
    echo "Failed to checkout branch $BRANCH_NAME" | tee -a "$LOG_FILE"
    exit 1
fi

# Reset local changes and ensure the branch is synced with the remote
if ! git reset --hard "origin/$BRANCH_NAME"; then
    echo "Failed to reset the branch $BRANCH_NAME" | tee -a "$LOG_FILE"
    exit 1
fi

# Pull the latest updates
if ! git pull; then
    echo "Failed to pull the latest updates from $BRANCH_NAME" | tee -a "$LOG_FILE"
    exit 1
else
    echo "$(date): Successfully updated code from $GIT_URL on branch $BRANCH_NAME" | tee -a "$LOG_FILE"
fi

# Apply stashed changes if needed
if ! git stash pop; then
    echo "No stashed changes to apply or failed to apply stashed changes." | tee -a "$LOG_FILE"
fi
