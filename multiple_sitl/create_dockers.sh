#!/bin/bash

# Exit on any command failure
set -e
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MDS_REPO_ROOT="$REPO_ROOT"
DEPLOYMENT_PROFILE_LOADER="$REPO_ROOT/tools/load_deployment_profile.sh"
if [[ -f "$DEPLOYMENT_PROFILE_LOADER" ]]; then
    # shellcheck disable=SC1090
    source "$DEPLOYMENT_PROFILE_LOADER"
fi

cat << "EOF"


  __  __   ___   _____ ___  _  __  ___  ___  ___  _  _ ___   ___ _  _  _____      __   ____  __ ___  _____  
 |  \/  | /_\ \ / / __|   \| |/ / |   \| _ \/ _ \| \| | __| / __| || |/ _ \ \    / /  / /  \/  |   \/ __\ \ 
 | |\/| |/ _ \ V /\__ \ |) | ' <  | |) |   / (_) | .` | _|  \__ \ __ | (_) \ \/\/ /  | || |\/| | |) \__ \| |
 |_|  |_/_/ \_\_/ |___/___/|_|\_\ |___/|_|_\\___/|_|\_|___| |___/_||_|\___/ \_/\_/   | ||_|  |_|___/|___/| |
                                                                                      \_\               /_/ 


EOF

echo "Project: mavsdk_drone_show (alireza787b/mavsdk_drone_show)"
echo "Launcher: Docker SITL bootstrap"
echo
echo "This script creates and configures multiple Docker container instances for the drone show simulation."
echo "Each container represents a drone instance running the SITL (Software In The Loop) environment."
echo "The active simulator path is headless PX4 Gazebo Harmonic via startup_sitl.sh."
echo
echo "Usage: bash create_dockers.sh <number_of_instances> [--verbose] [--subnet SUBNET] [--start-id START_ID] [--start-ip START_IP]"
echo
echo "Parameters:"
echo "  <number_of_instances>   Number of drone instances to create."
echo "  --verbose               Run in verbose mode for debugging (only creates one instance)."
echo "  --subnet SUBNET         Specify a custom Docker network subnet (default: 172.18.0.0/24)."
echo "  --start-id START_ID     Specify the starting drone ID (default: 1)."
echo "  --start-ip START_IP     Specify the starting IP address's last octet within the subnet (default: 2)."
echo
echo "Notes:"
echo "  - Drones are assigned IP addresses starting from the specified START_IP."
echo "    For example, with START_IP=2, the first drone will have IP '172.18.0.2' in the default subnet."
echo "  - Drone IDs and IP addresses are assigned independently."
echo "  - Reserved IP addresses (.0, .255) are skipped to avoid conflicts."
echo
echo "To debug and see full console logs of the container workflow, run:"
echo "  bash create_dockers.sh 1 --verbose"
echo
echo "For ADVANCED USERS - Custom Repository Configuration:"
echo "  Set environment variables before running this script:"
echo "    export MDS_REPO_URL=\"git@github.com:yourorg/yourrepo.git\""
echo "    export MDS_BRANCH=\"your-branch\""
echo "    export MDS_GIT_AUTH_TOKEN_FILE=\"/secure/path/github_read_token\"  # private HTTPS read-only"
echo "    export MDS_GIT_SSH_KEY_FILE=\"/secure/path/github_read_key\"       # private SSH read-only fallback"
echo "    export MDS_DOCKER_IMAGE=\"your-image:tag\""
echo "  Then run: bash create_dockers.sh <number>"
echo "  All MDS_* environment variables are forwarded into the container runtime."
echo "  See: docs/guides/custom-sitl-auth.md and docs/guides/advanced-sitl.md"
echo
echo "==============================================================="
echo

# =============================================================================
# DOCKER CONFIGURATION: Environment Variable Support (MDS v3.1+)
# =============================================================================
# This script now supports custom Docker images and repository configuration
# via environment variables while maintaining full backward compatibility.
#
# FOR NORMAL USERS (99%):
#   - No action required - uses the deployment profile default image
#   - Uses the deployment profile repo and branch, currently main
#   - Simply run: bash create_dockers.sh <number_of_drones>
#
# FOR ADVANCED USERS (Custom Docker Images & Repositories):
#   - Build custom image first (see tools/build_custom_image.sh)
#   - Set environment variables before running this script:
#     export MDS_DOCKER_IMAGE="company-mds-sitl:v1.0"
#     export MDS_REPO_URL="git@github.com:company/fork.git"
#     export MDS_BRANCH="production"
#     export MDS_GIT_AUTH_TOKEN_FILE="/secure/path/github_read_token"   # private GitHub HTTPS only
#     export MDS_GIT_SSH_KEY_FILE="/secure/path/github_read_key"        # private GitHub SSH fallback
#   - All containers will use your custom image and repository
#
# ENVIRONMENT VARIABLES SUPPORTED:
#   MDS_DOCKER_IMAGE  - Docker image name to use (default: deployment profile image)
#   Any MDS_* runtime variable exported on the host is forwarded into the
#   container, except the internal MDS_BASE_DIR path which is
#   fixed by this launcher.
#
# EXAMPLES:
#   # Normal usage (no environment variables):
#   bash create_dockers.sh 5
#
#   # Advanced usage with custom image and repository:
#   export MDS_DOCKER_IMAGE="mycompany-mds-sitl:v2.0"
#   export MDS_REPO_URL="git@github.com:mycompany/drone-fork.git"
#   export MDS_BRANCH="production"
#   bash create_dockers.sh 10
# =============================================================================

