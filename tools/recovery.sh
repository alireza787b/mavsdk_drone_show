#!/bin/bash
#
# MDS Recovery Tool - Diagnose and fix drone issues
#
# Usage:
#   ./recovery.sh status      - Show status of all MDS services
#   ./recovery.sh logs        - Show recent logs from all services
#   ./recovery.sh restart     - Restart the coordinator service
#   ./recovery.sh force-sync  - Force a git sync
#   ./recovery.sh reset-net   - Reset network failure counter
#   ./recovery.sh led-test    - Test LED colors
#   ./recovery.sh health      - Full health check
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
LED_CMD="$REPO_DIR/venv/bin/python $REPO_DIR/led_indicator.py"
# Droneshow user home for cleanup operations
DRONESHOW_HOME="/home/droneshow"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

print_header() {
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}  MDS Recovery Tool${NC}"
    echo -e "${CYAN}========================================${NC}"
}

show_status() {
    print_header
    echo ""
    echo "Service Status:"
    echo "---------------"

    local services=("led_indicator" "wifi-manager" "git_sync_mds" "mavlink-router" "coordinator")

    for svc in "${services[@]}"; do
        if systemctl is-active --quiet "$svc" 2>/dev/null; then
            echo -e "  [$svc] ${GREEN}RUNNING${NC}"
        elif systemctl is-enabled --quiet "$svc" 2>/dev/null; then
            echo -e "  [$svc] ${YELLOW}STOPPED (enabled)${NC}"
        else
            echo -e "  [$svc] ${RED}NOT INSTALLED${NC}"
        fi
    done

    echo ""
    echo "System Info:"
    echo "------------"
    echo "  Hostname: $(hostname)"
    echo "  Uptime: $(uptime -p)"
    echo "  Memory: $(free -h | awk '/^Mem:/ {print $3 "/" $2}')"
    echo "  Disk: $(df -h / | awk 'NR==2 {print $3 "/" $2 " (" $5 " used)"}')"

    # Check for local config
    if [[ -f /etc/mds/local.env ]]; then
        echo ""
        echo "Local Config (/etc/mds/local.env):"
        echo "----------------------------------"
        grep -v '^#' /etc/mds/local.env | grep -v '^$' | head -5
    fi
}

show_logs() {
    print_header
    echo ""
    echo "Recent logs (last hour):"
    echo "------------------------"
    journalctl -u coordinator -u git_sync_mds -u wifi-manager --since "1 hour ago" --no-pager -n 50
}

restart_coordinator() {
    print_header
    echo ""
    echo "Restarting coordinator service..."
    sudo systemctl restart coordinator
    sleep 2
    if systemctl is-active --quiet coordinator; then
        echo -e "${GREEN}Coordinator restarted successfully${NC}"
    else
        echo -e "${RED}Coordinator failed to start${NC}"
        journalctl -u coordinator --since "1 minute ago" --no-pager
    fi
}

force_sync() {
    print_header
    echo ""
    echo "Forcing git sync..."
    sudo systemctl restart git_sync_mds
    echo "Waiting for sync to complete (max 60s)..."

    local count=0
    while systemctl is-active --quiet git_sync_mds && [[ $count -lt 60 ]]; do
        sleep 1
        count=$((count + 1))
        echo -n "."
    done
    echo ""

    if systemctl is-failed --quiet git_sync_mds; then
        echo -e "${RED}Git sync failed${NC}"
        journalctl -u git_sync_mds --since "2 minutes ago" --no-pager
    else
        echo -e "${GREEN}Git sync completed${NC}"
    fi
}

reset_network() {
    print_header
    echo ""
    echo "Resetting network failure counter..."
    # Use explicit path for droneshow user (not current user's home)
    rm -f "$DRONESHOW_HOME/.mds/network_failures"
    echo "Restarting wifi-manager..."
    sudo systemctl restart wifi-manager
    echo -e "${GREEN}Network reset complete${NC}"
}

