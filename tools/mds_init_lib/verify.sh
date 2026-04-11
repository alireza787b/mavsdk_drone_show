#!/bin/bash
# =============================================================================
# MDS Initialization Library: Verification
# =============================================================================
# Version: 4.5.0
# Description: Component verification, health checks, and summary reporting
# Author: MDS Team
# =============================================================================

# Prevent double-sourcing
[[ -n "${_MDS_VERIFY_LOADED:-}" ]] && return 0
_MDS_VERIFY_LOADED=1

# =============================================================================
# COMPONENT VERIFICATION
# =============================================================================

# Verification results storage
declare -A VERIFY_RESULTS=()
declare -a VERIFY_COMPONENTS=(
    "hw_id"
    "real_mode"
    "repository"
    "python_env"
    "mavsdk"
    "local_env"
    "firewall"
    "services"
    "ntp"
    "mavlink_router"
    "serial_config"
    "netbird"
    "network"
)

verify_set_result() {
    local key="$1"
    local value="$2"
    VERIFY_RESULTS["$key"]="$value"
}

verify_get_result() {
    local key="$1"
    local default_value="${2:-SKIP:Not checked}"
    printf '%s' "${VERIFY_RESULTS["$key"]:-$default_value}"
}

# Verify hardware ID
verify_hw_id() {
    local drone_id="${DRONE_ID:-}"

    if [[ -z "$drone_id" ]]; then
        # Try to detect from hwID file
        drone_id=$(get_current_hwid 2>/dev/null || echo "")
    fi

    if [[ -n "$drone_id" ]] && [[ -f "${MDS_INSTALL_DIR}/${drone_id}.hwID" ]]; then
        verify_set_result "hw_id" "PASS:Drone ${drone_id}"
        return 0
    fi

    verify_set_result "hw_id" "FAIL:No hwID file found"
    return 1
}

# Verify real.mode marker
verify_real_mode() {
    if [[ -f "${MDS_INSTALL_DIR}/real.mode" ]]; then
        verify_set_result "real_mode" "PASS:Present"
        return 0
    fi

    verify_set_result "real_mode" "WARN:Not present (SITL mode)"
    return 0
}

# Verify repository
verify_repository() {
    if ! git -C "${MDS_INSTALL_DIR}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        verify_set_result "repository" "FAIL:Not a git repository"
        return 1
    fi

    local branch commit
    branch=$(cd "${MDS_INSTALL_DIR}" && git branch --show-current 2>/dev/null || echo "unknown")
    commit=$(cd "${MDS_INSTALL_DIR}" && git rev-parse --short HEAD 2>/dev/null || echo "unknown")

    verify_set_result "repository" "PASS:${branch}@${commit}"
    return 0
}

# Verify Python environment
verify_python_env() {
    if [[ ! -d "${MDS_INSTALL_DIR}/venv" ]]; then
        verify_set_result "python_env" "FAIL:venv not found"
        return 1
    fi

    if [[ ! -x "${MDS_INSTALL_DIR}/venv/bin/python" ]]; then
        verify_set_result "python_env" "FAIL:venv python not executable"
        return 1
    fi

    local version
    version=$("${MDS_INSTALL_DIR}/venv/bin/python" --version 2>&1 | awk '{print $2}')
    verify_set_result "python_env" "PASS:Python ${version}"
    return 0
}

# Verify MAVSDK binary
verify_mavsdk() {
    if [[ ! -x "${MDS_INSTALL_DIR}/mavsdk_server" ]]; then
        verify_set_result "mavsdk" "FAIL:Binary not found or not executable"
        return 1
    fi

    local version
    version=$("${MDS_INSTALL_DIR}/mavsdk_server" --version 2>&1 | head -1 | grep -oP 'v[\d.]+' || echo "unknown")
    verify_set_result "mavsdk" "PASS:${version}"
    return 0
}

# Verify local.env
verify_local_env() {
    if [[ ! -f "${MDS_LOCAL_ENV}" ]]; then
        verify_set_result "local_env" "WARN:Not found"
        return 0
    fi

    local hw_id
    hw_id=$(grep "^MDS_HW_ID=" "${MDS_LOCAL_ENV}" 2>/dev/null | cut -d= -f2)

    if [[ -n "$hw_id" ]]; then
        verify_set_result "local_env" "PASS:HW_ID=${hw_id}"
        return 0
    fi

    verify_set_result "local_env" "WARN:HW_ID not set"
    return 0
}

