#!/usr/bin/env bash
# Read-only SDK admission for unattended source sync. Bootstrap owns first install;
# an existing deployment must stage a compatible environment before SDK migration.

resolve_sdk_sync_python() {
    local candidate=""
    if [[ -n "${MDS_PYTHON_BIN:-}" ]]; then
        if [[ "$MDS_PYTHON_BIN" == */* && ! -x "$MDS_PYTHON_BIN" ]]; then
            return 1
        fi
        command -v -- "$MDS_PYTHON_BIN"
        return
    fi
    local environment="${MDS_VENV_PATH:-${REPO_DIR}/venv}"
    for candidate in "$environment/bin/python3" "$environment/bin/python"; do
        if [[ -x "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

preflight_validate_mavsdk_sync_environment() {
    local component="SDK-MAINTENANCE" python=""
    if [[ ! -f "$REPO_DIR/config/mavsdk-runtime.json" ]]; then
        return 0
    fi
    if ! python=$(resolve_sdk_sync_python); then
        # Do not turn a fresh source-only bootstrap into an SDK migration.
        # Explicit but invalid environment selection is never a fresh install.
        if [[ -z "${MDS_PYTHON_BIN:-}${MDS_VENV_PATH:-}" &&
              ! -e "$REPO_DIR/venv" && ! -e "$REPO_DIR/mavsdk_server" ]]; then
            MAVSDK_RUNTIME_STATUS="bootstrap_pending"
            log_info "$component" "No existing SDK environment; initial setup owns environment creation"
            return 0
        fi
        MAVSDK_RUNTIME_STATUS="maintenance_required"
        log_warn "$component" "Selected SDK Python is unavailable; preserve the working deployment and repair its environment during grounded maintenance"
        return 1
    fi
    if [[ ! -f "$REPO_DIR/tools/mavsdk_runtime.py" ]] ||
       ! timeout 30 "$python" "$REPO_DIR/tools/mavsdk_runtime.py" python-check; then
        MAVSDK_RUNTIME_STATUS="maintenance_required"
        log_warn "$component" "SDK environment does not match pulled source; stage and verify a replacement environment before retrying sync. Server, packages and services have not been changed"
        return 1
    fi
    return 0
}
