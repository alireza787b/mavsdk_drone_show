#!/bin/bash

# Render and install the coordinator systemd unit from the checked-in template.
# This keeps the legacy helper safe for both default and custom runtime paths.

set -euo pipefail

MDS_USER="${MDS_USER:-droneshow}"
MDS_HOME="${MDS_HOME:-$(eval echo "~${MDS_USER}")}"
MDS_INSTALL_DIR="${MDS_INSTALL_DIR:-${MDS_HOME}/mavsdk_drone_show}"
SYSTEMD_DIR="${MDS_SYSTEMD_DIR:-/etc/systemd/system}"
SERVICE_NAME="${MDS_COORDINATOR_SERVICE_NAME:-coordinator.service}"
SERVICE_TEMPLATE="${MDS_INSTALL_DIR}/tools/coordinator.service"
SERVICE_PATH="${SYSTEMD_DIR}/${SERVICE_NAME}"
BACKUP_PATH="${SERVICE_PATH}.bak"

if [[ ! -f "${SERVICE_TEMPLATE}" ]]; then
    echo "Coordinator service template not found: ${SERVICE_TEMPLATE}" >&2
    exit 1
fi

tmp_rendered="$(mktemp)"
cleanup() {
    rm -f "${tmp_rendered}"
}
trap cleanup EXIT

sed \
    -e "s|__MDS_USER__|${MDS_USER}|g" \
    -e "s|__MDS_HOME__|${MDS_HOME}|g" \
    -e "s|__MDS_INSTALL_DIR__|${MDS_INSTALL_DIR}|g" \
    "${SERVICE_TEMPLATE}" > "${tmp_rendered}"

current_checksum="$(md5sum "${SERVICE_PATH}" 2>/dev/null | awk '{ print $1 }' || true)"
new_checksum="$(md5sum "${tmp_rendered}" | awk '{ print $1 }')"

if [[ "${current_checksum}" == "${new_checksum}" ]]; then
    echo "Coordinator service file is already up-to-date. No action needed."
    exit 0
fi

echo "Detected a difference in the coordinator service file. Updating..."

if [[ -f "${SERVICE_PATH}" ]]; then
    echo "Backing up current service file..."
    sudo cp "${SERVICE_PATH}" "${BACKUP_PATH}"
fi

echo "Installing rendered coordinator service..."
sudo cp "${tmp_rendered}" "${SERVICE_PATH}"
sudo chmod 644 "${SERVICE_PATH}"

echo "Reloading systemd..."
sudo systemctl daemon-reload

echo "Restarting the coordinator service..."
sudo systemctl restart "${SERVICE_NAME}"

echo "Coordinator service update process completed."
