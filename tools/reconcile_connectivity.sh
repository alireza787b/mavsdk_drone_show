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

normalize_smart_wifi_mode() {
    case "${1:-fleet-merge}" in
        observe|local|fleet-merge|fleet-strict)
            printf '%s\n' "$1"
            ;;
        manage|managed)
            printf 'fleet-merge\n'
            ;;
        manual)
            printf 'local\n'
            ;;
        disabled|none)
            printf 'observe\n'
            ;;
        "")
            printf 'fleet-merge\n'
            ;;
        *)
            return 1
            ;;
    esac
}

smart_wifi_service_mode() {
    case "${1:-fleet-merge}" in
        observe)
            printf 'observe\n'
            ;;
        local|fleet-merge|fleet-strict|manage|managed|"")
            printf 'manage\n'
            ;;
        disabled|none)
            printf 'disabled\n'
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
    printf '%s\n' "${MDS_SMART_WIFI_MANAGER_REF:-${MDS_DEFAULT_SMART_WIFI_MANAGER_REF:-v2.1.11}}"
}

smart_wifi_git() {
    local install_dir="${MDS_SMART_WIFI_MANAGER_INSTALL_DIR:-/opt/smart-wifi-manager}"
    git -c "safe.directory=${install_dir}" -C "${install_dir}" "$@"
}

smart_wifi_profile_hash() {
    local profile_path="$1"
    if [[ -z "${profile_path}" || ! -f "${profile_path}" ]]; then
        printf '\n'
        return 0
    fi
    python3 - "${profile_path}" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    sys.exit(1)
if not isinstance(payload, dict):
    sys.exit(1)

def as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}

def as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def normalize_mode(value):
    normalized = str(value or "").strip().lower()
    aliases = {
        "manage": "fleet-merge",
        "managed": "fleet-merge",
        "manual": "local",
        "none": "observe",
        "disabled": "observe",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in {"observe", "local", "fleet-merge", "fleet-strict"} else "fleet-merge"

def secret_status(profile):
    explicit = str(profile.get("secret_status") or "").strip().lower()
    if explicit in {"stored", "missing", "external file", "redacted"}:
        return explicit
    if any(str(profile.get(key) or "").strip() for key in ("password_file", "passphrase_file", "psk_file", "secret_file")):
        return "external file"
    if any(str(profile.get(key) or "").strip() for key in ("password", "passphrase", "psk", "secret")):
        return "stored"
    return "missing"

profiles = []
for profile in payload.get("profiles") or []:
    if not isinstance(profile, dict):
        continue
    profiles.append({
        "id": str(profile.get("id") or profile.get("ssid") or "").strip(),
        "ssid": str(profile.get("ssid") or "").strip(),
        "priority": as_int(profile.get("priority"), 0),
        "connection_name": str(profile.get("connection_name") or "").strip(),
        "autoconnect": as_bool(profile.get("autoconnect"), True),
        "disabled": as_bool(profile.get("disabled"), False),
        "notes": str(profile.get("notes") or "").strip(),
        "secret_status": secret_status(profile),
    })
profiles.sort(key=lambda item: (item["id"].lower(), item["ssid"].lower()))

canonical = {
    "version": as_int(payload.get("version"), 1),
    "mode": normalize_mode(payload.get("mode")),
    "interface": str(payload.get("interface") or "").strip(),
    "scan_interval_sec": as_int(payload.get("scan_interval_sec"), 0),
    "signal_switch_threshold": as_int(payload.get("signal_switch_threshold"), 0),
    "connect_timeout_sec": as_int(payload.get("connect_timeout_sec"), 0),
    "cooldown_sec": as_int(payload.get("cooldown_sec"), 0),
    "allow_open_networks": as_bool(payload.get("allow_open_networks"), False),
    "profiles": profiles,
}
blob = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
print(hashlib.sha256(blob).hexdigest())
PY
}

smart_wifi_hash_input() {
    local profile_path="$1"
    local install_dir="${MDS_SMART_WIFI_MANAGER_INSTALL_DIR:-/opt/smart-wifi-manager}"
    local mode service_mode
    local import_mode="${MDS_SMART_WIFI_MANAGER_IMPORT_MODE:-merge}"
    local dashboard_listen="${MDS_SMART_WIFI_MANAGER_DASHBOARD_LISTEN:-127.0.0.1:9080}"
    local repo_url repo_ref skip_dashboard
    mode="$(normalize_smart_wifi_mode "${MDS_SMART_WIFI_MANAGER_MODE:-fleet-merge}")" || return 1
    repo_url="$(resolve_smart_wifi_repo_url)"
    repo_ref="$(resolve_smart_wifi_ref)"
    skip_dashboard="${MDS_SMART_WIFI_MANAGER_SKIP_DASHBOARD:-false}"
    local payload
    payload="mode=${mode};import_mode=${import_mode};install_dir=${install_dir};dashboard=${dashboard_listen};repo=${repo_url};ref=${repo_ref};skip_dashboard=${skip_dashboard}"

    if [[ -n "${profile_path}" && -f "${profile_path}" ]]; then
        payload="${payload};profile=$(smart_wifi_profile_hash "${profile_path}")"
    else
        payload="${payload};profile=none"
    fi

    printf '%s' "${payload}" | sha256sum | awk '{print $1}'
}

