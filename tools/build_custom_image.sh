#!/bin/bash

# =============================================================================
# MDS Custom Docker Image Builder (MDS v3.1+)
# =============================================================================
# This script automates the creation of custom Docker images for advanced users
# who want to deploy MDS with their own forked repositories.
#
# WHAT THIS SCRIPT DOES:
# 1. Takes a base drone-template:latest image
# 2. Temporarily runs it as a container
# 3. Updates the repository inside to your custom fork/branch
# 4. Commits the customized container as a new Docker image
# 5. Cleans up temporary containers
#
# PREREQUISITES:
# - Docker must be installed and running
# - Base image 'drone-template:latest' must exist
# - Network connectivity to access your repository
# - Appropriate git credentials (for private repos)
#
# FOR NORMAL USERS:
#   - This script is NOT needed - use the default image directly
#
# FOR ADVANCED USERS:
#   - Use this script to create custom images with your forked repository
#   - Run this script ONCE to create your custom image
#   - Then use the custom image with create_dockers.sh
# =============================================================================

set -euo pipefail  # Strict error handling

# Script metadata
SCRIPT_NAME=$(basename "$0")
SCRIPT_VERSION="1.0.0"

# =============================================================================
# CONFIGURATION WITH ENVIRONMENT VARIABLE SUPPORT
# =============================================================================
# You can override these values via:
# 1. Environment variables (MDS_REPO_URL, MDS_BRANCH, MDS_DOCKER_IMAGE)
# 2. Command line arguments (highest priority)
# 3. Default values (fallback)

DEFAULT_REPO_URL="${MDS_REPO_URL:-git@github.com:the-mak-00/mavsdk_drone_show.git}"
DEFAULT_BRANCH="${MDS_BRANCH:-main}"
DEFAULT_IMAGE_NAME="${MDS_DOCKER_IMAGE:-drone-template:custom}"
BASE_IMAGE="drone-template:latest"

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

# Display usage information
show_usage() {
    cat << EOF
🚀 MDS Custom Docker Image Builder v${SCRIPT_VERSION}

USAGE:
    ${SCRIPT_NAME} [REPO_URL] [BRANCH] [IMAGE_NAME]

PARAMETERS:
    REPO_URL     Git repository URL (SSH or HTTPS format)
                 Default: ${DEFAULT_REPO_URL}
                 Env var: MDS_REPO_URL

    BRANCH       Git branch name to checkout
                 Default: ${DEFAULT_BRANCH}
                 Env var: MDS_BRANCH

    IMAGE_NAME   Name for the new Docker image
                 Default: ${DEFAULT_IMAGE_NAME}
                 Env var: MDS_DOCKER_IMAGE

EXAMPLES:
    # Use defaults (from env vars or built-in defaults):
    ${SCRIPT_NAME}

    # Specify repository only:
    ${SCRIPT_NAME} git@github.com:company/fork.git

    # Specify repository and branch:
    ${SCRIPT_NAME} git@github.com:company/fork.git production

    # Specify all parameters:
    ${SCRIPT_NAME} git@github.com:company/fork.git production company-drone:v1.0

    # Use HTTPS (no SSH keys needed):
    ${SCRIPT_NAME} https://github.com/company/fork.git main company-drone:v1.0

ENVIRONMENT VARIABLES:
    export MDS_REPO_URL="git@github.com:company/fork.git"
    export MDS_BRANCH="production"
    export MDS_DOCKER_IMAGE="company-drone:v1.0"
    ${SCRIPT_NAME}

OPTIONS:
    -h, --help   Show this help message
    -v, --verbose Enable verbose output for debugging

NOTES:
    - This script requires the base image '${BASE_IMAGE}' to exist
    - For private repositories, ensure git credentials are properly configured
    - The resulting image can be used with: export MDS_DOCKER_IMAGE=<IMAGE_NAME>
EOF
}

# Logging functions
log_info() {
    echo "ℹ️  [INFO] $*"
}

log_success() {
    echo "✅ [SUCCESS] $*"
}

log_warning() {
    echo "⚠️  [WARNING] $*"
}

log_error() {
    echo "❌ [ERROR] $*" >&2
}

log_verbose() {
    if [[ "${VERBOSE:-false}" == "true" ]]; then
        echo "🔍 [VERBOSE] $*"
    fi
}

# Clean up function for error handling
cleanup() {
    local container_name="$1"
    if docker ps -a --format '{{.Names}}' | grep -q "^${container_name}$"; then
        log_verbose "Cleaning up temporary container: ${container_name}"
        docker rm -f "${container_name}" >/dev/null 2>&1 || true
    fi
}

# Validate Docker is available
check_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        log_error "Docker is not installed or not in PATH"
        exit 1
    fi

    if ! docker info >/dev/null 2>&1; then
        log_error "Docker daemon is not running or not accessible"
        log_error "Try: sudo systemctl start docker"
        exit 1
    fi

    log_verbose "Docker is available and running"
}

# Validate base image exists
check_base_image() {
    local base_image="$1"

    if ! docker images --format '{{.Repository}}:{{.Tag}}' | grep -q "^${base_image}$"; then
        log_error "Base image '${base_image}' not found"
        log_error "Please ensure the base image is loaded:"
        log_error "  docker load < drone-template-v3.tar"
        exit 1
    fi

    log_verbose "Base image '${base_image}' found"
}

