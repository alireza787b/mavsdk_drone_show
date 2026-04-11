#!/bin/bash
# =============================================================================
# MDS Initialization Library: MAVLink Router Setup
# =============================================================================
# Version: 4.5.0
# Description: Automated mavlink-anywhere installation and configuration
# Author: MDS Team
# =============================================================================
#
# This module handles MAVLink router setup with multiple modes:
#   - Auto: Full automation with auto-detection
#   - Interactive: Step-by-step guided setup
#   - Manual: Display instructions only (legacy behavior)
#   - Skip: Bypass MAVLink setup entirely
#
# Supports:
#   - Serial UART input (GPIO connection to flight controller)
#   - USB Serial input (USB-to-serial adapters)
#   - UDP Network input (for SITL/simulation)
#
# =============================================================================

# Prevent double-sourcing
[[ -n "${_MDS_MAVLINK_SETUP_LOADED:-}" ]] && return 0
_MDS_MAVLINK_SETUP_LOADED=1

# =============================================================================
# CONFIGURATION CONSTANTS
# =============================================================================

readonly MAVLINK_ANYWHERE_REPO="https://github.com/alireza787b/mavlink-anywhere.git"
readonly MAVLINK_ANYWHERE_DIR="/opt/mavlink-anywhere"
readonly MAVLINK_ROUTER_CONFIG="/etc/mavlink-router/main.conf"
readonly MAVLINK_ROUTER_SERVICE="mavlink-router"

# Default endpoints for MDS
readonly MDS_DEFAULT_ENDPOINTS="127.0.0.1:14540,127.0.0.1:14569,127.0.0.1:12550"

# =============================================================================
# MAVLINK SETUP GLOBAL VARIABLES
# =============================================================================

# These can be set via CLI arguments to mds_node_init.sh
MAVLINK_AUTO="${MAVLINK_AUTO:-false}"
MAVLINK_SKIP="${MAVLINK_SKIP:-false}"
MAVLINK_UART="${MAVLINK_UART:-}"
MAVLINK_BAUD="${MAVLINK_BAUD:-57600}"
MAVLINK_ENDPOINTS="${MAVLINK_ENDPOINTS:-}"
MAVLINK_INPUT_TYPE="${MAVLINK_INPUT_TYPE:-uart}"
MAVLINK_INPUT_PORT="${MAVLINK_INPUT_PORT:-14550}"

# =============================================================================
# MAVLINK-ROUTER STATUS CHECKS
# =============================================================================

# Check if mavlink-router is installed
check_mavlink_router_installed() {
    if command_exists mavlink-routerd; then
        return 0
    fi

    if [[ -x /usr/bin/mavlink-routerd ]] || [[ -x /usr/local/bin/mavlink-routerd ]]; then
        return 0
    fi

    if systemctl list-unit-files 2>/dev/null | grep -q "mavlink-router.service"; then
        return 0
    fi

    return 1
}

# Check if mavlink-router service is running
check_mavlink_router_running() {
    service_is_active "mavlink-router"
}

# Check if mavlink-router is configured
check_mavlink_router_configured() {
    [[ -f "$MAVLINK_ROUTER_CONFIG" ]]
}

# Get mavlink-router version
get_mavlink_router_version() {
    if command_exists mavlink-routerd; then
        mavlink-routerd --version 2>&1 | head -1 || echo "unknown"
    else
        echo "not installed"
    fi
}

# =============================================================================
# SERIAL PORT DETECTION (RPi-aware)
# =============================================================================

# Detect board type
detect_board_type() {
    if [[ -f /proc/device-tree/model ]]; then
        local model
        model=$(cat /proc/device-tree/model 2>/dev/null | tr -d '\0')

        if echo "$model" | grep -qi "raspberry"; then
            echo "raspberry_pi"
            return
        elif echo "$model" | grep -qi "jetson"; then
            echo "jetson"
            return
        fi
    fi

    if [[ -f /etc/rpi-issue ]] || [[ -d /opt/vc ]]; then
        echo "raspberry_pi"
        return
    fi

    echo "generic_linux"
}

# Detect Raspberry Pi model
detect_rpi_model() {
    if [[ ! -f /proc/device-tree/model ]]; then
        echo "not_pi"
        return
    fi

    local model
    model=$(cat /proc/device-tree/model 2>/dev/null | tr -d '\0')

    if echo "$model" | grep -qi "raspberry pi 5"; then
        echo "pi5"
    elif echo "$model" | grep -qi "raspberry pi 4"; then
        echo "pi4"
    elif echo "$model" | grep -qi "raspberry pi 3"; then
        echo "pi3"
    elif echo "$model" | grep -qi "zero 2"; then
        echo "pizero2"
    elif echo "$model" | grep -qi "zero"; then
        echo "pizero"
    else
        echo "pi_other"
    fi
}

