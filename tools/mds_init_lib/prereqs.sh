#!/bin/bash
# =============================================================================
# MDS Initialization Library: Prerequisites Check
# =============================================================================
# Version: 4.5.0
# Description: System prerequisites validation and package installation
# Author: MDS Team
# =============================================================================

# Prevent double-sourcing
[[ -n "${_MDS_PREREQS_LOADED:-}" ]] && return 0
_MDS_PREREQS_LOADED=1

# Required packages for MDS
readonly MDS_REQUIRED_PACKAGES=(
    "git"
    "curl"
    "jq"
    "ufw"
    "python3"
    "python3-venv"
    "python3-pip"
    "git-repair"
)

# Optional but recommended packages
readonly MDS_OPTIONAL_PACKAGES=(
    "htop"
    "vim"
    "tmux"
    "net-tools"
)

# Minimum disk space required in MB
readonly MIN_DISK_SPACE_MB=2000

# Supported Python versions
readonly MIN_PYTHON_VERSION=11
readonly MAX_PYTHON_VERSION=13
readonly WARN_PYTHON_VERSION=14

# =============================================================================
# PREREQUISITES CHECK FUNCTIONS
# =============================================================================

# Check if running with root/sudo privileges
check_sudo_access() {
    log_step "Checking sudo access..."

    if check_root; then
        log_success "Running with root privileges"
        return 0
    fi

    if sudo -n true 2>/dev/null; then
        log_success "Sudo access available"
        return 0
    fi

    log_error "Root/sudo access required. Run with: sudo $0"
    return 1
}

# Check operating system
check_os() {
    log_step "Checking operating system..."

    local os_name=""
    local os_version=""

    if [[ -f /etc/os-release ]]; then
        # shellcheck source=/dev/null
        source /etc/os-release
        os_name="${ID:-unknown}"
        os_version="${VERSION_ID:-unknown}"
    fi

    case "$os_name" in
        raspbian|debian)
            log_success "Detected: ${PRETTY_NAME:-$os_name $os_version}"
            state_set_value "os_name" "$os_name"
            state_set_value "os_version" "$os_version"
            return 0
            ;;
        ubuntu)
            log_warn "Ubuntu detected - not officially supported but may work"
            state_set_value "os_name" "$os_name"
            state_set_value "os_version" "$os_version"
            return 0
            ;;
        *)
            log_error "Unsupported OS: $os_name. Debian-family Linux required."
            return 1
            ;;
    esac
}

# Check system architecture
check_architecture() {
    log_step "Checking system architecture..."

    local arch
    arch=$(get_architecture)

    case "$arch" in
        arm64)
            log_success "Architecture: ARM64 (64-bit)"
            state_set_value "architecture" "arm64"
            return 0
            ;;
        armhf)
            log_warn "Architecture: ARM32 (32-bit) - 64-bit recommended"
            state_set_value "architecture" "armhf"
            return 0
            ;;
        x86_64)
            log_warn "Architecture: x86_64 - This appears to be SITL/development environment"
            state_set_value "architecture" "x86_64"
            return 0
            ;;
        *)
            log_error "Unsupported architecture: $arch"
            return 1
            ;;
    esac
}

# Check if running on Raspberry Pi hardware
check_raspberry_pi() {
    log_step "Checking companion-computer hardware hints..."

    if is_raspberry_pi; then
        local model
        model=$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || echo "Unknown")
        log_success "Hardware: $model"
        state_set_value "hardware_model" "$model"
        return 0
    fi

    if [[ "$(get_architecture)" == "x86_64" ]]; then
        log_warn "Not running on a known companion-computer board - assuming SITL/development mode"
        state_set_value "hardware_model" "SITL/x86_64"
        return 0
    fi

    log_warn "Known Raspberry Pi hardware not detected - board-specific tweaks may need manual review"
    return 0  # Don't fail, just warn
}

# Check available disk space
check_disk_space() {
    log_step "Checking disk space..."

    local available_mb
    available_mb=$(get_disk_space_mb "/")

    if [[ "$available_mb" -ge "$MIN_DISK_SPACE_MB" ]]; then
        log_success "Disk space: ${available_mb}MB available (minimum: ${MIN_DISK_SPACE_MB}MB)"
        state_set_value "disk_space_mb" "$available_mb"
        return 0
    fi

    log_error "Insufficient disk space: ${available_mb}MB (need ${MIN_DISK_SPACE_MB}MB)"
    return 1
}

# Check internet connectivity
check_internet() {
    log_step "Checking internet connectivity..."

    local test_hosts=("github.com" "8.8.8.8" "1.1.1.1")

    for host in "${test_hosts[@]}"; do
        if ping -c 1 -W 3 "$host" &>/dev/null; then
            log_success "Internet connectivity verified (via $host)"
            state_set_value "internet_check" "$host"
            return 0
        fi
    done

    # Try curl as fallback
    if curl -s --max-time 5 https://api.github.com &>/dev/null; then
        log_success "Internet connectivity verified (via HTTPS)"
        state_set_value "internet_check" "https"
        return 0
    fi

    log_error "No internet connectivity detected"
    return 1
}

# Check Python version
check_python_version() {
    log_step "Checking Python version..."

    if ! command_exists python3; then
        log_error "Python 3 not installed"
        return 1
    fi

    local python_version
    python_version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')

    local major minor
    major=$(echo "$python_version" | cut -d. -f1)
    minor=$(echo "$python_version" | cut -d. -f2)

    if [[ "$major" -ne 3 ]]; then
        log_error "Python 3 required, found Python $major"
        return 1
    fi

    if [[ "$minor" -lt "$MIN_PYTHON_VERSION" ]]; then
        log_error "Python 3.${MIN_PYTHON_VERSION}+ required, found 3.${minor}"
        return 1
    fi

    if [[ "$minor" -gt "$MAX_PYTHON_VERSION" ]]; then
        log_warn "Python 3.${minor} is newer than tested versions (3.${MIN_PYTHON_VERSION}-3.${MAX_PYTHON_VERSION})"
        log_warn "Proceeding with caution - some packages may have compatibility issues"
    fi

    log_success "Python version: $python_version"
    state_set_value "python_version" "$python_version"
    return 0
}

