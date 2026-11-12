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

DEFAULT_REPO_URL="${MDS_DEFAULT_REPO_URL_HTTPS:-https://github.com/alireza787b/mavsdk_drone_show.git}"
DEFAULT_BRANCH="${MDS_DEFAULT_BRANCH:-main}"
BASE_DIR="${MDS_BASE_DIR:-/root/mavsdk_drone_show}"
PX4_DIR="${MDS_PX4_DIR:-/root/PX4-Autopilot}"
REPO_URL="${1:-${MDS_REPO_URL:-$DEFAULT_REPO_URL}}"
BRANCH="${2:-${MDS_BRANCH:-$DEFAULT_BRANCH}}"
GIT_AUTH_TOKEN_FILE="${MDS_GIT_AUTH_TOKEN_FILE:-}"
GIT_AUTH_USERNAME="${MDS_GIT_AUTH_USERNAME:-x-access-token}"
GIT_SSH_KEY_FILE="${MDS_GIT_SSH_KEY_FILE:-}"
VENV_DIR="$BASE_DIR/venv"
VENV_REQUIREMENTS_MARKER="$VENV_DIR/.mds_requirements_state"
RUNTIME_VENV_HEALTH_CHECKER="$BASE_DIR/tools/check_runtime_venv.py"
PYTHON_RUNTIME_HELPER="$BASE_DIR/tools/python_runtime.py"
MDS_RUNTIME_PYTHON=""
MAVSDK_BINARY_PATH="$BASE_DIR/mavsdk_server"
MAVSDK_DOWNLOAD_SCRIPT="$BASE_DIR/tools/download_mavsdk_server.sh"
PX4_PROVENANCE_FILE="$BASE_DIR/.mds_px4_source_provenance.env"
PX4_SUBMODULE_STATUS_FILE="$BASE_DIR/.mds_px4_submodules.txt"
KEEP_ARM_TOOLCHAIN="${MDS_SITL_KEEP_ARM_TOOLCHAIN:-false}"

log() {
    printf '%s\n' "$*"
}

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