# Auto-detect UART device
detect_uart_device() {
    # Priority 1: /dev/serial0 symlink
    if [[ -e /dev/serial0 ]]; then
        readlink -f /dev/serial0
        return 0
    fi

    # Priority 2: Board-specific
    local rpi_model
    rpi_model=$(detect_rpi_model)

    case "$rpi_model" in
        pi5)
            [[ -e /dev/ttyAMA0 ]] && echo "/dev/ttyAMA0" && return 0
            ;;
        pi4|pizero2)
            [[ -e /dev/ttyAMA0 ]] && echo "/dev/ttyAMA0" && return 0
            [[ -e /dev/ttyS0 ]] && echo "/dev/ttyS0" && return 0
            ;;
        pi3|pizero|pi_other)
            [[ -e /dev/ttyS0 ]] && echo "/dev/ttyS0" && return 0
            ;;
    esac

    # Priority 3: Common devices
    for device in /dev/ttyS0 /dev/ttyAMA0 /dev/ttyUSB0 /dev/ttyACM0; do
        [[ -e "$device" ]] && echo "$device" && return 0
    done

    # Fallback
    echo "/dev/ttyS0"
    return 1
}

# Detect USB serial devices
detect_usb_serial() {
    local devices=()
    for device in /dev/ttyUSB* /dev/ttyACM*; do
        [[ -e "$device" ]] && devices+=("$device")
    done
    printf '%s\n' "${devices[@]}"
}

# Check if serial console is enabled (blocking UART)
check_serial_console_enabled() {
    local cmdline_file="/boot/cmdline.txt"
    [[ -f /boot/firmware/cmdline.txt ]] && cmdline_file="/boot/firmware/cmdline.txt"

    if [[ -f "$cmdline_file" ]]; then
        grep -qE "console=(serial0|ttyAMA0|ttyS0)" "$cmdline_file" && return 0
    fi

    return 1
}

# Check if UART is enabled in boot config
check_uart_enabled() {
    local config_file="/boot/config.txt"
    [[ -f /boot/firmware/config.txt ]] && config_file="/boot/firmware/config.txt"

    if [[ -f "$config_file" ]]; then
        grep -qE "^enable_uart=1" "$config_file" && return 0
    fi

    # UART might be enabled by default
    [[ -e /dev/serial0 ]] || [[ -e /dev/ttyS0 ]] || [[ -e /dev/ttyAMA0 ]]
}

# Check if current user is in dialout group
check_dialout_group() {
    groups 2>/dev/null | grep -q '\bdialout\b'
}

# =============================================================================
# SERIAL CONFIGURATION FIXES (Raspberry Pi)
# =============================================================================

# Get boot config file path
get_boot_config_path() {
    if [[ -f /boot/firmware/config.txt ]]; then
        echo "/boot/firmware/config.txt"
    else
        echo "/boot/config.txt"
    fi
}

# Get cmdline file path
get_cmdline_path() {
    if [[ -f /boot/firmware/cmdline.txt ]]; then
        echo "/boot/firmware/cmdline.txt"
    else
        echo "/boot/cmdline.txt"
    fi
}

# Backup boot configuration files
backup_boot_config() {
    local config_file cmdline_file timestamp
    config_file=$(get_boot_config_path)
    cmdline_file=$(get_cmdline_path)
    timestamp=$(date +%Y%m%d_%H%M%S)

    if [[ -f "$config_file" ]]; then
        cp "$config_file" "${config_file}.mds_backup.${timestamp}"
        log_debug "Backed up: $config_file"
    fi

    if [[ -f "$cmdline_file" ]]; then
        cp "$cmdline_file" "${cmdline_file}.mds_backup.${timestamp}"
        log_debug "Backed up: $cmdline_file"
    fi
}

# Fix boot config for UART
fix_boot_config() {
    local config_file
    config_file=$(get_boot_config_path)

    if [[ ! -f "$config_file" ]]; then
        log_warn "Boot config not found: $config_file"
        return 1
    fi

    # Add enable_uart=1 if not present
    if ! grep -qE "^enable_uart=" "$config_file"; then
        echo "enable_uart=1" >> "$config_file"
        log_info "Added enable_uart=1 to $config_file"
    elif ! grep -qE "^enable_uart=1" "$config_file"; then
        sed -i 's/^enable_uart=.*/enable_uart=1/' "$config_file"
        log_info "Set enable_uart=1 in $config_file"
    fi

    return 0
}

