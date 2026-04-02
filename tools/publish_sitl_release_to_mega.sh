#!/bin/bash

set -euo pipefail

DEFAULT_ARTIFACT_DIR="${PWD}"
DEFAULT_ARCHIVE_BASENAME="${MDS_SITL_IMAGE_ARCHIVE_BASENAME:-mavsdk-drone-show-sitl-image}"
DEFAULT_MEGA_TARGET="${MDS_SITL_MEGA_TARGET:-/Root/mavsdk-drone-show-sitl}"
DEFAULT_IMAGE_REPO="${MDS_SITL_IMAGE_REPO:-mavsdk-drone-show-sitl}"
DEFAULT_VERSION_TAG="${MDS_SITL_VERSION_TAG:-v5}"
DEFAULT_BRANCH="${MDS_BRANCH:-main-candidate}"
DEFAULT_REPO_URL="${MDS_REPO_URL:-https://github.com/alireza787b/mavsdk_drone_show.git}"

ARTIFACT_DIR="$DEFAULT_ARTIFACT_DIR"
ARCHIVE_BASENAME="$DEFAULT_ARCHIVE_BASENAME"
MEGA_TARGET="$DEFAULT_MEGA_TARGET"
IMAGE_REPO="$DEFAULT_IMAGE_REPO"
VERSION_TAG="$DEFAULT_VERSION_TAG"
COMMIT_TAG=""
BRANCH="$DEFAULT_BRANCH"
REPO_URL="$DEFAULT_REPO_URL"
REPLACE_EXISTING=false
LOGOUT_AFTER=false
PRINT_JSON=false
SKIP_EXPORT=false
SESSION_FILE=""
READ_SESSION_FROM_STDIN=false
ALLOW_STDIN_LOGIN=false

usage() {
    cat <<EOF
Publish a packaged SITL release archive to MEGA with session-first auth.

Usage:
  $(basename "$0") [options]

Options:
  --artifact-dir DIR       Directory containing the packaged release artifacts
                           (default: ${DEFAULT_ARTIFACT_DIR})
  --archive-basename NAME  Release archive basename without extension
                           (default: ${DEFAULT_ARCHIVE_BASENAME})
  --mega-target PATH       Remote MEGA folder path
                           (default: ${DEFAULT_MEGA_TARGET})
  --image-repo REPO        Metadata only, reported in final result
                           (default: ${DEFAULT_IMAGE_REPO})
  --version-tag TAG        Metadata only, reported in final result
                           (default: ${DEFAULT_VERSION_TAG})
  --commit-tag SHA         Metadata only, reported in final result
  --branch BRANCH          Metadata only, reported in final result
                           (default: ${DEFAULT_BRANCH})
  --repo-url URL           Metadata only, reported in final result
                           (default: ${DEFAULT_REPO_URL})
  --replace-existing       Remove matching remote artifact files before upload
  --logout-after           Logout after upload/export completes
  --skip-export            Upload files but do not export a public archive link
  --session-file PATH      Read a MEGA session string from a local file if needed
  --session-stdin          Read a MEGA session string from stdin if needed
  --stdin-login            Fallback only: read email/password from stdin if needed
  --json                   Print a final machine-readable JSON line
  -h, --help               Show this help message

Auth modes:
  1. Preferred: reuse an existing MEGAcmd session (`mega-whoami` succeeds).
  2. Safer fallback: pass a MEGA session string via --session-file or --session-stdin.
  3. Last resort: use --stdin-login. This still requires MEGAcmd to invoke
     'mega-login email password', so it avoids docs/history leakage but still
     carries brief argv exposure on the host during login.
EOF
}

log() {
    printf '%s\n' "$*" >&2
}

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

trim_trailing_slash() {
    local value="$1"
    while [[ "$value" != "/" && "$value" == */ ]]; do
        value="${value%/}"
    done
    printf '%s' "$value"
}