# Verify firewall
verify_firewall() {
    if ! command_exists ufw; then
        verify_set_result "firewall" "WARN:UFW not installed"
        return 0
    fi

    local status
    status=$(ufw status 2>/dev/null | head -1 | awk '{print $2}')

    if [[ "$status" == "active" ]]; then
        verify_set_result "firewall" "PASS:Active"
        return 0
    fi

    verify_set_result "firewall" "WARN:Inactive"
    return 0
}

# Verify services
verify_service_status() {
    local services=("led_indicator" "wifi-manager" "git_sync_mds" "coordinator")
    local enabled=0
    local total=${#services[@]}

    for service in "${services[@]}"; do
        if systemctl is-enabled "${service}.service" &>/dev/null; then
            ((enabled++))
        fi
    done

    if [[ $enabled -eq $total ]]; then
        verify_set_result "services" "PASS:${enabled}/${total} enabled"
        return 0
    fi

    verify_set_result "services" "WARN:${enabled}/${total} enabled"
    return 0
}

# Verify NTP
verify_ntp() {
    local sync_status
    sync_status=$(timedatectl show --property=NTPSynchronized --value 2>/dev/null || echo "no")

    if [[ "$sync_status" == "yes" ]]; then
        verify_set_result "ntp" "PASS:Synchronized"
        return 0
    fi

    verify_set_result "ntp" "WARN:Not synchronized"
    return 0
}

# Verify mavlink-router (enhanced in v4.5)
verify_mavlink_router() {
    # Check if binary is installed
    local binary_found=false
    if command_exists mavlink-routerd; then
        binary_found=true
    elif [[ -x /usr/bin/mavlink-routerd ]] || [[ -x /usr/local/bin/mavlink-routerd ]]; then
        binary_found=true
    fi

    if [[ "$binary_found" != "true" ]]; then
        verify_set_result "mavlink_router" "WARN:Not installed"
        return 0
    fi

    # Check if config exists
    if [[ ! -f /etc/mavlink-router/main.conf ]]; then
        verify_set_result "mavlink_router" "WARN:Installed but not configured"
        return 0
    fi

    # Check service status
    if systemctl is-active mavlink-router &>/dev/null; then
        # Get additional info if possible
        local uart_device=""
        if [[ -f /etc/mavlink-router/main.conf ]]; then
            uart_device=$(grep "^Device=" /etc/mavlink-router/main.conf 2>/dev/null | head -1 | cut -d= -f2)
        fi

        if [[ -n "$uart_device" ]]; then
            verify_set_result "mavlink_router" "PASS:Running (${uart_device})"
        else
            verify_set_result "mavlink_router" "PASS:Running"
        fi
        return 0
    fi

    if systemctl is-enabled mavlink-router &>/dev/null; then
        verify_set_result "mavlink_router" "WARN:Enabled but not running"
        return 0
    fi

    verify_set_result "mavlink_router" "WARN:Configured but not enabled"
    return 0
}

# Verify serial port configuration (NEW in v4.5)
verify_serial_config() {
    # Only relevant for Raspberry Pi
    if ! is_raspberry_pi 2>/dev/null; then
        verify_set_result "serial_config" "SKIP:Not Raspberry Pi"
        return 0
    fi

    local issues=""

    # Check if serial console is enabled (bad - blocks UART)
    local cmdline_file="/boot/cmdline.txt"
    [[ -f /boot/firmware/cmdline.txt ]] && cmdline_file="/boot/firmware/cmdline.txt"

    if [[ -f "$cmdline_file" ]]; then
        if grep -qE "console=(serial0|ttyAMA0|ttyS0)" "$cmdline_file"; then
            issues="${issues}console_enabled,"
        fi
    fi

    # Check if UART is enabled
    local config_file="/boot/config.txt"
    [[ -f /boot/firmware/config.txt ]] && config_file="/boot/firmware/config.txt"

    if [[ -f "$config_file" ]]; then
        if ! grep -qE "^enable_uart=1" "$config_file"; then
            # UART might still work via serial0 symlink
            if [[ ! -e /dev/serial0 ]]; then
                issues="${issues}uart_disabled,"
            fi
        fi
    fi

    # Check for serial device
    local serial_device=""
    if [[ -e /dev/serial0 ]]; then
        serial_device=$(readlink -f /dev/serial0 2>/dev/null || echo "/dev/serial0")
    elif [[ -e /dev/ttyS0 ]]; then
        serial_device="/dev/ttyS0"
    elif [[ -e /dev/ttyAMA0 ]]; then
        serial_device="/dev/ttyAMA0"
    fi

    if [[ -z "$serial_device" ]]; then
        issues="${issues}no_device,"
    fi

    # Report result
    if [[ -z "$issues" ]]; then
        verify_set_result "serial_config" "PASS:OK (${serial_device:-detected})"
        return 0
    fi

    # Remove trailing comma
    issues="${issues%,}"

    if [[ "$issues" == *"console_enabled"* ]]; then
        verify_set_result "serial_config" "WARN:Console blocking UART"
    elif [[ "$issues" == *"uart_disabled"* ]]; then
        verify_set_result "serial_config" "WARN:UART not enabled"
    elif [[ "$issues" == *"no_device"* ]]; then
        verify_set_result "serial_config" "WARN:No serial device"
    else
        verify_set_result "serial_config" "WARN:${issues}"
    fi

    return 0
}

# Verify network connectivity
verify_network() {
    local connectivity="none"

    if ping -c 1 -W 2 8.8.8.8 &>/dev/null; then
        connectivity="internet"
    elif ping -c 1 -W 2 192.168.1.1 &>/dev/null; then
        connectivity="local"
    fi

    if [[ "$connectivity" == "internet" ]]; then
        verify_set_result "network" "PASS:Internet connected"
        return 0
    elif [[ "$connectivity" == "local" ]]; then
        verify_set_result "network" "WARN:Local only"
        return 0
    fi

    verify_set_result "network" "FAIL:No connectivity"
    return 1
}

# Verify NetBird VPN
verify_netbird() {
    if ! command_exists netbird; then
        verify_set_result "netbird" "WARN:Not installed"
        return 0
    fi

    local status
    status=$(netbird status 2>/dev/null | grep -i "status:" | head -1 | awk '{print $2}' || echo "unknown")

    case "${status,,}" in
        connected)
            local nb_ip
            nb_ip=$(netbird status 2>/dev/null | grep -oP 'IP: \K[\d.]+' | head -1 || echo "")
            if [[ -n "$nb_ip" ]]; then
                verify_set_result "netbird" "PASS:Connected (${nb_ip})"
            else
                verify_set_result "netbird" "PASS:Connected"
            fi
            return 0
            ;;
        disconnected|idle)
            verify_set_result "netbird" "WARN:Disconnected"
            return 0
            ;;
        *)
            verify_set_result "netbird" "WARN:Unknown ($status)"
            return 0
            ;;
    esac
}