# Fix cmdline.txt to remove serial console
fix_cmdline() {
    local cmdline_file
    cmdline_file=$(get_cmdline_path)

    if [[ ! -f "$cmdline_file" ]]; then
        log_warn "Cmdline file not found: $cmdline_file"
        return 1
    fi

    # Remove console=serial0,* and console=ttyAMA0,* and console=ttyS0,*
    if grep -qE "console=(serial0|ttyAMA0|ttyS0)" "$cmdline_file"; then
        sed -i 's/console=serial0,[0-9]* //g' "$cmdline_file"
        sed -i 's/console=ttyAMA0,[0-9]* //g' "$cmdline_file"
        sed -i 's/console=ttyS0,[0-9]* //g' "$cmdline_file"
        log_info "Removed serial console from $cmdline_file"
    fi

    return 0
}

# Auto-fix UART configuration
auto_fix_uart_config() {
    local board_type
    board_type=$(detect_board_type)

    if [[ "$board_type" != "raspberry_pi" ]]; then
        log_warn "Auto-fix only supported on Raspberry Pi"
        return 1
    fi

    # Backup first
    backup_boot_config

    # Fix config.txt
    fix_boot_config

    # Fix cmdline.txt
    fix_cmdline

    # Save state for resume after reboot
    state_set_value "uart_fixed" "true"
    state_set_value "pending_reboot" "true"
    state_set_phase "mavlink_setup" "pending_reboot"

    return 0
}

# =============================================================================
# MAVLINK-ANYWHERE INSTALLATION
# =============================================================================

# Clone or update mavlink-anywhere repository
clone_mavlink_anywhere() {
    if [[ -d "$MAVLINK_ANYWHERE_DIR" ]]; then
        log_step "Updating mavlink-anywhere..."
        if is_dry_run; then
            log_info "[DRY-RUN] Would update mavlink-anywhere"
            return 0
        fi

        cd "$MAVLINK_ANYWHERE_DIR"
        git fetch origin
        git reset --hard origin/main || git reset --hard origin/master
        cd - > /dev/null
    else
        log_step "Cloning mavlink-anywhere..."
        if is_dry_run; then
            log_info "[DRY-RUN] Would clone mavlink-anywhere"
            return 0
        fi

        git clone "$MAVLINK_ANYWHERE_REPO" "$MAVLINK_ANYWHERE_DIR"
    fi

    return 0
}

# Run mavlink-router installation
run_mavlink_install() {
    log_step "Installing mavlink-router (this may take several minutes)..."

    if is_dry_run; then
        log_info "[DRY-RUN] Would run install_mavlink_router.sh"
        return 0
    fi

    if [[ ! -x "${MAVLINK_ANYWHERE_DIR}/install_mavlink_router.sh" ]]; then
        chmod +x "${MAVLINK_ANYWHERE_DIR}/install_mavlink_router.sh"
    fi

    cd "$MAVLINK_ANYWHERE_DIR"
    ./install_mavlink_router.sh
    local result=$?
    cd - > /dev/null

    return $result
}

# Run mavlink-router configuration (headless)
run_mavlink_configure_headless() {
    local uart_device="$1"
    local baud_rate="$2"
    local endpoints="$3"
    local input_type="${4:-uart}"
    local input_port="${5:-14550}"

    log_step "Configuring mavlink-router..."

    if is_dry_run; then
        log_info "[DRY-RUN] Would configure mavlink-router:"
        log_info "  UART: $uart_device"
        log_info "  Baud: $baud_rate"
        log_info "  Endpoints: $endpoints"
        return 0
    fi

    if [[ ! -x "${MAVLINK_ANYWHERE_DIR}/configure_mavlink_router.sh" ]]; then
        chmod +x "${MAVLINK_ANYWHERE_DIR}/configure_mavlink_router.sh"
    fi

    cd "$MAVLINK_ANYWHERE_DIR"

    if [[ "$input_type" == "udp" ]]; then
        ./configure_mavlink_router.sh --headless \
            --input-type udp \
            --input-port "$input_port" \
            --endpoints "$endpoints"
    else
        ./configure_mavlink_router.sh --headless \
            --uart "$uart_device" \
            --baud "$baud_rate" \
            --endpoints "$endpoints"
    fi

    local result=$?
    cd - > /dev/null

    return $result
}

