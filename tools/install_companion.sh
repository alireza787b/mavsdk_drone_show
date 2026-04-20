#!/bin/bash
# =============================================================================
# MDS Companion Computer Bootstrap Alias
# =============================================================================
# Description: Friendly public alias for install_mds_node.sh
#              Supports both local-repo execution and raw GitHub bootstrap use.
# =============================================================================

set -euo pipefail

SCRIPT_DIR=""
if [[ -n "${BASH_SOURCE[0]:-}" && "${BASH_SOURCE[0]}" != "bash" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

if [[ -n "$SCRIPT_DIR" && -f "${SCRIPT_DIR}/install_mds_node.sh" ]]; then
    exec "${SCRIPT_DIR}/install_mds_node.sh" "$@"
fi

REPO_URL="${MDS_REPO_URL:-https://github.com/alireza787b/mavsdk_drone_show.git}"
BRANCH="${MDS_BRANCH:-main-candidate}"

normalize_github_repo_path() {
    local spec="${1:-}"

    spec="${spec#https://github.com/}"
    spec="${spec#git@github.com:}"
    spec="${spec#github.com/}"
    spec="${spec%.git}"
    spec="${spec#/}"

    if [[ -z "$spec" ]]; then
        return 1
    fi

    if [[ "$spec" != */* ]]; then
        spec="${spec}/mavsdk_drone_show"
    fi

    printf '%s\n' "$spec"
}

REPO_PATH="$(normalize_github_repo_path "$REPO_URL" || echo "alireza787b/mavsdk_drone_show")"
RAW_URL="https://raw.githubusercontent.com/${REPO_PATH}/${BRANCH}/tools/install_mds_node.sh"
TMP_SCRIPT="$(mktemp /tmp/install_mds_node.XXXXXX.sh)"
trap 'rm -f "$TMP_SCRIPT"' EXIT

echo "[INFO] install_companion.sh is a public alias for install_mds_node.sh"
echo "[INFO] Fetching bootstrap from: ${RAW_URL}"

if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$RAW_URL" -o "$TMP_SCRIPT"
elif command -v wget >/dev/null 2>&1; then
    wget -qO "$TMP_SCRIPT" "$RAW_URL"
else
    echo "[ERROR] curl or wget is required to fetch install_mds_node.sh" >&2
    exit 1
fi

chmod +x "$TMP_SCRIPT"
exec bash "$TMP_SCRIPT" "$@"
