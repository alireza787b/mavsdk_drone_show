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
VERIFY_RESULTS_TEXT=""

verify_component_stream() {
    cat <<'EOF'
hw_id
runtime_mode
connectivity_backend
repository
python_env
mavsdk
local_env
firewall
services
ntp
mavlink_router
serial_config
netbird
network
smart_wifi_manager
EOF
}

verify_set_result() {
    local key="$1"
    local value="$2"
    local line
    local updated=""

    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        if [[ "${line%%$'\t'*}" != "$key" ]]; then
            updated+="${line}"$'\n'
        fi
    done <<< "${VERIFY_RESULTS_TEXT}"

    updated+="${key}"$'\t'"${value}"$'\n'
    VERIFY_RESULTS_TEXT="$updated"
}

verify_get_result() {
    local key="$1"
    local default_value="${2:-SKIP:Not checked}"
    local line

    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        if [[ "${line%%$'\t'*}" == "$key" ]]; then
            printf '%s' "${line#*$'\t'}"
            return 0
        fi
    done <<< "${VERIFY_RESULTS_TEXT}"

    printf '%s' "$default_value"
}

verify_run_git_query() {
    git -c safe.directory="${MDS_INSTALL_DIR}" -C "${MDS_INSTALL_DIR}" "$@" 2>/dev/null || \
        sudo -u "${MDS_USER}" git -C "${MDS_INSTALL_DIR}" "$@" 2>/dev/null || true
}

get_verified_hw_id() {
    local drone_id="${DRONE_ID:-}"

    if [[ -z "$drone_id" ]]; then
        drone_id=$(grep "^MDS_HW_ID=" "${MDS_LOCAL_ENV}" 2>/dev/null | cut -d= -f2 || true)
    fi

    if [[ -z "$drone_id" ]] && [[ -f "${MDS_NODE_IDENTITY_FILE}" ]] && command -v jq &>/dev/null; then
        drone_id=$(jq -r '.hw_id // ""' "${MDS_NODE_IDENTITY_FILE}" 2>/dev/null || echo "")
    fi

    printf '%s\n' "$drone_id"
}

# Verify hardware ID
verify_hw_id() {
    local drone_id
    drone_id="$(get_verified_hw_id)"

    if [[ -n "$drone_id" ]]; then
        verify_set_result "hw_id" "PASS:Drone ${drone_id}"
        return 0
    fi

    verify_set_result "hw_id" "FAIL:No canonical HW_ID found"
    return 1
}

# Verify runtime mode
verify_runtime_mode() {
    local runtime_mode=""
    runtime_mode=$(grep "^MDS_MODE=" "${MDS_LOCAL_ENV}" 2>/dev/null | cut -d= -f2 || true)

    if [[ "$runtime_mode" == "real" || "$runtime_mode" == "sitl" ]]; then
        verify_set_result "runtime_mode" "PASS:${runtime_mode}"
        return 0
    fi

    verify_set_result "runtime_mode" "WARN:canonical MDS_MODE missing"
    return 0
}

verify_connectivity_backend() {
    local backend=""
    backend=$(grep "^MDS_CONNECTIVITY_BACKEND=" "${MDS_LOCAL_ENV}" 2>/dev/null | cut -d= -f2 || true)
    [[ -z "$backend" ]] && backend="${MDS_DEFAULT_CONNECTIVITY_BACKEND:-none}"

    case "$backend" in
        none|manual)
            verify_set_result "connectivity_backend" "PASS:none"
            ;;
        smart-wifi-manager)
            verify_set_result "connectivity_backend" "PASS:smart-wifi-manager"
            ;;
        *)
            verify_set_result "connectivity_backend" "WARN:Unknown (${backend})"
            ;;
    esac

    return 0
}