# Verify mavlink-router service
verify_mavlink_service() {
    log_step "Verifying mavlink-router service..."

    if ! check_mavlink_router_running; then
        log_warn "mavlink-router service not running"
        log_info "Starting service..."
        systemctl start mavlink-router 2>/dev/null || true

        sleep 2

        if ! check_mavlink_router_running; then
            log_error "Failed to start mavlink-router service"
            return 1
        fi
    fi

    log_success "mavlink-router service is running"
    return 0
}

# =============================================================================
# DISPLAY FUNCTIONS
# =============================================================================

# Display current MAVLink router status
display_mavlink_status() {
    local installed running configured version uart_device

    # Check status
    if check_mavlink_router_installed; then
        installed="${GREEN}✓ Installed${NC}"
        version=$(get_mavlink_router_version)
    else
        installed="${RED}✗ Not found${NC}"
        version=""
    fi

    if check_mavlink_router_running; then
        running="${GREEN}● Running${NC}"
    elif check_mavlink_router_configured; then
        running="${YELLOW}○ Stopped${NC}"
    else
        running="${DIM}─ Not configured${NC}"
    fi

    if check_mavlink_router_configured; then
        configured="${GREEN}✓${NC} $MAVLINK_ROUTER_CONFIG"
    else
        configured="${YELLOW}○${NC} Not found"
    fi

    # Detect UART
    uart_device=$(detect_uart_device 2>/dev/null || echo "unknown")

    echo ""
    echo -e "${CYAN}┌────────────────────────────────────────────────────────────────────────────┐${NC}"
    echo -e "${CYAN}│${NC}  ${WHITE}MAVLink Router Status${NC}                                                    ${CYAN}│${NC}"
    echo -e "${CYAN}├────────────────────────────────────────────────────────────────────────────┤${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}  mavlink-router: $installed $(printf '%*s' $((40 - ${#version})) '') ${CYAN}│${NC}"
    [[ -n "$version" ]] && echo -e "${CYAN}│${NC}  Version:        ${DIM}$version${NC}$(printf '%*s' $((45 - ${#version})) '') ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}  Service status: $running                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}  Configuration:  $configured        ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}  UART device:    ${DIM}$uart_device${NC} (detected)$(printf '%*s' $((32 - ${#uart_device})) '') ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}└────────────────────────────────────────────────────────────────────────────┘${NC}"
    echo ""
}

# Display serial configuration status
display_serial_status() {
    local board_type board_desc uart_enabled serial_console uart_device dialout_ok

    board_type=$(detect_board_type)
    board_desc=$(is_raspberry_pi && echo "Raspberry Pi $(detect_rpi_model)" || echo "Generic Linux")

    uart_enabled=$(check_uart_enabled && echo "yes" || echo "no")
    serial_console=$(check_serial_console_enabled && echo "enabled" || echo "disabled")
    uart_device=$(detect_uart_device 2>/dev/null || echo "/dev/ttyS0")
    dialout_ok=$(check_dialout_group && echo "yes" || echo "no")

    echo ""
    echo -e "${CYAN}┌────────────────────────────────────────────────────────────────────────────┐${NC}"
    echo -e "${CYAN}│${NC}  ${WHITE}Serial Port Configuration${NC}                                                ${CYAN}│${NC}"
    echo -e "${CYAN}├────────────────────────────────────────────────────────────────────────────┤${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}  Hardware:                                                                 ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}    Board:           ${board_desc}$(printf '%*s' $((42 - ${#board_desc})) '') ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}    Architecture:    $(get_architecture)                                             ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}  Serial Status:                                                            ${CYAN}│${NC}"

    if [[ "$uart_enabled" == "yes" ]]; then
        echo -e "${CYAN}│${NC}    UART enabled:       ${GREEN}✓ Yes${NC}                                            ${CYAN}│${NC}"
    else
        echo -e "${CYAN}│${NC}    UART enabled:       ${RED}✗ No${NC}                                             ${CYAN}│${NC}"
    fi

    if [[ "$serial_console" == "disabled" ]]; then
        echo -e "${CYAN}│${NC}    Serial console:     ${GREEN}✗ Disabled (good)${NC}                                ${CYAN}│${NC}"
    else
        echo -e "${CYAN}│${NC}    Serial console:     ${YELLOW}⚠ ENABLED (blocking UART!)${NC}                       ${CYAN}│${NC}"
    fi

    if [[ -e "$uart_device" ]]; then
        echo -e "${CYAN}│${NC}    Device available:   ${GREEN}✓ $uart_device${NC}$(printf '%*s' $((36 - ${#uart_device})) '') ${CYAN}│${NC}"
    else
        echo -e "${CYAN}│${NC}    Device available:   ${RED}✗ $uart_device (not found)${NC}$(printf '%*s' $((23 - ${#uart_device})) '') ${CYAN}│${NC}"
    fi

    if [[ "$dialout_ok" == "yes" ]]; then
        echo -e "${CYAN}│${NC}    Permissions:        ${GREEN}✓ User in dialout group${NC}                          ${CYAN}│${NC}"
    else
        echo -e "${CYAN}│${NC}    Permissions:        ${YELLOW}⚠ User not in dialout group${NC}                      ${CYAN}│${NC}"
    fi

    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}└────────────────────────────────────────────────────────────────────────────┘${NC}"
    echo ""
}