smart_wifi_service_profile_path() {
    local profile_path="$1"
    local temp_path
    if [[ -z "${profile_path}" || ! -f "${profile_path}" ]]; then
        printf '\n'
        return 0
    fi
    temp_path="$(mktemp "${TMPDIR:-/tmp}/mds-smart-wifi-profile.XXXXXX.json")" || return 1
    python3 - "${profile_path}" "${temp_path}" <<'PY'
import json
import sys
from pathlib import Path

source = Path(sys.argv[1])
target = Path(sys.argv[2])
payload = json.loads(source.read_text(encoding="utf-8"))
if isinstance(payload, dict):
    mode = str(payload.get("mode") or "").strip().lower()
    if mode in {"local", "fleet-merge", "fleet-strict", "manage", "managed"}:
        payload["mode"] = "manage"
    elif mode == "observe":
        payload["mode"] = "observe"
    elif mode in {"disabled", "none"}:
        payload["mode"] = "disabled"
target.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
PY
    printf '%s\n' "${temp_path}"
}

ensure_smart_wifi_manager_runtime() {
    local install_dir="${MDS_SMART_WIFI_MANAGER_INSTALL_DIR:-/opt/smart-wifi-manager}"
    local dashboard_listen="${MDS_SMART_WIFI_MANAGER_DASHBOARD_LISTEN:-127.0.0.1:9080}"
    local skip_dashboard="${MDS_SMART_WIFI_MANAGER_SKIP_DASHBOARD:-false}"
    local repo_url repo_ref install_args

    repo_url="$(resolve_smart_wifi_repo_url)"
    repo_ref="$(resolve_smart_wifi_ref)"

    if [[ -d "${install_dir}/.git" ]]; then
        if [[ -x "${install_dir}/configure_smart_wifi_manager.sh" ]]; then
            local current_ref=""
            current_ref="$(smart_wifi_git describe --tags --exact-match HEAD 2>/dev/null || true)"
            if [[ "${current_ref}" == "${repo_ref}" ]]; then
                log INFO "Smart Wi-Fi Manager runtime already at ${repo_ref}; skipping runtime fetch"
                return 0
            fi
        fi
        log INFO "Syncing Smart Wi-Fi Manager runtime (${repo_ref})"
        smart_wifi_git remote set-url origin "${repo_url}" >/dev/null 2>&1
        if ! smart_wifi_git fetch --depth 1 origin "${repo_ref}" >/dev/null 2>&1; then
            if [[ -x "${install_dir}/configure_smart_wifi_manager.sh" ]]; then
                log WARN "Smart Wi-Fi Manager runtime fetch failed; continuing with existing local runtime"
                return 0
            fi
            return 1
        fi
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
    local mode
    local import_mode="${MDS_SMART_WIFI_MANAGER_IMPORT_MODE:-merge}"
    local profile_path=""
    local import_profile_path=""
    local new_hash=""
    local old_hash=""
    local runtime_present="false"

    if ! mode="$(normalize_smart_wifi_mode "${MDS_SMART_WIFI_MANAGER_MODE:-fleet-merge}")"; then
        log ERROR "Unsupported Smart Wi-Fi Manager mode: ${MDS_SMART_WIFI_MANAGER_MODE:-}"
        return 1
    fi
    if ! service_mode="$(smart_wifi_service_mode "${mode}")"; then
        log ERROR "Unsupported Smart Wi-Fi Manager service mode for policy: ${mode}"
        return 1
    fi

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

    local cmd=("${configure_script}" --headless --config "${config_path}" --mode "${service_mode}")
    if [[ -n "${profile_path}" ]]; then
        if [[ ! -f "${profile_path}" ]]; then
            log ERROR "Configured Smart Wi-Fi Manager profile not found: ${profile_path}"
            return 1
        fi
        import_profile_path="$(smart_wifi_service_profile_path "${profile_path}")" || return 1
        cmd+=(--import "${import_profile_path}" --import-mode "${import_mode}")
    fi

    log INFO "Applying Smart Wi-Fi Manager configuration"
    if ! "${cmd[@]}"; then
        if [[ -n "${import_profile_path}" && "${import_profile_path}" != "${profile_path}" ]]; then
            rm -f "${import_profile_path}"
        fi
        return 1
    fi
    if [[ -n "${import_profile_path}" && "${import_profile_path}" != "${profile_path}" ]]; then
        rm -f "${import_profile_path}"
    fi

    mkdir -p "${STATE_DIR}"
    printf '%s\n' "${new_hash}" > "${STATE_FILE}"
    return 0
}

show_status() {
    local backend profile_path desired_hash applied_hash="" profile_hash="" mode=""
    backend="$(normalize_backend "${MDS_CONNECTIVITY_BACKEND:-none}" || echo "unknown")"
    echo "backend=${backend}"
    if [[ "${backend}" == "smart-wifi-manager" ]]; then
        profile_path="$(resolve_profile_path)"
        desired_hash="$(smart_wifi_hash_input "${profile_path}")"
        if [[ -f "${STATE_FILE}" ]]; then
            applied_hash="$(tr -d '\r\n' < "${STATE_FILE}")"
        fi
        if [[ -n "${profile_path}" && -f "${profile_path}" ]]; then
            profile_hash="$(smart_wifi_profile_hash "${profile_path}")"
        fi

        echo "repo_url=$(resolve_smart_wifi_repo_url)"
        echo "ref=$(resolve_smart_wifi_ref)"
        echo "install_dir=${MDS_SMART_WIFI_MANAGER_INSTALL_DIR:-/opt/smart-wifi-manager}"
        mode="$(normalize_smart_wifi_mode "${MDS_SMART_WIFI_MANAGER_MODE:-fleet-merge}" || echo "unknown")"
        echo "mode=${mode}"
        echo "import_mode=${MDS_SMART_WIFI_MANAGER_IMPORT_MODE:-merge}"
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
