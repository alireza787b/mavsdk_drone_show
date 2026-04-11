#!/bin/bash
# =============================================================================
# MDS Initialization Library: MAVSDK Binary
# =============================================================================
# Version: 4.4.1
# Description: MAVSDK server binary download and configuration
# Author: MDS Team
# =============================================================================

# Prevent double-sourcing
[[ -n "${_MDS_MAVSDK_LOADED:-}" ]] && return 0
_MDS_MAVSDK_LOADED=1

# =============================================================================
# CONSTANTS
# =============================================================================

readonly MAVSDK_BINARY="${MDS_INSTALL_DIR}/mavsdk_server"
readonly MAVSDK_GITHUB_API="https://api.github.com/repos/mavlink/MAVSDK/releases/latest"
readonly MAVSDK_FALLBACK_VERSION="v3.15.0"

# =============================================================================
# VERSION DETECTION
# =============================================================================

# Fetch latest MAVSDK version from GitHub API
fetch_latest_version() {
    log_step "Fetching latest MAVSDK version..."

    local version
    version=$(curl -s --max-time 10 "${MAVSDK_GITHUB_API}" | jq -r '.tag_name' 2>/dev/null)

    if [[ -n "$version" && "$version" != "null" ]]; then
        log_success "Latest version: $version"
        echo "$version"
        return 0
    fi

    log_warn "Failed to fetch latest version, using fallback: ${MAVSDK_FALLBACK_VERSION}"
    echo "${MAVSDK_FALLBACK_VERSION}"
    return 0
}

# Get currently installed MAVSDK version
get_installed_version() {
    if [[ -x "${MAVSDK_BINARY}" ]]; then
        "${MAVSDK_BINARY}" --version 2>/dev/null | head -1 | grep -oP 'v[\d.]+' || echo ""
    else
        echo ""
    fi
}

# =============================================================================
# ARCHITECTURE DETECTION
# =============================================================================

resolve_mavsdk_binary_name() {
    case "${1:-}" in
        arm64)
            printf '%s\n' "mavsdk_server_linux-arm64-musl"
            ;;
        armhf)
            printf '%s\n' "mavsdk_server_linux-armv7l-musl"
            ;;
        x86_64)
            printf '%s\n' "mavsdk_server_musl_x86_64"
            ;;
        *)
            return 1
            ;;
    esac
}

# Get MAVSDK binary name for current architecture
get_mavsdk_binary_name() {
    local arch
    arch=$(get_architecture)

    local binary_name
    binary_name=$(resolve_mavsdk_binary_name "$arch") || {
        log_error "Unsupported architecture for MAVSDK: $arch"
        return 1
    }

    printf '%s\n' "$binary_name"
}

# Construct download URL
construct_download_url() {
    local version="$1"
    local binary_name="$2"

    echo "https://github.com/mavlink/MAVSDK/releases/download/${version}/${binary_name}"
}

# =============================================================================
# DOWNLOAD AND INSTALLATION
# =============================================================================

# Download MAVSDK binary
download_mavsdk_binary() {
    local url="$1"
    local output="${MAVSDK_BINARY}"

    log_step "Downloading MAVSDK binary..."
    log_info "URL: $url"

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would download: ${url}${NC}"
        echo -e "  ${DIM}[DRY-RUN] To: ${output}${NC}"
        return 0
    fi

    # Create temp file for download
    local tmp_file="${output}.tmp"

    # Download with progress
    if curl -L --progress-bar --fail --max-time 120 \
        -o "${tmp_file}" "${url}"; then

        # Move to final location
        mv "${tmp_file}" "${output}"
        chmod +x "${output}"
        chown "${MDS_USER}:${MDS_USER}" "${output}"

        log_success "MAVSDK binary downloaded"
        return 0
    fi

    # Cleanup on failure
    rm -f "${tmp_file}"
    log_error "Failed to download MAVSDK binary"
    return 1
}