# =============================================================================
# COMPREHENSIVE CHECKS
# =============================================================================

# Run all verifications
run_all_verifications() {
    log_step "Running verification checks..."

    verify_hw_id
    verify_real_mode
    verify_repository
    verify_python_env
    verify_mavsdk
    verify_local_env
    verify_firewall
    verify_service_status
    verify_ntp
    verify_mavlink_router
    verify_serial_config
    verify_netbird
    verify_network

    return 0
}

# Run recovery.sh health check if available
run_recovery_health() {
    local recovery_script="${MDS_INSTALL_DIR}/tools/recovery.sh"

    if [[ ! -x "$recovery_script" ]]; then
        log_info "Recovery script not found, skipping health check"
        return 0
    fi

    log_step "Running recovery.sh health check..."

    echo ""
    sudo -u "${MDS_USER}" "$recovery_script" health 2>&1 | while read -r line; do
        echo "    $line"
    done
    echo ""

    return 0
}

# =============================================================================
# SUMMARY REPORT
# =============================================================================

# Generate summary report
generate_summary_report() {
    local drone_id="${DRONE_ID:-$(get_current_hwid 2>/dev/null || echo 'Unknown')}"

    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}                     ${WHITE}MDS INITIALIZATION SUMMARY${NC}                              ${CYAN}║${NC}"
    echo -e "${CYAN}╠══════════════════════════════════════════════════════════════════════════════╣${NC}"
    echo -e "${CYAN}║${NC}                                                                              ${CYAN}║${NC}"
    printf "${CYAN}║${NC}  %-20s : %-52s ${CYAN}║${NC}\n" "Drone ID" "${drone_id}"
    printf "${CYAN}║${NC}  %-20s : %-52s ${CYAN}║${NC}\n" "Hostname" "$(hostname)"
    printf "${CYAN}║${NC}  %-20s : %-52s ${CYAN}║${NC}\n" "MDS Version" "${MDS_VERSION}"
    printf "${CYAN}║${NC}  %-20s : %-52s ${CYAN}║${NC}\n" "Timestamp" "$(date '+%Y-%m-%d %H:%M:%S')"
    echo -e "${CYAN}║${NC}                                                                              ${CYAN}║${NC}"
    echo -e "${CYAN}╠══════════════════════════════════════════════════════════════════════════════╣${NC}"
    echo -e "${CYAN}║${NC}  ${WHITE}COMPONENT STATUS${NC}                                                           ${CYAN}║${NC}"
    echo -e "${CYAN}╠══════════════════════════════════════════════════════════════════════════════╣${NC}"

    local pass_count=0
    local warn_count=0
    local fail_count=0

    for component in "${VERIFY_COMPONENTS[@]}"; do
        local result
        result="$(verify_get_result "$component")"
        local status="${result%%:*}"
        local details="${result#*:}"

        local status_color
        case "$status" in
            PASS)
                status_color="${GREEN}"
                ((pass_count++))
                ;;
            WARN)
                status_color="${YELLOW}"
                ((warn_count++))
                ;;
            FAIL)
                status_color="${RED}"
                ((fail_count++))
                ;;
            *)
                status_color="${DIM}"
                ;;
        esac

        printf "${CYAN}║${NC}  %-18s ${status_color}%-6s${NC} %-46s ${CYAN}║${NC}\n" \
            "$component" "[$status]" "$details"
    done

    echo -e "${CYAN}╠══════════════════════════════════════════════════════════════════════════════╣${NC}"

    local total=$((pass_count + warn_count + fail_count))
    local overall_status

    if [[ $fail_count -eq 0 && $warn_count -eq 0 ]]; then
        overall_status="${GREEN}ALL CHECKS PASSED${NC}"
    elif [[ $fail_count -eq 0 ]]; then
        overall_status="${YELLOW}PASSED WITH WARNINGS${NC}"
    else
        overall_status="${RED}SOME CHECKS FAILED${NC}"
    fi

    echo -e "${CYAN}║${NC}                                                                              ${CYAN}║${NC}"
    printf "${CYAN}║${NC}  ${WHITE}OVERALL:${NC} %-66b ${CYAN}║${NC}\n" "$overall_status"
    printf "${CYAN}║${NC}  ${GREEN}PASS: %d${NC}  ${YELLOW}WARN: %d${NC}  ${RED}FAIL: %d${NC}  Total: %d                                   ${CYAN}║${NC}\n" \
        "$pass_count" "$warn_count" "$fail_count" "$total"
    echo -e "${CYAN}║${NC}                                                                              ${CYAN}║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

