#!/bin/bash
# =============================================================================
# MDS GCS Initialization Library: Node.js Installation
# =============================================================================
# Version: 4.4.0
# Description: Detect or install Node.js 22.x LTS (nvm-aware, sudo-safe)
# Author: MDS Team
# =============================================================================

# Prevent double-sourcing
[[ -n "${_MDS_GCS_NODEJS_LOADED:-}" ]] && return 0
_MDS_GCS_NODEJS_LOADED=1

# =============================================================================
# CONSTANTS
# =============================================================================

readonly NODESOURCE_URL="https://deb.nodesource.com/setup_${GCS_NODE_TARGET_VERSION}.x"
readonly NVM_INSTALL_URL="https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh"

# =============================================================================
# NODE.JS CHECKS
# =============================================================================

# Check if Node.js is available and meets minimum version.
# Uses discover_nodejs() from gcs_common.sh to search nvm, /usr/local/bin, etc.
check_nodejs_available() {
    # discover_nodejs searches all common paths and adds to PATH
    if ! discover_nodejs; then
        return 1
    fi

    local version
    version=$(get_node_version)
    if [[ -z "$version" ]]; then
        return 1
    fi

    local major="${version%%.*}"
    if [[ "$major" -ge "$GCS_NODE_MIN_VERSION" ]]; then
        log_debug "Found Node.js $version (major: $major) at $(command -v node)"
        return 0
    fi

    return 1
}

# Check if npm is available
check_npm_available() {
    discover_nodejs &>/dev/null
    command -v npm &>/dev/null
}

# =============================================================================
# NVM INSTALLATION (recommended method)
# =============================================================================

# Install Node.js via nvm for the invoking user (best practice)
install_via_nvm() {
    local invoking_user="${SUDO_USER:-$(whoami)}"
    local invoking_home
    invoking_home=$(eval echo "~${invoking_user}" 2>/dev/null)
    local nvm_dir="${invoking_home}/.nvm"

    log_step "Installing Node.js ${GCS_NODE_TARGET_VERSION}.x via nvm for user '${invoking_user}'..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would install nvm and Node.js ${GCS_NODE_TARGET_VERSION}.x${NC}"
        return 0
    fi

    # Install nvm if not present
    if [[ ! -d "$nvm_dir" ]]; then
        start_progress "Installing nvm" "downloading from GitHub"
        sudo -u "$invoking_user" bash -c "curl -fsSL '${NVM_INSTALL_URL}' | bash" >/dev/null 2>&1
        local rc=$?
        stop_progress

        if [[ $rc -eq 0 ]]; then
            log_success "nvm installed"
        else
            log_error "Failed to install nvm"
            return 1
        fi
    else
        log_info "nvm already installed at ${nvm_dir}"
    fi

    # Install the target Node.js version via nvm as the invoking user
    start_progress "Installing Node.js ${GCS_NODE_TARGET_VERSION} via nvm" "downloading and compiling, may take 1-2 min"
    sudo -u "$invoking_user" bash -c "
        export NVM_DIR='${nvm_dir}'
        source '${nvm_dir}/nvm.sh'
        nvm install ${GCS_NODE_TARGET_VERSION}
        nvm alias default ${GCS_NODE_TARGET_VERSION}
    " >/dev/null 2>&1
    local rc=$?
    stop_progress

    if [[ $rc -eq 0 ]]; then
        log_success "Node.js ${GCS_NODE_TARGET_VERSION} installed via nvm"
    else
        log_error "Failed to install Node.js via nvm"
        return 1
    fi

    # Re-discover to pick up the new installation
    _MDS_NODE_DIR=""
    if discover_nodejs; then
        return 0
    else
        log_error "Node.js installed but not found in expected paths"
        return 1
    fi
}

# =============================================================================
# NODESOURCE FALLBACK
# =============================================================================

# Add NodeSource repository (fallback if nvm not suitable)
add_nodesource_repo() {
    log_step "Adding NodeSource repository for Node.js ${GCS_NODE_TARGET_VERSION}.x..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would add NodeSource repository${NC}"
        return 0
    fi

    # Check if already added
    if [[ -f /etc/apt/sources.list.d/nodesource.list ]] || \
       grep -rq "nodesource" /etc/apt/sources.list.d/ 2>/dev/null; then
        log_info "NodeSource repository already configured"
        return 0
    fi

    # Download and run NodeSource setup script (show output for progress)
    log_info "Downloading NodeSource setup script..."
    local tmp_script
    tmp_script=$(mktemp /tmp/nodesource_setup.XXXXXX.sh)

    if ! curl -fsSL "$NODESOURCE_URL" -o "$tmp_script"; then
        rm -f "$tmp_script"
        log_error "Failed to download NodeSource setup script"
        return 1
    fi

    # Run the setup script and capture exit code properly
    start_progress "Running NodeSource setup" "configuring apt repository"
    if bash "$tmp_script" >/dev/null 2>&1; then
        stop_progress
        rm -f "$tmp_script"
        # Verify the repo was actually added
        if [[ -f /etc/apt/sources.list.d/nodesource.list ]] || \
           grep -rq "nodesource" /etc/apt/sources.list.d/ 2>/dev/null; then
            log_success "NodeSource repository added"
            return 0
        else
            log_error "NodeSource setup script ran but repository was not added (GPG key issue?)"
            return 1
        fi
    else
        stop_progress
        rm -f "$tmp_script"
        log_error "Failed to run NodeSource setup script"
        return 1
    fi
}

