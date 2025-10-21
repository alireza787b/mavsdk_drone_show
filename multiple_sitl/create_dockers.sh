#!/bin/bash

# Exit on any command failure
set -e
set -o pipefail

cat << "EOF"


  __  __   ___   _____ ___  _  __  ___  ___  ___  _  _ ___   ___ _  _  _____      __   ____  __ ___  _____  
 |  \/  | /_\ \ / / __|   \| |/ / |   \| _ \/ _ \| \| | __| / __| || |/ _ \ \    / /  / /  \/  |   \/ __\ \ 
 | |\/| |/ _ \ V /\__ \ |) | ' <  | |) |   / (_) | .` | _|  \__ \ __ | (_) \ \/\/ /  | || |\/| | |) \__ \| |
 |_|  |_/_/ \_\_/ |___/___/|_|\_\ |___/|_|_\\___/|_|\_|___| |___/_||_|\___/ \_/\_/   | ||_|  |_|___/|___/| |
                                                                                      \_\               /_/ 


EOF

echo "Project: mavsdk_drone_show (alireza787b/mavsdk_drone_show)"
echo "Version: 1.4 (November 2024)"
echo
echo "This script creates and configures multiple Docker container instances for the drone show simulation."
echo "Each container represents a drone instance running the SITL (Software In The Loop) environment."
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
echo "    export MDS_DOCKER_IMAGE=\"your-image:tag\""
echo "  Then run: bash create_dockers.sh <number>"
echo "  See: docs/advanced_sitl.md for complete guide"
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
#   - No action required - uses default drone-template:latest image
#   - Uses: git@github.com:alireza787b/mavsdk_drone_show.git@main
#   - Simply run: bash create_dockers.sh <number_of_drones>
#
# FOR ADVANCED USERS (Custom Docker Images & Repositories):
#   - Build custom image first (see tools/build_custom_image.sh)
#   - Set environment variables before running this script:
#     export MDS_DOCKER_IMAGE="company-drone:v1.0"
#     export MDS_REPO_URL="git@github.com:company/fork.git"
#     export MDS_BRANCH="production"
#   - All containers will use your custom image and repository
#
# ENVIRONMENT VARIABLES SUPPORTED:
#   MDS_DOCKER_IMAGE  - Docker image name to use (default: drone-template:latest)
#   MDS_REPO_URL      - Git repository URL (passed to containers)
#   MDS_BRANCH        - Git branch name (passed to containers)
#
# EXAMPLES:
#   # Normal usage (no environment variables):
#   bash create_dockers.sh 5
#
#   # Advanced usage with custom image and repository:
#   export MDS_DOCKER_IMAGE="mycompany-drone:v2.0"
#   export MDS_REPO_URL="git@github.com:mycompany/drone-fork.git"
#   export MDS_BRANCH="production"
#   bash create_dockers.sh 10
# =============================================================================

# Global variables (with environment variable override support)
STARTUP_SCRIPT_HOST="$HOME/mavsdk_drone_show/multiple_sitl/startup_sitl.sh"
STARTUP_SCRIPT_CONTAINER="/root/mavsdk_drone_show/multiple_sitl/startup_sitl.sh"
TEMPLATE_IMAGE="${MDS_DOCKER_IMAGE:-drone-template:latest}"
VERBOSE=false

# Variables for custom network, starting drone ID, and starting IP
CUSTOM_SUBNET="172.18.0.0/24"  # Default subnet
START_ID=1
START_IP=2
DOCKER_NETWORK_NAME="drone-network"
NETWORK_PREFIX=""
CIDR=0
HOST_BITS=0