# Display main menu
display_mavlink_menu() {
    echo ""
    echo -e "${CYAN}┌────────────────────────────────────────────────────────────────────────────┐${NC}"
    echo -e "${CYAN}│${NC}  ${WHITE}What would you like to do?${NC}                                               ${CYAN}│${NC}"
    echo -e "${CYAN}├────────────────────────────────────────────────────────────────────────────┤${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}    ${GREEN}[1]${NC} Auto-configure (Recommended)                                        ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}        - Installs mavlink-router if needed                                 ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}        - Auto-detects UART device                                          ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}        - Configures standard MDS endpoints                                 ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}        - Uses GCS IP from your configuration                               ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}    ${YELLOW}[2]${NC} Interactive configuration                                           ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}        - Step-by-step prompts for all settings                             ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}        - Recommended if you have custom requirements                       ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}    ${BLUE}[3]${NC} Manual setup (show instructions only)                                ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}        - Display setup guide                                               ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}        - You configure mavlink-anywhere yourself                           ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}    ${DIM}[4]${NC} Skip (mavlink-router already configured)                             ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}└────────────────────────────────────────────────────────────────────────────┘${NC}"
    echo ""
}

# Display input method selection
display_input_method_menu() {
    echo ""
    echo -e "${CYAN}┌────────────────────────────────────────────────────────────────────────────┐${NC}"
    echo -e "${CYAN}│${NC}  ${WHITE}MAVLink Input Source${NC}                                                     ${CYAN}│${NC}"
    echo -e "${CYAN}├────────────────────────────────────────────────────────────────────────────┤${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}  How is your flight controller connected?                                  ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}    ${GREEN}[1]${NC} Serial UART (Recommended for real hardware)                         ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}        - Direct GPIO connection to Pixhawk TELEM port                      ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}    ${YELLOW}[2]${NC} USB Serial                                                          ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}        - USB-to-serial adapter or direct USB connection                    ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}    ${BLUE}[3]${NC} UDP Network Input                                                   ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}        - For SITL simulation or network-bridged setups                     ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}    ${DIM}[4]${NC} Not connected yet (skip and configure later)                        ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}└────────────────────────────────────────────────────────────────────────────┘${NC}"
    echo ""
}

# Display manual setup instructions
display_mavlink_instructions() {
    local gcs_ip="${1:-\${GCS_IP\}}"

    echo ""
    echo -e "${CYAN}┌────────────────────────────────────────────────────────────────────────────┐${NC}"
    echo -e "${CYAN}│${NC}  ${WHITE}mavlink-anywhere Installation Steps${NC}                                       ${CYAN}│${NC}"
    echo -e "${CYAN}├────────────────────────────────────────────────────────────────────────────┤${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}  ${BOLD}1. Clone the repository:${NC}                                                 ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}     ${GREEN}git clone https://github.com/alireza787b/mavlink-anywhere.git${NC}         ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}  ${BOLD}2. Install mavlink-router:${NC}                                               ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}     ${GREEN}cd mavlink-anywhere${NC}                                                    ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}     ${GREEN}sudo ./install_mavlink_router.sh${NC}                                       ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}  ${BOLD}3. Configure mavlink-router:${NC}                                             ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}     ${GREEN}sudo ./configure_mavlink_router.sh${NC}                                     ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}     ${DIM}When prompted, enter:${NC}                                                  ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}     ${DIM}- UART Device: /dev/ttyS0 (or /dev/ttyAMA0 for RPi 5)${NC}                 ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}     ${DIM}- Baud Rate: 57600${NC}                                                     ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}     ${DIM}- UDP Endpoints:${NC}                                                       ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}       ${DIM}• 127.0.0.1:14540  (MAVSDK)${NC}                                          ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}       ${DIM}• 127.0.0.1:14569  (mavlink2rest)${NC}                                    ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}       ${DIM}• 127.0.0.1:12550  (Local telemetry)${NC}                                 ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}       ${DIM}• ${gcs_ip}:24550  (GCS over VPN)${NC}                                     ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}  ${BOLD}4. Verify installation:${NC}                                                  ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}     ${GREEN}sudo systemctl status mavlink-router${NC}                                   ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}└────────────────────────────────────────────────────────────────────────────┘${NC}"
    echo ""
}