# Global variables (with environment variable override support)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STARTUP_SCRIPT_HOST="$REPO_ROOT/multiple_sitl/startup_sitl.sh"
STARTUP_SCRIPT_CONTAINER="/tmp/mds_startup_sitl.sh"
HOST_RUNTIME_ROOT="${MDS_SITL_HOST_RUNTIME_ROOT:-$HOME/.local/share/mavsdk_drone_show/sitl_runtime}"
HOST_SHARED_SWARM_TRAJECTORY_DIR="${MDS_SITL_HOST_SWARM_TRAJECTORY_DIR:-$REPO_ROOT/shapes_sitl/swarm_trajectory}"
CONTAINER_SHARED_SWARM_TRAJECTORY_DIR="${MDS_SITL_SHARED_SWARM_TRAJECTORY_DIR:-/tmp/mds_shared_swarm_trajectory}"
SHARE_HOST_SWARM_TRAJECTORY="${MDS_SITL_SHARE_SWARM_TRAJECTORY:-true}"
HWID_CONTAINER_DIR="/root/mavsdk_drone_show"
STARTUP_SCRIPT_IMAGE="${HWID_CONTAINER_DIR}/multiple_sitl/startup_sitl.sh"
STARTUP_LOG_CONTAINER="${HWID_CONTAINER_DIR}/logs/startup_sitl.log"
TEMPLATE_IMAGE="${MDS_DOCKER_IMAGE:-${MDS_DEFAULT_DOCKER_IMAGE:-mavsdk-drone-show-sitl:latest}}"
USE_HOST_STARTUP_SCRIPT="${MDS_SITL_USE_HOST_STARTUP_SCRIPT:-}"
USE_HOST_STARTUP_SCRIPT_SOURCE="unset"
DOCKER_RESTART_POLICY="${MDS_SITL_DOCKER_RESTART_POLICY:-unless-stopped}"
VERBOSE=false
DOCKER_ENV_ARGS=()
DOCKER_SECRET_ARGS=()
CREATED_CONTAINERS=()
READY_CONTAINERS=()
FAILED_CONTAINERS=()
WAIT_FOR_READY="${MDS_SITL_WAIT_FOR_READY:-true}"
READY_TIMEOUT_SECONDS="${MDS_SITL_READY_TIMEOUT_SECONDS:-60}"
READY_POLL_INTERVAL_SECONDS="${MDS_SITL_READY_POLL_INTERVAL_SECONDS:-2}"
SITL_GIT_SYNC_PREFLIGHT="${MDS_SITL_GIT_SYNC_PREFLIGHT:-true}"

# Variables for custom network, starting drone ID, and starting IP
CUSTOM_SUBNET="172.18.0.0/24"  # Default subnet
START_ID=1
START_IP=2
DOCKER_NETWORK_NAME="${MDS_SITL_DOCKER_NETWORK:-drone-network}"
NETWORK_PREFIX=""
CIDR=0
HOST_BITS=0

# Function: display usage information
usage() {
    printf "Usage: %s <number_of_instances> [--verbose] [--subnet SUBNET] [--start-id START_ID] [--start-ip START_IP]\n" "$0"
    exit 1
}

collect_mds_env_args() {
    DOCKER_ENV_ARGS=(
        -e "MDS_BASE_DIR=/root/mavsdk_drone_show"
        -e "MDS_INSTALL_DIR=/root/mavsdk_drone_show"
        -e "MDS_REPO_ROOT=/root/mavsdk_drone_show"
        -e "MDS_DEPLOYMENT_PROFILE_FILE=/root/mavsdk_drone_show/deployment/defaults.env"
    )
    DOCKER_SECRET_ARGS=()

    local env_name
    while IFS='=' read -r env_name _; do
        case "$env_name" in
            MDS_BASE_DIR|MDS_INSTALL_DIR|MDS_REPO_ROOT|MDS_DEPLOYMENT_PROFILE_FILE|MDS_HW_ID|MDS_GIT_AUTH_TOKEN|MDS_GIT_AUTH_TOKEN_FILE|MDS_GIT_SSH_KEY_FILE)
                continue
                ;;
        esac
        DOCKER_ENV_ARGS+=(-e "$env_name")
    done < <(env | sort | grep '^MDS_[A-Za-z0-9_]*=' || true)

    prepare_git_auth_secret_args
    prepare_git_ssh_secret_args
    DOCKER_ENV_ARGS+=(-e "MDS_SITL_USE_HOST_STARTUP_SCRIPT=${USE_HOST_STARTUP_SCRIPT}")
}

