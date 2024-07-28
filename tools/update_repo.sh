#!/bin/bash

# update_repo.sh
# Script to ensure the drone's software repository is up-to-date before operations.
# This script handles the Git operations needed to synchronize the local codebase
# with the remote repository. It checks out the specified branch, resets any local
# changes, and pulls the latest updates from the remote branch.
#
# Usage:
# This script is intended to be run automatically by the system service that
# starts the drone's operation software, ensuring all components are up-to-date.
# It can also be run manually for troubleshooting or manual updates.
#
# Configuration:
# - GIT_URL: URL to the Git repository.
# - BRANCH_NAME: The branch to which the repository should be set.
#
# Logging:
# The script logs all operations and their outcomes to a log file to aid in debugging
# and operational monitoring.

# Configuration variables
GIT_URL="git@github.com:alireza787b/mavsdk_drone_show.git"  # Repository URL
BRANCH_NAME="real-test-1"  # Branch to synchronize with

# Navigate to the project directory
cd /home/droneshow/mavsdk_drone_show || exit

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
    echo "$(date): Failed to update code from Git repository" >> /home/droneshow/mavsdk_drone_show/logs/git_operations.log
    # Optionally, you can perform additional error handling here, such as retrying the operation.
else
    echo "$(date): Successfully updated code from Git repository" >> /home/droneshow/mavsdk_drone_show/logs/git_operations.log
fi
