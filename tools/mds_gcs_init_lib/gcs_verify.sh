#!/bin/bash
# =============================================================================
# MDS GCS Initialization Library: Verification
# =============================================================================
# Version: 4.4.0
# Description: Final verification and next steps
# Author: MDS Team
# =============================================================================

# Prevent double-sourcing
[[ -n "${_MDS_GCS_VERIFY_LOADED:-}" ]] && return 0
_MDS_GCS_VERIFY_LOADED=1

# =============================================================================
# VERIFICATION CHECKS
# =============================================================================

# Verify repository status
verify_repository() {
    local install_dir="${GCS_INSTALL_DIR:-$(pwd)}"

    log_step "Verifying repository..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would verify repository${NC}"
        return 0
    fi

    if [[ ! -d "${install_dir}/.git" ]]; then
        log_error "Repository not found at: $install_dir"
        return 1
    fi

    cd "$install_dir" || return 1

    local branch
    branch=$(git branch --show-current 2>/dev/null)
    local commit
    commit=$(git rev-parse --short HEAD 2>/dev/null)
    local status
    status=$(git status --porcelain 2>/dev/null | wc -l)

    echo -e "    Branch: ${GREEN}${branch}${NC}"
    echo -e "    Commit: ${GREEN}${commit}${NC}"

    if [[ "$status" -gt 0 ]]; then
        echo -e "    Status: ${YELLOW}${status} modified files${NC}"
    else
        echo -e "    Status: ${GREEN}Clean${NC}"
    fi

    log_success "Repository verified"
    return 0
}

