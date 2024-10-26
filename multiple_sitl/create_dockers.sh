#!/bin/bash

# Exit on any command failure
set -e

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
echo

# Global variables
STARTUP_SCRIPT_HOST="$HOME/mavsdk_drone_show/multiple_sitl/startup_sitl.sh"
STARTUP_SCRIPT_CONTAINER="/root/mavsdk_drone_show/multiple_sitl/startup_sitl.sh"
TEMPLATE_IMAGE="drone-template"

# Function: display usage information
usage() {
    printf "Usage: %s <number_of_instances>\n" "$0"
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
        exit 1
    fi

    # Run the container and keep it running
    if ! docker run --name "$container_name" -d "$TEMPLATE_IMAGE" tail -f /dev/null >/dev/null; then
        printf "Error: Failed to start container '%s'\n" "$container_name" >&2
        rm -f "$hwid_file"  # Clean up local .hwID file
        exit 1
    fi

    printf "Container '%s' started.\n" "$container_name"

    # Ensure the directory exists inside the container
    if ! docker exec "$container_name" mkdir -p "/root/mavsdk_drone_show/multiple_sitl/"; then
        printf "Error: Failed to create directory in '%s'\n" "$container_name" >&2
        docker stop "$container_name" >/dev/null
        docker rm "$container_name" >/dev/null
        rm -f "$hwid_file"
        exit 1
    fi

    # Transfer the .hwID file to the container
    if ! docker cp "$hwid_file" "${container_name}:/root/mavsdk_drone_show/"; then
        printf "Error: Failed to copy hwID file to container '%s'\n" "$container_name" >&2
        docker stop "$container_name" >/dev/null
        docker rm "$container_name" >/dev/null
        rm -f "$hwid_file"
        exit 1
    fi
    rm -f "$hwid_file"  # Clean up local .hwID file

    # Transfer the startup script to the container
    if ! docker cp "$STARTUP_SCRIPT_HOST" "${container_name}:${STARTUP_SCRIPT_CONTAINER}"; then
        printf "Error: Failed to copy startup script to container '%s'\n" "$container_name" >&2
        docker stop "$container_name" >/dev/null
        docker rm "$container_name" >/dev/null
        exit 1
    fi

    # Make the startup script executable inside the container
    if ! docker exec "$container_name" chmod +x "$STARTUP_SCRIPT_CONTAINER"; then
        printf "Error: Failed to make startup script executable in '%s'\n" "$container_name" >&2
        docker stop "$container_name" >/dev/null
        docker rm "$container_name" >/dev/null
        exit 1
    fi

    # Run the startup SITL script inside the container
    printf "Running startup script in container '%s'...\n" "$container_name"
    if ! docker exec "$container_name" bash "$STARTUP_SCRIPT_CONTAINER"; then
        printf "Error: Failed to run startup script in '%s'\n" "$container_name" >&2
        docker stop "$container_name" >/dev/null  # Stop container if startup fails
        docker rm "$container_name" >/dev/null
        return 1
    fi

    printf "Instance '%s' configured successfully.\n" "$container_name"
}

# Main function: loop to create multiple instances
main() {
    local num_instances=$1

    # Create instances loop
    for ((i=1; i<=num_instances; i++)); do
        if ! create_instance "$i"; then
            printf "Error: Instance creation failed for drone-%d. Aborting...\n" "$i" >&2
            exit 1
        fi
    done

    printf "\nAll %d instances created and configured successfully.\n" "$num_instances"
}

# Validate input and ensure the startup script exists
validate_input "$1"
if [[ ! -f "$STARTUP_SCRIPT_HOST" ]]; then
    printf "Error: Startup script '%s' not found.\n" "$STARTUP_SCRIPT_HOST" >&2
    exit 1
fi

# Execute the main function
main "$1"
