#!/bin/bash
# =============================================================================
# MDS Initialization Library: Python Environment
# =============================================================================
# Version: 4.4.0
# Description: Python virtual environment setup and requirements installation
# Author: MDS Team
# =============================================================================

# Prevent double-sourcing
[[ -n "${_MDS_PYTHON_ENV_LOADED:-}" ]] && return 0
_MDS_PYTHON_ENV_LOADED=1

# =============================================================================
# CONSTANTS
# =============================================================================

readonly VENV_DIR="${MDS_INSTALL_DIR}/venv"
readonly REQUIREMENTS_FILE="${MDS_INSTALL_DIR}/requirements.txt"

# Critical packages to verify after installation
# Note: Flask removed in v4.3.0 (FastAPI only backend)
readonly CRITICAL_PACKAGES=(
    "mavsdk"
    "aiohttp"
    "requests"
    "numpy"
)

# =============================================================================
# PYTHON VALIDATION
# =============================================================================

# Get Python version info
get_python_version_info() {
    python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")'
}

# Check if Python version is supported
validate_python_version() {
    log_step "Validating Python version..."

    if ! command_exists python3; then
        log_error "Python 3 is not installed"
        return 1
    fi

    local version
    version=$(get_python_version_info)
    local minor
    minor=$(echo "$version" | cut -d. -f2)

    if [[ "$minor" -lt 11 ]]; then
        log_error "Python 3.11+ required, found: $version"
        return 1
    fi

    if [[ "$minor" -gt 13 ]]; then
        log_warn "Python 3.$minor is untested (supported: 3.11-3.13)"
        log_warn "Some packages may have compatibility issues"
    fi

    log_success "Python version: $version"
    state_set_value "python_version" "$version"
    return 0
}

# =============================================================================
# PYTHON PACKAGE INSTALLATION
# =============================================================================