read_secret_line() {
    local prompt="$1"
    local secret=false
    if [[ "${2:-}" == "secret" ]]; then
        secret=true
    fi

    if [[ -t 0 && -t 1 ]]; then
        if [[ "$secret" == true ]]; then
            printf '%s' "$prompt" >&2
            stty -echo
            IFS= read -r REPLY || true
            stty echo
            printf '\n' >&2
        else
            printf '%s' "$prompt" >&2
            IFS= read -r REPLY || true
        fi
    else
        IFS= read -r REPLY || true
    fi

    [[ -n "$REPLY" ]] || fail "Expected input for: ${prompt}"
}

ensure_logged_in() {
    if mega-whoami >/dev/null 2>&1; then
        local account
        account="$(mega-whoami 2>/dev/null | tr -d '\r' | head -n 1)"
        log "Reusing active MEGA session${account:+: ${account}}"
        return 0
    fi

    if [[ -n "$SESSION_FILE" ]]; then
        [[ -f "$SESSION_FILE" ]] || fail "Session file not found: ${SESSION_FILE}"
        local session
        session="$(tr -d '\r\n' < "$SESSION_FILE")"
        [[ -n "$session" ]] || fail "Session file is empty: ${SESSION_FILE}"
        log "Logging into MEGA with session string from file."
        mega-login "$session" >/dev/null
        return 0
    fi

    if [[ "$READ_SESSION_FROM_STDIN" == true ]]; then
        read_secret_line "MEGA session: " secret
        log "Logging into MEGA with session string from stdin."
        mega-login "$REPLY" >/dev/null
        unset REPLY
        return 0
    fi

    if [[ "$ALLOW_STDIN_LOGIN" == true ]]; then
        log "No active MEGA session found. Falling back to stdin credential login."
        log "Warning: MEGAcmd accepts email/password as argv internally; use session mode when possible."
        read_secret_line "MEGA email: "
        local mega_email="$REPLY"
        read_secret_line "MEGA password: " secret
        local mega_password="$REPLY"
        HISTFILE=/dev/null mega-login "$mega_email" "$mega_password" >/dev/null
        unset REPLY mega_email mega_password
        return 0
    fi

    fail "No active MEGA session found. Log in manually first, or provide --session-file, --session-stdin, or --stdin-login."
}

delete_remote_file_if_requested() {
    local remote_path="$1"
    if [[ "$REPLACE_EXISTING" != true ]]; then
        return 0
    fi

    mega-export -d "$remote_path" >/dev/null 2>&1 || true
    mega-rm "$remote_path" >/dev/null 2>&1 || true
}

capture_export_link() {
    local remote_path="$1"
    local output
    output="$(mega-export -af "$remote_path" 2>/dev/null || true)"
    printf '%s\n' "$output" | grep -Eo 'https://mega\.nz/[[:graph:]]+' | tail -n 1
}

json_escape() {
    local value="$1"
    value="${value//\\/\\\\}"
    value="${value//\"/\\\"}"
    value="${value//$'\n'/\\n}"
    value="${value//$'\r'/\\r}"
    printf '%s' "$value"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --artifact-dir)
            ARTIFACT_DIR="$2"
            shift 2
            ;;
        --archive-basename)
            ARCHIVE_BASENAME="$2"
            shift 2
            ;;
        --mega-target)
            MEGA_TARGET="$2"
            shift 2
            ;;
        --image-repo)
            IMAGE_REPO="$2"
            shift 2
            ;;
        --version-tag)
            VERSION_TAG="$2"
            shift 2
            ;;
        --commit-tag)
            COMMIT_TAG="$2"
            shift 2
            ;;
        --branch)
            BRANCH="$2"
            shift 2
            ;;
        --repo-url)
            REPO_URL="$2"
            shift 2
            ;;
        --replace-existing)
            REPLACE_EXISTING=true
            shift
            ;;
        --logout-after)
            LOGOUT_AFTER=true
            shift
            ;;
        --skip-export)
            SKIP_EXPORT=true
            shift
            ;;
        --session-file)
            SESSION_FILE="$2"
            shift 2
            ;;
        --session-stdin)
            READ_SESSION_FROM_STDIN=true
            shift
            ;;
        --stdin-login)
            ALLOW_STDIN_LOGIN=true
            shift
            ;;
        --json)
            PRINT_JSON=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "Unknown argument: $1"
            ;;
    esac
