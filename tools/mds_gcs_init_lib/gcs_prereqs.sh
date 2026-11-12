#!/bin/bash
# =============================================================================
# MDS GCS Initialization Library: Prerequisites
# =============================================================================
# Version: 1.0.0
# Description: System validation, base packages, directory creation
# Author: MDS Team
# =============================================================================

# Prevent double-sourcing
[[ -n "${_MDS_GCS_PREREQS_LOADED:-}" ]] && return 0
_MDS_GCS_PREREQS_LOADED=1

# =============================================================================
# CONSTANTS
# =============================================================================

readonly -a GCS_BASE_PACKAGES=(
    "git"
    "curl"
    "wget"
    "jq"
    "iputils-ping"
    "ufw"
    "tmux"
    "lsof"
    "build-essential"
    "software-properties-common"
    "apt-transport-https"
    "ca-certificates"
    "gnupg"
)

readonly -a GCS_SUPPORTED_UBUNTU_VERSIONS=("20.04" "22.04" "24.04")
readonly -a GCS_SUPPORTED_ARCHITECTURES=("x86_64" "arm64" "aarch64")
readonly GCS_MIN_DISK_SPACE_GB=5
readonly GCS_MIN_RAM_MB=2048
readonly GCS_RECOMMENDED_RAM_MB=4096

# =============================================================================
# SYSTEM CHECKS
# =============================================================================

# Check Bash version (need 4.0+ for associative arrays)
check_bash_version() {
    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would check Bash version (minimum 4.0)${NC}"
        return 0
    fi

    local bash_version="${BASH_VERSION%%.*}"
    log_debug "Detected Bash version: $BASH_VERSION"

    if [[ "$bash_version" -lt 4 ]]; then
        log_error "Bash 4.0+ required (found: $BASH_VERSION)"
        log_error "Associative arrays are used throughout this script"
        return 1
    fi
    log_success "Bash version OK: $BASH_VERSION"
    return 0
}

# Check if OS is supported
check_os_supported() {
    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would check OS compatibility${NC}"
        return 0
    fi

    local os_info
    os_info=$(get_os_info)
    local os_id="${os_info%%:*}"
    local os_version="${os_info##*:}"

    log_debug "Detected OS: $os_id $os_version"

    case "$os_id" in
        ubuntu)
            local supported=false
            for ver in "${GCS_SUPPORTED_UBUNTU_VERSIONS[@]}"; do
                if [[ "$os_version" == "$ver" ]]; then
                    supported=true
                    break
                fi
            done
            if [[ "$supported" == "true" ]]; then
                log_success "Ubuntu $os_version is supported"
                return 0
            else
                log_warn "Ubuntu $os_version may not be fully tested (supported: ${GCS_SUPPORTED_UBUNTU_VERSIONS[*]})"
                return 0
            fi
            ;;
        debian)
            log_warn "Debian detected - Ubuntu is recommended, but Debian should work"
            return 0
            ;;
        *)
            log_error "Unsupported OS: $os_id. Ubuntu 20.04/22.04/24.04 recommended"
            return 1
            ;;
    esac
}

# Check system architecture
check_architecture() {
    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would check system architecture${NC}"
        return 0
    fi

    local arch
    arch=$(get_architecture)

    log_debug "Detected architecture: $arch"

    local supported=false
    for a in "${GCS_SUPPORTED_ARCHITECTURES[@]}"; do
        if [[ "$arch" == "$a" ]]; then
            supported=true
            break
        fi
    done

    if [[ "$supported" == "true" ]]; then
        log_success "Architecture $arch is supported"
        gcs_state_set_value "architecture" "$arch"
        return 0
    else
        log_error "Unsupported architecture: $arch"
        return 1
    fi
}

# Check available disk space
check_disk_space_prereq() {
    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would check disk space (min ${GCS_MIN_DISK_SPACE_GB}GB)${NC}"
        return 0
    fi

    local available_mb
    available_mb=$(get_disk_space_mb "/")
    local available_gb=$((available_mb / 1024))

    log_debug "Available disk space: ${available_gb}GB"

    if check_disk_space "$GCS_MIN_DISK_SPACE_GB" "/"; then
        log_success "Disk space: ${available_gb}GB available (minimum: ${GCS_MIN_DISK_SPACE_GB}GB)"
        return 0
    else
        log_error "Insufficient disk space: ${available_gb}GB available, ${GCS_MIN_DISK_SPACE_GB}GB required"
        return 1
    fi
}