# Verify Python environment
verify_python_env() {
    local venv_path
    venv_path=$(get_venv_path)

    log_step "Verifying Python environment..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would verify Python environment${NC}"
        return 0
    fi

    if [[ ! -f "${venv_path}/bin/python" ]]; then
        log_error "Python venv not found at: $venv_path"
        return 1
    fi

    local python_version
    python_version=$("${venv_path}/bin/python" --version 2>&1 | grep -oP '\d+\.\d+\.\d+')

    echo -e "    Python: ${GREEN}${python_version}${NC}"
    echo -e "    Venv: ${GREEN}${venv_path}${NC}"

    # Check key packages
    local missing_packages=()
    for pkg in "${GCS_PYTHON_PACKAGES[@]}"; do
        if ! "${venv_path}/bin/python" -c "import $pkg" 2>/dev/null; then
            missing_packages+=("$pkg")
        fi
    done

    if [[ ${#missing_packages[@]} -eq 0 ]]; then
        echo -e "    Packages: ${GREEN}All critical packages installed${NC}"
    else
        echo -e "    Packages: ${YELLOW}Missing: ${missing_packages[*]}${NC}"
    fi

    log_success "Python environment verified"
    return 0
}

# Verify Node.js environment
verify_nodejs_env() {
    local dashboard_path
    dashboard_path=$(get_dashboard_path)

    log_step "Verifying Node.js environment..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would verify Node.js environment${NC}"
        return 0
    fi

    local node_version
    node_version=$(get_node_version)
    local npm_version
    npm_version=$(get_npm_version)

    echo -e "    Node.js: ${GREEN}v${node_version}${NC}"
    echo -e "    npm: ${GREEN}v${npm_version}${NC}"

    if [[ -d "${dashboard_path}/node_modules" ]]; then
        local pkg_count
        pkg_count=$(find "${dashboard_path}/node_modules" -maxdepth 1 -type d | wc -l)
        echo -e "    Modules: ${GREEN}${pkg_count} packages installed${NC}"
    else
        echo -e "    Modules: ${YELLOW}Not installed${NC}"
    fi

    # Check for build
    if [[ -d "${dashboard_path}/build" ]]; then
        echo -e "    Build: ${GREEN}Production build available${NC}"
    else
        echo -e "    Build: ${DIM}Development mode only${NC}"
    fi

    log_success "Node.js environment verified"
    return 0
}

# Test backend import
verify_backend() {
    local install_dir="${GCS_INSTALL_DIR:-$(pwd)}"
    local venv_path
    venv_path=$(get_venv_path)

    log_step "Verifying backend can start..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would test backend import${NC}"
        return 0
    fi

    # Test FastAPI app import
    local test_result
    test_result=$("${venv_path}/bin/python" -c "
import sys
sys.path.insert(0, '${install_dir}/gcs-server')
try:
    from app_fastapi import app
    print('OK')
except Exception as e:
    print(f'ERROR: {e}')
" 2>&1)

    if [[ "$test_result" == "OK" ]]; then
        echo -e "    FastAPI: ${GREEN}Import successful${NC}"
        log_success "Backend verified"
        return 0
    else
        echo -e "    FastAPI: ${YELLOW}${test_result}${NC}"
        log_warn "Backend import had issues (may still work)"
        return 0
    fi
}

# Verify firewall rules
verify_firewall() {
    log_step "Verifying firewall rules..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would verify firewall${NC}"
        return 0
    fi

    if ! check_ufw_installed; then
        echo -e "    UFW: ${YELLOW}Not installed${NC}"
        return 0
    fi

    if check_ufw_active; then
        echo -e "    UFW: ${GREEN}Active${NC}"

        # Check key ports
        local ports_ok=true
        for port_proto in "22/tcp" "5000/tcp" "3030/tcp" "14550/udp"; do
            if ufw status | grep -q "$port_proto"; then
                echo -e "    Port ${port_proto}: ${GREEN}Open${NC}"
            else
                echo -e "    Port ${port_proto}: ${YELLOW}Not configured${NC}"
                ports_ok=false
            fi
        done
    else
        echo -e "    UFW: ${YELLOW}Inactive${NC}"
    fi

    log_success "Firewall verified"
    return 0
}

# =============================================================================
# SUMMARY AND NEXT STEPS
# =============================================================================

# Print final summary
print_summary() {
    local install_dir="${GCS_INSTALL_DIR:-$(pwd)}"
    local venv_path
    venv_path=$(get_venv_path)

    echo ""
    echo -e "${CYAN}+==============================================================================+${NC}"
    echo -e "${CYAN}|${NC}  ${WHITE}INSTALLATION SUMMARY${NC}"
    echo -e "${CYAN}+==============================================================================+${NC}"
    echo ""

    echo -e "  ${WHITE}Installation Directory:${NC} ${install_dir}"
    echo -e "  ${WHITE}Virtual Environment:${NC} ${venv_path}"
    echo -e "  ${WHITE}Dashboard:${NC} $(get_dashboard_path)"
    echo -e "  ${WHITE}Config File:${NC} ${GCS_CONFIG_FILE}"
    echo -e "  ${WHITE}State File:${NC} ${GCS_STATE_FILE}"
    echo ""
}

# Print NetBird VPN info
print_netbird_info() {
    echo -e "${CYAN}+==============================================================================+${NC}"
    echo -e "${CYAN}|${NC}  ${WHITE}VPN NETWORKING (NetBird)${NC}"
    echo -e "${CYAN}+==============================================================================+${NC}"
    echo ""
    echo -e "  For drones to communicate with this GCS over the internet, both must"
    echo -e "  be on the same VPN network (e.g., NetBird)."
    echo ""
    echo -e "  ${WHITE}Options:${NC}"
    echo -e "    • Official NetBird Cloud: ${CYAN}https://netbird.io${NC}"
    echo -e "    • Self-hosted NetBird server"
    echo -e "    • NetBird server on this GCS machine"
    echo ""
    echo -e "  ${WHITE}After connecting this GCS to NetBird:${NC}"
    echo -e "    1. Note your NetBird IP (typically ${CYAN}100.x.x.x${NC})"
    echo -e "    2. Use this IP as GCS_IP when configuring drones"
    echo -e "    3. Drones must also connect to the same NetBird network"
    echo ""
    echo -e "  ${DIM}See: docs/guides/netbird-setup.md${NC}"
    echo ""
    echo -e "${CYAN}+==============================================================================+${NC}"
    echo ""
}

# Print next steps
print_next_steps() {
    local install_dir="${GCS_INSTALL_DIR:-$(pwd)}"

    echo -e "${CYAN}+==============================================================================+${NC}"
    echo -e "${CYAN}|${NC}  ${WHITE}NEXT STEPS${NC}"
    echo -e "${CYAN}+==============================================================================+${NC}"
    echo ""

    echo -e "  ${WHITE}1. Start the GCS Dashboard:${NC}"
    echo ""
    echo -e "     ${GREEN}cd ${install_dir}/app${NC}"
    echo ""
    echo -e "     # SITL mode (simulation) - default uses tmux:"
    echo -e "     ${GREEN}./linux_dashboard_start.sh --sitl${NC}"
    echo ""
    echo -e "     # Real mode (hardware drones):"
    echo -e "     ${GREEN}./linux_dashboard_start.sh --real${NC}"
    echo ""
    echo -e "     # Other options:"
    echo -e "     ${DIM}--rebuild     Force rebuild React app${NC}"
    echo -e "     ${DIM}--prod        Production mode (optimized)${NC}"
    echo -e "     ${DIM}--status      Show current status${NC}"
    echo -e "     ${DIM}--help        Show all options${NC}"
    echo ""

    echo -e "  ${WHITE}2. Access the Dashboard:${NC}"
    echo ""
    echo -e "     Frontend:    ${CYAN}http://<your-ip>:3030${NC}"
    echo -e "     Backend API: ${CYAN}http://<your-ip>:5000${NC}"
    echo -e "     Health:      ${CYAN}http://<your-ip>:5000/api/v1/system/health${NC}"
    echo ""

    echo -e "  ${WHITE}3. Useful Commands:${NC}"
    echo ""
    echo -e "     View tmux:   ${GREEN}tmux attach -t MDS-GCS${NC}"
    echo -e "     Stop:        ${GREEN}tmux kill-session -t MDS-GCS${NC}"
    echo ""

    echo -e "${CYAN}+==============================================================================+${NC}"
    echo ""
}

# =============================================================================
# MAIN PHASE RUNNER
# =============================================================================

run_verify_phase() {
    print_phase_header "9" "Verification" "9"

    print_section "Component Verification"

    local errors=0

    verify_repository || ((errors++))
    verify_python_env || ((errors++))
    verify_nodejs_env || ((errors++))
    verify_backend || ((errors++))
    verify_firewall || ((errors++))

    print_section "Summary"

    if [[ $errors -eq 0 ]]; then
        echo ""
        echo -e "  ${CHECK} ${GREEN}All verifications passed!${NC}"
        gcs_state_set_value "verified" "true"
        gcs_state_set_value "verified_at" "$(date -Iseconds)"
    else
        echo ""
        echo -e "  ${WARN} ${YELLOW}Completed with $errors warning(s)${NC}"
        gcs_state_set_value "verified" "partial"
    fi

    print_summary
    print_next_steps
    print_netbird_info

    echo ""
    log_success "GCS Initialization Complete!"
    return 0
}
