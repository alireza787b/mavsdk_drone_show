#!/bin/bash
# =============================================================================
# MAVLink Router for SITL
# =============================================================================
# Runs mavlink-routerd with fixed endpoints for SITL containers.
#
# This script is called by startup_sitl.sh to provide MAVLink routing
# inside Docker containers. For real hardware, use mavlink-anywhere
# as a systemd service instead.
#
# Input: PX4 SITL UDP (default: 0.0.0.0:14550)
# Outputs:
#   - 127.0.0.1:14569 (mavlink2rest)
#   - 127.0.0.1:12550 (LocalMavlinkController - pymavlink telemetry)
#   - GCS_IP:24550 (Remote Ground Control Station)
#
# Note: MAVSDK connects directly to PX4 on port 14540 (no routing needed)
#
# Environment Variables:
#   GCS_IP - IP address of GCS (required for MAVLink stream to GCS)
#            Default: 172.18.0.1 (Docker host gateway)
#
# Usage:
#   ./run_mavlink_router.sh [PX4_SITL_PORT]
#
# Examples:
#   ./run_mavlink_router.sh           # Uses default port 14550
#   ./run_mavlink_router.sh 14570     # Custom PX4 SITL port
#
# Author: Alireza Ghaderi
# =============================================================================

set -e

# Fixed output ports (no +hwid offsets - external routing uses fixed ports)
# Note: MAVSDK connects directly to PX4:14540, no routing needed
MAVLINK2REST_PORT=14569
LOCAL_MAVLINK_PORT=12550
REMOTE_GCS_MAVLINK_PORT=24550

# Default PX4 SITL input port (PX4 SITL streams to 14550 for GCS)
DEFAULT_PX4_PORT=14550

# Parse arguments
PX4_PORT="${1:-$DEFAULT_PX4_PORT}"

# GCS IP from environment or default to Docker gateway
GCS_IP="${GCS_IP:-172.18.0.1}"

# =============================================================================
# Functions
# =============================================================================

check_mavlink_routerd_installed() {
    if command -v mavlink-routerd &> /dev/null; then
        echo "[OK] mavlink-routerd is installed"
        return 0
    else
        echo "[ERROR] mavlink-routerd is not installed!"
        echo ""
        echo "To install mavlink-router:"
        echo "  cd ~/mavlink-anywhere"
        echo "  sudo ./install_mavlink_router.sh"
        echo ""
        echo "Or clone first:"
        echo "  git clone https://github.com/alireza787b/mavlink-anywhere.git ~/mavlink-anywhere"
        exit 1
    fi
}

print_config() {
    echo "============================================================"
    echo "  MAVLink Router for SITL"
    echo "============================================================"
    echo "  Input:   0.0.0.0:${PX4_PORT} (PX4 SITL UDP)"
    echo "  Output:  127.0.0.1:${MAVLINK2REST_PORT} (mavlink2rest)"
    echo "  Output:  127.0.0.1:${LOCAL_MAVLINK_PORT} (LocalMavlinkController)"
    echo "  Output:  ${GCS_IP}:${REMOTE_GCS_MAVLINK_PORT} (Remote GCS)"
    echo "  Note:    MAVSDK connects directly to PX4:14540"
    echo "============================================================"
}

run_mavlink_router() {
    mavlink-routerd \
        -e 127.0.0.1:${MAVLINK2REST_PORT} \
        -e 127.0.0.1:${LOCAL_MAVLINK_PORT} \
        -e ${GCS_IP}:${REMOTE_GCS_MAVLINK_PORT} \
        0.0.0.0:${PX4_PORT}
}

# =============================================================================
# Main
# =============================================================================

echo "Starting MAVLink router for SITL..."

check_mavlink_routerd_installed
print_config

echo ""
echo "Starting mavlink-routerd..."
run_mavlink_router
