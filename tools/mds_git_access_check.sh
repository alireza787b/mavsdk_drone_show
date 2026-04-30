#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MDS_REPO_ROOT="$REPO_ROOT"
DEPLOYMENT_PROFILE_LOADER="$SCRIPT_DIR/load_deployment_profile.sh"
if [[ -f "$DEPLOYMENT_PROFILE_LOADER" ]]; then
    # shellcheck disable=SC1090
    source "$DEPLOYMENT_PROFILE_LOADER"
fi

DEFAULT_REPO_URL="${MDS_REPO_URL:-${MDS_DEFAULT_REPO_URL_HTTPS:-https://github.com/alireza787b/mavsdk_drone_show.git}}"
DEFAULT_BRANCH="${MDS_BRANCH:-${MDS_DEFAULT_BRANCH:-main}}"
DOCS_PATH="${MDS_GIT_AUTH_DOCS_PATH:-docs/guides/custom-sitl-auth.md}"

REPO_URL="$DEFAULT_REPO_URL"
BRANCH="$DEFAULT_BRANCH"
MODE="${MDS_GIT_ACCESS_CHECK_MODE:-sitl-read}"

usage() {
    cat <<EOF
Validate non-interactive git access for MDS repo sync/build workflows.

Usage:
  $(basename "$0") [--repo-url URL] [--branch BRANCH] [--mode MODE]

Modes:
  sitl-read   Validate read access for disposable SITL containers
  image-prep  Validate read access before custom SITL image preparation
  gcs-write   Validate GCS repo reachability before write-capable setup

Auth inputs:
  MDS_GIT_AUTH_TOKEN_FILE  HTTPS token file
  MDS_GIT_AUTH_USERNAME    HTTPS username for token auth, default x-access-token
  MDS_GIT_SSH_KEY_FILE     Optional SSH private key for git@github.com URLs

Docs:
  ${DOCS_PATH}
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo-url)
            REPO_URL="$2"
            shift 2
            ;;
        --branch)
            BRANCH="$2"
            shift 2
            ;;
        --mode)
            MODE="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf 'Error: unknown argument: %s\n' "$1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    printf 'Docs: %s\n' "$DOCS_PATH" >&2
    exit 1
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

redact_url() {
    sed -E 's#(https?://)[^/@:]+(:[^/@]*)?@#\1***@#g'
}

github_https_fallback_url() {
    local repo_url="$1"
    if [[ "$repo_url" =~ ^git@github\.com:(.+)$ ]]; then
        printf 'https://github.com/%s\n' "${BASH_REMATCH[1]}"
        return 0
    fi
    return 1
}

should_use_ssh() {
    [[ -n "${MDS_GIT_SSH_KEY_FILE:-}" ]] || return 1
    [[ "$REPO_URL" =~ ^git@github\.com: ]]
}

github_https_repo_url() {
    local repo_url="$1"
    if [[ "$repo_url" =~ ^git@github\.com:(.+)$ ]]; then
        printf 'https://github.com/%s\n' "${BASH_REMATCH[1]}"
        return 0
    fi
    if [[ "$repo_url" =~ ^https://github\.com/.+ ]]; then
        printf '%s\n' "$repo_url"
        return 0
    fi
    return 1
}

require_cmd git

[[ -n "$REPO_URL" ]] || fail "MDS_REPO_URL is empty"
[[ -n "$BRANCH" ]] || fail "MDS_BRANCH is empty"

case "$MODE" in
    sitl-read|image-prep|gcs-write) ;;
    *) fail "Unsupported access-check mode: $MODE" ;;
esac

