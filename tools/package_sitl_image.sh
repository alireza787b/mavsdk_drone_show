#!/bin/bash

set -euo pipefail

SCRIPT_NAME=$(basename "$0")
DEFAULT_IMAGE_REPO="${MDS_SITL_IMAGE_REPO:-mavsdk-drone-show-sitl}"
DEFAULT_ARCHIVE_BASENAME="${MDS_SITL_IMAGE_ARCHIVE_BASENAME:-mavsdk-drone-show-sitl-image}"
OUTPUT_DIR="${PWD}"
IMAGE_REPO="$DEFAULT_IMAGE_REPO"
VERSION_TAG="latest"
COMMIT_TAG=""
ARCHIVE_BASENAME="$DEFAULT_ARCHIVE_BASENAME"
COMPRESS=true
KEEP_TAR=false

usage() {
    cat <<EOF
Package the official Docker SITL image into a stable tar/7z distribution.

Usage:
  ${SCRIPT_NAME} [--image-repo REPO] [--version-tag TAG] [--commit-tag SHA] [--output-dir DIR] [--archive-basename NAME] [--no-compress] [--keep-tar]

Defaults:
  image repo        ${DEFAULT_IMAGE_REPO}
  version tag       latest
  archive basename  ${DEFAULT_ARCHIVE_BASENAME}

Examples:
  ${SCRIPT_NAME} --version-tag v5 --commit-tag 5ac3a36f
  ${SCRIPT_NAME} --image-repo mycompany-mds-sitl --version-tag v5-custom --no-compress

Notes:
  - The exported tar keeps Docker tags inside the image metadata.
  - Official public archives should keep a stable filename; versioning belongs in Docker tags.
  - Official releases should include both the stable release tag and latest.
  - If --commit-tag is set, that tag is exported too for traceability.
  - When compression is enabled, the generated .7z is verified with '7z t'.
  - Compression writes a .sha256 checksum and manifest. The raw tar is deleted
    after compression unless --keep-tar is set.
  - When compression is enabled without --keep-tar, packaging streams
    'docker save' directly into 7z to avoid large intermediate tar files on
    disk-constrained hosts.
EOF
}

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

image_ref_exists() {
    docker image inspect "$1" >/dev/null 2>&1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
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
        --keep-tar)
            KEEP_TAR=true
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

require_cmd docker
require_cmd sha256sum
mkdir -p "$OUTPUT_DIR"

image_refs=("${IMAGE_REPO}:${VERSION_TAG}")

if [[ "${VERSION_TAG}" != "latest" ]]; then
    image_refs+=("${IMAGE_REPO}:latest")
fi

if [[ -n "${COMMIT_TAG}" ]]; then
    image_refs+=("${IMAGE_REPO}:${COMMIT_TAG}")
fi

unique_refs=()
for ref in "${image_refs[@]}"; do
    skip=false
    for seen in "${unique_refs[@]}"; do
        if [[ "$seen" == "$ref" ]]; then
            skip=true
            break
        fi
    done
    if [[ "$skip" == false ]]; then
        unique_refs+=("$ref")
    fi
done

for ref in "${unique_refs[@]}"; do
    image_ref_exists "$ref" || fail "Docker image tag not found: $ref"
done

tar_path="${OUTPUT_DIR}/${ARCHIVE_BASENAME}.tar"
archive_path="${OUTPUT_DIR}/${ARCHIVE_BASENAME}.7z"
archive_sha_path="${archive_path}.sha256"
tar_sha_path="${tar_path}.sha256"
manifest_path="${OUTPUT_DIR}/${ARCHIVE_BASENAME}.manifest.json"

log "Packaging Docker SITL image"
log "  Image refs : ${unique_refs[*]}"

tar_file="$(basename "$tar_path")"
tar_sha_file=""
if [[ "$COMPRESS" == true ]]; then
    require_cmd 7z
    rm -f "$archive_path"
    rm -f "$archive_sha_path"
    log "  7z output  : ${archive_path}"
    if [[ "$KEEP_TAR" == "true" ]]; then
        log "  Tar output : ${tar_path}"
        docker save -o "$tar_path" "${unique_refs[@]}"
        7z a "$archive_path" "$tar_path" >/dev/null
    else
        log "  Tar stream : ${ARCHIVE_BASENAME}.tar"
        docker save "${unique_refs[@]}" | 7z a "$archive_path" "-si${ARCHIVE_BASENAME}.tar" >/dev/null
    fi
    log "  7z verify  : ${archive_path}"
    7z t "$archive_path" >/dev/null
    sha256sum "$archive_path" > "$archive_sha_path"
    if [[ "$KEEP_TAR" == "true" ]]; then
        sha256sum "$tar_path" > "$tar_sha_path"
        tar_sha_file="$(basename "$tar_sha_path")"
    else
        tar_file=""
    fi
else
    log "  Tar output : ${tar_path}"
    docker save -o "$tar_path" "${unique_refs[@]}"
    sha256sum "$tar_path" > "$tar_sha_path"
    tar_sha_file="$(basename "$tar_sha_path")"
fi

archive_file=""
archive_sha_file=""
if [[ "$COMPRESS" == true ]]; then
    archive_file="$(basename "$archive_path")"
    archive_sha_file="$(basename "$archive_sha_path")"
fi

cat > "$manifest_path" <<EOF
{
  "image_repo": "${IMAGE_REPO}",
  "version_tag": "${VERSION_TAG}",
  "commit_tag": "${COMMIT_TAG}",
  "image_refs": [
$(for idx in "${!unique_refs[@]}"; do
    suffix=","
    if [[ "$idx" -eq $((${#unique_refs[@]} - 1)) ]]; then
        suffix=""
    fi
    printf '    "%s"%s\n' "${unique_refs[$idx]}" "$suffix"
done)
  ],
  "tar_file": "${tar_file}",
  "tar_sha256_file": "${tar_sha_file}",
  "archive_file": "${archive_file}",
  "archive_sha256_file": "${archive_sha_file}"
}
EOF

log "Done."