# Display NetBird VPN info box
display_netbird_summary() {
    local nb_status
    nb_status="$(verify_get_result "netbird")"
    local status="${nb_status%%:*}"
    local details="${nb_status#*:}"

    echo ""
    echo -e "${CYAN}┌────────────────────────────────────────────────────────────────────────────┐${NC}"
    echo -e "${CYAN}│${NC}  ${WHITE}VPN NETWORKING (NetBird)${NC}                                                  ${CYAN}│${NC}"
    echo -e "${CYAN}├────────────────────────────────────────────────────────────────────────────┤${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"

    if [[ "$status" == "PASS" ]]; then
        # Extract IP if available
        local nb_ip=""
        if [[ "$details" =~ \(([0-9.]+)\) ]]; then
            nb_ip="${BASH_REMATCH[1]}"
        fi

        echo -e "${CYAN}│${NC}  Status:     ${GREEN}Connected${NC}                                                     ${CYAN}│${NC}"
        if [[ -n "$nb_ip" ]]; then
            printf "${CYAN}│${NC}  NetBird IP: ${GREEN}%-60s${NC}${CYAN}│${NC}\n" "$nb_ip"
        fi
        echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
        echo -e "${CYAN}│${NC}  ${DIM}This drone should use the GCS NetBird IP for communication.${NC}               ${CYAN}│${NC}"
        echo -e "${CYAN}│${NC}  ${DIM}Ensure the GCS is also on the same NetBird network.${NC}                       ${CYAN}│${NC}"
    elif [[ "$status" == "WARN" ]]; then
        if [[ "$details" == "Not installed" ]]; then
            echo -e "${CYAN}│${NC}  Status:     ${YELLOW}Not installed${NC}                                                 ${CYAN}│${NC}"
            echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
            echo -e "${CYAN}│${NC}  ${DIM}NetBird VPN is recommended for drone/GCS communication.${NC}                   ${CYAN}│${NC}"
            echo -e "${CYAN}│${NC}  ${DIM}Run: sudo ./tools/mds_node_init.sh --netbird-key YOUR_KEY${NC}                      ${CYAN}│${NC}"
        else
            echo -e "${CYAN}│${NC}  Status:     ${YELLOW}${details}${NC}                                                   ${CYAN}│${NC}"
            echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
            echo -e "${CYAN}│${NC}  ${DIM}Check NetBird status: netbird status${NC}                                      ${CYAN}│${NC}"
        fi
    else
        echo -e "${CYAN}│${NC}  Status:     ${DIM}Unknown${NC}                                                        ${CYAN}│${NC}"
    fi

    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}└────────────────────────────────────────────────────────────────────────────┘${NC}"
}

