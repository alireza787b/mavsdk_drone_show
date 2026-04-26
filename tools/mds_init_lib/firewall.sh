#!/bin/bash
# =============================================================================
# MDS Initialization Library: Firewall Configuration
# =============================================================================
# Version: 4.5.0
# Description: UFW firewall setup and port configuration for MDS services
# Author: MDS Team
# =============================================================================

# Prevent double-sourcing
[[ -n "${_MDS_FIREWALL_LOADED:-}" ]] && return 0
_MDS_FIREWALL_LOADED=1

# =============================================================================
# PORT DEFINITIONS
# =============================================================================

# MDS required ports with descriptions
declare -A MDS_PORTS=(
    ["22/tcp"]="SSH access"
    ["${MDS_GCS_API_PORT:-${MDS_DEFAULT_GCS_API_PORT:-5030}}/tcp"]="GCS API Server"
    ["${MDS_DRONE_API_PORT:-${MDS_DEFAULT_DRONE_API_PORT:-7070}}/tcp"]="Drone API Server"
    ["14540/udp"]="MAVSDK SDK connection"
    ["14550/udp"]="GCS/QGroundControl"
    ["14569/udp"]="mavlink2rest API"
    ["12550/udp"]="Local MAVLink telemetry"
    ["24550/udp"]="Remote GCS over VPN"
    ["34550/udp"]="MAVLink aggregation"
)

# =============================================================================
# SSH PORT DETECTION
# =============================================================================

# Detect the SSH port being used for the current session
# This is critical to avoid locking ourselves out when enabling UFW
detect_ssh_port() {
    local ssh_port=""

    # Method 1: Try to detect from SSH_CONNECTION environment variable
    # SSH_CONNECTION format: client_ip client_port server_ip server_port
    if [[ -n "${SSH_CONNECTION:-}" ]]; then
        ssh_port=$(echo "$SSH_CONNECTION" | awk '{print $4}')
        log_debug "Detected SSH port from SSH_CONNECTION: ${ssh_port:-none}"
    fi

    # Method 2: Fallback - check sshd config
    if [[ -z "$ssh_port" ]] && [[ -f /etc/ssh/sshd_config ]]; then
        ssh_port=$(grep -E "^Port " /etc/ssh/sshd_config 2>/dev/null | awk '{print $2}' | head -1)
        log_debug "Detected SSH port from sshd_config: ${ssh_port:-none}"
    fi

    # Method 3: Fallback - check active sshd process
    if [[ -z "$ssh_port" ]]; then
        ssh_port=$(ss -tlnp 2>/dev/null | grep sshd | awk '{print $4}' | grep -oP ':\K[0-9]+' | head -1)
        log_debug "Detected SSH port from active sshd: ${ssh_port:-none}"
    fi

    # Default to port 22 if detection fails
    echo "${ssh_port:-22}"
}

# =============================================================================
# UFW FUNCTIONS
# =============================================================================

# Check if UFW is installed
check_ufw_installed() {
    if command_exists ufw; then
        return 0
    fi
    return 1
}

# Install UFW if missing
install_ufw() {
    log_step "Installing UFW firewall..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would install: ufw${NC}"
        return 0
    fi

    apt-get update -qq
    apt-get install -y -qq ufw

    if check_ufw_installed; then
        log_success "UFW installed successfully"
        return 0
    fi

    log_error "Failed to install UFW"
    return 1
}

# Check UFW status
get_ufw_status() {
    ufw status 2>/dev/null | head -1 | awk '{print $2}'
}

# Enable UFW with default policies
# IMPORTANT: Always detects and allows SSH port before enabling to prevent lockout
enable_ufw() {
    log_step "Enabling UFW firewall..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would enable UFW with default policies${NC}"
        return 0
    fi

    # CRITICAL: Detect and allow SSH port BEFORE enabling UFW to prevent lockout
    local ssh_port
    ssh_port=$(detect_ssh_port)

    log_info "Ensuring SSH access on port ${ssh_port} before enabling firewall..."
    ufw allow "${ssh_port}/tcp" comment "SSH access (detected)" 2>/dev/null || {
        log_warn "Failed to add SSH rule - proceeding with caution"
    }

    # Set default policies
    ufw default deny incoming 2>/dev/null
    ufw default allow outgoing 2>/dev/null

    # Enable UFW (--force to avoid interactive prompt)
    if ufw --force enable; then
        log_success "UFW enabled with default deny incoming"
        log_success "SSH port ${ssh_port} allowed"
        return 0
    fi

    log_error "Failed to enable UFW"
    return 1
}

# Open a single port
open_port() {
    local port="$1"
    local description="${2:-}"

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would open: ${port} (${description})${NC}"
        return 0
    fi

    if ufw allow "$port" comment "MDS: ${description}" &>/dev/null; then
        log_debug "Opened port: $port"
        return 0
    fi

    log_warn "Failed to open port: $port"
    return 1
}

