#!/bin/bash
# Expert, opt-in Docker limits. Never change aircraft/mission admission policy.

sitl_configure_resource_limits() {
    DOCKER_RESOURCE_ARGS=()
    local prefix="${1:-MDS_SITL_DOCKER}"
    local memory_key="${prefix}_MEMORY" swap_key="${prefix}_MEMORY_SWAP"
    local cpu_key="${prefix}_CPUS" pids_key="${prefix}_PIDS_LIMIT"
    local memory="${!memory_key:-}" swap="${!swap_key:-}"
    local cpus="${!cpu_key:-}" pids="${!pids_key:-}"
    local value

    for value in "$memory" "$swap"; do
        if [[ -n "$value" && ! "$value" =~ ^[1-9][0-9]*[bBkKmMgG]?$ ]]; then
            printf 'Error: SITL memory limits must be positive Docker sizes, e.g. 2g.\n' >&2
            return 1
        fi
    done
    if [[ -n "$swap" && -z "$memory" ]]; then
        printf 'Error: %s requires %s.\n' "$swap_key" "$memory_key" >&2
        return 1
    fi
    if [[ -n "$cpus" ]]; then
        if [[ ! "$cpus" =~ ^([0-9]+([.][0-9]+)?|[.][0-9]+)$ ]] ||
                ! awk -v value="$cpus" 'BEGIN { exit !(value > 0) }'; then
            printf 'Error: %s must be a positive number.\n' "$cpu_key" >&2
            return 1
        fi
        DOCKER_RESOURCE_ARGS+=(--cpus "$cpus")
    fi
    if [[ -n "$pids" ]]; then
        if [[ ! "$pids" =~ ^[1-9][0-9]*$ ]]; then
            printf 'Error: %s must be a positive integer.\n' "$pids_key" >&2
            return 1
        fi
        DOCKER_RESOURCE_ARGS+=(--pids-limit "$pids")
    fi
    [[ -z "$memory" ]] || DOCKER_RESOURCE_ARGS+=(--memory "$memory")
    [[ -z "$swap" ]] || DOCKER_RESOURCE_ARGS+=(--memory-swap "$swap")
    return 0
}
