#!/bin/bash
# Companion bootstrap uses the same reviewed manifest as SITL and git-sync.
[[ -n "${_MDS_MAVSDK_LOADED:-}" ]] && return 0
_MDS_MAVSDK_LOADED=1
readonly MAVSDK_BINARY="${MDS_INSTALL_DIR}/mavsdk_server"
MAVSDK_LIBRARY_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

get_pinned_mavsdk_version() {
    python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["server"]["version"])' \
        "${MAVSDK_LIBRARY_REPO}/config/mavsdk-runtime.json"
}

# Retain the old function name for shell callers, but never resolve live latest.
fetch_latest_version() {
    log_warn "MAVSDK uses the reviewed compatibility manifest, not automatic latest" >&2
    get_pinned_mavsdk_version
}

get_installed_version() {
    local version expected_hash actual_hash
    version=$(state_get_value "mavsdk_version" "")
    expected_hash=$(state_get_value "mavsdk_sha256" "")
    if [[ -x "${MAVSDK_BINARY}" && -n "$version" && -n "$expected_hash" ]]; then
        actual_hash=$(sha256sum "${MAVSDK_BINARY}" | awk '{print $1}')
        [[ "$actual_hash" != "$expected_hash" ]] || printf '%s\n' "$version"
    fi
    return 0
}

resolve_mavsdk_binary_name() {
    local architecture="${1:-}"
    python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); a={"arm64":"aarch64","armhf":"armv7l"}.get(sys.argv[2],sys.argv[2]); print(m["server"]["assets"][a]["name"])' \
        "${MAVSDK_LIBRARY_REPO}/config/mavsdk-runtime.json" "$architecture"
}

get_mavsdk_binary_name() {
    resolve_mavsdk_binary_name "$(get_architecture)"
}

verify_mavsdk_binary() {
    [[ -x "${MAVSDK_BINARY}" ]] || return 1
    # This CLI probe is deliberately not a claim of version/pair compatibility.
    timeout --kill-after=1s 5s "${MAVSDK_BINARY}" --help >/dev/null 2>&1
}

run_mavsdk_phase() {
    print_phase_header "8" "MAVSDK Binary"
    if [[ "${SKIP_MAVSDK:-false}" == "true" ]]; then
        log_warn "Skipping MAVSDK provisioning; compatibility is not verified"
        return 0
    fi
    local args=() provenance="${MDS_INSTALL_DIR}/runtime_data/mavsdk/provenance.json"
    [[ -z "${MAVSDK_VERSION:-}" ]] || args+=(--version "$MAVSDK_VERSION")
    [[ -z "${MAVSDK_URL:-}" ]] || args+=(--url "$MAVSDK_URL")
    if is_dry_run; then
        log_info "[DRY-RUN] Would verify/provision manifest-pinned MAVSDK (explicit overrides are custom)"
        return 0
    fi
    MDS_INSTALL_DIR="${MDS_INSTALL_DIR}" bash "${MDS_INSTALL_DIR}/tools/download_mavsdk_server.sh" "${args[@]}" || return 1
    chown "${MDS_USER}:${MDS_USER}" "${MAVSDK_BINARY}"
    local verified_version compatibility
    verified_version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["verified_server_version"] or "unverified")' "$provenance")
    compatibility=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["compatibility"])' "$provenance")
    state_set_value "mavsdk_version" "$verified_version"
    state_set_value "mavsdk_sha256" "$(sha256sum "${MAVSDK_BINARY}" | awk '{print $1}')"
    state_set_value "mavsdk_compatibility" "$compatibility"
    [[ "$compatibility" == pinned ]] || log_warn "Custom MAVSDK artifact: $compatibility (not the default reviewed pair)"
    log_success "MAVSDK server: $verified_version ($compatibility)"
}