# Verify MAVSDK binary works
verify_mavsdk_binary() {
    log_step "Verifying MAVSDK binary..."

    if [[ ! -f "${MAVSDK_BINARY}" ]]; then
        log_error "MAVSDK binary not found: ${MAVSDK_BINARY}"
        return 1
    fi

    if [[ ! -x "${MAVSDK_BINARY}" ]]; then
        log_error "MAVSDK binary is not executable"
        return 1
    fi

    # Test that it runs
    local version
    version=$("${MAVSDK_BINARY}" --version 2>&1 | head -1)

    if [[ -n "$version" ]]; then
        log_success "MAVSDK binary verified: $version"
        state_set_value "mavsdk_version" "$version"
        return 0
    fi

    log_error "MAVSDK binary verification failed"
    return 1
}

# =============================================================================
# UPDATE LOGIC
# =============================================================================

# Check if update is needed
check_update_needed() {
    local target_version="$1"
    local installed_version

    installed_version=$(get_installed_version)

    if [[ -z "$installed_version" ]]; then
        log_info "MAVSDK not installed"
        return 0  # Needs install
    fi

    if [[ "$installed_version" == "$target_version" ]]; then
        log_info "MAVSDK is up to date: $installed_version"
        return 1  # No update needed
    fi

    log_info "Update available: $installed_version -> $target_version"
    return 0  # Needs update
}

# =============================================================================
# MAIN MAVSDK RUNNER
# =============================================================================

run_mavsdk_phase() {
    print_phase_header "8" "MAVSDK Binary"

    # Check skip flag
    if [[ "${SKIP_MAVSDK:-false}" == "true" ]]; then
        log_info "Skipping MAVSDK installation (--skip-mavsdk)"
        return 0
    fi

    print_section "Version Detection"

    # Determine target version
    local target_version
    if [[ -n "${MAVSDK_VERSION:-}" ]]; then
        # User specified version
        target_version="${MAVSDK_VERSION}"
        log_info "Using specified version: $target_version"
    elif [[ -n "${MAVSDK_URL:-}" ]]; then
        # User specified direct URL
        log_info "Using direct URL: ${MAVSDK_URL}"
        target_version="custom"
    else
        # Auto-detect latest
        target_version=$(fetch_latest_version)
    fi

    # Check current installation
    local installed_version
    installed_version=$(get_installed_version)

    if [[ -n "$installed_version" ]]; then
        echo ""
        echo -e "  ${INFO} Currently installed: ${GREEN}$installed_version${NC}"
        echo -e "  ${INFO} Target version: ${CYAN}$target_version${NC}"
        echo ""
    fi

    # Check if update needed
    if [[ -z "${MAVSDK_URL:-}" ]] && ! check_update_needed "$target_version"; then
        if [[ "${NON_INTERACTIVE:-false}" != "true" ]]; then
            if ! confirm "Force reinstall anyway?" "n"; then
                verify_mavsdk_binary && return 0
            fi
        else
            verify_mavsdk_binary && return 0
        fi
    fi

    print_section "Architecture Detection"

    # Get architecture-specific binary name
    local binary_name
    binary_name=$(get_mavsdk_binary_name)

    if [[ -z "$binary_name" ]]; then
        return 1
    fi

    local arch
    arch=$(get_architecture)
    log_success "Architecture: $arch -> $binary_name"

    print_section "Download"

    # Construct or use provided URL
    local download_url
    if [[ -n "${MAVSDK_URL:-}" ]]; then
        download_url="${MAVSDK_URL}"
    else
        download_url=$(construct_download_url "$target_version" "$binary_name")
    fi

    # Download binary
    if ! download_mavsdk_binary "$download_url"; then
        log_error "MAVSDK download failed"

        # Offer fallback version
        if [[ "$target_version" != "${MAVSDK_FALLBACK_VERSION}" ]]; then
            echo ""
            log_info "Trying fallback version: ${MAVSDK_FALLBACK_VERSION}"
            download_url=$(construct_download_url "${MAVSDK_FALLBACK_VERSION}" "$binary_name")

            if ! download_mavsdk_binary "$download_url"; then
                log_error "Fallback download also failed"
                return 1
            fi
        else
            return 1
        fi
    fi

    print_section "Verification"

    # Verify the binary
    verify_mavsdk_binary || return 1

    log_success "MAVSDK installation complete"
    return 0
}