if [[ "$REPO_URL" =~ ^https?://[^/]+@ ]]; then
    fail "Do not embed credentials in MDS_REPO_URL. Use MDS_GIT_AUTH_TOKEN_FILE or MDS_GIT_SSH_KEY_FILE."
fi

AUTH_MODE="public-or-preconfigured"
EFFECTIVE_REPO_URL="$REPO_URL"
TMP_DIR=""

runtime_tmp_dir() {
    local candidate
    for candidate in "${XDG_RUNTIME_DIR:-}" "${HOME:-}/.cache/mds-runtime" "/var/tmp/mds-runtime"; do
        [[ -n "$candidate" ]] || continue
        mkdir -p "$candidate" 2>/dev/null || continue
        chmod 700 "$candidate" 2>/dev/null || true
        printf '%s\n' "$candidate"
        return 0
    done

    printf '%s\n' "/var/tmp"
}

cleanup() {
    if [[ -n "$TMP_DIR" ]]; then
        rm -rf "$TMP_DIR"
    fi
}
trap cleanup EXIT

if should_use_ssh; then
    [[ -r "$MDS_GIT_SSH_KEY_FILE" ]] || fail "MDS_GIT_SSH_KEY_FILE is not readable: $MDS_GIT_SSH_KEY_FILE"
    mkdir -p "$HOME/.ssh"
    chmod 700 "$HOME/.ssh"
    export GIT_SSH_COMMAND="ssh -i $MDS_GIT_SSH_KEY_FILE -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=${MDS_GIT_KNOWN_HOSTS_FILE:-$HOME/.ssh/known_hosts}"
    export GIT_TERMINAL_PROMPT=0
    AUTH_MODE="ssh-key-file"
elif [[ -n "${MDS_GIT_AUTH_TOKEN_FILE:-}" ]]; then
    [[ -r "$MDS_GIT_AUTH_TOKEN_FILE" ]] || fail "MDS_GIT_AUTH_TOKEN_FILE is not readable: $MDS_GIT_AUTH_TOKEN_FILE"
    AUTH_MODE="https-token-file"

    if ! EFFECTIVE_REPO_URL="$(github_https_repo_url "$REPO_URL")"; then
        fail "Token auth supports GitHub HTTPS or git@github.com URLs only: $(printf '%s' "$REPO_URL" | redact_url)"
    fi

    TMP_DIR="$(mktemp -d -p "$(runtime_tmp_dir)")"
    ASKPASS="$TMP_DIR/git-askpass.sh"
    cat > "$ASKPASS" <<'EOS'
#!/bin/sh
case "$1" in
    *Username*) printf '%s\n' "${MDS_ASKPASS_USERNAME:-x-access-token}" ;;
    *Password*)
        tr -d '\r\n' < "$MDS_ASKPASS_TOKEN_FILE"
        ;;
    *) printf '\n' ;;
esac
EOS
    chmod 700 "$ASKPASS"
    export GIT_ASKPASS="$ASKPASS"
    export GIT_TERMINAL_PROMPT=0
    export MDS_ASKPASS_USERNAME="${MDS_GIT_AUTH_USERNAME:-x-access-token}"
    export MDS_ASKPASS_TOKEN_FILE="$MDS_GIT_AUTH_TOKEN_FILE"
elif fallback_url="$(github_https_fallback_url "$REPO_URL")"; then
    EFFECTIVE_REPO_URL="$fallback_url"
fi

TMP_DIR="${TMP_DIR:-$(mktemp -d -p "$(runtime_tmp_dir)")}"
STDOUT_FILE="$TMP_DIR/ls-remote.out"
STDERR_FILE="$TMP_DIR/ls-remote.err"

if ! git ls-remote --heads "$EFFECTIVE_REPO_URL" "$BRANCH" >"$STDOUT_FILE" 2>"$STDERR_FILE"; then
    printf 'ERROR: git access check failed for %s@%s in %s mode.\n' \
        "$(printf '%s' "$REPO_URL" | redact_url)" "$BRANCH" "$MODE" >&2
    printf 'Auth mode: %s\n' "$AUTH_MODE" >&2
    if [[ -s "$STDERR_FILE" ]]; then
        printf 'Git diagnostic:\n' >&2
        head -n 8 "$STDERR_FILE" | redact_url >&2
    fi
    printf 'Docs: %s\n' "$DOCS_PATH" >&2
    exit 1
fi

if [[ ! -s "$STDOUT_FILE" ]]; then
    printf 'ERROR: repository is reachable, but branch was not found: %s\n' "$BRANCH" >&2
    printf 'Repo: %s\n' "$(printf '%s' "$REPO_URL" | redact_url)" >&2
    printf 'Docs: %s\n' "$DOCS_PATH" >&2
    exit 1
fi

COMMIT="$(awk '{print substr($1,1,12); exit}' "$STDOUT_FILE")"
printf 'MDS git access check OK: mode=%s auth=%s repo=%s branch=%s commit=%s\n' \
    "$MODE" "$AUTH_MODE" "$(printf '%s' "$REPO_URL" | redact_url)" "$BRANCH" "$COMMIT"