# Check available RAM
check_ram_prereq() {
    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would check RAM (min ${GCS_MIN_RAM_MB}MB, recommended ${GCS_RECOMMENDED_RAM_MB}MB)${NC}"
        return 0
    fi

    local total_ram_kb total_ram_mb
    total_ram_kb=$(grep MemTotal /proc/meminfo | awk '{print $2}')
    total_ram_mb=$((total_ram_kb / 1024))

    log_debug "Available RAM: ${total_ram_mb}MB"

    if [[ $total_ram_mb -lt $GCS_MIN_RAM_MB ]]; then
        log_error "Insufficient RAM: ${total_ram_mb}MB available, ${GCS_MIN_RAM_MB}MB minimum required"
        return 1
    elif [[ $total_ram_mb -lt $GCS_RECOMMENDED_RAM_MB ]]; then
        log_warn "RAM: ${total_ram_mb}MB available (recommended: ${GCS_RECOMMENDED_RAM_MB}MB)"
        echo ""
        echo -e "  ${YELLOW}┌────────────────────────────────────────────────────────────────────────────┐${NC}"
        echo -e "  ${YELLOW}│${NC}  ${WHITE}⚠ LOW MEMORY WARNING${NC}"
        echo -e "  ${YELLOW}├────────────────────────────────────────────────────────────────────────────┤${NC}"
        echo -e "  ${YELLOW}│${NC}  Your system has ${total_ram_mb}MB RAM (recommended: ${GCS_RECOMMENDED_RAM_MB}MB)"
        echo -e "  ${YELLOW}│${NC}"
        echo -e "  ${YELLOW}│${NC}  ${WHITE}npm build may fail with 'JavaScript heap out of memory' error.${NC}"
        echo -e "  ${YELLOW}│${NC}  If this happens, you can:"
        echo -e "  ${YELLOW}│${NC}    1. Add swap space: ${CYAN}sudo fallocate -l 2G /swapfile${NC}"
        echo -e "  ${YELLOW}│${NC}       ${CYAN}sudo chmod 600 /swapfile && sudo mkswap /swapfile${NC}"
        echo -e "  ${YELLOW}│${NC}       ${CYAN}sudo swapon /swapfile${NC}"
        echo -e "  ${YELLOW}│${NC}    2. Or increase NODE_OPTIONS: ${CYAN}export NODE_OPTIONS='--max-old-space-size=1536'${NC}"
        echo -e "  ${YELLOW}│${NC}"
        echo -e "  ${YELLOW}└────────────────────────────────────────────────────────────────────────────┘${NC}"
        echo ""
        gcs_state_set_value "low_memory_warning" "true"
        return 0
    else
        log_success "RAM: ${total_ram_mb}MB available (recommended: ${GCS_RECOMMENDED_RAM_MB}MB)"
        return 0
    fi
}

# Check if running as root
check_root_prereq() {
    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would check root privileges${NC}"
        return 0
    fi

    if check_root; then
        log_success "Running as root"
        return 0
    else
        log_error "This script must be run as root (use sudo)"
        return 1
    fi
}

# Check network connectivity
check_network() {
    log_step "Checking network connectivity..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would check network connectivity${NC}"
        return 0
    fi

    # Try multiple endpoints
    local endpoints=("github.com" "archive.ubuntu.com" "deb.nodesource.com")
    local success=false

    for endpoint in "${endpoints[@]}"; do
        if ping -c 1 -W 5 "$endpoint" &>/dev/null; then
            success=true
            break
        fi
    done

    if [[ "$success" == "true" ]]; then
        log_success "Network connectivity verified"
        return 0
    else
        log_error "No network connectivity detected"
        return 1
    fi
}

# =============================================================================
# PACKAGE INSTALLATION
# =============================================================================

# Update package lists
update_package_lists() {
    log_step "Updating package lists..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would run: apt-get update${NC}"
        return 0
    fi

    start_progress "Updating package lists" "may take 1-2 min on slow connections"
    apt-get update -qq >/dev/null 2>&1
    local rc=$?
    stop_progress

    if [[ $rc -eq 0 ]]; then
        log_success "Package lists updated"
        return 0
    else
        log_warn "Package list update had warnings (continuing anyway)"
        return 0
    fi
}

# Install base packages
install_base_packages() {
    log_step "Installing base packages..."

    local packages_to_install=()

    for pkg in "${GCS_BASE_PACKAGES[@]}"; do
        if ! dpkg -l "$pkg" 2>/dev/null | grep -q "^ii"; then
            packages_to_install+=("$pkg")
        else
            log_debug "Package already installed: $pkg"
        fi
    done

    if [[ ${#packages_to_install[@]} -eq 0 ]]; then
        log_success "All base packages already installed"
        return 0
    fi

    log_info "Installing: ${packages_to_install[*]}"

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would install: ${packages_to_install[*]}${NC}"
        return 0
    fi

    start_progress "Installing ${#packages_to_install[@]} packages" "may take 1-3 min"
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${packages_to_install[@]}" >/dev/null 2>&1
    local rc=$?
    stop_progress

    if [[ $rc -eq 0 ]]; then
        log_success "Base packages installed"
        return 0
    else
        log_error "Failed to install some packages"
        return 1
    fi
}

# =============================================================================
# DIRECTORY CREATION
# =============================================================================

# Create required directories
create_directories() {
    log_step "Creating required directories..."

    local dirs=(
        "${MDS_STATE_DIR}"
        "${MDS_CONFIG_DIR}"
        "${MDS_LOG_DIR}"
    )

    if is_dry_run; then
        for dir in "${dirs[@]}"; do
            echo -e "  ${DIM}[DRY-RUN] Would create: $dir${NC}"
        done
        return 0
    fi

    for dir in "${dirs[@]}"; do
        if [[ ! -d "$dir" ]]; then
            mkdir -p "$dir"
            chmod 755 "$dir"
            log_debug "Created directory: $dir"
        fi
    done

    log_success "Required directories created"
    return 0
}

# =============================================================================
# MAIN PHASE RUNNER
# =============================================================================

run_prereqs_phase() {
    print_phase_header "1" "Prerequisites" "9"

    # Check skip flag
    if [[ "${SKIP_PREREQS:-false}" == "true" ]]; then
        log_info "Skipping prerequisites check (--skip-prereqs)"
        return 0
    fi

    print_section "System Validation"

    # Run system checks
    check_bash_version || return 1
    check_root_prereq || return 1
    check_os_supported || return 1
    check_architecture || return 1
    check_disk_space_prereq || return 1
    check_ram_prereq || return 1

    print_section "Network Check"
    check_network || return 1

    print_section "Directory Setup"
    create_directories || return 1

    print_section "Package Installation"
    update_package_lists || return 1
    install_base_packages || return 1

    # Store OS info in state
    local os_info
    os_info=$(get_os_info)
    gcs_state_set_value "os_id" "${os_info%%:*}"
    gcs_state_set_value "os_version" "${os_info##*:}"

    echo ""
    log_success "Prerequisites phase completed"
    return 0
}