# Open all MDS ports
open_mds_ports() {
    log_step "Opening MDS service ports..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would open all MDS ports${NC}"
        for port in "${!MDS_PORTS[@]}"; do
            echo -e "    ${DIM}- ${port}: ${MDS_PORTS[$port]}${NC}"
        done
        return 0
    fi

    local failed=0

    for port in "${!MDS_PORTS[@]}"; do
        local description="${MDS_PORTS[$port]}"
        if open_port "$port" "$description"; then
            echo -e "    ${CHECK} ${port} - ${description}"
        else
            echo -e "    ${CROSS} ${port} - ${description}"
            ((failed++))
        fi
    done

    if [[ $failed -eq 0 ]]; then
        log_success "All MDS ports opened successfully"
        return 0
    fi

    log_warn "Some ports failed to open ($failed failures)"
    return 0  # Don't fail the whole phase for port issues
}

# Verify firewall rules are active
verify_firewall_rules() {
    log_step "Verifying firewall configuration..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would verify firewall rules${NC}"
        return 0
    fi

    local status
    status=$(get_ufw_status)

    if [[ "$status" != "active" ]]; then
        log_warn "UFW is not active (status: $status)"
        return 1
    fi

    # Check that our ports are open
    local rules
    rules=$(ufw status numbered 2>/dev/null)

    local missing=()
    for port in "${!MDS_PORTS[@]}"; do
        # Extract just the port number and protocol for checking
        local port_num="${port%/*}"
        local proto="${port#*/}"

        if ! echo "$rules" | grep -qE "${port_num}.*${proto^^}"; then
            missing+=("$port")
        fi
    done

    if [[ ${#missing[@]} -gt 0 ]]; then
        log_warn "Some ports may not be properly configured: ${missing[*]}"
        return 1
    fi

    log_success "Firewall rules verified"
    return 0
}

# Display current firewall status
display_firewall_status() {
    echo ""
    echo -e "  ${BOLD}Current UFW Status:${NC}"
    echo -e "  ${DIM}$(printf '%.0s─' {1..50})${NC}"

    if [[ "$(get_ufw_status)" == "active" ]]; then
        echo -e "  Status: ${GREEN}Active${NC}"
    else
        echo -e "  Status: ${YELLOW}Inactive${NC}"
    fi

    echo ""
    echo -e "  ${BOLD}MDS Port Rules:${NC}"
    echo -e "  ${DIM}$(printf '%.0s─' {1..50})${NC}"

    ufw status | grep -E "(ALLOW|DENY)" | while read -r line; do
        echo -e "  $line"
    done

    echo ""
}

# Reset firewall to defaults (use with caution)
reset_firewall() {
    log_warn "Resetting firewall to defaults..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would reset UFW to defaults${NC}"
        return 0
    fi

    ufw --force reset
    log_info "Firewall reset complete"
    return 0
}

# =============================================================================
# MAIN FIREWALL RUNNER
# =============================================================================

run_firewall_phase() {
    print_phase_header "6" "Firewall Configuration"

    # Check skip flag
    if [[ "${SKIP_FIREWALL:-false}" == "true" ]]; then
        log_info "Skipping firewall configuration (--skip-firewall)"
        return 0
    fi

    # Check if UFW is installed
    if ! check_ufw_installed; then
        print_section "UFW Installation"

        if [[ "${NON_INTERACTIVE:-false}" == "true" ]]; then
            install_ufw || return 1
        else
            if confirm "UFW not installed. Install now?" "y"; then
                install_ufw || return 1
            else
                log_warn "Skipping firewall configuration"
                return 0
            fi
        fi
    else
        log_success "UFW is installed"
    fi

    print_section "Firewall Configuration"

    # Check current status
    local current_status
    current_status=$(get_ufw_status)

    if [[ "$current_status" == "active" ]]; then
        log_info "UFW is currently active"

        if [[ "${NON_INTERACTIVE:-false}" != "true" ]]; then
            if ! confirm "Add/update MDS firewall rules?" "y"; then
                log_info "Keeping existing firewall configuration"
                display_firewall_status
                return 0
            fi
        fi
    else
        log_info "UFW is not enabled"
        enable_ufw || return 1
    fi

    print_section "Opening MDS Ports"

    echo ""
    echo -e "  ${INFO} The following ports will be opened:"
    echo ""
    printf "  ${BOLD}%-15s %-40s${NC}\n" "PORT" "SERVICE"
    echo -e "  ${DIM}$(printf '%.0s─' {1..55})${NC}"
    for port in "${!MDS_PORTS[@]}"; do
        printf "  %-15s %-40s\n" "$port" "${MDS_PORTS[$port]}"
    done
    echo ""

    # Open ports
    open_mds_ports || return 1

    # Reload UFW to apply changes
    if ! is_dry_run; then
        ufw reload 2>/dev/null || true
    fi

    print_section "Verification"

    verify_firewall_rules || true

    if [[ "${VERBOSE:-false}" == "true" ]]; then
        display_firewall_status
    fi

    log_success "Firewall configuration complete"
    return 0
}
