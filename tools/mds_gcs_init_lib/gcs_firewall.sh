#!/bin/bash
# =============================================================================
# MDS GCS Initialization Library: Firewall Configuration
# =============================================================================
# Version: 1.0.0
# Description: Configure UFW with GCS-specific ports
# Author: MDS Team
# =============================================================================

# Prevent double-sourcing
[[ -n "${_MDS_GCS_FIREWALL_LOADED:-}" ]] && return 0
_MDS_GCS_FIREWALL_LOADED=1

# =============================================================================
# FIREWALL CHECKS
# =============================================================================

# Check if UFW is installed
check_ufw_installed() {
    command_exists ufw
}

# Check if UFW is active
check_ufw_active() {
    ufw status 2>/dev/null | grep -qi "status: active"
}

# =============================================================================
# UFW CONFIGURATION
# =============================================================================

# Enable UFW
enable_ufw() {
    log_step "Enabling UFW firewall..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would enable UFW${NC}"
        return 0
    fi

    # Set default policies
    ufw default deny incoming 2>/dev/null
    ufw default allow outgoing 2>/dev/null

    # Enable UFW without leaving a prompt hanging in non-interactive runs.
    if ufw --force enable 2>/dev/null; then
        log_success "UFW enabled"
        return 0
    else
        log_error "Failed to enable UFW"
        return 1
    fi
}

# Open a single port
open_port() {
    local port_proto="$1"
    local description="$2"
    local port="${port_proto%/*}"
    local proto="${port_proto#*/}"

    log_debug "Opening port: $port/$proto ($description)"

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would open: $port/$proto - $description${NC}"
        return 0
    fi

    if ufw allow "$port/$proto" comment "$description" 2>/dev/null; then
        return 0
    else
        # Try without comment (older UFW versions)
        ufw allow "$port/$proto" 2>/dev/null
    fi
}