# Display serial issue warning and options
display_serial_issue_options() {
    echo ""
    echo -e "${YELLOW}┌────────────────────────────────────────────────────────────────────────────┐${NC}"
    echo -e "${YELLOW}│${NC}  ${WHITE}⚠ Serial Configuration Required${NC}                                         ${YELLOW}│${NC}"
    echo -e "${YELLOW}├────────────────────────────────────────────────────────────────────────────┤${NC}"
    echo -e "${YELLOW}│${NC}                                                                            ${YELLOW}│${NC}"
    echo -e "${YELLOW}│${NC}  Issues found:                                                             ${YELLOW}│${NC}"

    if check_serial_console_enabled; then
        echo -e "${YELLOW}│${NC}    ${RED}•${NC} Serial console is enabled (blocking UART for MAVLink)                ${YELLOW}│${NC}"
    fi
    if ! check_uart_enabled; then
        echo -e "${YELLOW}│${NC}    ${RED}•${NC} UART hardware not enabled in boot config                             ${YELLOW}│${NC}"
    fi

    echo -e "${YELLOW}│${NC}                                                                            ${YELLOW}│${NC}"
    echo -e "${YELLOW}│${NC}  ${RED}⚠ REBOOT REQUIRED after fixing serial configuration${NC}                     ${YELLOW}│${NC}"
    echo -e "${YELLOW}│${NC}                                                                            ${YELLOW}│${NC}"
    echo -e "${YELLOW}│${NC}  What would you like to do?                                                ${YELLOW}│${NC}"
    echo -e "${YELLOW}│${NC}                                                                            ${YELLOW}│${NC}"
    echo -e "${YELLOW}│${NC}    ${GREEN}[1]${NC} Auto-fix configuration (Raspberry Pi only)                         ${YELLOW}│${NC}"
    echo -e "${YELLOW}│${NC}        - Modifies /boot/config.txt and /boot/cmdline.txt                   ${YELLOW}│${NC}"
    echo -e "${YELLOW}│${NC}        - Creates backup of original files                                  ${YELLOW}│${NC}"
    echo -e "${YELLOW}│${NC}        - Will prompt to reboot when done                                   ${YELLOW}│${NC}"
    echo -e "${YELLOW}│${NC}                                                                            ${YELLOW}│${NC}"
    echo -e "${YELLOW}│${NC}    ${BLUE}[2]${NC} Manual configuration (show instructions)                            ${YELLOW}│${NC}"
    echo -e "${YELLOW}│${NC}        - For custom boards or advanced users                               ${YELLOW}│${NC}"
    echo -e "${YELLOW}│${NC}        - Re-run this script after reboot                                   ${YELLOW}│${NC}"
    echo -e "${YELLOW}│${NC}                                                                            ${YELLOW}│${NC}"
    echo -e "${YELLOW}│${NC}    ${DIM}[3]${NC} Skip serial setup (use USB or UDP instead)                          ${YELLOW}│${NC}"
    echo -e "${YELLOW}│${NC}                                                                            ${YELLOW}│${NC}"
    echo -e "${YELLOW}└────────────────────────────────────────────────────────────────────────────┘${NC}"
    echo ""
}

# Display manual serial setup instructions
display_manual_serial_instructions() {
    echo ""
    echo -e "${CYAN}┌────────────────────────────────────────────────────────────────────────────┐${NC}"
    echo -e "${CYAN}│${NC}  ${WHITE}Manual Serial Configuration Instructions${NC}                                 ${CYAN}│${NC}"
    echo -e "${CYAN}├────────────────────────────────────────────────────────────────────────────┤${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}  ${BOLD}For Raspberry Pi:${NC}                                                        ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}    1. Run: ${GREEN}sudo raspi-config${NC}                                               ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}    2. Navigate to: Interface Options → Serial Port                         ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}    3. \"Login shell over serial?\" → ${GREEN}NO${NC}                                      ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}    4. \"Enable serial hardware?\" → ${GREEN}YES${NC}                                      ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}    5. Reboot: ${GREEN}sudo reboot${NC}                                                   ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}  ${BOLD}For Other Linux Boards:${NC}                                                   ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}    1. Ensure UART hardware is enabled in your board's config               ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}    2. Disable any serial console that may be using the port                ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}    3. Verify device exists: ${GREEN}ls -la /dev/ttyS* /dev/ttyAMA*${NC}                 ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}    4. Add user to dialout group: ${GREEN}sudo usermod -aG dialout \$USER${NC}            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}    5. Reboot to apply changes                                              ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}  ${BOLD}After reboot, re-run this script:${NC}                                        ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}    ${GREEN}sudo ./tools/mds_node_init.sh --resume${NC}                                       ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}└────────────────────────────────────────────────────────────────────────────┘${NC}"
    echo ""
}

