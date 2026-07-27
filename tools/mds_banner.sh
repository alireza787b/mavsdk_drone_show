#!/bin/bash
# =============================================================================
# MDS Unified Banner - Shared across all initialization scripts
# =============================================================================
# Version: Reads from VERSION file
# Description: Provides consistent branding and version display for all MDS scripts
# Author: MDS Team
# =============================================================================

# Prevent double-sourcing
[[ -n "${_MDS_BANNER_LOADED:-}" ]] && return 0
_MDS_BANNER_LOADED=1

# =============================================================================
# VERSION
# =============================================================================
_MDS_BANNER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MDS_BANNER_VERSION_FILE="$(cd "${_MDS_BANNER_DIR}/.." && pwd)/VERSION"
readonly MDS_BANNER_VERSION="$(
    if [[ -f "${_MDS_BANNER_VERSION_FILE}" ]]; then
        tr -d '[:space:]' < "${_MDS_BANNER_VERSION_FILE}"
    else
        printf 'unknown'
    fi
)"

# =============================================================================
# BANNER FUNCTION
# =============================================================================

# Print the unified MDS banner with optional context and version info
# Usage: print_mds_banner "Context" "version" "branch" "commit"
print_mds_banner() {
    local context="${1:-MDS}"
    local version="${2:-}"
    local branch="${3:-}"
    local commit="${4:-}"

    # Use colors if available (check if they're defined)
    local cyan="${CYAN:-}"
    local nc="${NC:-}"
    local white="${WHITE:-}"
    local dim="${DIM:-}"

    echo ""
    echo -e "${cyan},--.   ,--.,------.   ,---.   ${nc}"
    echo -e "${cyan}|   \`.'   ||  .-.  \\ '   .-'  ${nc}"
    echo -e "${cyan}|  |'.'|  ||  |  \\  :\`.  \`-.  ${nc}"
    echo -e "${cyan}|  |   |  ||  '--'  /.-'    | ${nc}"
    echo -e "${cyan}\`--'   \`--'\`-------' \`-----'  ${nc}"
    echo ""
    echo -e "${white}MDS - Mission-Directed Swarm - ${context}${nc}"
    echo "================================================"
    [[ -n "$version" ]] && echo -e "Version:  ${white}$version${nc}"
    [[ -n "$branch" ]]  && echo -e "Branch:   ${white}$branch${nc}"
    [[ -n "$commit" ]]  && echo -e "Commit:   ${white}$commit${nc}"
    [[ -n "$version" ]] && echo "================================================"
    echo ""
}

# =============================================================================
# GIT INFO FUNCTION
# =============================================================================

# Get git information from a directory
# Usage: get_git_info "/path/to/repo"
# Returns: "branch|commit|date" (pipe-separated)
get_git_info() {
    local install_dir="${1:-.}"
    local branch commit date

    if [[ -d "$install_dir/.git" ]]; then
        branch=$(cd "$install_dir" && git branch --show-current 2>/dev/null || echo "unknown")
        commit=$(cd "$install_dir" && git rev-parse --short HEAD 2>/dev/null || echo "unknown")
        date=$(cd "$install_dir" && git log -1 --format=%ci 2>/dev/null | cut -d' ' -f1 || echo "unknown")
        echo "${branch}|${commit}|${date}"
    else
        echo "unknown|unknown|unknown"
    fi
}

# =============================================================================
# EXPORT
# =============================================================================
export MDS_BANNER_VERSION