# Open all GCS ports
open_gcs_ports() {
    log_step "Opening GCS ports..."

    local count=0
    local total=${#GCS_PORTS[@]}

    for port_proto in "${!GCS_PORTS[@]}"; do
        local description="${GCS_PORTS[$port_proto]}"
        ((count++))

        if is_dry_run; then
            echo -e "  ${DIM}[DRY-RUN] [$count/$total] $port_proto - $description${NC}"
        else
            open_port "$port_proto" "$description"
            echo -e "  ${CHECK} [$count/$total] ${port_proto} - ${description}"
        fi
    done

    return 0
}

# Display firewall rules summary
show_firewall_summary() {
    log_step "Current firewall rules:"
    echo ""

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would show UFW status${NC}"
        return 0
    fi

    # Show UFW status in a formatted way
    ufw status numbered 2>/dev/null | while IFS= read -r line; do
        echo "  $line"
    done

    echo ""
}

# =============================================================================
# MAIN PHASE RUNNER
# =============================================================================

# Detect current SSH port from sshd config or connection
detect_ssh_port() {
    local ssh_port="22"

    # Check sshd_config for custom port
    if [[ -f /etc/ssh/sshd_config ]]; then
        local config_port
        config_port=$(grep -E "^Port\s+" /etc/ssh/sshd_config 2>/dev/null | awk '{print $2}')
        if [[ -n "$config_port" ]]; then
            ssh_port="$config_port"
        fi
    fi

    # Also check from current SSH connection
    if [[ -n "${SSH_CONNECTION:-}" ]]; then
        local conn_port
        conn_port=$(echo "$SSH_CONNECTION" | awk '{print $4}')
        if [[ -n "$conn_port" ]] && [[ "$conn_port" != "22" ]]; then
            ssh_port="$conn_port"
        fi
    fi

    echo "$ssh_port"
}

run_firewall_phase() {
    print_phase_header "5" "Firewall Configuration" "9"

    # Check skip flag
    if [[ "${SKIP_FIREWALL:-false}" == "true" ]]; then
        log_info "Skipping firewall configuration (--skip-firewall)"
        return 0
    fi

    print_section "UFW Check"

    # Check if UFW is installed
    if ! check_ufw_installed; then
        log_info "UFW is not installed. Installing..."
        if is_dry_run; then
            echo -e "  ${DIM}[DRY-RUN] Would install UFW${NC}"
        else
            start_progress "Installing UFW"
            apt-get install -y -qq ufw >/dev/null 2>&1
            local ufw_rc=$?
            stop_progress
            if [[ $ufw_rc -ne 0 ]]; then
                log_error "Failed to install UFW"
                return 1
            fi
        fi
    fi

    log_success "UFW is installed"

    # Detect SSH port
    local ssh_port
    ssh_port=$(detect_ssh_port)

    print_section "Port Configuration"

    # Display port list
    echo ""
    echo -e "  ${WHITE}GCS Required Ports:${NC}"
    echo -e "  ${DIM}───────────────────────────────────────────────────────────────${NC}"
    printf "  ${WHITE}%-12s %-10s %s${NC}\n" "PORT" "PROTO" "DESCRIPTION"
    echo -e "  ${DIM}───────────────────────────────────────────────────────────────${NC}"

    # Always show SSH port first
    printf "  %-12s %-10s %s\n" "$ssh_port" "tcp" "SSH access (CRITICAL)"

    for port_proto in "${!GCS_PORTS[@]}"; do
        local port="${port_proto%/*}"
        local proto="${port_proto#*/}"
        local desc="${GCS_PORTS[$port_proto]}"
        # Skip if it's the SSH port (already shown)
        [[ "$port" == "$ssh_port" ]] && continue
        printf "  %-12s %-10s %s\n" "$port" "$proto" "$desc"
    done

    echo -e "  ${DIM}───────────────────────────────────────────────────────────────${NC}"
    echo ""

    # Warning if enabling firewall for first time
    if ! check_ufw_active; then
        echo -e "  ${YELLOW}NOTE: Firewall is not currently active.${NC}"
        echo -e "  ${YELLOW}Enabling it will allow ONLY the ports listed above.${NC}"
        echo -e "  ${GREEN}SSH port $ssh_port will be allowed automatically.${NC}"
        echo ""
    fi

    # Ask for custom ports in interactive mode - cleaner UX
    if can_prompt; then
        echo -e "  ${WHITE}Additional ports (optional):${NC}"
        echo -e "  ${DIM}Enter extra ports if needed, or press Enter to skip${NC}"
        echo -e "  ${DIM}Format: 8080 or 8080,9000 or 8080/udp${NC}"
        echo ""

        local custom_ports=""
        read -p "  Extra ports [none]: " custom_ports </dev/tty

        if [[ -n "$custom_ports" ]]; then
            # Parse and store custom ports
            IFS=',' read -ra CUSTOM_PORTS <<< "$custom_ports"
            for port in "${CUSTOM_PORTS[@]}"; do
                port=$(echo "$port" | tr -d ' ')
                if [[ -n "$port" ]]; then
                    # Default to tcp if no protocol specified
                    if [[ "$port" != */* ]]; then
                        port="${port}/tcp"
                    fi
                    GCS_PORTS["$port"]="Custom port"
                    log_info "Added: $port"
                fi
            done
        fi
        echo ""

        # Check if user is using non-standard SSH port
        if [[ "$ssh_port" != "22" ]]; then
            echo -e "  ${YELLOW}IMPORTANT: You are using SSH on port $ssh_port (not standard 22)${NC}"
            echo -e "  ${YELLOW}This port will be allowed to maintain your connection.${NC}"
            echo ""
        fi

        # Final warning before applying
        echo -e "  ${WHITE}The firewall will ONLY allow the ports listed above.${NC}"
        echo -e "  ${WHITE}All other incoming connections will be blocked.${NC}"
        echo ""

        if ! confirm "Apply firewall configuration?" "y"; then
            log_info "Skipping firewall configuration"
            echo ""
            echo -e "  ${DIM}You can configure firewall later with:${NC}"
            echo -e "  ${CYAN}sudo ufw allow PORT/tcp${NC}"
            echo ""
            return 0
        fi
    elif [[ "${NON_INTERACTIVE:-false}" != "true" ]]; then
        log_warn "No interactive TTY detected; applying default firewall configuration"
    fi

    print_section "Applying Rules"

    # CRITICAL: Always allow SSH first before enabling firewall
    if ! is_dry_run; then
        log_step "Ensuring SSH access on port $ssh_port..."
        ufw allow "$ssh_port/tcp" comment "SSH access" 2>/dev/null
        log_success "SSH port $ssh_port allowed"
    fi

    # Enable UFW if not active
    if ! check_ufw_active; then
        enable_ufw || return 1
    else
        log_info "UFW already active"
    fi

    # Open all GCS ports
    open_gcs_ports || return 1

    # Reload UFW
    if ! is_dry_run; then
        ufw reload 2>/dev/null
    fi

    print_section "Summary"
    show_firewall_summary

    echo ""
    log_success "Firewall phase completed"
    return 0
}