# Install Python system packages
install_python_system_deps() {
    log_step "Installing Python system packages..."

    local packages=(
        "python3"
        "python3-venv"
        "python3-pip"
        "python3-dev"
        "libffi-dev"
        "libssl-dev"
        "proj-bin"
        "proj-data"
        "libproj-dev"
        "libgeos-dev"
    )

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would install: ${packages[*]}${NC}"
        return 0
    fi

    apt-get update -qq

    local missing=()
    for pkg in "${packages[@]}"; do
        if ! package_is_installed "$pkg"; then
            missing+=("$pkg")
        fi
    done

    if [[ ${#missing[@]} -eq 0 ]]; then
        log_success "All Python system packages already installed"
        return 0
    fi

    log_info "Installing: ${missing[*]}"
    apt-get install -y -qq "${missing[@]}" || {
        log_error "Failed to install Python system packages"
        return 1
    }

    log_success "Python system packages installed"
    return 0
}

# =============================================================================
# VIRTUAL ENVIRONMENT
# =============================================================================

# Check if venv exists and is valid
venv_exists() {
    [[ -d "${VENV_DIR}" && -f "${VENV_DIR}/bin/python" && -f "${VENV_DIR}/bin/pip" ]]
}

# Create Python virtual environment
create_venv() {
    log_step "Creating Python virtual environment..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would create venv at: ${VENV_DIR}${NC}"
        return 0
    fi

    # Remove broken venv if exists
    if [[ -d "${VENV_DIR}" ]] && ! venv_exists; then
        log_warn "Removing broken venv..."
        rm -rf "${VENV_DIR}"
    fi

    # Create new venv
    if venv_exists; then
        log_info "Virtual environment already exists"
        return 0
    fi

    log_info "Creating venv at: ${VENV_DIR}"

    if ! sudo -u "${MDS_USER}" python3 -m venv "${VENV_DIR}"; then
        log_error "Failed to create virtual environment"
        return 1
    fi

    # Ensure ownership
    chown -R "${MDS_USER}:${MDS_USER}" "${VENV_DIR}"

    log_success "Virtual environment created"
    return 0
}

# Upgrade pip in venv
upgrade_pip() {
    log_step "Upgrading pip..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would upgrade pip${NC}"
        return 0
    fi

    sudo -u "${MDS_USER}" "${VENV_DIR}/bin/pip" install --upgrade pip --quiet || {
        log_warn "Failed to upgrade pip (continuing anyway)"
    }

    return 0
}

# =============================================================================
# REQUIREMENTS INSTALLATION
# =============================================================================

# Install requirements from requirements.txt
install_requirements() {
    log_step "Installing Python requirements..."

    if [[ ! -f "${REQUIREMENTS_FILE}" ]]; then
        log_error "requirements.txt not found at: ${REQUIREMENTS_FILE}"
        return 1
    fi

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would install from: ${REQUIREMENTS_FILE}${NC}"
        return 0
    fi

    local pip="${VENV_DIR}/bin/pip"

    log_info "Installing from: ${REQUIREMENTS_FILE}"
    log_info "This may take several minutes..."

    # Install with progress - use subshell with pipefail to detect pip failures
    # (Without pipefail, pipe exit status is from the while loop, not pip)
    if ( set -o pipefail
         sudo -u "${MDS_USER}" "$pip" install -r "${REQUIREMENTS_FILE}" \
             --quiet \
             --no-warn-script-location \
             2>&1 | while read -r line; do
                 # Show only important output
                 if [[ "$line" =~ "error" || "$line" =~ "Error" || "$line" =~ "WARNING" ]]; then
                     echo "    $line"
                 fi
             done
       ); then
        log_success "Requirements installed successfully"
        return 0
    fi

    log_error "Failed to install requirements"
    return 1
}

# =============================================================================
# VERIFICATION
# =============================================================================

# Verify a Python package can be imported
verify_package() {
    local package="$1"
    "${VENV_DIR}/bin/python" -c "import $package" 2>/dev/null
}

# Verify critical packages are installed
verify_critical_packages() {
    log_step "Verifying critical packages..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would verify: ${CRITICAL_PACKAGES[*]}${NC}"
        return 0
    fi

    local failed=()

    for package in "${CRITICAL_PACKAGES[@]}"; do
        if verify_package "$package"; then
            log_debug "Package OK: $package"
        else
            failed+=("$package")
            log_warn "Package missing or broken: $package"
        fi
    done

    if [[ ${#failed[@]} -eq 0 ]]; then
        log_success "All critical packages verified"
        return 0
    fi

    log_error "Missing packages: ${failed[*]}"
    return 1
}

# Get installed package version
get_package_version() {
    local package="$1"
    "${VENV_DIR}/bin/pip" show "$package" 2>/dev/null | grep "^Version:" | awk '{print $2}'
}

# Display installed package versions
display_package_versions() {
    echo ""
    echo -e "  ${BOLD}Key Package Versions:${NC}"
    echo -e "  ${DIM}$(printf '%.0s─' {1..40})${NC}"

    for package in "${CRITICAL_PACKAGES[@]}"; do
        local version
        version=$(get_package_version "$package")
        if [[ -n "$version" ]]; then
            printf "  %-20s %s\n" "$package" "$version"
        else
            printf "  %-20s ${RED}not installed${NC}\n" "$package"
        fi
    done

    echo ""
}

# =============================================================================
# MAIN PYTHON ENV RUNNER
# =============================================================================

run_python_env_phase() {
    print_phase_header "7" "Python Environment"

    # Check skip flag
    if [[ "${SKIP_VENV:-false}" == "true" ]]; then
        log_info "Skipping Python environment setup (--skip-venv)"
        return 0
    fi

    # Validate Python version
    validate_python_version || return 1

    print_section "System Dependencies"

    # Install system packages
    install_python_system_deps || return 1

    print_section "Virtual Environment"

    # Check if repository is cloned (required for requirements.txt)
    if [[ ! -d "${MDS_INSTALL_DIR}" ]]; then
        log_error "Repository not found. Run repository phase first."
        return 1
    fi

    # Create venv
    create_venv || return 1

    # Upgrade pip
    upgrade_pip

    print_section "Requirements Installation"

    # Install requirements
    install_requirements || return 1

    print_section "Verification"

    # Verify packages
    if ! verify_critical_packages; then
        log_warn "Some packages may need manual installation"
    fi

    if [[ "${VERBOSE:-false}" == "true" ]]; then
        display_package_versions
    fi

    # Record venv info
    state_set_value "venv_path" "${VENV_DIR}"
    state_set_value "pip_version" "$("${VENV_DIR}/bin/pip" --version | awk '{print $2}')"

    log_success "Python environment setup complete"
    return 0
}
