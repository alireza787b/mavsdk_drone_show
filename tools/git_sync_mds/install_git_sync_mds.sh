#!/bin/bash
# Install Git Sync (MDS) Service
#
# Installs the git_sync_mds systemd service, substituting the correct
# user and home directory. Supports both default (droneshow) and custom users.

set -euo pipefail

echo "-----------------------------------------"
echo "Installing Git Sync (MDS) Service"
echo "-----------------------------------------"

# Ensure the script is run as root
if [[ $EUID -ne 0 ]]; then
    echo "Error: This script must be run as root!" 1>&2
    exit 1
fi

# Determine the MDS user/install paths (defaults remain backward compatible)
MDS_USER="${1:-${MDS_USER:-droneshow}}"
MDS_HOME="${MDS_HOME:-$(eval echo "~${MDS_USER}")}"
MDS_INSTALL_DIR="${MDS_INSTALL_DIR:-${MDS_HOME}/mavsdk_drone_show}"
MDS_SYSTEMD_DIR="${MDS_SYSTEMD_DIR:-/etc/systemd/system}"

echo "MDS User: ${MDS_USER}"
echo "MDS Home: ${MDS_HOME}"
echo "MDS Install Dir: ${MDS_INSTALL_DIR}"

# Define paths
GIT_SYNC_SCRIPT="${MDS_INSTALL_DIR}/tools/update_repo_ssh.sh"
SERVICE_FILE="${MDS_SYSTEMD_DIR}/git_sync_mds.service"
SOURCE_TEMPLATE="${MDS_INSTALL_DIR}/tools/git_sync_mds/git_sync_mds.service"

# Step 1: Check if the Git sync script exists
if [ ! -f "$GIT_SYNC_SCRIPT" ]; then
    echo "Error: Git sync script not found at $GIT_SYNC_SCRIPT!" 1>&2
    exit 1
else
    echo "Git sync script found. Proceeding..."
fi

# Step 2: Check the service template exists
if [ ! -f "$SOURCE_TEMPLATE" ]; then
    echo "Error: Service template not found at $SOURCE_TEMPLATE!" 1>&2
    exit 1
fi

# Step 3: Install service file with user/home substitution
echo "Installing service file with user=${MDS_USER}, home=${MDS_HOME}..."
mkdir -p "$MDS_SYSTEMD_DIR"
sed -e "s|__MDS_USER__|${MDS_USER}|g" \
    -e "s|__MDS_HOME__|${MDS_HOME}|g" \
    -e "s|__MDS_INSTALL_DIR__|${MDS_INSTALL_DIR}|g" \
    "$SOURCE_TEMPLATE" > "$SERVICE_FILE"

# Reload systemd daemon to register the new service
echo "Reloading systemd daemon..."
systemctl daemon-reload

# Enable the Git Sync service to run on boot
echo "Enabling Git Sync service to run on boot..."
systemctl enable git_sync_mds.service

# Restart the Git Sync service immediately so reruns refresh the live sync state
echo "Restarting Git Sync service..."
systemctl restart git_sync_mds.service

# Check the status of the service
echo "Checking the status of the Git Sync service..."
systemctl status git_sync_mds.service --no-pager

echo "-----------------------------------------"
echo "Git Sync (MDS) Service installation complete!"
echo "-----------------------------------------"