# Display next steps
display_next_steps() {
    local has_warnings=false
    local has_failures=false

    for component in "${VERIFY_COMPONENTS[@]}"; do
        local status
        status="$(verify_get_result "$component")"
        status="${status%%:*}"
        [[ "$status" == "WARN" ]] && has_warnings=true
        [[ "$status" == "FAIL" ]] && has_failures=true
    done

    echo -e "${WHITE}NEXT STEPS:${NC}"
    echo -e "${DIM}$(printf '%.0s─' {1..78})${NC}"

    if [[ "$has_failures" == "true" ]]; then
        echo -e "  ${CROSS} Review failed components above and re-run: ${GREEN}sudo ./mds_node_init.sh --resume${NC}"
    elif [[ "$has_warnings" == "true" ]]; then
        echo -e "  ${WARN} Warnings detected - review above, but system should be operational"
    fi

    # Check mavlink-router
    local mavlink_router_status
    mavlink_router_status="$(verify_get_result "mavlink_router")"
    if [[ "$mavlink_router_status" == *"Not installed"* ]] || [[ "$mavlink_router_status" == *"Not configured"* ]]; then
        echo ""
        echo -e "  ${ARROW} Configure mavlink-router for MAVLink routing:"
        echo -e "      ${GREEN}sudo ./tools/mds_node_init.sh --resume --mavlink-auto${NC}"
        echo -e "      ${DIM}Or manually:${NC}"
        echo -e "      ${GREEN}cd /opt/mavlink-anywhere && sudo ./configure_mavlink_router.sh --auto${NC}"
    fi

    # Check serial config
    local serial_status
    serial_status="$(verify_get_result "serial_config")"
    if [[ "$serial_status" == *"Console blocking"* ]]; then
        echo ""
        echo -e "  ${WARN} Serial console is blocking UART - run raspi-config to disable it"
        echo -e "      ${DIM}Interface Options → Serial Port → Login shell: NO, Hardware: YES${NC}"
    fi

    echo ""
    echo -e "  ${INFO} Reboot to apply all changes: ${GREEN}sudo reboot${NC}"
    echo ""
    echo -e "  ${INFO} After reboot, verify services: ${GREEN}./tools/recovery.sh status${NC}"
    echo ""
    echo -e "  ${INFO} View logs: ${GREEN}journalctl -u coordinator -f${NC}"
    echo ""
}

# =============================================================================
# MAIN VERIFICATION RUNNER
# =============================================================================

run_verify_phase() {
    print_phase_header "13" "Verification"

    set_led_state "STARTUP_COMPLETE"

    print_section "Component Verification"

    run_all_verifications

    print_section "Summary Report"

    generate_summary_report

    # Display NetBird VPN summary if relevant
    if command_exists netbird || [[ -n "${NETBIRD_KEY:-}" ]]; then
        display_netbird_summary
    fi

    # Run recovery health check if verbose
    if [[ "${VERBOSE:-false}" == "true" ]]; then
        print_section "Recovery Health Check"
        run_recovery_health
    fi

    print_section "Next Steps"

    display_next_steps

    # Mark initialization as complete
    _MDS_COMPLETED=true
    state_set_phase "completed" "completed"

    log_success "MDS initialization verification complete"
    return 0
}
