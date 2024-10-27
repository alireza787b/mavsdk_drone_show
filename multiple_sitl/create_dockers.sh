#!/bin/bash

# Exit on any command failure
set -e
set -o pipefail

# Introductory banner
cat << "EOF"

  __  __   ___   _____ ___  _  __  ___  ___  ___  _  _ ___   ___ _  _  _____      __   ____  __ ___  _____  
 |  \/  | /_\ \ / / __|   \| |/ / |   \| _ \/ _ \| \| | __| / __| || |/ _ \ \    / /  / /  \/  |   \/ __\ \ 
 | |\/| |/ _ \ V /\__ \ |) | ' <  | |) |   / (_) | .` | _|  \__ \ __ | (_) \ \/\/ /  | || |\/| | |) \__ \| |
 |_|  |_/_/ \_\_/ |___/___/|_|\_\ |___/|_|_\\___/|_|\_|___| |___/_||_|\___/ \_/\_/   | ||_|  |_|___/|___/| |
                                                                                      \_\               /_/ 

EOF

echo "Project: mavsdk_drone_show (alireza787b/mavsdk_drone_show)"
echo "Version: 1.0 (October 2024)"
echo
echo "This script creates and configures multiple Docker container instances for the drone show simulation."
echo "Each container represents a drone instance running the SITL (Software In The Loop) environment."
echo "To debug, run bash create_dockers.sh 1 --verbose to see full console logs of the container workflow."
echo "You can also manually craete containers with command:  docker run -it --name my-drone drone-template:latest /bin/bash "
echo

# Global variables
STARTUP_SCRIPT_HOST="$HOME/mavsdk_drone_show/multiple_sitl/startup_sitl.sh"
STARTUP_SCRIPT_CONTAINER="/root/mavsdk_drone_show/multiple_sitl/startup_sitl.sh"
TEMPLATE_IMAGE="drone-template"
VERBOSE=false

# Function: display usage information
usage() {
    printf "Usage: %s <number_of_instances> [--verbose]\n" "$0"
    exit 1
}

# Validate the number of instances input
validate_input() {
    if [[ -z "$1" ]]; then
        printf "Error: Number of instances not provided.\n" >&2
        usage
    elif ! [[ "$1" =~ ^[1-9][0-9]*$ ]]; then
        printf "Error: Number of instances must be a positive integer.\n" >&2
        usage
    fi
}

# Function: create and configure a single Docker container instance
create_instance() {
    local instance_num=$1
    local container_name="drone-$instance_num"
    local hwid_file="${instance_num}.hwID"

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

    # Run the container and keep it running
    if ! docker run --name "$container_name" -d "$TEMPLATE_IMAGE" tail -f /dev/null >/dev/null; then
        printf "Error: Failed to start container '%s'\n" "$container_name" >&2
        rm -f "$hwid_file"  # Clean up local .hwID file
        return 1
    fi

    printf "Container '%s' started.\n" "$container_name"

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
        printf "\nVerbose mode is ON. Running one container in attached mode for debugging.\n"
        printf "Container '%s' will run in attached mode. Check logs for any errors inside the container.\n" "$container_name"
        docker exec -it "$container_name" bash "$STARTUP_SCRIPT_CONTAINER"
        return 0
    fi

    # Run the startup SITL script inside the container in detached mode
    printf "Running startup script in container '%s' (detached)...\n" "$container_name"
    if ! docker exec -d "$container_name" bash "$STARTUP_SCRIPT_CONTAINER"; then
        printf "Error: Failed to run startup script in '%s'\n" "$container_name" >&2
        docker stop "$container_name" >/dev/null  # Stop container if startup fails
        docker rm "$container_name" >/dev/null
        return 1
    fi

    printf "Instance '%s' configured successfully.\n" "$container_name"
}

# Function: report system resource usage
report_resources() {
    local container_name=$1
    local cpu_usage memory_usage storage_usage

    # Get CPU usage
    cpu_usage=$(docker stats "$container_name" --no-stream --format "{{.CPUPerc}}")
    memory_usage=$(docker stats "$container_name" --no-stream --format "{{.MemUsage}}")
    storage_usage=$(docker exec "$container_name" df -h / | tail -1 | awk '{print $3 "/" $2}')

    printf "Resources for container '%s': CPU: %s, Memory: %s, Storage: %s\n" "$container_name" "$cpu_usage" "$memory_usage" "$storage_usage"
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
            *)
                shift
                ;;
        esac
    done

    # Create instances loop
    for ((i=1; i<=num_instances; i++)); do
        if $VERBOSE && [[ $i -gt 1 ]]; then
            printf "Verbose mode only supports running one container for debugging purposes.\n"
            printf "Skipping creation of container 'drone-%d'.\n" "$i"
            break
        fi

        if ! create_instance "$i"; then
            printf "Error: Instance creation failed for drone-%d. Aborting...\n" "$i" >&2
            exit 1
        fi

        # Report resources after container setup (only in non-verbose mode)
        if ! $VERBOSE; then
            report_resources "drone-$i"
        fi
    done

    printf "\nAll %d instances created and configured successfully.\n" "$num_instances"

    # Provide cleanup command to remove all drone containers
    printf "\nTo remove all created containers, you can run the following command:\n"
    printf "docker rm -f \$(docker ps -a --filter 'name=drone-' --format '{{.Names}}')\n"
}

# Validate input and ensure the startup script exists
validate_input "$1"
if [[ ! -f "$STARTUP_SCRIPT_HOST" ]]; then
    printf "Error: Startup script '%s' not found.\n" "$STARTUP_SCRIPT_HOST" >&2
    exit 1
fi

# Execute the main function
main "$@"