done

require_cmd mega-whoami
require_cmd mega-login
require_cmd mega-mkdir
require_cmd mega-put
require_cmd mega-export
require_cmd mega-rm

ARTIFACT_DIR="$(cd "$ARTIFACT_DIR" && pwd)"
MEGA_TARGET="$(trim_trailing_slash "$MEGA_TARGET")"

ARCHIVE_FILE="${ARCHIVE_BASENAME}.7z"
ARCHIVE_SHA_FILE="${ARCHIVE_FILE}.sha256"
MANIFEST_FILE="${ARCHIVE_BASENAME}.manifest.json"

ARCHIVE_PATH="${ARTIFACT_DIR}/${ARCHIVE_FILE}"
ARCHIVE_SHA_PATH="${ARTIFACT_DIR}/${ARCHIVE_SHA_FILE}"
MANIFEST_PATH="${ARTIFACT_DIR}/${MANIFEST_FILE}"

[[ -f "$ARCHIVE_PATH" ]] || fail "Archive not found: $ARCHIVE_PATH"
[[ -f "$ARCHIVE_SHA_PATH" ]] || fail "Archive checksum not found: $ARCHIVE_SHA_PATH"
[[ -f "$MANIFEST_PATH" ]] || fail "Manifest not found: $MANIFEST_PATH"

ensure_logged_in

log "Ensuring MEGA target folder exists: ${MEGA_TARGET}"
mega-mkdir -p "$MEGA_TARGET" >/dev/null 2>&1 || true

REMOTE_ARCHIVE_PATH="${MEGA_TARGET}/${ARCHIVE_FILE}"
REMOTE_ARCHIVE_SHA_PATH="${MEGA_TARGET}/${ARCHIVE_SHA_FILE}"
REMOTE_MANIFEST_PATH="${MEGA_TARGET}/${MANIFEST_FILE}"

delete_remote_file_if_requested "$REMOTE_ARCHIVE_PATH"
delete_remote_file_if_requested "$REMOTE_ARCHIVE_SHA_PATH"
delete_remote_file_if_requested "$REMOTE_MANIFEST_PATH"

log "Uploading release artifacts to MEGA..."
mega-put -c "$ARCHIVE_PATH" "$MEGA_TARGET" >/dev/null
mega-put -c "$ARCHIVE_SHA_PATH" "$MEGA_TARGET" >/dev/null
mega-put -c "$MANIFEST_PATH" "$MEGA_TARGET" >/dev/null

ARCHIVE_LINK=""
if [[ "$SKIP_EXPORT" != true ]]; then
    log "Exporting public link for ${REMOTE_ARCHIVE_PATH}"
    ARCHIVE_LINK="$(capture_export_link "$REMOTE_ARCHIVE_PATH")"
    [[ -n "$ARCHIVE_LINK" ]] || fail "Failed to export archive link for ${REMOTE_ARCHIVE_PATH}"
fi

if [[ "$LOGOUT_AFTER" == true ]]; then
    log "Logging out of MEGA."
    mega-logout >/dev/null 2>&1 || true
fi

if [[ "$PRINT_JSON" == true ]]; then
    printf '%s\n' \
      "{\"success\":true,\"mega_target\":\"$(json_escape "$MEGA_TARGET")\",\"archive_file\":\"$(json_escape "$ARCHIVE_FILE")\",\"archive_link\":\"$(json_escape "$ARCHIVE_LINK")\",\"image_repo\":\"$(json_escape "$IMAGE_REPO")\",\"version_tag\":\"$(json_escape "$VERSION_TAG")\",\"commit_tag\":\"$(json_escape "$COMMIT_TAG")\",\"branch\":\"$(json_escape "$BRANCH")\",\"repo_url\":\"$(json_escape "$REPO_URL")\"}"
else
    log "MEGA publish complete."
    log "  target      : ${MEGA_TARGET}"
    log "  archive     : ${ARCHIVE_FILE}"
    if [[ -n "$ARCHIVE_LINK" ]]; then
        log "  public link : ${ARCHIVE_LINK}"
    fi
fi
