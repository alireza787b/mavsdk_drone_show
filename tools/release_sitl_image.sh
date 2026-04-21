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
source "$SCRIPT_DIR/docker_sitl_image_lib.sh"

DEFAULT_BASE_IMAGE="${MDS_SITL_BASE_IMAGE:-mavsdk-drone-show-sitl:latest}"
DEFAULT_IMAGE_REPO="${MDS_SITL_IMAGE_REPO:-mavsdk-drone-show-sitl}"
DEFAULT_VERSION_TAG="${MDS_SITL_VERSION_TAG:-v5}"
DEFAULT_REPO_URL="${MDS_REPO_URL:-${MDS_DEFAULT_REPO_URL_HTTPS:-https://github.com/alireza787b/mavsdk_drone_show.git}}"
DEFAULT_BRANCH="${MDS_BRANCH:-${MDS_DEFAULT_BRANCH:-main-candidate}}"
DEFAULT_ARCHIVE_BASENAME="${MDS_SITL_IMAGE_ARCHIVE_BASENAME:-mavsdk-drone-show-sitl-image}"

BASE_IMAGE="$DEFAULT_BASE_IMAGE"
IMAGE_REPO="$DEFAULT_IMAGE_REPO"
VERSION_TAG="$DEFAULT_VERSION_TAG"
REPO_URL="$DEFAULT_REPO_URL"
BRANCH="$DEFAULT_BRANCH"
PACKAGE_IMAGE=false
OUTPUT_DIR="$REPO_ROOT"
ARCHIVE_BASENAME="$DEFAULT_ARCHIVE_BASENAME"
COMPRESS=true
TAG_LATEST=true
TAG_COMMIT=true

usage() {
    cat <<EOF
Build a flattened, optimized SITL image from an existing base image.

Usage:
  $(basename "$0") [options]

Options:
  --base-image REF         Base image to optimize (default: ${DEFAULT_BASE_IMAGE})
  --image-repo REPO        Output image repository (default: ${DEFAULT_IMAGE_REPO})
  --version-tag TAG        Release tag to apply alongside latest (default: ${DEFAULT_VERSION_TAG})
  --repo-url URL           Git repository to preload in the image (default: ${DEFAULT_REPO_URL})
  --branch BRANCH          Git branch to preload in the image (default: ${DEFAULT_BRANCH})
  --package                Also export/package the resulting image archive
  --output-dir DIR         Archive output directory when --package is used (default: repo root)
  --archive-basename NAME  Archive basename when --package is used (default: ${DEFAULT_ARCHIVE_BASENAME})
  --no-compress            Keep only the .tar export when --package is used
  --no-tag-latest          Do not retag the output image as latest
  --no-tag-commit          Do not create the short commit tag
  -h, --help               Show this help message

Result:
  - Tags the output image as ${DEFAULT_IMAGE_REPO}:latest and ${DEFAULT_IMAGE_REPO}:${DEFAULT_VERSION_TAG}
  - Keeps the image filesystem ready for fast SITL container startup with runtime git sync enabled
  - Preserves the real PX4 git/submodule metadata and writes PX4 provenance into image metadata files
  - Export MDS_MAVSDK_VERSION or MDS_MAVSDK_URL before running if you want to
    pin the baked mavsdk_server binary for this release
  - For a private GitHub repo, prefer MDS_GIT_AUTH_TOKEN_FILE so image
    preparation can clone through authenticated HTTPS without exposing the
    token in process arguments. MDS_GIT_AUTH_TOKEN remains a legacy fallback.
  - MDS_GIT_SSH_KEY_FILE is also supported as a read-only SSH fallback. The
    release helper stages it only during image prep and removes it before
    flattening the final image.
  - Export MDS_SITL_KEEP_ARM_TOOLCHAIN=true before running only if you
    intentionally need the PX4 ARM firmware toolchain preserved in the image
EOF
}

log() {
    printf '%s\n' "$*"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --base-image)
            BASE_IMAGE="$2"
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
        --repo-url)
            REPO_URL="$2"
            shift 2
            ;;
        --branch)
            BRANCH="$2"
            shift 2
            ;;
        --package)
            PACKAGE_IMAGE=true
            shift
            ;;
        --output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --archive-basename)
            ARCHIVE_BASENAME="$2"
            shift 2
            ;;
        --no-compress)
            COMPRESS=false
            shift
            ;;
        --no-tag-latest)
            TAG_LATEST=false
            shift
            ;;
        --no-tag-commit)
            TAG_COMMIT=false
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf 'Error: Unknown argument: %s\n' "$1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

docker_sitl_check_docker
docker_sitl_check_image_exists "$BASE_IMAGE"