# =============================================================================
# MAIN FUNCTIONS
# =============================================================================

# Build custom Docker image
build_custom_image() {
    local repo_url="$1"
    local branch="$2"
    local image_name="$3"
    local base_image="$4"

    # Generate unique temporary container name
    local temp_container="mds-custom-build-$(date +%s)-$$"

    log_info "Building custom Docker image..."
    log_info "  Repository: ${repo_url}"
    log_info "  Branch: ${branch}"
    log_info "  New Image: ${image_name}"
    log_info "  Base Image: ${base_image}"

    # Set up cleanup trap
    trap "cleanup '${temp_container}'" EXIT ERR

    # Step 1: Create temporary container
    log_info "Step 1/4: Creating temporary container..."
    if ! docker run --name "${temp_container}" -d "${base_image}" tail -f /dev/null >/dev/null; then
        log_error "Failed to create temporary container from base image"
        exit 1
    fi
    log_verbose "Temporary container '${temp_container}' created"

    # Step 2: Update repository inside container
    log_info "Step 2/4: Updating repository configuration..."

    local git_commands
    git_commands=$(cat << EOF
set -e
cd /root/mavsdk_drone_show
echo "Current repository status:"
git remote -v
git branch -a
echo "Updating remote URL to: ${repo_url}"
git remote set-url origin "${repo_url}"
echo "Fetching from repository..."
git fetch origin "${branch}"
echo "Checking out branch: ${branch}"
git checkout "${branch}"
echo "Pulling latest changes..."
git pull origin "${branch}"
echo "Repository update completed successfully"
git log --oneline -5
EOF
)

    if [[ "${VERBOSE:-false}" == "true" ]]; then
        # Run with visible output for debugging
        if ! docker exec "${temp_container}" bash -c "${git_commands}"; then
            log_error "Failed to update repository inside container"
            exit 1
        fi
    else
        # Run silently for normal operation
        if ! docker exec "${temp_container}" bash -c "${git_commands}" >/dev/null 2>&1; then
            log_error "Failed to update repository inside container"
            log_error "Try running with --verbose flag to see detailed error messages"
            exit 1
        fi
    fi

    log_verbose "Repository successfully updated inside container"

    # Step 3: Commit container to new image
    log_info "Step 3/4: Creating new Docker image..."
    local commit_message="Custom MDS image: ${repo_url}@${branch} ($(date '+%Y-%m-%d %H:%M:%S'))"

    if ! docker commit -m "${commit_message}" "${temp_container}" "${image_name}" >/dev/null; then
        log_error "Failed to commit container to new image"
        exit 1
    fi

    log_verbose "Container committed to image '${image_name}'"

    # Step 4: Cleanup temporary container
    log_info "Step 4/4: Cleaning up..."
    cleanup "${temp_container}"

    # Verify the image was created successfully
    if docker images --format '{{.Repository}}:{{.Tag}}' | grep -q "^${image_name}$"; then
        log_success "Custom Docker image '${image_name}' created successfully!"
    else
        log_error "Image creation appeared to succeed but image not found"
        exit 1
    fi
}

# =============================================================================
# MAIN SCRIPT EXECUTION
# =============================================================================

main() {
    # Parse command line arguments
    VERBOSE=false

    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_usage
                exit 0
                ;;
            -v|--verbose)
                VERBOSE=true
                shift
                ;;
            -*)
                log_error "Unknown option: $1"
                show_usage >&2
                exit 1
                ;;
            *)
                break
                ;;
        esac
    done

    # Get parameters (command line overrides environment variables and defaults)
    local repo_url="${1:-${DEFAULT_REPO_URL}}"
    local branch="${2:-${DEFAULT_BRANCH}}"
    local image_name="${3:-${DEFAULT_IMAGE_NAME}}"

    # Validate inputs
    if [[ -z "${repo_url}" ]]; then
        log_error "Repository URL cannot be empty"
        show_usage >&2
        exit 1
    fi

    if [[ -z "${branch}" ]]; then
        log_error "Branch name cannot be empty"
        show_usage >&2
        exit 1
    fi

    if [[ -z "${image_name}" ]]; then
        log_error "Image name cannot be empty"
        show_usage >&2
        exit 1
    fi

    # Pre-flight checks
    check_docker
    check_base_image "${BASE_IMAGE}"

    # Main execution
    build_custom_image "${repo_url}" "${branch}" "${image_name}" "${BASE_IMAGE}"

    # Success message with next steps
    log_success "🎉 Custom Docker image ready!"
    echo
    echo "NEXT STEPS:"
    echo "1. Set environment variable:"
    echo "   export MDS_DOCKER_IMAGE=\"${image_name}\""
    echo
    echo "2. Deploy drones using your custom image:"
    echo "   bash multiple_sitl/create_dockers.sh <number_of_drones>"
    echo
    echo "3. All containers will automatically use:"
    echo "   - Repository: ${repo_url}"
    echo "   - Branch: ${branch}"
    echo "   - Image: ${image_name}"
    echo
    log_info "Happy flying! 🚁"
}

# Execute main function with all arguments
main "$@"