# Function: display usage information
usage() {
    printf "Usage: %s <number_of_instances> [--verbose] [--subnet SUBNET] [--start-id START_ID] [--start-ip START_IP]\n" "$0"
    exit 1
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
    local hwid_file="${drone_id}.hwID"

    printf "\nCreating container '%s'...\n" "$container_name"

    # Remove existing container if it exists
    if docker ps -a --format '{{.Names}}' | grep -Eq "^${container_name}\$"; then
        printf "Container '%s' already exists. Removing it...\n" "$container_name"
        docker rm -f "$container_name" >/dev/null 2>&1
    fi

    # Create an empty .hwID file for the container
    if ! touch "$hwid_file"; then
        printf "Error: Failed to create hwID file '%s'\n" "$hwid_file" >&2
        return 1
    fi

    # Calculate IP address
    last_octet=$((START_IP + instance_num -1))
    IP_ADDRESS="${NETWORK_PREFIX}.${last_octet}"

    # Check for reserved IP addresses
    if [[ "$last_octet" -eq 0 || "$last_octet" -eq 255 ]]; then
        printf "Error: Calculated IP address ends with reserved octet '%d'\n" "$last_octet" >&2
        rm -f "$hwid_file"
        return 1
    fi

    # Run the container with specified network and IP (pass environment variables for repository config)
    if ! docker run --name "$container_name" --network "$DOCKER_NETWORK_NAME" --ip "$IP_ADDRESS" \
        -e MDS_REPO_URL="${MDS_REPO_URL:-}" \
        -e MDS_BRANCH="${MDS_BRANCH:-}" \
        -d "$TEMPLATE_IMAGE" tail -f /dev/null >/dev/null; then
        printf "Error: Failed to start container '%s'\n" "$container_name" >&2
        rm -f "$hwid_file"  # Clean up local .hwID file
        return 1
    fi

    printf "Container '%s' started successfully with IP '%s'.\n" "$container_name" "$IP_ADDRESS"

    # Ensure the directory exists inside the container
    if ! docker exec "$container_name" mkdir -p "/root/mavsdk_drone_show/multiple_sitl/"; then
        printf "Error: Failed to create directory in '%s'\n" "$container_name" >&2
        docker stop "$container_name" >/dev/null
        docker rm "$container_name" >/dev/null
        rm -f "$hwid_file"
        return 1
    fi

    # Transfer the .hwID file to the container
    if ! docker cp "$hwid_file" "${container_name}:/root/mavsdk_drone_show/"; then
        printf "Error: Failed to copy hwID file to container '%s'\n" "$container_name" >&2
        docker stop "$container_name" >/dev/null
        docker rm "$container_name" >/dev/null
        rm -f "$hwid_file"
        return 1
    fi
    rm -f "$hwid_file"  # Clean up local .hwID file

    # Transfer the startup script to the container
    if ! docker cp "$STARTUP_SCRIPT_HOST" "${container_name}:${STARTUP_SCRIPT_CONTAINER}"; then
        printf "Error: Failed to copy startup script to container '%s'\n" "$container_name" >&2
        docker stop "$container_name" >/dev/null
        docker rm "$container_name" >/dev/null
        return 1
    fi

    # Make the startup script executable inside the container
    if ! docker exec "$container_name" chmod +x "$STARTUP_SCRIPT_CONTAINER"; then
        printf "Error: Failed to make startup script executable in '%s'\n" "$container_name" >&2
        docker stop "$container_name" >/dev/null
        docker rm "$container_name" >/dev/null
        return 1
    fi

    # If verbose mode is enabled, run attached mode for debugging purposes
    if $VERBOSE; then
        printf "\nVerbose mode is enabled. Running container '%s' in attached mode for debugging.\n" "$container_name"
        printf "To exit the attached mode, press CTRL+C.\n"
        docker exec -it "$container_name" bash "$STARTUP_SCRIPT_CONTAINER" --verbose
        return 0
    fi

    # Run the startup SITL script inside the container in detached mode
    printf "Executing startup script in container '%s' (detached)...\n" "$container_name"
    if ! docker exec -d "$container_name" bash "$STARTUP_SCRIPT_CONTAINER"; then
        printf "Error: Failed to execute startup script in '%s'\n" "$container_name" >&2
        docker stop "$container_name" >/dev/null  # Stop container if startup fails
        docker rm "$container_name" >/dev/null
        return 1
    fi

    printf "Instance '%s' configured and started successfully.\n" "$container_name"
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
    printf "All %d instance(s) created and configured successfully.\n" "$num_instances"
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

    printf "To access QGC on another system, ensure 'mavlink-router' is installed:\n"
    printf "  bash ~/mavsdk_drone_show/tools/mavlink-router-install.sh\n\n"

    printf "Then run one of the following commands:\n"
    printf "  mavlink-routerd -e REMOTE_GCS_IP:24550 0.0.0.0:34550\n"
    printf "  bash ~/mavsdk_drone_show/tools/mavlink_route.sh REMOTE_GCS_IP:24550\n\n"

    printf "Now you can connect via QGC on port 24550 UDP from the remote GCS client.\n"

    # Provide cleanup command to remove all drone containers
    echo
    printf "To remove all created containers, execute the following command:\n"
    printf "  docker rm -f \$(docker ps -a --filter 'name=drone-' --format '{{.Names}}')\n"
    echo
}

# Ensure the startup script exists
if [[ ! -f "$STARTUP_SCRIPT_HOST" ]]; then
    printf "Error: Startup script '%s' not found.\n" "$STARTUP_SCRIPT_HOST" >&2
    exit 1
fi

# Execute the main function
main "$@"