if [[ "${MDS_SKIP_GIT_ACCESS_PREFLIGHT:-false}" != "true" ]]; then
    MDS_GIT_AUTH_TOKEN_FILE="${MDS_GIT_AUTH_TOKEN_FILE:-}" \
        MDS_GIT_AUTH_TOKEN="${MDS_GIT_AUTH_TOKEN:-}" \
        MDS_GIT_AUTH_USERNAME="${MDS_GIT_AUTH_USERNAME:-}" \
        MDS_GIT_SSH_KEY_FILE="${MDS_GIT_SSH_KEY_FILE:-}" \
        MDS_GIT_KNOWN_HOSTS_FILE="${MDS_GIT_KNOWN_HOSTS_FILE:-}" \
        bash "$SCRIPT_DIR/mds_git_access_check.sh" \
        --repo-url "$REPO_URL" \
        --branch "$BRANCH" \
        --mode image-prep
fi

TEMP_CONTAINER="mds-sitl-release-$(date +%s)-$$"
trap 'docker_sitl_cleanup_container "$TEMP_CONTAINER"' EXIT

log "Creating temporary container from ${BASE_IMAGE}..."
if [[ -n "${MDS_MAVSDK_VERSION:-}" ]]; then
    log "Using MAVSDK version override: ${MDS_MAVSDK_VERSION}"
fi
if [[ -n "${MDS_MAVSDK_URL:-}" ]]; then
    log "Using MAVSDK URL override: ${MDS_MAVSDK_URL}"
fi
if [[ -n "${MDS_SITL_KEEP_ARM_TOOLCHAIN:-}" ]]; then
    log "Preserving PX4 ARM toolchain: ${MDS_SITL_KEEP_ARM_TOOLCHAIN}"
fi
docker run --name "$TEMP_CONTAINER" -d "$BASE_IMAGE" tail -f /dev/null >/dev/null

log "Preparing runtime filesystem inside temporary container..."
docker_sitl_copy_prepare_script "$REPO_ROOT" "$TEMP_CONTAINER"
if ! docker_sitl_run_prepare_script "$TEMP_CONTAINER" "$REPO_URL" "$BRANCH"; then
    printf 'Error: Failed to prepare runtime filesystem for %s@%s\n' "$REPO_URL" "$BRANCH" >&2
    exit 1
fi

MDS_COMMIT=$(docker exec "$TEMP_CONTAINER" git -C /root/mavsdk_drone_show rev-parse --short HEAD)
TARGET_IMAGE="${IMAGE_REPO}:${VERSION_TAG}"

log "Flattening prepared container into ${TARGET_IMAGE}..."
docker_sitl_flatten_container \
    "$TEMP_CONTAINER" \
    "$BASE_IMAGE" \
    "$TARGET_IMAGE" \
    "LABEL mds.sitl.image.repo=${IMAGE_REPO}" \
    "LABEL mds.sitl.image.version=${VERSION_TAG}" \
    "LABEL mds.sitl.image.branch=${BRANCH}" \
    "LABEL mds.sitl.image.commit=${MDS_COMMIT}" \
    "LABEL mds.sitl.image.prepared_from=${BASE_IMAGE}"

if [[ "$TAG_LATEST" == true ]]; then
    docker tag "$TARGET_IMAGE" "${IMAGE_REPO}:latest"
fi
if [[ "$TAG_COMMIT" == true ]]; then
    docker tag "$TARGET_IMAGE" "${IMAGE_REPO}:${MDS_COMMIT}"
fi

log "Resulting tags:"
log "  ${TARGET_IMAGE}"
if [[ "$TAG_LATEST" == true ]]; then
    log "  ${IMAGE_REPO}:latest"
fi
if [[ "$TAG_COMMIT" == true ]]; then
    log "  ${IMAGE_REPO}:${MDS_COMMIT}"
fi
log "  commit=${MDS_COMMIT}"

if [[ "$PACKAGE_IMAGE" == true ]]; then
    PACKAGE_ARGS=(
        --image-repo "$IMAGE_REPO"
        --version-tag "$VERSION_TAG"
        --output-dir "$OUTPUT_DIR"
        --archive-basename "$ARCHIVE_BASENAME"
    )
    if [[ "$TAG_COMMIT" == true ]]; then
        PACKAGE_ARGS+=(--commit-tag "$MDS_COMMIT")
    fi
    if [[ "$COMPRESS" == false ]]; then
        PACKAGE_ARGS+=(--no-compress)
    fi
    bash "$SCRIPT_DIR/package_sitl_image.sh" "${PACKAGE_ARGS[@]}"
fi

log "Done."