# Verify repository
verify_repository() {
    if [[ "$(verify_run_git_query rev-parse --is-inside-work-tree)" != "true" ]]; then
        verify_set_result "repository" "FAIL:Not a git repository"
        return 1
    fi

    local branch commit
    branch="$(verify_run_git_query branch --show-current)"
    commit="$(verify_run_git_query rev-parse --short HEAD)"
    [[ -z "$branch" ]] && branch="unknown"
    [[ -z "$commit" ]] && commit="unknown"

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

    local hw_id runtime_mode
    hw_id=$(grep "^MDS_HW_ID=" "${MDS_LOCAL_ENV}" 2>/dev/null | cut -d= -f2)
    runtime_mode=$(grep "^MDS_MODE=" "${MDS_LOCAL_ENV}" 2>/dev/null | cut -d= -f2)

    if [[ -n "$hw_id" ]] && [[ -n "$runtime_mode" ]]; then
        verify_set_result "local_env" "PASS:HW_ID=${hw_id},MODE=${runtime_mode}"
        return 0
    fi

    verify_set_result "local_env" "WARN:HW_ID or MDS_MODE not set"
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
    local services=("led_indicator" "git_sync_mds" "coordinator")
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

verify_smart_wifi_manager() {
    local backend=""
    backend=$(grep "^MDS_CONNECTIVITY_BACKEND=" "${MDS_LOCAL_ENV}" 2>/dev/null | cut -d= -f2 || true)
    [[ -z "$backend" ]] && backend="${MDS_DEFAULT_CONNECTIVITY_BACKEND:-none}"

    if [[ "$backend" != "smart-wifi-manager" ]]; then
        verify_set_result "smart_wifi_manager" "SKIP:Not selected"
        return 0
    fi

    if ! systemctl is-enabled smart-wifi-manager.service &>/dev/null; then
        verify_set_result "smart_wifi_manager" "WARN:Not enabled"
        return 0
    fi

    if systemctl is-active smart-wifi-manager.service &>/dev/null; then
        local mode="unknown"
        local connected_ssid=""

        if [[ -f /etc/smart-wifi-manager/config.json ]] && command -v jq &>/dev/null; then
            mode=$(jq -r '.mode // "unknown"' /etc/smart-wifi-manager/config.json 2>/dev/null || echo "unknown")
        fi

        if [[ -f /run/smart-wifi-manager/status.json ]] && command -v jq &>/dev/null; then
            connected_ssid=$(jq -r '.connected_ssid // ""' /run/smart-wifi-manager/status.json 2>/dev/null || echo "")
        fi

        if [[ -n "$connected_ssid" ]]; then
            verify_set_result "smart_wifi_manager" "PASS:${mode} (${connected_ssid})"
        else
            verify_set_result "smart_wifi_manager" "PASS:${mode}"
        fi
        return 0
    fi

    verify_set_result "smart_wifi_manager" "WARN:Enabled but not running"
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

    local netbird_output status nb_ip
    netbird_output="$(netbird status --detail 2>/dev/null || netbird status 2>/dev/null || true)"
    nb_ip="$(printf '%s\n' "$netbird_output" | grep -oP '^NetBird IP: \K[\d.]+' | head -1 || echo "")"

    if printf '%s\n' "$netbird_output" | grep -q '^Management: Connected'; then
        status="connected"
    elif printf '%s\n' "$netbird_output" | grep -q 'Status:[[:space:]]*Connected'; then
        status="connected"
    elif printf '%s\n' "$netbird_output" | grep -q 'Status:[[:space:]]*Disconnected'; then
        status="disconnected"
    elif printf '%s\n' "$netbird_output" | grep -q 'Status:[[:space:]]*Idle'; then
        status="idle"
    else
        status="unknown"
    fi

    case "${status,,}" in
        connected)
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
    verify_runtime_mode
    verify_connectivity_backend
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
    verify_smart_wifi_manager

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
    local drone_id="${DRONE_ID:-$(get_verified_hw_id 2>/dev/null || echo 'Unknown')}"

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

    while IFS= read -r component; do
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
    done < <(verify_component_stream)

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

    while IFS= read -r component; do
        local status
        status="$(verify_get_result "$component")"
        status="${status%%:*}"
        [[ "$status" == "WARN" ]] && has_warnings=true
        [[ "$status" == "FAIL" ]] && has_failures=true
    done < <(verify_component_stream)

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

    local connectivity_status
    connectivity_status="$(verify_get_result "smart_wifi_manager")"
    if [[ "$connectivity_status" == WARN:* ]]; then
        echo ""
        echo -e "  ${WARN} Smart Wi-Fi Manager is selected but not healthy"
        echo -e "      ${GREEN}sudo ./tools/reconcile_connectivity.sh apply --force${NC}"
        echo -e "      ${DIM}Then inspect: journalctl -u smart-wifi-manager --since '10 minutes ago'${NC}"
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
    print_phase_header "14" "Verification"

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