# Display reboot prompt
display_reboot_prompt() {
    echo ""
    echo -e "${YELLOW}┌────────────────────────────────────────────────────────────────────────────┐${NC}"
    echo -e "${YELLOW}│${NC}  ${WHITE}Reboot Required${NC}                                                          ${YELLOW}│${NC}"
    echo -e "${YELLOW}├────────────────────────────────────────────────────────────────────────────┤${NC}"
    echo -e "${YELLOW}│${NC}                                                                            ${YELLOW}│${NC}"
    echo -e "${YELLOW}│${NC}  Serial configuration has been updated. A reboot is required for           ${YELLOW}│${NC}"
    echo -e "${YELLOW}│${NC}  the changes to take effect.                                               ${YELLOW}│${NC}"
    echo -e "${YELLOW}│${NC}                                                                            ${YELLOW}│${NC}"
    echo -e "${YELLOW}│${NC}  After reboot, re-run this script with:                                    ${YELLOW}│${NC}"
    echo -e "${YELLOW}│${NC}    ${GREEN}sudo ./tools/mds_node_init.sh --resume${NC}                                       ${YELLOW}│${NC}"
    echo -e "${YELLOW}│${NC}                                                                            ${YELLOW}│${NC}"
    echo -e "${YELLOW}└────────────────────────────────────────────────────────────────────────────┘${NC}"
    echo ""
}

# =============================================================================
# AUTO-CONFIGURATION LOGIC
# =============================================================================

# Run automatic MAVLink configuration
run_mavlink_auto_config() {
    local gcs_ip="${GCS_IP:-}"
    local uart_device baud_rate endpoints

    log_step "Starting auto-configuration..."

    if is_raspberry_pi; then
        if check_serial_console_enabled || ! check_uart_enabled; then
            log_info "Applying Raspberry Pi UART boot configuration fixes"
            auto_fix_uart_config || return 1
        fi
    fi

    # Step 1: Check/install mavlink-router
    if ! check_mavlink_router_installed; then
        log_info "mavlink-router not installed, installing..."
        clone_mavlink_anywhere || return 1
        run_mavlink_install || return 1
    else
        log_success "mavlink-router already installed"
    fi

    # Step 2: Auto-detect UART
    uart_device=$(detect_uart_device)
    log_info "Auto-detected UART device: $uart_device"

    # Step 3: Use default baud rate
    baud_rate="${MAVLINK_BAUD:-57600}"
    log_info "Using baud rate: $baud_rate"

    # Step 4: Build endpoints list
    endpoints="$MDS_DEFAULT_ENDPOINTS"
    if [[ -n "$gcs_ip" ]]; then
        endpoints="${endpoints},${gcs_ip}:24550"
        log_info "Added GCS endpoint: ${gcs_ip}:24550"
    fi

    # Step 5: Run configuration
    run_mavlink_configure_headless "$uart_device" "$baud_rate" "$endpoints" "uart" || return 1

    # Step 6: Verify service
    verify_mavlink_service || return 1

    log_success "Auto-configuration complete"
    return 0
}

# =============================================================================
# MAIN PHASE RUNNER
# =============================================================================

