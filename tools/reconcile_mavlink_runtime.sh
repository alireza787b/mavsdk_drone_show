#!/bin/bash
#
# Reconcile managed mavlink-anywhere runtime ownership for an MDS node.
#
# This script intentionally manages only the external tool checkout/install and
# optional dashboard service. It does not synthesize a fresh router profile from
# scratch; node-specific MAVLink input configuration still belongs to bootstrap
# or explicit operator reconfiguration.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOCAL_ENV_FILE="${MDS_LOCAL_ENV_FILE:-/etc/mds/local.env}"
STATE_DIR="${MDS_MAVLINK_STATE_DIR:-/var/lib/mds/mavlink-runtime}"
STATE_FILE="${STATE_DIR}/mavlink_anywhere_runtime.sha256"
ROUTER_CONFIG_FILE="${MAVLINK_ROUTER_CONFIG:-/etc/mavlink-router/main.conf}"
QUIET=false
FORCE=false

log() {
    local level="$1"
    local message="$2"
    if [[ "${QUIET}" != "true" ]]; then
        printf '[%s] %s\n' "${level}" "${message}"
    fi
}

load_runtime_env() {
    local deployment_loader="${REPO_DIR}/tools/load_deployment_profile.sh"
    if [[ -f "${deployment_loader}" ]]; then
        export MDS_REPO_ROOT="${REPO_DIR}"
        # shellcheck source=/dev/null
        source "${deployment_loader}"
    fi

    if [[ -f "${LOCAL_ENV_FILE}" ]]; then
        set -a
        # shellcheck source=/dev/null
        source "${LOCAL_ENV_FILE}"
        set +a
    fi
}

normalize_management_mode() {
    case "${1:-local}" in
        fleet-merge|fleet-strict|observe|local)
            printf '%s\n' "$1"
            ;;
        managed)
            printf 'fleet-merge\n'
            ;;
        manual|disabled|skip|none)
            printf 'local\n'
            ;;
        "")
            printf 'local\n'
            ;;
        *)
            return 1
            ;;
    esac
}

resolve_repo_url() {
    if [[ -n "${MDS_MAVLINK_ANYWHERE_REPO_URL:-}" ]]; then
        printf '%s\n' "${MDS_MAVLINK_ANYWHERE_REPO_URL}"
        return 0
    fi

    if [[ -n "${MDS_DEFAULT_MAVLINK_ANYWHERE_REPO_URL_HTTPS:-}" ]]; then
        printf '%s\n' "${MDS_DEFAULT_MAVLINK_ANYWHERE_REPO_URL_HTTPS}"
        return 0
    fi

    local slug="${MDS_DEFAULT_MAVLINK_ANYWHERE_REPO_SLUG:-alireza787b/mavlink-anywhere}"
    printf 'https://github.com/%s.git\n' "${slug}"
}

resolve_repo_ref() {
    printf '%s\n' "${MDS_MAVLINK_ANYWHERE_REF:-${MDS_DEFAULT_MAVLINK_ANYWHERE_REF:-v3.0.10}}"
}

resolve_install_dir() {
    printf '%s\n' "${MDS_MAVLINK_ANYWHERE_INSTALL_DIR:-${MDS_DEFAULT_MAVLINK_ANYWHERE_INSTALL_DIR:-/opt/mavlink-anywhere}}"
}

resolve_dashboard_listen() {
    printf '%s\n' "${MDS_MAVLINK_ANYWHERE_DASHBOARD_LISTEN:-${MDS_DEFAULT_MAVLINK_ANYWHERE_DASHBOARD_LISTEN:-127.0.0.1:9070}}"
}

resolve_skip_dashboard() {
    printf '%s\n' "${MDS_MAVLINK_ANYWHERE_SKIP_DASHBOARD:-${MDS_DEFAULT_MAVLINK_ANYWHERE_SKIP_DASHBOARD:-false}}"
}

runtime_present() {
    local install_dir
    install_dir="$(resolve_install_dir)"
    [[ -d "${install_dir}/.git" ]] && [[ -x "${install_dir}/configure_mavlink_router.sh" ]]
}

router_binary_present() {
    command -v mavlink-routerd >/dev/null 2>&1 || [[ -x /usr/bin/mavlink-routerd ]] || [[ -x /usr/local/bin/mavlink-routerd ]]
}