# Check if a package is installed
package_is_installed() {
    local package="$1"
    dpkg -l "$package" 2>/dev/null | grep -q "^ii"
}

# Check required packages
check_required_packages() {
    log_step "Checking required packages..."

    local missing_packages=()

    for package in "${MDS_REQUIRED_PACKAGES[@]}"; do
        if package_is_installed "$package"; then
            log_debug "Package installed: $package"
        else
            missing_packages+=("$package")
            log_debug "Package missing: $package"
        fi
    done

    if [[ ${#missing_packages[@]} -eq 0 ]]; then
        log_success "All required packages are installed"
        return 0
    fi

    log_warn "Missing packages: ${missing_packages[*]}"
    state_set_value "missing_packages" "${missing_packages[*]}"
    return 1
}

# Install missing packages
install_missing_packages() {
    log_step "Installing missing packages..."

    local packages=("$@")

    if [[ ${#packages[@]} -eq 0 ]]; then
        # Get from state if not provided
        local missing
        missing=$(state_get_value "missing_packages" "")
        if [[ -z "$missing" ]]; then
            log_success "No packages to install"
            return 0
        fi
        read -ra packages <<< "$missing"
    fi

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would install: ${packages[*]}${NC}"
        return 0
    fi

    log_info "Updating package lists..."
    if ! apt-get update -qq; then
        log_error "Failed to update package lists"
        return 1
    fi

    log_info "Installing: ${packages[*]}"
    if ! apt-get install -y -qq "${packages[@]}"; then
        log_error "Failed to install packages"
        return 1
    fi

    log_success "Packages installed successfully"
    return 0
}

# Check if droneshow user exists
check_user_exists() {
    log_step "Checking for '${MDS_USER}' user..."

    if user_exists "${MDS_USER}"; then
        log_success "User '${MDS_USER}' exists"
        state_set_value "user_exists" "true"
        return 0
    fi

    log_warn "User '${MDS_USER}' does not exist"
    state_set_value "user_exists" "false"
    return 1
}

# Create the droneshow user
create_mds_user() {
    log_step "Creating '${MDS_USER}' user..."

    if user_exists "${MDS_USER}"; then
        log_success "User '${MDS_USER}' already exists"
        return 0
    fi

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would create user: ${MDS_USER}${NC}"
        return 0
    fi

    # Create user with home directory
    if ! useradd -m -s /bin/bash "${MDS_USER}"; then
        log_error "Failed to create user '${MDS_USER}'"
        return 1
    fi

    # Add to necessary groups
    local groups=("gpio" "dialout" "video" "audio")
    for group in "${groups[@]}"; do
        if getent group "$group" &>/dev/null; then
            usermod -aG "$group" "${MDS_USER}" 2>/dev/null || true
        fi
    done

    log_success "User '${MDS_USER}' created successfully"
    state_set_value "user_exists" "true"
    return 0
}

# Check /home/droneshow directory
check_home_directory() {
    log_step "Checking home directory..."

    local home_dir="/home/${MDS_USER}"

    if [[ -d "$home_dir" ]]; then
        log_success "Home directory exists: $home_dir"
        return 0
    fi

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would create: $home_dir${NC}"
        return 0
    fi

    mkdir -p "$home_dir"
    chown "${MDS_USER}:${MDS_USER}" "$home_dir"
    chmod 755 "$home_dir"

    log_success "Home directory created: $home_dir"
    return 0
}

# =============================================================================
# MAIN PREREQUISITES RUNNER
# =============================================================================

# Run all prerequisites checks
run_prereqs_phase() {
    print_phase_header "1" "Prerequisites Check"

    set_led_state "BOOT_STARTED"

    local failed=0

    # Run all checks
    check_sudo_access || ((failed++))
    check_os || ((failed++))
    check_architecture || true  # Don't fail on architecture warnings
    check_raspberry_pi || true  # Don't fail if not RPi
    check_disk_space || ((failed++))
    check_internet || ((failed++))
    check_python_version || ((failed++))

    # Check packages
    if ! check_required_packages; then
        print_section "Package Installation"

        if [[ "${NON_INTERACTIVE:-false}" == "true" ]]; then
            install_missing_packages || ((failed++))
        else
            echo ""
            if confirm "Install missing packages?"; then
                install_missing_packages || ((failed++))
            else
                log_warn "Skipping package installation - some features may not work"
            fi
        fi
    fi

    # Check user
    if ! check_user_exists; then
        print_section "User Setup"

        if [[ "${NON_INTERACTIVE:-false}" == "true" ]]; then
            create_mds_user || ((failed++))
        else
            echo ""
            if confirm "Create '${MDS_USER}' user?"; then
                create_mds_user || ((failed++))
            else
                log_error "User '${MDS_USER}' is required"
                ((failed++))
            fi
        fi
    fi

    check_home_directory || ((failed++))

    # Create config directories
    ensure_dir "${MDS_CONFIG_DIR}" "root:root" "755"
    ensure_dir "${MDS_STATE_DIR}" "root:root" "755"

    echo ""
    if [[ $failed -eq 0 ]]; then
        log_success "All prerequisites satisfied"
        return 0
    else
        log_error "Prerequisites check failed ($failed issues)"
        return 1
    fi
}