run_mavlink_setup_phase() {
    print_phase_header "2" "MAVLink Router Setup"

    set_led_state "NETWORK_INIT"

    # Check for pending reboot from previous run
    if [[ "$(state_get_value 'pending_reboot')" == "true" ]]; then
        log_info "Resuming after reboot..."
        state_set_value "pending_reboot" "false"
        # Continue with mavlink setup
    fi

    # Display current status
    display_mavlink_status

    # Check if already configured and running
    if check_mavlink_router_installed && check_mavlink_router_running; then
        log_success "mavlink-router is installed and running"

        if [[ "${NON_INTERACTIVE:-false}" != "true" ]]; then
            if confirm "mavlink-router appears configured. Skip setup?" "y"; then
                return 0
            fi
        else
            # In non-interactive mode, skip if already configured
            if [[ "${MAVLINK_AUTO:-false}" != "true" ]]; then
                log_info "Using existing mavlink-router configuration"
                return 0
            fi
        fi
    fi

    # Handle CLI-specified options
    if [[ "${MAVLINK_SKIP:-false}" == "true" ]]; then
        log_info "Skipping mavlink-router setup (--mavlink-skip)"
        return 0
    fi

    if [[ "${MAVLINK_AUTO:-false}" == "true" ]]; then
        log_info "Running auto-configuration (--mavlink-auto)"
        run_mavlink_auto_config
        return $?
    fi

    # Handle headless configuration with CLI options
    if [[ -n "${MAVLINK_UART:-}" ]] || [[ -n "${MAVLINK_ENDPOINTS:-}" ]]; then
        log_info "Running headless configuration with CLI options"

        local uart_device="${MAVLINK_UART:-$(detect_uart_device)}"
        local baud_rate="${MAVLINK_BAUD:-57600}"
        local endpoints="${MAVLINK_ENDPOINTS:-$MDS_DEFAULT_ENDPOINTS}"
        local input_type="${MAVLINK_INPUT_TYPE:-uart}"

        if [[ -n "${GCS_IP:-}" ]] && [[ ! "$endpoints" =~ "${GCS_IP}" ]]; then
            endpoints="${endpoints},${GCS_IP}:24550"
        fi

        # Install if needed
        if ! check_mavlink_router_installed; then
            clone_mavlink_anywhere || return 1
            run_mavlink_install || return 1
        fi

        run_mavlink_configure_headless "$uart_device" "$baud_rate" "$endpoints" "$input_type" "${MAVLINK_INPUT_PORT:-14550}" || return 1
        verify_mavlink_service || return 1

        return 0
    fi

    # Non-interactive mode without specific options
    if [[ "${NON_INTERACTIVE:-false}" == "true" ]]; then
        log_info "Non-interactive mode: running auto-configuration"
        run_mavlink_auto_config
        return $?
    fi

    # ==========================================================================
    # INTERACTIVE MODE
    # ==========================================================================

    # Display menu
    display_mavlink_menu

    local choice
    read -p "  Enter your choice [1-4]: " choice </dev/tty

    case "$choice" in
        1)
            # Auto-configure
            log_info "Selected: Auto-configure"

            # Check serial prerequisites first
            if is_raspberry_pi; then
                if check_serial_console_enabled || ! check_uart_enabled; then
                    display_serial_status
                    display_serial_issue_options

                    local serial_choice
                    read -p "  Enter your choice [1-3]: " serial_choice </dev/tty

                    case "$serial_choice" in
                        1)
                            # Auto-fix
                            log_info "Auto-fixing serial configuration..."
                            if auto_fix_uart_config; then
                                display_reboot_prompt
                                if confirm "Reboot now?" "y"; then
                                    log_info "Rebooting..."
                                    reboot
                                fi
                                return 1  # Need reboot
                            fi
                            ;;
                        2)
                            # Manual instructions
                            display_manual_serial_instructions
                            return 1
                            ;;
                        3)
                            # Skip serial, continue with auto (will fail if no serial)
                            log_warn "Proceeding without serial fix..."
                            ;;
                    esac
                fi
            fi

            run_mavlink_auto_config
            ;;

        2)
            # Interactive configuration
            log_info "Selected: Interactive configuration"

            # Prompt for GCS IP if not set
            if [[ -z "${GCS_IP:-}" ]]; then
                prompt_input "Enter GCS IP address (leave empty to skip)" "" "GCS_IP"
            fi

            # Install if needed
            if ! check_mavlink_router_installed; then
                log_info "Installing mavlink-router..."
                clone_mavlink_anywhere || return 1
                run_mavlink_install || return 1
            fi

            # Run interactive configuration
            cd "$MAVLINK_ANYWHERE_DIR"
            ./configure_mavlink_router.sh
            local result=$?
            cd - > /dev/null

            return $result
            ;;

        3)
            # Manual setup - show instructions
            log_info "Selected: Manual setup"
            display_mavlink_instructions "${GCS_IP:-}"

            if [[ "${VERBOSE:-false}" == "true" ]]; then
                display_serial_status
            fi

            echo ""
            if confirm "Continue with initialization (configure mavlink later)?" "y"; then
                return 0
            else
                return 1
            fi
            ;;

        4)
            # Skip
            log_info "Skipping mavlink-router setup"
            return 0
            ;;

        *)
            log_error "Invalid choice: $choice"
            return 1
            ;;
    esac
}

# Alias for backward compatibility
run_mavlink_guidance_phase() {
    run_mavlink_setup_phase
}