runtime_git() {
    local install_dir
    install_dir="$(resolve_install_dir)"
    git -c "safe.directory=${install_dir}" -C "${install_dir}" "$@"
}

dashboard_ready() {
    local skip_dashboard
    local install_dir
    skip_dashboard="$(resolve_skip_dashboard)"
    if [[ "${skip_dashboard}" == "true" ]]; then
        return 0
    fi

    install_dir="$(resolve_install_dir)"
    if [[ ! -x "${install_dir}/mavlink-anywhere" ]]; then
        return 1
    fi

    systemctl is-enabled --quiet mavlink-anywhere-dashboard.service 2>/dev/null || \
        [[ -f /etc/systemd/system/mavlink-anywhere-dashboard.service ]]
}

mavlink_hash_input() {
    local mode repo_url repo_ref install_dir dashboard_listen skip_dashboard
    mode="$(normalize_management_mode "${MDS_MAVLINK_MANAGEMENT_MODE:-${MDS_DEFAULT_MAVLINK_MANAGEMENT_MODE:-local}}" || echo local)"
    repo_url="$(resolve_repo_url)"
    repo_ref="$(resolve_repo_ref)"
    install_dir="$(resolve_install_dir)"
    dashboard_listen="$(resolve_dashboard_listen)"
    skip_dashboard="$(resolve_skip_dashboard)"

    printf 'mode=%s;repo=%s;ref=%s;install=%s;dashboard=%s;skip_dashboard=%s' \
        "${mode}" "${repo_url}" "${repo_ref}" "${install_dir}" "${dashboard_listen}" "${skip_dashboard}" | \
        sha256sum | awk '{print $1}'
}

ensure_runtime_checkout() {
    local repo_url repo_ref install_dir
    repo_url="$(resolve_repo_url)"
    repo_ref="$(resolve_repo_ref)"
    install_dir="$(resolve_install_dir)"

    if [[ -d "${install_dir}/.git" ]]; then
        log INFO "Syncing managed mavlink-anywhere runtime (${repo_ref})"
        runtime_git remote set-url origin "${repo_url}" >/dev/null 2>&1
        runtime_git fetch --depth 1 origin "${repo_ref}" >/dev/null 2>&1
        runtime_git checkout -f FETCH_HEAD >/dev/null 2>&1
        return 0
    fi

    if [[ -e "${install_dir}" ]]; then
        log WARN "Replacing non-git mavlink-anywhere install at ${install_dir}"
        rm -rf "${install_dir}"
    fi

    log INFO "Installing managed mavlink-anywhere runtime (${repo_ref})"
    git clone --depth 1 --branch "${repo_ref}" "${repo_url}" "${install_dir}" >/dev/null 2>&1
}

install_router_if_needed() {
    local install_dir
    install_dir="$(resolve_install_dir)"

    if router_binary_present; then
        return 0
    fi

    if [[ ! -x "${install_dir}/install_mavlink_router.sh" ]]; then
        log ERROR "install_mavlink_router.sh not found in ${install_dir}"
        return 1
    fi

    log INFO "mavlink-router binary not found; running managed installer"
    (cd "${install_dir}" && bash ./install_mavlink_router.sh)
}

ensure_dashboard_runtime() {
    local install_dir repo_ref dashboard_listen skip_dashboard
    install_dir="$(resolve_install_dir)"
    repo_ref="$(resolve_repo_ref)"
    dashboard_listen="$(resolve_dashboard_listen)"
    skip_dashboard="$(resolve_skip_dashboard)"

    if [[ "${skip_dashboard}" == "true" ]]; then
        log INFO "Managed dashboard install is disabled for mavlink-anywhere"
        return 0
    fi

    if [[ -f "${install_dir}/lib/dashboard.sh" ]]; then
        log INFO "Reconciling managed mavlink-anywhere dashboard (${repo_ref})"
        (
            cd "${install_dir}"
            # shellcheck disable=SC1091
            source "./lib/dashboard.sh"
            install_dashboard_binary "${repo_ref}" || true
            setup_dashboard_service "${dashboard_listen}"
        )
        return $?
    fi

    if [[ -x "${install_dir}/configure_mavlink_router.sh" ]]; then
        log INFO "Installing/updating managed mavlink-anywhere dashboard"
        (cd "${install_dir}" && bash ./configure_mavlink_router.sh --install-dashboard --dashboard-listen "${dashboard_listen}")
        return $?
    fi

    log ERROR "No dashboard helper found in ${install_dir}"
    return 1
}

