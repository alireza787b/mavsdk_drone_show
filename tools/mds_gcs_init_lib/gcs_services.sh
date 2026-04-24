#!/bin/bash
# =============================================================================
# MDS GCS Initialization Library: Services
# =============================================================================
# Version: 1.0.0
# Description: Reconcile GCS-side system services after env configuration
# Author: MDS Team
# =============================================================================

# Prevent double-sourcing
[[ -n "${_MDS_GCS_SERVICES_LOADED:-}" ]] && return 0
_MDS_GCS_SERVICES_LOADED=1

gcs_git_sync_service_user() {
    printf '%s\n' "${MDS_GCS_RUNTIME_USER:-$(id -un 2>/dev/null || echo root)}"
}

gcs_git_sync_service_home() {
    if [[ -n "${MDS_GCS_RUNTIME_HOME:-}" ]]; then
        printf '%s\n' "${MDS_GCS_RUNTIME_HOME}"
        return 0
    fi

    local runtime_user="${1:-$(gcs_git_sync_service_user)}"
    local passwd_home=""
    passwd_home="$(getent passwd "$runtime_user" 2>/dev/null | cut -d: -f6 || true)"
    if [[ -n "$passwd_home" ]]; then
        printf '%s\n' "$passwd_home"
    else
        printf '/root\n'
    fi
}

install_gcs_git_sync_service() {
    local install_dir="${GCS_INSTALL_DIR:-$(pwd)}"
    local installer="${install_dir}/tools/git_sync_mds/install_git_sync_mds.sh"
    local runtime_user
    runtime_user="$(gcs_git_sync_service_user)"
    local runtime_home
    runtime_home="$(gcs_git_sync_service_home "$runtime_user")"

    log_step "Reconciling git_sync_mds.service..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would run: MDS_HOME=${runtime_home} MDS_INSTALL_DIR=${install_dir} ${installer} ${runtime_user}${NC}"
        return 0
    fi

    if [[ ! -f "$installer" ]]; then
        log_error "Git sync service installer not found: $installer"
        return 1
    fi

    env \
        MDS_USER="$runtime_user" \
        MDS_HOME="$runtime_home" \
        MDS_INSTALL_DIR="$install_dir" \
        bash "$installer" "$runtime_user"
}

run_services_phase() {
    print_phase_header "9" "Services" "10"

    if [[ "${SKIP_SERVICES:-false}" == "true" ]]; then
        log_info "Skipping services phase (--skip-services)"
        return 0
    fi

    print_section "System Service Reconciliation"
    install_gcs_git_sync_service || return 1

    log_success "GCS services phase completed"
    return 0
}