# Install Node.js via apt (NodeSource or system repos)
install_via_apt() {
    log_step "Installing Node.js via apt..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would install: nodejs npm${NC}"
        return 0
    fi

    # Try NodeSource first
    add_nodesource_repo

    # Install nodejs (and npm separately in case using Ubuntu repos)
    start_progress "Installing Node.js via apt" "may take 1-2 min"
    DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs >/dev/null 2>&1
    local rc=$?
    stop_progress

    if [[ $rc -eq 0 ]]; then
        log_success "Node.js installed"
    else
        log_error "Failed to install Node.js"
        return 1
    fi

    # Ensure npm is available (NodeSource bundles it, Ubuntu repos don't)
    if ! command -v npm &>/dev/null; then
        log_info "npm not bundled, installing separately..."
        start_progress "Installing npm"
        DEBIAN_FRONTEND=noninteractive apt-get install -y npm >/dev/null 2>&1
        rc=$?
        stop_progress

        if [[ $rc -eq 0 ]]; then
            log_success "npm installed"
        else
            log_error "Failed to install npm"
            return 1
        fi
    fi

    return 0
}

# =============================================================================
# VERIFICATION
# =============================================================================

# Verify Node.js installation
verify_nodejs() {
    log_step "Verifying Node.js installation..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would verify Node.js installation${NC}"
        return 0
    fi

    # Re-discover after any installation
    _MDS_NODE_DIR=""
    if ! discover_nodejs; then
        log_error "Node.js not found after installation"
        return 1
    fi

    local node_version
    node_version=$(get_node_version)
    if [[ -z "$node_version" ]]; then
        log_error "Could not determine Node.js version"
        return 1
    fi

    local node_path
    node_path=$(command -v node)
    log_success "Node.js verified: v${node_version} (${node_path})"
    gcs_state_set_value "node_version" "$node_version"
    gcs_state_set_value "node_path" "$node_path"

    # Check npm
    if ! command -v npm &>/dev/null; then
        log_error "npm not found"
        return 1
    fi

    local npm_version
    npm_version=$(get_npm_version)
    local npm_path
    npm_path=$(command -v npm)
    log_success "npm verified: v${npm_version} (${npm_path})"
    gcs_state_set_value "npm_version" "$npm_version"

    return 0
}

# =============================================================================
# MAIN PHASE RUNNER
# =============================================================================

run_nodejs_phase() {
    print_phase_header "3" "Node.js Installation" "9"

    # Check skip flag
    if [[ "${SKIP_NODEJS:-false}" == "true" ]]; then
        log_info "Skipping Node.js installation (--skip-nodejs)"
        return 0
    fi

    print_section "Node.js Check"

    # Check if Node.js already available anywhere (nvm, /usr/local, system, etc.)
    if check_nodejs_available && check_npm_available; then
        local node_version
        node_version=$(get_node_version)
        local npm_version
        npm_version=$(get_npm_version)
        local node_path
        node_path=$(command -v node)

        log_success "Node.js already installed: v${node_version} (${node_path})"
        log_success "npm already installed: v${npm_version}"
        gcs_state_set_value "node_version" "$node_version"
        gcs_state_set_value "npm_version" "$npm_version"
        gcs_state_set_value "node_path" "$node_path"

        # Warn if version is old but still acceptable
        local major="${node_version%%.*}"
        if [[ "$major" -lt "$GCS_NODE_TARGET_VERSION" ]]; then
            log_warn "Node.js ${major} works but ${GCS_NODE_TARGET_VERSION}.x LTS is recommended"
            log_info "Upgrade: nvm install ${GCS_NODE_TARGET_VERSION} && nvm alias default ${GCS_NODE_TARGET_VERSION}"
        fi

        echo ""
        log_success "Node.js phase completed"
        return 0
    fi

    # Node.js not found anywhere — need to install
    print_section "Installation"

    log_info "Node.js >= ${GCS_NODE_MIN_VERSION} not found on this system"

    # Determine install method
    local invoking_user="${SUDO_USER:-$(whoami)}"
    local install_method="nvm"

    if can_prompt; then
        echo ""
        echo -e "  ${WHITE}How should Node.js ${GCS_NODE_TARGET_VERSION}.x be installed?${NC}"
        echo ""
        echo -e "    ${GREEN}1)${NC} nvm (recommended) — installs for user '${invoking_user}', easy upgrades"
        echo -e "    ${YELLOW}2)${NC} apt/NodeSource — system-wide, requires repo setup"
        echo ""
        local choice
        read -p "  Select [1]: " choice </dev/tty
        choice=${choice:-1}

        case "$choice" in
            2) install_method="apt" ;;
            *) install_method="nvm" ;;
        esac
    elif [[ "${NON_INTERACTIVE:-false}" != "true" ]]; then
        log_warn "No interactive TTY detected; using default Node.js install method: nvm"
    fi

    if [[ "$install_method" == "nvm" ]]; then
        install_via_nvm || return 1
    else
        install_via_apt || return 1
    fi

    verify_nodejs || return 1

    echo ""
    log_success "Node.js phase completed"
    return 0
}
