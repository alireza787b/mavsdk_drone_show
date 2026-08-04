#!/bin/bash
# =============================================================================
# MDS GCS Initialization Library: Node.js Environment
# =============================================================================
# Version: 1.0.0
# Description: Install npm dependencies for React dashboard
# Author: MDS Team
# =============================================================================

# Prevent double-sourcing
[[ -n "${_MDS_GCS_NODEJS_ENV_LOADED:-}" ]] && return 0
_MDS_GCS_NODEJS_ENV_LOADED=1

# =============================================================================
# CONSTANTS
# =============================================================================

readonly GCS_DASHBOARD_SUBDIR="app/dashboard/drone-dashboard"
readonly GCS_NPM_ALLOW_INSTALL_FALLBACK="${MDS_ALLOW_NPM_INSTALL_FALLBACK:-false}"

# =============================================================================
# DASHBOARD PATH
# =============================================================================

# Get the dashboard directory path
get_dashboard_path() {
    local install_dir="${GCS_INSTALL_DIR:-$(pwd)}"
    echo "${install_dir}/${GCS_DASHBOARD_SUBDIR}"
}

# Check if dashboard directory exists
check_dashboard_exists() {
    local dashboard_path
    dashboard_path=$(get_dashboard_path)
    [[ -d "$dashboard_path" ]] && [[ -f "${dashboard_path}/package.json" ]]
}

# Check if node_modules exists
check_node_modules_exists() {
    local dashboard_path
    dashboard_path=$(get_dashboard_path)
    [[ -d "${dashboard_path}/node_modules" ]]
}

# =============================================================================
# NPM OPERATIONS
# =============================================================================

run_npm_with_log() {
    local log_file="$1"
    shift
    if "$@" >"$log_file" 2>&1; then
        return 0
    fi
    return 1
}

# Fix node_modules ownership when running as sudo
# npm ci/install as root creates files owned by root — the invoking user
# can't write to .cache later (eslint, webpack, etc.)
fix_node_modules_ownership() {
    local dashboard_path="$1"
    local target_user="${SUDO_USER:-}"

    # Only needed when running as sudo (root with a real invoking user)
    if [[ -z "$target_user" ]] || [[ "$target_user" == "root" ]]; then
        return 0
    fi

    if [[ -d "${dashboard_path}/node_modules" ]]; then
        log_info "Fixing node_modules ownership for user: $target_user"
        chown -R "$target_user":"$target_user" "${dashboard_path}/node_modules" 2>/dev/null || true
    fi
}

# Install npm dependencies
install_npm_dependencies() {
    local dashboard_path
    dashboard_path=$(get_dashboard_path)

    log_step "Installing npm dependencies..."
    log_info "Dashboard path: $dashboard_path"

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would run: npm ci in $dashboard_path${NC}"
        return 0
    fi

    # Change to dashboard directory
    cd "$dashboard_path" || {
        log_error "Could not change to dashboard directory"
        return 1
    }

    # Try npm ci first (clean install). npm install fallback is opt-in only
    # because it mutates package-lock.json and can dirty the repo on a host.
    log_info "Running npm ci (clean install)..."
    local npm_log
    npm_log=$(mktemp)

    start_progress "Running npm ci" "may take 2-5 min depending on network"
    if run_npm_with_log "$npm_log" npm ci --include=dev --no-audit --no-fund; then
        stop_progress
        grep -q "added" "$npm_log" && log_debug "$(grep "added" "$npm_log" | tail -1)"
        fix_node_modules_ownership "$dashboard_path"
        rm -f "$npm_log"
        log_success "npm dependencies installed"
        return 0
    fi
    stop_progress

    if [[ "$GCS_NPM_ALLOW_INSTALL_FALLBACK" != "true" ]]; then
        log_error "npm ci failed. Refusing to run npm install automatically on this host."
        tail -10 "$npm_log"
        rm -f "$npm_log"
        return 1
    fi

    log_warn "npm ci failed. MDS_ALLOW_NPM_INSTALL_FALLBACK=true, trying npm install..."
    start_progress "Running npm install (fallback)" "may take 2-5 min"
    if run_npm_with_log "$npm_log" npm install --include=dev --no-audit --no-fund; then
        stop_progress
        grep -q "added" "$npm_log" && log_debug "$(grep "added" "$npm_log" | tail -1)"
        fix_node_modules_ownership "$dashboard_path"
        rm -f "$npm_log"
        log_success "npm dependencies installed (via npm install)"
        return 0
    fi
    stop_progress

    log_error "Failed to install npm dependencies"
    tail -10 "$npm_log"
    rm -f "$npm_log"
    return 1
}

