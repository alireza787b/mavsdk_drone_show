#!/bin/bash
#
# Reconcile optional connectivity backends for an MDS node.
#
# This script is intentionally standalone so bootstrap, git_sync_mds, and
# recovery tooling can all reuse the same connectivity-apply logic.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOCAL_ENV_FILE="${MDS_LOCAL_ENV_FILE:-/etc/mds/local.env}"
STATE_DIR="/var/lib/mds/connectivity"
STATE_DIR="${MDS_CONNECTIVITY_STATE_DIR:-${STATE_DIR}}"
STATE_FILE="${STATE_DIR}/smart_wifi_manager_profile.sha256"
QUIET=false
FORCE=false

log() {
    local level="$1"
    local message="$2"
    if [[ "${QUIET}" != "true" ]]; then
        printf '[%s] %s\n' "$level" "$message"
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

normalize_backend() {
    case "${1:-none}" in
        none|manual|"")
            printf 'none\n'
            ;;
        smart-wifi-manager|smart_wifi_manager|smartwifi|wifi)
            printf 'smart-wifi-manager\n'
            ;;
        *)
            return 1
            ;;
    esac
}

resolve_profile_path() {
    local source="${MDS_SMART_WIFI_MANAGER_PROFILE_SOURCE:-}"
    local default_relative="${MDS_DEFAULT_SMART_WIFI_MANAGER_PROFILE_PATH:-deployment/connectivity/smart-wifi-manager/profile.json}"

    if [[ -z "${source}" && -f "${REPO_DIR}/${default_relative}" ]]; then
        source="repo:${default_relative}"
    fi

    case "${source}" in
        repo:*)
            printf '%s\n' "${REPO_DIR}/${source#repo:}"
            ;;
        file:*)
            printf '%s\n' "${source#file:}"
            ;;
        /*)
            printf '%s\n' "${source}"
            ;;
        "")
            printf '\n'
            ;;
        *)
            printf '%s\n' "${source}"
            ;;
    esac
}

resolve_smart_wifi_repo_url() {
    if [[ -n "${MDS_SMART_WIFI_MANAGER_REPO_URL:-}" ]]; then
        printf '%s\n' "${MDS_SMART_WIFI_MANAGER_REPO_URL}"
        return 0
    fi

    if [[ -n "${MDS_DEFAULT_SMART_WIFI_MANAGER_REPO_URL_HTTPS:-}" ]]; then
        printf '%s\n' "${MDS_DEFAULT_SMART_WIFI_MANAGER_REPO_URL_HTTPS}"
        return 0
    fi

    local slug="${MDS_DEFAULT_SMART_WIFI_MANAGER_REPO_SLUG:-alireza787b/smart-wifi-manager}"
    printf 'https://github.com/%s.git\n' "${slug}"
}

resolve_smart_wifi_ref() {
    printf '%s\n' "${MDS_SMART_WIFI_MANAGER_REF:-${MDS_DEFAULT_SMART_WIFI_MANAGER_REF:-v2.1.4}}"
}

smart_wifi_git() {
    local install_dir="${MDS_SMART_WIFI_MANAGER_INSTALL_DIR:-/opt/smart-wifi-manager}"
    git -c "safe.directory=${install_dir}" -C "${install_dir}" "$@"
}

smart_wifi_hash_input() {
    local profile_path="$1"
    local install_dir="${MDS_SMART_WIFI_MANAGER_INSTALL_DIR:-/opt/smart-wifi-manager}"
    local mode="${MDS_SMART_WIFI_MANAGER_MODE:-observe}"
    local import_mode="${MDS_SMART_WIFI_MANAGER_IMPORT_MODE:-replace}"
    local dashboard_listen="${MDS_SMART_WIFI_MANAGER_DASHBOARD_LISTEN:-127.0.0.1:9080}"
    local repo_url repo_ref skip_dashboard
    repo_url="$(resolve_smart_wifi_repo_url)"
    repo_ref="$(resolve_smart_wifi_ref)"
    skip_dashboard="${MDS_SMART_WIFI_MANAGER_SKIP_DASHBOARD:-false}"
    local payload
    payload="mode=${mode};import_mode=${import_mode};install_dir=${install_dir};dashboard=${dashboard_listen};repo=${repo_url};ref=${repo_ref};skip_dashboard=${skip_dashboard}"

    if [[ -n "${profile_path}" && -f "${profile_path}" ]]; then
        payload="${payload};profile=$(sha256sum "${profile_path}" | awk '{print $1}')"
    else
        payload="${payload};profile=none"
    fi

    printf '%s' "${payload}" | sha256sum | awk '{print $1}'
}

ensure_smart_wifi_manager_runtime() {
    local install_dir="${MDS_SMART_WIFI_MANAGER_INSTALL_DIR:-/opt/smart-wifi-manager}"
    local dashboard_listen="${MDS_SMART_WIFI_MANAGER_DASHBOARD_LISTEN:-127.0.0.1:9080}"
    local skip_dashboard="${MDS_SMART_WIFI_MANAGER_SKIP_DASHBOARD:-false}"
    local repo_url repo_ref install_args

    repo_url="$(resolve_smart_wifi_repo_url)"
    repo_ref="$(resolve_smart_wifi_ref)"

    if [[ -d "${install_dir}/.git" ]]; then
        log INFO "Syncing Smart Wi-Fi Manager runtime (${repo_ref})"
        smart_wifi_git remote set-url origin "${repo_url}" >/dev/null 2>&1
        smart_wifi_git fetch --depth 1 origin "${repo_ref}" >/dev/null 2>&1
        smart_wifi_git checkout -f FETCH_HEAD >/dev/null 2>&1
    else
        if [[ -e "${install_dir}" && ! -d "${install_dir}/.git" ]]; then
            log WARN "Replacing non-git Smart Wi-Fi Manager install at ${install_dir}"
            rm -rf "${install_dir}"
        fi
        log INFO "Installing Smart Wi-Fi Manager runtime (${repo_ref})"
        git clone --depth 1 --branch "${repo_ref}" "${repo_url}" "${install_dir}" >/dev/null 2>&1
    fi

    install_args=("--dashboard-listen" "${dashboard_listen}" "--dashboard-version" "${repo_ref}")
    if [[ "${skip_dashboard}" == "true" ]]; then
        install_args=("--skip-dashboard")
    fi

    (cd "${install_dir}" && bash ./install.sh "${install_args[@]}" >/dev/null 2>&1)
}

apply_smart_wifi_manager() {
    local install_dir="${MDS_SMART_WIFI_MANAGER_INSTALL_DIR:-/opt/smart-wifi-manager}"
    local configure_script="${install_dir}/configure_smart_wifi_manager.sh"
    local config_path="${MDS_SMART_WIFI_MANAGER_CONFIG_FILE:-/etc/smart-wifi-manager/config.json}"
    local mode="${MDS_SMART_WIFI_MANAGER_MODE:-observe}"
    local import_mode="${MDS_SMART_WIFI_MANAGER_IMPORT_MODE:-replace}"
    local profile_path=""
    local new_hash=""
    local old_hash=""
    local runtime_present="false"

    profile_path="$(resolve_profile_path)"
    new_hash="$(smart_wifi_hash_input "${profile_path}")"

    if [[ -f "${STATE_FILE}" ]]; then
        old_hash="$(tr -d '\r\n' < "${STATE_FILE}")"
    fi

    if [[ -x "${configure_script}" && -d "${install_dir}/.git" ]]; then
        runtime_present="true"
    fi

    if [[ "${FORCE}" != "true" && -n "${old_hash}" && "${old_hash}" == "${new_hash}" && "${runtime_present}" == "true" ]]; then
        log INFO "Connectivity profile unchanged; skipping Smart Wi-Fi Manager reconcile"
        return 0
    fi

    ensure_smart_wifi_manager_runtime || {
        log ERROR "Failed to install or update Smart Wi-Fi Manager runtime"
        return 1
    }

    if [[ ! -x "${configure_script}" ]]; then
        log ERROR "Smart Wi-Fi Manager config helper not found at ${configure_script}"
        return 1
    fi

    local cmd=("${configure_script}" --headless --config "${config_path}" --mode "${mode}")
    if [[ -n "${profile_path}" ]]; then
        if [[ ! -f "${profile_path}" ]]; then
            log ERROR "Configured Smart Wi-Fi Manager profile not found: ${profile_path}"
            return 1
        fi
        cmd+=(--import "${profile_path}" --import-mode "${import_mode}")
    fi

    log INFO "Applying Smart Wi-Fi Manager configuration"
    "${cmd[@]}"

    mkdir -p "${STATE_DIR}"
    printf '%s\n' "${new_hash}" > "${STATE_FILE}"
    return 0
}

show_status() {
    local backend profile_path desired_hash applied_hash="" profile_hash=""
    backend="$(normalize_backend "${MDS_CONNECTIVITY_BACKEND:-none}" || echo "unknown")"
    echo "backend=${backend}"
    if [[ "${backend}" == "smart-wifi-manager" ]]; then
        profile_path="$(resolve_profile_path)"
        desired_hash="$(smart_wifi_hash_input "${profile_path}")"
        if [[ -f "${STATE_FILE}" ]]; then
            applied_hash="$(tr -d '\r\n' < "${STATE_FILE}")"
        fi
        if [[ -n "${profile_path}" && -f "${profile_path}" ]]; then
            profile_hash="$(sha256sum "${profile_path}" | awk '{print $1}')"
        fi

        echo "repo_url=$(resolve_smart_wifi_repo_url)"
        echo "ref=$(resolve_smart_wifi_ref)"
        echo "install_dir=${MDS_SMART_WIFI_MANAGER_INSTALL_DIR:-/opt/smart-wifi-manager}"
        echo "mode=${MDS_SMART_WIFI_MANAGER_MODE:-observe}"
        echo "import_mode=${MDS_SMART_WIFI_MANAGER_IMPORT_MODE:-replace}"
        echo "profile_path=${profile_path}"
        echo "profile_hash=${profile_hash:-unknown}"
        echo "desired_config_hash=${desired_hash}"
        echo "applied_config_hash=${applied_hash:-unknown}"
        if [[ -n "${applied_hash}" && "${applied_hash}" == "${desired_hash}" ]]; then
            echo "config_hash_match=true"
        else
            echo "config_hash_match=false"
        fi
        echo "dashboard_listen=${MDS_SMART_WIFI_MANAGER_DASHBOARD_LISTEN:-127.0.0.1:9080}"
        echo "skip_dashboard=${MDS_SMART_WIFI_MANAGER_SKIP_DASHBOARD:-false}"
        if systemctl is-active --quiet smart-wifi-manager.service 2>/dev/null; then
            echo "service_status=active"
        elif systemctl is-enabled --quiet smart-wifi-manager.service 2>/dev/null; then
            echo "service_status=enabled"
        else
            echo "service_status=absent"
        fi
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

    local backend
    backend="$(normalize_backend "${MDS_CONNECTIVITY_BACKEND:-none}" || echo "unknown")"

    case "${command}" in
        status)
            show_status
            ;;
        apply)
            case "${backend}" in
                none)
                    log INFO "Connectivity backend is manual/none; nothing to apply"
                    ;;
                smart-wifi-manager)
                    apply_smart_wifi_manager
                    ;;
                *)
                    log ERROR "Unsupported connectivity backend: ${backend}"
                    exit 1
                    ;;
            esac
            ;;
        *)
            log ERROR "Unknown command: ${command}"
            usage
            exit 1
            ;;
    esac
}

main "$@"
