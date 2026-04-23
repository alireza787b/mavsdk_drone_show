#!/bin/bash
#
# gcs_fast_forward_update.sh - constrained GCS fast-forward updater
#
# This script is intentionally narrow:
# - only fast-forward merges to the current tracking branch
# - no dependency install / frontend rebuild / repo repair
# - restart happens through the canonical linux_dashboard_start.sh launcher
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
START_SCRIPT="${REPO_ROOT}/app/linux_dashboard_start.sh"
UPDATE_LOG="${MDS_GCS_UPDATE_LOG:-/tmp/mds_gcs_update.log}"
RESTART_DELAY_SECONDS="${MDS_GCS_UPDATE_RESTART_DELAY_SECONDS:-2}"

TRACKING_BRANCH="${1:-}"
TARGET_MODE="${2:-}"

log() {
    local message="$1"
    printf '[%s] [gcs-runtime-update] %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$message" >> "$UPDATE_LOG"
}

fail() {
    local message="$1"
    log "ERROR: ${message}"
    exit 1
}

if [[ -z "$TRACKING_BRANCH" ]]; then
    fail "tracking branch argument is required"
fi

if [[ "$TARGET_MODE" != "sitl" && "$TARGET_MODE" != "real" ]]; then
    fail "target mode must be 'sitl' or 'real'"
fi

if [[ ! -x "$START_SCRIPT" ]]; then
    fail "launcher not found or not executable at ${START_SCRIPT}"
fi

cd "$REPO_ROOT"

current_commit="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
target_commit="$(git rev-parse --short "$TRACKING_BRANCH" 2>/dev/null || echo unknown)"
log "Starting controlled fast-forward update current=${current_commit} tracking=${TRACKING_BRANCH} target=${target_commit} mode=${TARGET_MODE}"

git merge --ff-only "$TRACKING_BRANCH" >> "$UPDATE_LOG" 2>&1 || fail "git merge --ff-only ${TRACKING_BRANCH} failed"

updated_commit="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
log "Fast-forward complete new_commit=${updated_commit}; relaunching through canonical launcher"

sleep "$RESTART_DELAY_SECONDS"
exec "$START_SCRIPT" --prod --"$TARGET_MODE" >> "$UPDATE_LOG" 2>&1