resolve_host_startup_script_mode() {
    local requested="${MDS_SITL_USE_HOST_STARTUP_SCRIPT:-}"
    local effective_git_sync="${MDS_SITL_GIT_SYNC:-true}"

    if [[ -n "$requested" ]]; then
        USE_HOST_STARTUP_SCRIPT="$requested"
        USE_HOST_STARTUP_SCRIPT_SOURCE="env:MDS_SITL_USE_HOST_STARTUP_SCRIPT"
        return 0
    fi

    if [[ "$effective_git_sync" == "true" ]]; then
        USE_HOST_STARTUP_SCRIPT="true"
        USE_HOST_STARTUP_SCRIPT_SOURCE="auto:mutable_git_sync"
    else
        USE_HOST_STARTUP_SCRIPT="false"
        USE_HOST_STARTUP_SCRIPT_SOURCE="auto:pinned_image"
    fi
}

prepare_git_auth_secret_args() {
    local host_secret_file="${MDS_GIT_AUTH_TOKEN_FILE:-}"
    local generated_secret_file=""
    local secret_dir=""
    local container_secret_file="/run/secrets/mds_git_auth_token"

    if [[ -z "$host_secret_file" && -z "${MDS_GIT_AUTH_TOKEN:-}" ]]; then
        return 0
    fi

    if [[ -n "$host_secret_file" ]]; then
        if [[ ! -r "$host_secret_file" ]]; then
            printf "Error: MDS_GIT_AUTH_TOKEN_FILE is not readable: %s\n" "$host_secret_file" >&2
            exit 1
        fi
    else
        secret_dir="${HOST_RUNTIME_ROOT}/_secrets"
        mkdir -p "$secret_dir"
        chmod 700 "$secret_dir"
        generated_secret_file="${secret_dir}/mds_git_auth_token"
        local old_umask
        old_umask=$(umask)
        umask 077
        printf '%s' "$MDS_GIT_AUTH_TOKEN" > "$generated_secret_file"
        umask "$old_umask"
        chmod 600 "$generated_secret_file"
        host_secret_file="$generated_secret_file"
    fi

    DOCKER_SECRET_ARGS+=(-v "${host_secret_file}:${container_secret_file}:ro")
    DOCKER_ENV_ARGS+=(-e "MDS_GIT_AUTH_TOKEN_FILE=${container_secret_file}")
}

prepare_git_ssh_secret_args() {
    local host_secret_file="${MDS_GIT_SSH_KEY_FILE:-}"
    local container_secret_file="/run/secrets/mds_git_ssh_key"

    if [[ -z "$host_secret_file" ]]; then
        return 0
    fi

    if [[ ! -r "$host_secret_file" ]]; then
        printf "Error: MDS_GIT_SSH_KEY_FILE is not readable: %s\n" "$host_secret_file" >&2
        exit 1
    fi

    DOCKER_SECRET_ARGS+=(-v "${host_secret_file}:${container_secret_file}:ro")
    DOCKER_ENV_ARGS+=(-e "MDS_GIT_SSH_KEY_FILE=${container_secret_file}")
}