test_led() {
    print_header
    echo ""
    echo "Testing LED colors..."

    # Comprehensive LED state test covering all major operational states
    local states=(
        "BOOT_STARTED"           # Red - boot
        "NETWORK_INIT"           # Blue pulse - network
        "NETWORK_READY"          # Blue solid
        "GIT_SYNCING"            # Cyan pulse - sync
        "GIT_SUCCESS"            # Green flash
        "GIT_FAILED_CONTINUING"  # Yellow solid
        "SERVICES_UPDATING"      # Orange pulse
        "STARTUP_COMPLETE"       # White flash
        "IDLE_CONNECTED"         # Green solid - ready
        "IDLE_DISCONNECTED"      # Purple solid - offline
        "MISSION_ARMED"          # Orange solid - armed
        "MISSION_ACTIVE"         # Cyan pulse - executing
        "ERROR_RECOVERABLE"      # Red slow blink
        "ERROR_CRITICAL"         # Red fast blink
    )

    for state in "${states[@]}"; do
        echo "  Testing: $state"
        $LED_CMD --state "$state" 2>/dev/null || echo "    (LED unavailable)"
        sleep 1
    done

    echo ""
    echo "Setting LED to IDLE_CONNECTED (green)..."
    $LED_CMD --state "IDLE_CONNECTED" 2>/dev/null || true
    echo -e "${GREEN}LED test complete${NC}"
}

health_check() {
    print_header
    echo ""
    echo "Running full health check..."
    echo ""

    local issues=0

    # Check services
    echo "1. Service Status:"
    for svc in coordinator git_sync_mds wifi-manager; do
        if ! systemctl is-active --quiet "$svc" 2>/dev/null; then
            echo -e "   ${RED}[FAIL]${NC} $svc not running"
            issues=$((issues + 1))
        else
            echo -e "   ${GREEN}[OK]${NC}   $svc running"
        fi
    done

    # Check git repo
    echo ""
    echo "2. Git Repository:"
    if git -C "$REPO_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        cd "$REPO_DIR"
        local branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
        local commit=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
        echo -e "   ${GREEN}[OK]${NC}   Branch: $branch, Commit: $commit"
    else
        echo -e "   ${RED}[FAIL]${NC} Not a git repository"
        issues=$((issues + 1))
    fi

    # Check config files
    echo ""
    echo "3. Configuration:"
    if [[ -f "$REPO_DIR/config.json" ]]; then
        echo -e "   ${GREEN}[OK]${NC}   config.json exists"
    else
        echo -e "   ${YELLOW}[WARN]${NC} config.json missing"
    fi

    if [[ -f /etc/mds/local.env ]]; then
        echo -e "   ${GREEN}[OK]${NC}   /etc/mds/local.env exists"
    else
        echo -e "   ${YELLOW}[WARN]${NC} /etc/mds/local.env missing (using defaults)"
    fi

    # Check venv
    echo ""
    echo "4. Python Environment:"
    if [[ -x "$REPO_DIR/venv/bin/python" ]]; then
        echo -e "   ${GREEN}[OK]${NC}   venv/bin/python exists"
    else
        echo -e "   ${RED}[FAIL]${NC} venv not found or broken"
        issues=$((issues + 1))
    fi

    # Summary
    echo ""
    echo "=========================================="
    if [[ $issues -eq 0 ]]; then
        echo -e "${GREEN}Health check passed - no issues found${NC}"
    else
        echo -e "${RED}Health check found $issues issue(s)${NC}"
    fi
}

show_help() {
    print_header
    echo ""
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  status      Show status of all MDS services"
    echo "  logs        Show recent logs from all services"
    echo "  restart     Restart the coordinator service"
    echo "  force-sync  Force a git sync"
    echo "  reset-net   Reset network failure counter"
    echo "  led-test    Test LED colors"
    echo "  health      Full health check"
    echo "  help        Show this help message"
    echo ""
}

# Main
case "${1:-help}" in
    status)
        show_status
        ;;
    logs)
        show_logs
        ;;
    restart)
        restart_coordinator
        ;;
    force-sync)
        force_sync
        ;;
    reset-net|reset-network)
        reset_network
        ;;
    led-test|led)
        test_led
        ;;
    health)
        health_check
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        echo "Unknown command: $1"
        show_help
        exit 1
        ;;
esac