# Verify node_modules
verify_node_modules() {
    local dashboard_path
    dashboard_path=$(get_dashboard_path)

    log_step "Verifying node_modules..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would verify node_modules${NC}"
        return 0
    fi

    if check_node_modules_exists; then
        # Count packages
        local pkg_count
        pkg_count=$(find "${dashboard_path}/node_modules" -maxdepth 1 -type d | wc -l)
        log_success "node_modules verified ($pkg_count packages)"
        return 0
    else
        log_error "node_modules not found after installation"
        return 1
    fi
}

# Optional: Build production bundle
build_dashboard() {
    local dashboard_path
    dashboard_path=$(get_dashboard_path)

    log_step "Building production bundle (optional)..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would run: npm run build${NC}"
        return 0
    fi

    # Check if build script exists
    if ! grep -q "\"build\"" "${dashboard_path}/package.json" 2>/dev/null; then
        log_info "No build script found, skipping"
        return 0
    fi

    cd "$dashboard_path" || return 1

    # Ask for confirmation in interactive mode
    if [[ "${NON_INTERACTIVE:-false}" != "true" ]]; then
        if ! confirm "Build production bundle now? (can be done later)" "n"; then
            log_info "Skipping production build"
            return 0
        fi
    fi

    local build_log
    build_log=$(mktemp)

    start_progress "Building React dashboard" "may take 2-5 min, needs 2GB+ RAM"
    if run_npm_with_log "$build_log" npm run build; then
        stop_progress
        rm -f "$build_log"
        log_success "Production bundle built"
        gcs_state_set_value "dashboard_built" "true"
        return 0
    fi
    stop_progress

    log_warn "Build failed (dashboard can still run in development mode)"
    log_debug "Build output: $(tail -5 "$build_log")"
    rm -f "$build_log"
    return 0
}

# =============================================================================
# MAIN PHASE RUNNER
# =============================================================================

run_nodejs_env_phase() {
    print_phase_header "7" "Node.js Environment" "9"

    # Check skip flag
    if [[ "${SKIP_NODEJS_ENV:-false}" == "true" ]]; then
        log_info "Skipping Node.js environment setup (--skip-nodejs-env)"
        return 0
    fi

    local install_dir="${GCS_INSTALL_DIR:-$(pwd)}"

    print_section "Dashboard Check"

    # Verify dashboard directory exists
    if ! check_dashboard_exists; then
        log_error "Dashboard not found at: $(get_dashboard_path)"
        log_error "Please ensure repository is cloned first"
        return 1
    fi

    log_success "Dashboard directory found"

    # Check if node_modules already exists
    if check_node_modules_exists; then
        log_info "node_modules already exists"

        if [[ "${NON_INTERACTIVE:-false}" != "true" ]]; then
            if ! confirm "Reinstall npm dependencies?" "n"; then
                log_info "Keeping existing node_modules"
                verify_node_modules
                echo ""
                log_success "Node.js environment phase completed"
                return 0
            fi
        else
            # In non-interactive mode, skip if already installed
            verify_node_modules
            echo ""
            log_success "Node.js environment phase completed"
            return 0
        fi
    fi

    print_section "NPM Installation"
    install_npm_dependencies || return 1
    verify_node_modules || return 1

    print_section "Production Build"
    build_dashboard  # Optional, failure is OK

    # Store dashboard path in state
    gcs_state_set_value "dashboard_path" "$(get_dashboard_path)"

    echo ""
    log_success "Node.js environment phase completed"
    return 0
}