print_launcher_configuration() {
    echo "Launcher Configuration:"
    echo "  Docker Image   : ${TEMPLATE_IMAGE}"
    echo "  Repo Root      : ${REPO_ROOT}"
    if [[ "${USE_HOST_STARTUP_SCRIPT}" == "true" ]]; then
        echo "  Startup Script : host override (${STARTUP_SCRIPT_HOST})"
    else
        echo "  Startup Script : image-baked (${STARTUP_SCRIPT_IMAGE})"
    fi
    echo "  Startup Source : ${USE_HOST_STARTUP_SCRIPT_SOURCE}"
    echo "  Container Repo : /root/mavsdk_drone_show"
    echo "  Runtime Root   : ${HOST_RUNTIME_ROOT}"
    echo "  Shared Traj    : ${SHARE_HOST_SWARM_TRAJECTORY}"
    if [[ "${SHARE_HOST_SWARM_TRAJECTORY}" == "true" ]]; then
        echo "  Traj Source    : ${HOST_SHARED_SWARM_TRAJECTORY_DIR}"
        echo "  Traj Mount     : ${CONTAINER_SHARED_SWARM_TRAJECTORY_DIR}"
    fi
    echo "  Restart Policy : ${DOCKER_RESTART_POLICY}"
    echo "  Wait For Ready : ${WAIT_FOR_READY}"
    echo "  Ready Timeout  : ${READY_TIMEOUT_SECONDS}s"
    echo "  Ready Poll     : ${READY_POLL_INTERVAL_SECONDS}s"

    local forwarded_names=()
    local env_name
    for ((i=0; i<${#DOCKER_ENV_ARGS[@]}; i++)); do
        if [[ "${DOCKER_ENV_ARGS[$i]}" == "-e" && $((i + 1)) -lt ${#DOCKER_ENV_ARGS[@]} ]]; then
            env_name="${DOCKER_ENV_ARGS[$((i + 1))]%%=*}"
            forwarded_names+=("$env_name")
        fi
    done

    if [ ${#forwarded_names[@]} -gt 0 ]; then
        echo "  Forwarded Env  : ${forwarded_names[*]}"
    fi

    echo
}

validate_launcher_configuration() {
    case "$WAIT_FOR_READY" in
        true|false) ;;
        *)
            printf "Error: MDS_SITL_WAIT_FOR_READY must be 'true' or 'false'.\n" >&2
            exit 1
            ;;
    esac

    if ! [[ "$READY_TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
        printf "Error: MDS_SITL_READY_TIMEOUT_SECONDS must be a positive integer.\n" >&2
        exit 1
    fi

    if ! [[ "$READY_POLL_INTERVAL_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
        printf "Error: MDS_SITL_READY_POLL_INTERVAL_SECONDS must be a positive integer.\n" >&2
        exit 1
    fi

    case "$USE_HOST_STARTUP_SCRIPT" in
        true|false) ;;
        *)
            printf "Error: MDS_SITL_USE_HOST_STARTUP_SCRIPT must be 'true' or 'false'.\n" >&2
            exit 1
            ;;
    esac

    case "$SITL_GIT_SYNC_PREFLIGHT" in
        true|false) ;;
        *)
            printf "Error: MDS_SITL_GIT_SYNC_PREFLIGHT must be 'true' or 'false'.\n" >&2
            exit 1
            ;;
    esac

    case "$SHARE_HOST_SWARM_TRAJECTORY" in
        true|false) ;;
        *)
            printf "Error: MDS_SITL_SHARE_SWARM_TRAJECTORY must be 'true' or 'false'.\n" >&2
            exit 1
            ;;
    esac

    if [[ -z "$DOCKER_RESTART_POLICY" ]]; then
        printf "Error: MDS_SITL_DOCKER_RESTART_POLICY must not be empty.\n" >&2
        exit 1
    fi
}

print_scale_guidance() {
    local num_instances="$1"
    local effective_git_sync="${MDS_SITL_GIT_SYNC:-true}"
    local effective_requirements_sync="${MDS_SITL_REQUIREMENTS_SYNC:-true}"

    if (( num_instances >= 10 )) && [[ "$effective_git_sync" == "true" ]]; then
        printf "Warning: launching %d containers with MDS_SITL_GIT_SYNC=true will trigger %d runtime git fetch/reset operations.\n" "$num_instances" "$num_instances" >&2
        printf "For validated large-fleet runs, prefer a rebuilt image plus MDS_SITL_GIT_SYNC=false.\n" >&2
    fi

    if (( num_instances >= 10 )) && [[ "$effective_requirements_sync" == "true" ]]; then
        printf "Notice: if requirements.txt changes, MDS_SITL_REQUIREMENTS_SYNC=true can also trigger one pip sync per container at boot.\n" >&2
        printf "For validated large-fleet runs, usually keep MDS_SITL_REQUIREMENTS_SYNC=false after baking the approved venv into the image.\n" >&2
    fi
}

run_git_access_preflight() {
    local effective_git_sync="${MDS_SITL_GIT_SYNC:-true}"
    local repo_url="${MDS_REPO_URL:-${MDS_DEFAULT_REPO_URL_HTTPS:-https://github.com/alireza787b/mavsdk_drone_show.git}}"
    local branch="${MDS_BRANCH:-${MDS_DEFAULT_BRANCH:-main}}"

    if [[ "$effective_git_sync" != "true" ]]; then
        echo "Git Access     : skipped (MDS_SITL_GIT_SYNC=false; using baked image checkout)"
        return 0
    fi

    if [[ "$SITL_GIT_SYNC_PREFLIGHT" != "true" ]]; then
        echo "Git Access     : skipped (MDS_SITL_GIT_SYNC_PREFLIGHT=false)"
        return 0
    fi

    echo "Git Access     : validating ${repo_url}@${branch} before launching containers"
    if ! MDS_GIT_AUTH_TOKEN_FILE="${MDS_GIT_AUTH_TOKEN_FILE:-}" \
        MDS_GIT_AUTH_TOKEN="${MDS_GIT_AUTH_TOKEN:-}" \
        MDS_GIT_AUTH_USERNAME="${MDS_GIT_AUTH_USERNAME:-}" \
        MDS_GIT_SSH_KEY_FILE="${MDS_GIT_SSH_KEY_FILE:-}" \
        MDS_GIT_KNOWN_HOSTS_FILE="${MDS_GIT_KNOWN_HOSTS_FILE:-}" \
        bash "$REPO_ROOT/tools/mds_git_access_check.sh" \
        --repo-url "$repo_url" \
        --branch "$branch" \
        --mode sitl-read; then
        cat >&2 <<'EOF'

SITL repo access preflight failed.
Containers were not created because startup git sync would fail inside them.
Fix the repo URL, branch, or read-only credential, then rerun this command.

Guide: docs/guides/custom-sitl-auth.md
EOF
        exit 1
    fi
}

# Validate the number of instances and inputs
validate_input() {
    local num_instances="$1"
    shift

    if [[ -z "$num_instances" ]]; then
        printf "Error: Number of instances not provided.\n" >&2
        usage
    elif ! [[ "$num_instances" =~ ^[1-9][0-9]*$ ]]; then
        printf "Error: Number of instances must be a positive integer.\n" >&2
        usage
    fi

    # Validate START_ID if provided
    if ! [[ "$START_ID" =~ ^[1-9][0-9]*$ ]]; then
        printf "Error: Starting drone ID must be a positive integer.\n" >&2
        usage
    fi

    # Validate START_IP if provided
    if ! [[ "$START_IP" =~ ^[0-9]+$ ]] || (( START_IP < 2 || START_IP > 254 )); then
        printf "Error: Starting IP must be an integer between 2 and 254.\n" >&2
        usage
    fi

    # Validate subnet format
    if [[ -n "$CUSTOM_SUBNET" ]]; then
        if ! echo "$CUSTOM_SUBNET" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/[0-9]+$'; then
            printf "Error: Invalid subnet format. Use CIDR notation, e.g., 172.18.0.0/24\n" >&2
            exit 1
        fi
        CIDR=$(echo "$CUSTOM_SUBNET" | cut -d'/' -f2)
        if ! [[ "$CIDR" -eq 24 ]]; then
            printf "Error: Only /24 subnets are currently supported.\n" >&2
            exit 1
        fi

        # Calculate the maximum last octet
        last_octet_max=$((START_IP + num_instances - 1))
        if (( last_octet_max > 254 )); then
            printf "Error: The calculated IP addresses exceed the subnet capacity (max host IP octet is 254).\n" >&2
            exit 1
        fi
    fi
}
report_system_resources() {
    echo "---------------------------------------------------------------"
    echo "System Resource Usage:"

    # CPU Usage
    cpu_idle=$(top -bn1 | grep "Cpu(s)" | awk -F'id,' '{split($1, a, ","); print 100 - a[length(a)]}')
    cpu_usage=$(printf "%.0f" "$cpu_idle")
    echo "CPU Usage      : ${cpu_usage}%"

    # Memory Usage
    mem_total=$(free -h | awk '/^Mem:/ {print $2}')
    mem_used=$(free -h | awk '/^Mem:/ {print $3}')
    mem_free=$(free -h | awk '/^Mem:/ {print $4}')
    echo "Memory Usage   : Used ${mem_used} / Total ${mem_total} (Free: ${mem_free})"

    # Disk Usage
    disk_total=$(df -h / | awk 'NR==2 {print $2}')
    disk_used=$(df -h / | awk 'NR==2 {print $3}')
    disk_available=$(df -h / | awk 'NR==2 {print $4}')
    echo "Disk Usage     : Used ${disk_used} / Total ${disk_total} (Available: ${disk_available})"

    # Uptime + Load + Users
    uptime_raw=$(uptime)
    uptime_info=$(echo "$uptime_raw" | sed -E 's/.*up (.*), *[0-9]+ user.*/\1/')
    users=$(echo "$uptime_raw" | awk -F',' '{print $2}' | grep -o '[0-9]\+')
    load_avg=$(echo "$uptime_raw" | awk -F'load average: ' '{print $2}')

    echo "Uptime         : ${uptime_info}"
    echo "Logged-in Users: ${users}"
    echo "Load Averages  : ${load_avg}"

    echo "---------------------------------------------------------------"
    echo
}


# Function: create or use a Docker network with a custom subnet
setup_docker_network() {
    # Check if the network already exists
    if ! docker network ls --format '{{.Name}}' | grep -q "^${DOCKER_NETWORK_NAME}$"; then
        echo "Creating Docker network '${DOCKER_NETWORK_NAME}' with subnet '${CUSTOM_SUBNET}'..."
        docker network create --subnet="$CUSTOM_SUBNET" "$DOCKER_NETWORK_NAME"
    else
        local existing_subnet
        existing_subnet=$(docker network inspect "$DOCKER_NETWORK_NAME" --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}')
        if [[ "$existing_subnet" != "$CUSTOM_SUBNET" ]]; then
            printf "Error: Docker network '%s' already exists with subnet '%s' (requested '%s').\n" "$DOCKER_NETWORK_NAME" "$existing_subnet" "$CUSTOM_SUBNET" >&2
            exit 1
        fi
        echo "Docker network '${DOCKER_NETWORK_NAME}' already exists. Using existing network."
    fi

    # Extract network prefix and CIDR
    NETWORK_PREFIX=$(echo "$CUSTOM_SUBNET" | cut -d'/' -f1 | cut -d'.' -f1-3)
    CIDR=$(echo "$CUSTOM_SUBNET" | cut -d'/' -f2)
    HOST_BITS=$((32 - CIDR))

    # Ensure only /24 subnets are used
    if [[ "$CIDR" -ne 24 ]]; then
        echo "Error: Only /24 subnets are currently supported." >&2
        exit 1
    fi
}

# Function: create and configure a single Docker container instance
create_instance() {
    local instance_num=$1
    local drone_id=$((START_ID + instance_num -1))
    local container_name="drone-$drone_id"
    local startup_script_container
    local startup_bootstrap
    local detached_command
    local docker_run_args=()

    printf "\nCreating container '%s'...\n" "$container_name"

    # Remove existing container if it exists
    if docker ps -a --format '{{.Names}}' | grep -Eq "^${container_name}\$"; then
        printf "Container '%s' already exists. Removing it...\n" "$container_name"
        docker rm -f "$container_name" >/dev/null 2>&1
    fi

    # Calculate IP address
    last_octet=$((START_IP + instance_num -1))
    IP_ADDRESS="${NETWORK_PREFIX}.${last_octet}"

    # Check for reserved IP addresses
    if [[ "$last_octet" -eq 0 || "$last_octet" -eq 255 ]]; then
        printf "Error: Calculated IP address ends with reserved octet '%d'\n" "$last_octet" >&2
        rm -rf "$runtime_dir"
        return 1
    fi

    startup_script_container="$STARTUP_SCRIPT_IMAGE"
    docker_run_args=(
        --name "$container_name"
        --network "$DOCKER_NETWORK_NAME"
        --ip "$IP_ADDRESS"
        --restart "$DOCKER_RESTART_POLICY"
        -e "MDS_HW_ID=${drone_id}"
        "${DOCKER_ENV_ARGS[@]}"
        "${DOCKER_SECRET_ARGS[@]}"
    )

    if [[ "${SHARE_HOST_SWARM_TRAJECTORY}" == "true" ]]; then
        mkdir -p "${HOST_SHARED_SWARM_TRAJECTORY_DIR}"
        docker_run_args+=(
            -e "MDS_SITL_SHARED_SWARM_TRAJECTORY_DIR=${CONTAINER_SHARED_SWARM_TRAJECTORY_DIR}"
            -v "${HOST_SHARED_SWARM_TRAJECTORY_DIR}:${CONTAINER_SHARED_SWARM_TRAJECTORY_DIR}:ro"
        )
    fi

    if [[ "${USE_HOST_STARTUP_SCRIPT}" == "true" ]]; then
        startup_script_container="$STARTUP_SCRIPT_CONTAINER"
        docker_run_args+=(-v "${STARTUP_SCRIPT_HOST}:${STARTUP_SCRIPT_CONTAINER}:ro")
    fi

    startup_bootstrap="mkdir -p '$HWID_CONTAINER_DIR/logs' && exec bash '$startup_script_container'"
    detached_command="${startup_bootstrap} >> '$STARTUP_LOG_CONTAINER' 2>&1"

    # If verbose mode is enabled, run attached mode for debugging purposes
    if $VERBOSE; then
        printf "\nVerbose mode is enabled. Running container '%s' in attached mode for debugging.\n" "$container_name"
        printf "To exit the attached mode, press CTRL+C.\n"
        if [[ -t 0 && -t 1 ]]; then
            docker run "${docker_run_args[@]}" -it "$TEMPLATE_IMAGE" bash -lc "${startup_bootstrap} --verbose"
        else
            printf "No interactive TTY detected. Falling back to non-TTY verbose mode.\n"
            docker run "${docker_run_args[@]}" -i "$TEMPLATE_IMAGE" bash -lc "${startup_bootstrap} --verbose"
        fi
        return 0
    fi

    # Run the startup SITL script as the container's main process so restart
    # semantics remain correct after host reboots or docker restarts.
    printf "Starting container '%s' with startup_sitl.sh as PID 1...\n" "$container_name"
    if ! docker run "${docker_run_args[@]}" -d "$TEMPLATE_IMAGE" bash -lc "$detached_command" >/dev/null; then
        printf "Error: Failed to start container '%s'\n" "$container_name" >&2
        return 1
    fi

    printf "Container '%s' started successfully with IP '%s'.\n" "$container_name" "$IP_ADDRESS"

    printf "Instance '%s' launched. Awaiting readiness verification.\n" "$container_name"
    CREATED_CONTAINERS+=("$container_name")
}

instance_is_ready() {
    local container_name="$1"
    docker exec "$container_name" bash -lc '
        px4_dir="${MDS_PX4_DIR:-/root/PX4-Autopilot}"
        base_dir="${MDS_BASE_DIR:-/root/mavsdk_drone_show}"
        pgrep -f "${px4_dir}/build/px4_sitl_default/bin/px4" >/dev/null &&
        pgrep -x mavlink-routerd >/dev/null &&
        pgrep -f "${base_dir}/coordinator.py" >/dev/null
    ' >/dev/null 2>&1
}

print_container_failure_logs() {
    local container_name="$1"

    printf "Recent startup diagnostics for '%s':\n" "$container_name" >&2
    docker exec "$container_name" bash -lc "
        echo '--- startup_sitl.log ---'
        tail -n 60 '$STARTUP_LOG_CONTAINER' 2>/dev/null || true
        echo '--- mavlink_router.log ---'
        tail -n 40 '$HWID_CONTAINER_DIR/logs/mavlink_router.log' 2>/dev/null || true
        echo '--- coordinator.log ---'
        tail -n 40 '$HWID_CONTAINER_DIR/logs/coordinator.log' 2>/dev/null || true
        echo '--- sitl_simulation.log ---'
        tail -n 40 '$HWID_CONTAINER_DIR/logs/sitl_simulation.log' 2>/dev/null || true
    " >&2 || true
}

wait_for_instances_ready() {
    local pending=("${CREATED_CONTAINERS[@]}")
    local next_pending=()
    local elapsed=0
    local container_name

    if [ ${#pending[@]} -eq 0 ]; then
        return 0
    fi

    printf "\nWaiting for %d container(s) to become ready...\n" "${#pending[@]}"

    while [ ${#pending[@]} -gt 0 ] && [ "$elapsed" -lt "$READY_TIMEOUT_SECONDS" ]; do
        next_pending=()

        for container_name in "${pending[@]}"; do
            if instance_is_ready "$container_name"; then
                READY_CONTAINERS+=("$container_name")
                printf "Ready: %s\n" "$container_name"
            else
                next_pending+=("$container_name")
            fi
        done

        pending=("${next_pending[@]}")
        if [ ${#pending[@]} -eq 0 ]; then
            return 0
        fi

        sleep "$READY_POLL_INTERVAL_SECONDS"
        elapsed=$((elapsed + READY_POLL_INTERVAL_SECONDS))
    done

    FAILED_CONTAINERS=("${pending[@]}")
    for container_name in "${FAILED_CONTAINERS[@]}"; do
        printf "Error: '%s' did not become ready within %ss.\n" "$container_name" "$READY_TIMEOUT_SECONDS" >&2
        print_container_failure_logs "$container_name"
    done

    return 1
}

# Function: report container-specific resource usage
report_container_resources() {
    local container_name=$1
    local cpu_usage memory_usage storage_usage ip_address

    # Get CPU usage
    cpu_usage=$(docker stats "$container_name" --no-stream --format "{{.CPUPerc}}")
    # Get Memory usage
    memory_usage=$(docker stats "$container_name" --no-stream --format "{{.MemUsage}}")
    # Get Storage usage (assuming root filesystem)
    storage_usage=$(docker exec "$container_name" df -h / | tail -1 | awk '{print $3 "/" $2}')
    # Get IP address
    ip_address=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$container_name")

    printf "Resources for '%s': CPU: %s | Memory: %s | Storage: %s | IP: %s\n" "$container_name" "$cpu_usage" "$memory_usage" "$storage_usage" "$ip_address"
}

# Main function: loop to create multiple instances
main() {
    local num_instances=$1
    shift

    # Parse options
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --verbose)
                VERBOSE=true
                shift
                ;;
            --subnet)
                CUSTOM_SUBNET="$2"
                shift 2
                ;;
            --start-id)
                START_ID="$2"
                shift 2
                ;;
            --start-ip)
                START_IP="$2"
                shift 2
                ;;
            *)
                echo "Unknown option: $1"
                usage
                ;;
        esac
    done

    # Validate inputs
    validate_input "$num_instances"
    resolve_host_startup_script_mode
    validate_launcher_configuration

    collect_mds_env_args
    print_launcher_configuration
    print_scale_guidance "$num_instances"
    run_git_access_preflight

    # Setup Docker network
    setup_docker_network

    # Create instances loop
    for ((i=1; i<=num_instances; i++)); do
        if $VERBOSE && [[ $i -gt 1 ]]; then
            printf "\nVerbose mode only supports running one container for debugging purposes.\n"
            printf "Skipping creation of container 'drone-%d'.\n" "$((START_ID + i -1))"
            break
        fi

        if ! create_instance "$i"; then
            printf "Error: Instance creation failed for drone-%d. Aborting...\n" "$((START_ID + i -1))" >&2
            exit 1
        fi

        # Report system resources after each container setup (only in non-verbose mode)
        if ! $VERBOSE; then
            report_system_resources
        fi
    done

    if ! $VERBOSE && [[ "$WAIT_FOR_READY" == "true" ]]; then
        if ! wait_for_instances_ready; then
            printf "Error: one or more containers failed readiness checks.\n" >&2
            exit 1
        fi
    fi

    # Introductory banner
    cat << "EOF"
    ___  ___  ___  _   _ ___________ _   __ ____________ _____ _   _  _____   _____ _   _ _____  _    _    ____  ________  _______  
    |  \/  | / _ \| | | /  ___|  _  \ | / / |  _  \ ___ \  _  | \ | ||  ___| /  ___| | | |  _  || |  | |  / /  \/  |  _  \/  ___\ \ 
    | .  . |/ /_\ \ | | \ `--.| | | | |/ /  | | | | |_/ / | | |  \| || |__   \ `--.| |_| | | | || |  | | | || .  . | | | |\ `--. | |
    | |\/| ||  _  | | | |`--. \ | | |    \  | | | |    /| | | | . ` ||  __|   `--. \  _  | | | || |/\| | | || |\/| | | | | `--. \| |
    | |  | || | | \ \_/ /\__/ / |/ /| |\  \ | |/ /| |\ \\ \_/ / |\  || |___  /\__/ / | | \ \_/ /\  /\  / | || |  | | |/ / /\__/ /| |
    \_|  |_/\_| |_/\___/\____/|___/ \_| \_/ |___/ \_| \_|\___/\_| \_/\____/  \____/\_| |_/\___/  \/  \/  | |\_|  |_/___/  \____/ | |
                                                                                                          \_\                   /_/                                                                                                                                                                                                                                                
EOF

    echo
    if ! $VERBOSE && [[ "$WAIT_FOR_READY" == "true" ]]; then
        printf "All %d instance(s) created and verified ready.\n" "$num_instances"
    else
        printf "All %d instance(s) created and configured successfully.\n" "$num_instances"
    fi
    echo "========================================================="
    echo
    printf "Instances created with starting drone ID: %d\n" "$START_ID"
    printf "Starting IP address's last octet: %d\n" "$START_IP"
    printf "Docker network name: %s\n" "$DOCKER_NETWORK_NAME"
    printf "Subnet used: %s\n" "$CUSTOM_SUBNET"
    echo

    # Final system resource summary
    printf "Final System Resource Summary:\n"
    report_system_resources

    # Provide guidance to the user
    echo "To monitor resources in real-time, consider using 'htop':"
    echo "  sudo apt-get install htop   # Install htop if not already installed"
    echo "  htop                        # Run htop to view real-time system metrics"
    echo

    # Print success message with additional instructions
    printf "To run the Swarm Dashboard, execute the following command:\n"
    printf "  bash ~/mavsdk_drone_show/app/linux_dashboard_start.sh --sitl\n"
    printf "You can access the swarm dashboard at http://GCS_SERVER_IP:3030\n\n"

    printf "For remote QGroundControl / multi-GCS routing, use the current routing guide:\n"
    printf "  ~/mavsdk_drone_show/docs/guides/mavlink-routing-setup.md\n\n"

    printf "If you need the host-side MAVLink router helper, install it with:\n"
    printf "  git clone https://github.com/alireza787b/mavlink-anywhere\n"
    printf "  cd mavlink-anywhere\n"
    printf "  sudo ./install_mavlink_router.sh\n\n"

    printf "Then point your remote GCS/QGC workflow at UDP port 24550 as documented in the routing guide.\n"

    # Provide cleanup command to remove all drone containers
    echo
    printf "To remove all created containers, execute the following command:\n"
    printf "  docker rm -f \$(docker ps -a --filter 'name=drone-' --format '{{.Names}}')\n"
    echo
}

# Ensure the startup script exists when host override mode is enabled
if [[ "${USE_HOST_STARTUP_SCRIPT}" == "true" ]] && [[ ! -f "$STARTUP_SCRIPT_HOST" ]]; then
    printf "Error: Startup script '%s' not found.\n" "$STARTUP_SCRIPT_HOST" >&2
    exit 1
fi

# Execute the main function
main "$@"
