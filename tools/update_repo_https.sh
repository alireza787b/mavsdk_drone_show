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

# update_repo_https.sh
# Script to update the software repository.

set -euo pipefail

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
cd "$REPO_DIR"

# Check network connectivity
if ! ping -c 1 github.com >/dev/null 2>&1; then
    echo "No network connectivity. Cannot update repository." | tee -a "$LOG_FILE"
    exit 1
fi

# Fetch the latest updates
git fetch --all

# Checkout the specified branch
git checkout "$BRANCH_NAME"

# Pull the latest updates
git pull --rebase

echo "$(date): Successfully updated code from $GIT_URL on branch $BRANCH_NAME" | tee -a "$LOG_FILE"
