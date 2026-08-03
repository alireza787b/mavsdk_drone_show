#!/bin/bash

# Shared path resolution for launchers that may run under minimal supervisors.
# Do not assign HOME here: callers keep the process environment unchanged and
# use the resolved value only for MDS-owned state and SSH support files.

[[ -n "${_MDS_SHELL_RUNTIME_PATHS_LOADED:-}" ]] && return 0
_MDS_SHELL_RUNTIME_PATHS_LOADED=1

mds_resolve_user_home() {
    local candidate="${MDS_USER_HOME:-${HOME:-}}"
    if [[ -n "$candidate" ]]; then
        printf '%s\n' "$candidate"
        return 0
    fi

    local current_uid=""
    local passwd_home=""
    current_uid="$(id -u 2>/dev/null || true)"
    if [[ -n "$current_uid" ]] && command -v getent >/dev/null 2>&1; then
        passwd_home="$(getent passwd "$current_uid" 2>/dev/null | cut -d: -f6 || true)"
    fi
    if [[ -z "$passwd_home" && -n "$current_uid" && -r /etc/passwd ]]; then
        passwd_home="$(awk -F: -v uid="$current_uid" '$3 == uid { print $6; exit }' /etc/passwd)"
    fi
    [[ -n "$passwd_home" ]] || return 1
    printf '%s\n' "$passwd_home"
}