apply_runtime() {
    local mode new_hash old_hash=""
    mode="$(normalize_management_mode "${MDS_MAVLINK_MANAGEMENT_MODE:-${MDS_DEFAULT_MAVLINK_MANAGEMENT_MODE:-local}}" || echo local)"

    if [[ "${mode}" != "fleet-merge" && "${mode}" != "fleet-strict" ]]; then
        log INFO "MAVLink runtime ownership is ${mode}; nothing to reconcile"
        return 0
    fi

    new_hash="$(mavlink_hash_input)"
    if [[ -f "${STATE_FILE}" ]]; then
        old_hash="$(tr -d '\r\n' < "${STATE_FILE}")"
    fi

    if [[ "${FORCE}" != "true" && -n "${old_hash}" && "${old_hash}" == "${new_hash}" ]] && runtime_present && router_binary_present && dashboard_ready; then
        log INFO "Managed mavlink-anywhere runtime unchanged; skipping reconcile"
        return 0
    fi

    ensure_runtime_checkout || return 1
    install_router_if_needed || return 1
    ensure_dashboard_runtime || log WARN "Managed dashboard reconcile did not complete cleanly"

    if [[ ! -f "${ROUTER_CONFIG_FILE}" ]]; then
        log WARN "Managed mavlink-anywhere runtime is installed, but ${ROUTER_CONFIG_FILE} is missing"
        log WARN "Re-run bootstrap or configure_mavlink_router.sh when this host needs a router profile"
    fi

    mkdir -p "${STATE_DIR}"
    printf '%s\n' "${new_hash}" > "${STATE_FILE}"
    log INFO "Managed mavlink-anywhere runtime reconciled"
}

show_status() {
    local mode desired_hash applied_hash=""
    mode="$(normalize_management_mode "${MDS_MAVLINK_MANAGEMENT_MODE:-${MDS_DEFAULT_MAVLINK_MANAGEMENT_MODE:-local}}" || echo unknown)"
    desired_hash="$(mavlink_hash_input)"
    if [[ -f "${STATE_FILE}" ]]; then
        applied_hash="$(tr -d '\r\n' < "${STATE_FILE}")"
    fi

    echo "mode=${mode}"
    echo "repo_url=$(resolve_repo_url)"
    echo "ref=$(resolve_repo_ref)"
    echo "install_dir=$(resolve_install_dir)"
    echo "dashboard_listen=$(resolve_dashboard_listen)"
    echo "skip_dashboard=$(resolve_skip_dashboard)"
    echo "desired_config_hash=${desired_hash}"
    echo "applied_config_hash=${applied_hash:-unknown}"
    if [[ -n "${applied_hash}" && "${applied_hash}" == "${desired_hash}" ]]; then
        echo "config_hash_match=true"
    else
        echo "config_hash_match=false"
    fi

    if runtime_present; then
        echo "runtime_present=true"
        echo "runtime_head=$(runtime_git rev-parse --short HEAD 2>/dev/null || echo unknown)"
    else
        echo "runtime_present=false"
    fi

    if router_binary_present; then
        echo "router_binary=present"
    else
        echo "router_binary=missing"
    fi

    if systemctl is-active --quiet mavlink-router 2>/dev/null; then
        echo "router_service=active"
    elif systemctl is-enabled --quiet mavlink-router 2>/dev/null; then
        echo "router_service=enabled"
    else
        echo "router_service=absent"
    fi

    if systemctl is-active --quiet mavlink-anywhere-dashboard.service 2>/dev/null; then
        echo "dashboard_service=active"
    elif systemctl is-enabled --quiet mavlink-anywhere-dashboard.service 2>/dev/null; then
        echo "dashboard_service=enabled"
    else
        echo "dashboard_service=absent"
    fi
}

usage() {
    cat <<EOF
Usage: $0 <apply|status> [--force] [--quiet]
EOF
}

main() {
    local command="${1:-status}"
    shift || true

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --force) FORCE=true; shift ;;
            --quiet) QUIET=true; shift ;;
            -h|--help) usage; exit 0 ;;
            *) log ERROR "Unknown option: $1"; usage; exit 1 ;;
        esac
    done

    load_runtime_env

    case "${command}" in
        apply) apply_runtime ;;
        status) show_status ;;
        *) log ERROR "Unknown command: ${command}"; usage; exit 1 ;;
    esac
}

main "$@"