load_git_auth_token() {
    # Reject userinfo/query credentials before logging or executing Git.
    if [[ "$REPO_URL" == http*://*@* || "$REPO_URL" == *\?* || "$REPO_URL" == *\#* ]]; then
        fail "MDS_REPO_URL must not contain credentials, a query or a fragment; use credential files"
    fi
    if [[ -n "$GIT_AUTH_TOKEN_FILE" ]]; then
        [[ -r "$GIT_AUTH_TOKEN_FILE" ]] || fail "MDS_GIT_AUTH_TOKEN_FILE is not readable: $GIT_AUTH_TOKEN_FILE"
        [[ -s "$GIT_AUTH_TOKEN_FILE" ]] || fail "MDS_GIT_AUTH_TOKEN_FILE is empty"
        export GIT_ASKPASS="$SCRIPT_DIR/git_token_askpass.sh"
        export GIT_TERMINAL_PROMPT=0 MDS_GIT_AUTH_TOKEN_FILE="$GIT_AUTH_TOKEN_FILE"
        export MDS_GIT_AUTH_USERNAME="$GIT_AUTH_USERNAME"
        [[ -x "$GIT_ASKPASS" ]] || fail "Git file-backed authentication helper is missing or not executable"
        unset GIT_TRACE GIT_TRACE_PACKET GIT_TRACE_CURL GIT_CURL_VERBOSE GIT_TRACE_SETUP
    fi
}

load_git_ssh_key() {
    if [[ -z "$GIT_SSH_KEY_FILE" ]]; then
        return 0
    fi

    [[ -r "$GIT_SSH_KEY_FILE" ]] || fail "MDS_GIT_SSH_KEY_FILE is not readable: $GIT_SSH_KEY_FILE"
    mkdir -p "$HOME/.ssh"
    chmod 700 "$HOME/.ssh"
    export GIT_SSH_COMMAND="ssh -i $GIT_SSH_KEY_FILE -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$HOME/.ssh/known_hosts"
}

retry_cmd() {
    local attempts="$1"
    shift
    local delay=2
    local try=1

    while true; do
        if "$@"; then
            return 0
        fi

        if [ "$try" -ge "$attempts" ]; then
            return 1
        fi

        sleep "$delay"
        try=$((try + 1))
        delay=$((delay * 2))
    done
}

github_https_fallback_url() {
    local repo_url="$1"
    if [[ "$repo_url" =~ ^git@github\.com:(.+)$ ]]; then
        echo "https://github.com/${BASH_REMATCH[1]}"
        return 0
    fi
    return 1
}

should_prefer_ssh_repo_url() {
    [[ -n "$GIT_SSH_KEY_FILE" ]] || return 1
    [[ "$1" =~ ^git@github\.com: ]]
}

github_repo_path() {
    local repo_url="$1"
    local repo_path=""

    if [[ "$repo_url" =~ ^git@github\.com:(.+)$ ]]; then
        repo_path="${BASH_REMATCH[1]}"
    elif [[ "$repo_url" =~ ^https://github\.com/(.+)$ ]]; then
        repo_path="${BASH_REMATCH[1]}"
    else
        return 1
    fi

    repo_path="${repo_path%.git}"
    printf '%s.git\n' "$repo_path"
}

github_token_https_url() {
    local repo_url="$1"
    local repo_path=""

    [[ -n "$GIT_AUTH_TOKEN_FILE" ]] || return 1
    repo_path=$(github_repo_path "$repo_url") || return 1

    printf 'https://github.com/%s\n' "$repo_path"
}

requirements_state_value() {
    local requirements_file="$BASE_DIR/requirements.txt"
    python3 "$PYTHON_RUNTIME_HELPER" state --venv "$VENV_DIR" --requirements "$requirements_file"
}

fresh_clone_mds_repo() {
    local authenticated_repo_url=""
    local fallback_repo_url=""
    local effective_repo_url="$REPO_URL"
    local clone_parent
    local clone_dir
    local preserve_dir
    preserve_dir=$(mktemp -d)

    if should_prefer_ssh_repo_url "$REPO_URL"; then
        effective_repo_url="$REPO_URL"
    elif authenticated_repo_url=$(github_token_https_url "$REPO_URL"); then
        effective_repo_url="$authenticated_repo_url"
        fallback_repo_url=""
    elif fallback_repo_url=$(github_https_fallback_url "$REPO_URL"); then
        :
    else
        fallback_repo_url=""
    fi

    if [ -x "$BASE_DIR/mavsdk_server" ]; then
        cp "$BASE_DIR/mavsdk_server" "$preserve_dir/mavsdk_server"
    fi

    clone_parent=$(mktemp -d)
    clone_dir="$clone_parent/repo"

    log "Cloning ${REPO_URL}@${BRANCH} as a shallow working tree..."
    if ! retry_cmd 3 git -c credential.helper= -c http.extraHeader= clone --depth 1 --branch "$BRANCH" "$effective_repo_url" "$clone_dir"; then
        if [ -n "$fallback_repo_url" ] && [ "$fallback_repo_url" != "$REPO_URL" ]; then
            log "Primary clone failed. Retrying with HTTPS fallback: $fallback_repo_url"
            retry_cmd 3 git -c credential.helper= -c http.extraHeader= clone --depth 1 --branch "$BRANCH" "$fallback_repo_url" "$clone_dir"
        else
            fail "Unable to clone ${REPO_URL}@${BRANCH}"
        fi
    fi

    # The authenticated transport URL must never survive in the flattened git
    # config. Sanitize before moving the checkout, not only at runtime startup.
    git -C "$clone_dir" remote set-url origin "$REPO_URL"
    python3 "$clone_dir/tools/audit_sitl_image.py" git --repo "$clone_dir"

    rm -rf "$BASE_DIR"
    mv "$clone_dir" "$BASE_DIR"
    rm -rf "$clone_parent"

    if [ -f "$preserve_dir/mavsdk_server" ] && [ ! -f "$BASE_DIR/mavsdk_server" ]; then
        mv "$preserve_dir/mavsdk_server" "$BASE_DIR/mavsdk_server"
        chmod +x "$BASE_DIR/mavsdk_server"
    fi

    rm -rf "$preserve_dir"
}

ensure_mavsdk_server() {
    [ -f "$MAVSDK_DOWNLOAD_SCRIPT" ] || fail "Missing MAVSDK download helper: $MAVSDK_DOWNLOAD_SCRIPT"
    log "Provisioning mavsdk_server into $BASE_DIR..."
    MDS_INSTALL_DIR="$BASE_DIR" bash "$MAVSDK_DOWNLOAD_SCRIPT" >/tmp/mds_mavsdk_download.log 2>&1 || {
        tail -n 40 /tmp/mds_mavsdk_download.log >&2 || true
        fail "Failed to download mavsdk_server"
    }
    # Keep this bounded metadata log until image cleanup; custom overrides must
    # not disappear behind a generic download-success message.
    cat /tmp/mds_mavsdk_download.log
    [ -x "$MAVSDK_BINARY_PATH" ] || fail "mavsdk_server is still missing after download"
}

ensure_python_env() {
    log "Preparing Python virtual environment..."
    MDS_RUNTIME_PYTHON=$(python3 "$PYTHON_RUNTIME_HELPER" provision-image) || fail "No supported image Python runtime"
    rm -rf "$VENV_DIR"
    "$MDS_RUNTIME_PYTHON" -m venv "$VENV_DIR"

    PIP_NO_CACHE_DIR=1 "$VENV_DIR/bin/python" -m pip install --upgrade pip >/tmp/mds_pip_install.log 2>&1
    PIP_NO_CACHE_DIR=1 "$VENV_DIR/bin/python" -m pip install -r "$BASE_DIR/requirements.txt" >>/tmp/mds_pip_install.log 2>&1 || {
        tail -n 40 /tmp/mds_pip_install.log >&2 || true
        fail "Failed to install Python requirements"
    }
    python3 "$PYTHON_RUNTIME_HELPER" check-venv \
        --venv "$VENV_DIR" \
        --module requests \
        --module aiohttp \
        --module mavsdk_grpc >/tmp/mds_venv_health.log 2>&1 || {
        cat /tmp/mds_venv_health.log >&2 || true
        fail "Created Python virtual environment is unhealthy"
    }
    "$VENV_DIR/bin/python" "$BASE_DIR/tools/mavsdk_runtime.py" python-check || fail "MAVSDK Python pins/imports differ from the manifest"
    printf "%s\n" "$(requirements_state_value)" > "$VENV_REQUIREMENTS_MARKER"
    rm -f /tmp/mds_pip_install.log
    rm -f /tmp/mds_venv_health.log
}

stabilize_mavlink2rest_binary() {
    local current_bin
    current_bin=$(command -v mavlink2rest || true)
    [ -n "$current_bin" ] || fail "mavlink2rest is not installed in the base image"

    if [ "$current_bin" != "/usr/local/bin/mavlink2rest" ]; then
        install -m 0755 "$current_bin" /usr/local/bin/mavlink2rest
    fi
}

prepare_px4_build() {
    # Header updates from interpreter build dependencies can invalidate gz_bridge.
    # Prepare build-only targets once; never start a simulator during image prep.
    local build_dir="$PX4_DIR/build/px4_sitl_default"
    [[ -f "$build_dir/CMakeCache.txt" ]] || fail "Missing prepared PX4 CMake cache"
    require_cmd cmake
    require_cmd timeout
    log "Preparing PX4/Gazebo build dependencies with at most two workers..."
    CMAKE_BUILD_PARALLEL_LEVEL=2 timeout --signal=TERM --kill-after=15s 1200s cmake --build "$build_dir" \
        --target px4 px4_gz_plugins --parallel 2 || fail "PX4/Gazebo dependency preparation failed"
    [[ -x "$build_dir/bin/px4" ]] || fail "Prepared PX4 executable is unavailable"
}

capture_px4_provenance() {
    local px4_branch="unknown"
    local px4_commit="unknown"
    local px4_describe="unknown"
    local px4_gitlinks=0
    local px4_submodule_provenance="unavailable"
    local px4_binary_sha256="unknown"
    local px4_git_metadata="unavailable"
    : > "$PX4_SUBMODULE_STATUS_FILE"

    if git -C "$PX4_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        px4_git_metadata="present_not_independently_verified"
        px4_branch=$(git -C "$PX4_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
        px4_commit=$(git -C "$PX4_DIR" rev-parse HEAD 2>/dev/null || echo "unknown")
        px4_describe=$(git -C "$PX4_DIR" describe --tags --always --dirty 2>/dev/null || echo "$px4_commit")
        px4_gitlinks=$(git -C "$PX4_DIR" ls-tree -r HEAD | awk '$1 == "160000" {count++} END {print count+0}')
        if [[ "$px4_gitlinks" -eq 0 ]]; then
            px4_submodule_provenance="unavailable_no_gitlinks"
        elif git -C "$PX4_DIR" submodule status --recursive >"$PX4_SUBMODULE_STATUS_FILE" 2>/dev/null && \
                [[ -s "$PX4_SUBMODULE_STATUS_FILE" ]]; then
            px4_submodule_provenance="recorded_not_independently_verified"
        fi
    fi
    if [[ -f "$PX4_DIR/build/px4_sitl_default/bin/px4" ]]; then
        px4_binary_sha256=$(sha256sum "$PX4_DIR/build/px4_sitl_default/bin/px4" | awk '{print $1}')
    fi

    cat > "$PX4_PROVENANCE_FILE" <<EOF
MDS_IMAGE_PX4_DIR=${PX4_DIR}
MDS_IMAGE_PX4_BRANCH=${px4_branch}
MDS_IMAGE_PX4_COMMIT=${px4_commit}
MDS_IMAGE_PX4_DESCRIBE=${px4_describe}
MDS_IMAGE_PX4_GIT_METADATA=${px4_git_metadata}
MDS_IMAGE_PX4_BINARY_SHA256=${px4_binary_sha256}
MDS_IMAGE_PX4_GITLINK_COUNT=${px4_gitlinks}
MDS_IMAGE_PX4_SUBMODULE_PROVENANCE=${px4_submodule_provenance}
EOF
}

cleanup_runtime_baggage() {
    log "Removing cached and development-only baggage..."

    rm -rf "$BASE_DIR/logs"
    mkdir -p "$BASE_DIR/logs"
    rm -rf "$BASE_DIR/app/dashboard/drone-dashboard/node_modules"
    rm -rf "$BASE_DIR/app/dashboard/drone-dashboard/build"
    rm -rf "$BASE_DIR/.pytest_cache"

    if [ -d "$PX4_DIR/build" ]; then
        find "$PX4_DIR/build" -mindepth 1 -maxdepth 1 ! -name px4_sitl_default -exec rm -rf {} +
    fi

    # PX4 docs and repo metadata stay intact so the runtime image still behaves
    # like a normal upstream checkout for provenance and future maintenance.

    if [ "$KEEP_ARM_TOOLCHAIN" != "true" ]; then
        rm -rf /opt/gcc-arm-none-eabi-*
    fi

    rm -rf /root/.cargo
    rm -rf /root/.rustup
    rm -rf /root/.cache/pip
    rm -rf /root/.npm
    rm -rf /tmp/*
    rm -rf /var/tmp/*
    rm -rf /var/lib/apt/lists/*

    if [ -f /root/.profile ]; then
        sed -i '\#\.cargo/env#d' /root/.profile
    fi

    if [ -f /root/.bashrc ]; then
        sed -i '\#\.cargo/env#d' /root/.bashrc
    fi
}

write_build_metadata() {
    local commit_hash
    commit_hash=$(git -C "$BASE_DIR" rev-parse --short HEAD)

    local px4_branch="unknown"
    local px4_commit="unknown"
    local px4_describe="unknown"
    if [ -f "$PX4_PROVENANCE_FILE" ]; then
        # shellcheck disable=SC1090
        source "$PX4_PROVENANCE_FILE"
        px4_branch="${MDS_IMAGE_PX4_BRANCH:-unknown}"
        px4_commit="${MDS_IMAGE_PX4_COMMIT:-unknown}"
        px4_describe="${MDS_IMAGE_PX4_DESCRIBE:-unknown}"
    fi

    local mavsdk_evidence
    mavsdk_evidence=$(python3 -c '
import json,sys
m=json.load(open(sys.argv[1]))
for key,value in {
 "VERSION_VERIFIED":m["verified_server_version"] or "unverified",
 "SHA256":m["sha256"], "COMPATIBILITY":m["compatibility"],
 "MANIFEST_SHA256":m["manifest_sha256"],
 "PYTHON_DISTRIBUTION":m["python"]["distribution"],
 "PYTHON_VERSION":m["python"]["version"],
 "GRPCIO_VERSION":m["python"]["grpcio"],
 "PROTOBUF_VERSION":m["python"]["protobuf"]}.items():
 print("MDS_IMAGE_MAVSDK_"+key+"="+value)
' "$BASE_DIR/runtime_data/mavsdk/provenance.json")

    cat > "$BASE_DIR/.mds_sitl_image_build.env" <<EOF
MDS_IMAGE_REPO_URL=${REPO_URL}
MDS_IMAGE_BRANCH=${BRANCH}
MDS_IMAGE_COMMIT=${commit_hash}
MDS_IMAGE_SYNC_MODE=mutable_latest_on_boot
MDS_IMAGE_MAVSDK_VERSION_REQUESTED=${MDS_MAVSDK_VERSION:-}
${mavsdk_evidence}
MDS_IMAGE_KEEP_ARM_TOOLCHAIN=${KEEP_ARM_TOOLCHAIN}
MDS_IMAGE_PYTHON_EXECUTABLE=${MDS_RUNTIME_PYTHON}
MDS_IMAGE_PYTHON_VERSION=$("$VENV_DIR/bin/python" -c 'import platform; print(platform.python_version())')
MDS_IMAGE_PYTHON_MANIFEST_SHA256=$(sha256sum "$BASE_DIR/config/python-runtime.json" | awk '{print $1}')
MDS_IMAGE_PX4_BRANCH=${px4_branch}
MDS_IMAGE_PX4_COMMIT=${px4_commit}
MDS_IMAGE_PX4_DESCRIBE=${px4_describe}
MDS_IMAGE_PREPARED_AT_UTC=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
EOF
}

main() {
    load_git_auth_token
    load_git_ssh_key
    require_cmd git
    require_cmd python3
    require_cmd sha256sum

    fresh_clone_mds_repo
    ensure_mavsdk_server
    ensure_python_env
    prepare_px4_build
    stabilize_mavlink2rest_binary
    cleanup_runtime_baggage
    capture_px4_provenance
    write_build_metadata
    # The caller removes staged credentials and runs the final filesystem gate
    # before flattening. Git configuration is already checked after cloning.

    log "Prepared image workspace:"
    log "  Base dir : $BASE_DIR"
    log "  PX4 dir  : $PX4_DIR"
    log "  Repo     : ${REPO_URL}@${BRANCH}"
    log "  Commit   : $(git -C "$BASE_DIR" rev-parse --short HEAD)"
}

main "$@"
