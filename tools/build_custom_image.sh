#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/docker_sitl_image_lib.sh"

SCRIPT_NAME=$(basename "$0")
SCRIPT_VERSION="2.0.0"

DEFAULT_REPO_URL="${MDS_REPO_URL:-https://github.com/alireza787b/mavsdk_drone_show.git}"
DEFAULT_BRANCH="${MDS_BRANCH:-main-candidate}"
DEFAULT_IMAGE_NAME="${MDS_DOCKER_IMAGE:-mavsdk-drone-show-sitl:custom}"
BASE_IMAGE="${MDS_SITL_BASE_IMAGE:-mavsdk-drone-show-sitl:latest}"

show_usage() {
    cat <<EOF
MDS Custom Docker Image Builder v${SCRIPT_VERSION}

Usage:
  ${SCRIPT_NAME} [REPO_URL] [BRANCH] [IMAGE_NAME]

Parameters:
  REPO_URL     Git repository URL to preload into the image
               Default: ${DEFAULT_REPO_URL}
  BRANCH       Git branch name to preload
               Default: ${DEFAULT_BRANCH}
  IMAGE_NAME   Final Docker image reference to create
               Default: ${DEFAULT_IMAGE_NAME}

Notes:
  - This builder no longer uses 'docker commit' for releases.
  - It prepares a shallow repo checkout, pre-installs the Python venv,
    removes unnecessary baggage, then flattens the container filesystem into
    a clean image.
  - Export MDS_MAVSDK_VERSION or MDS_MAVSDK_URL before running if you need
    the image to bake in a specific MAVSDK server binary.
  - For a private GitHub repo, prefer MDS_GIT_AUTH_TOKEN_FILE so the builder
    can clone through authenticated HTTPS without exposing the token in
    process arguments. MDS_GIT_AUTH_TOKEN remains a legacy fallback.
  - Export MDS_SITL_KEEP_ARM_TOOLCHAIN=true before running only if your
    custom image intentionally needs the PX4 ARM firmware toolchain preserved.
  - The resulting image keeps the MDS repo as a shallow git checkout so each
    SITL container can fetch/reset to the latest branch state on startup.
  - PX4 stays pinned in the image with its real git/submodule metadata intact.
    Startup git sync is a mutable MDS-code mode, not a full image rebuild.
EOF
}

log_info() {
    printf '[INFO] %s\n' "$*"
}

log_success() {
    printf '[OK] %s\n' "$*"
}

main() {
    local repo_url="${1:-${DEFAULT_REPO_URL}}"
    local branch="${2:-${DEFAULT_BRANCH}}"
    local image_name="${3:-${DEFAULT_IMAGE_NAME}}"
    local image_repo="$image_name"
    local image_tag="latest"
    local last_segment="${image_name##*/}"

    if [[ -z "$repo_url" || -z "$branch" || -z "$image_name" ]]; then
        show_usage >&2
        exit 1
    fi

    if [[ "$last_segment" == *:* ]]; then
        image_repo="${image_name%:*}"
        image_tag="${image_name##*:}"
    fi

    docker_sitl_check_docker
    docker_sitl_check_image_exists "$BASE_IMAGE"

    local temp_container="mds-custom-build-$(date +%s)-$$"
    trap "docker_sitl_cleanup_container '$temp_container'" EXIT

    log_info "Base image : ${BASE_IMAGE}"
    log_info "Repo       : ${repo_url}"
    log_info "Branch     : ${branch}"
    log_info "Target     : ${image_name}"
    if [[ -n "${MDS_MAVSDK_VERSION:-}" ]]; then
        log_info "MAVSDK ver : ${MDS_MAVSDK_VERSION}"
    fi
    if [[ -n "${MDS_MAVSDK_URL:-}" ]]; then
        log_info "MAVSDK URL : ${MDS_MAVSDK_URL}"
    fi
    if [[ -n "${MDS_SITL_KEEP_ARM_TOOLCHAIN:-}" ]]; then
        log_info "Keep ARM   : ${MDS_SITL_KEEP_ARM_TOOLCHAIN}"
    fi

    docker run --name "$temp_container" -d "$BASE_IMAGE" tail -f /dev/null >/dev/null
    docker_sitl_copy_prepare_script "$REPO_ROOT" "$temp_container"
    docker_sitl_run_prepare_script "$temp_container" "$repo_url" "$branch"

    local commit_hash
    commit_hash=$(docker exec "$temp_container" git -C /root/mavsdk_drone_show rev-parse --short HEAD)

    docker_sitl_flatten_container \
        "$temp_container" \
        "$BASE_IMAGE" \
        "$image_name" \
        "LABEL mds.sitl.image.repo=${image_repo}" \
        "LABEL mds.sitl.image.version=${image_tag}" \
        "LABEL mds.sitl.image.branch=${branch}" \
        "LABEL mds.sitl.image.commit=${commit_hash}" \
        "LABEL mds.sitl.image.prepared_from=${BASE_IMAGE}"

    if [[ "$image_tag" != "latest" ]]; then
        docker tag "$image_name" "${image_repo}:latest"
        log_info "Also tagged: ${image_repo}:latest"
    fi

    log_success "Custom SITL image ready: ${image_name}"
    log_info "Preloaded commit: ${commit_hash}"
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    show_usage
    exit 0
fi

main "$@"
