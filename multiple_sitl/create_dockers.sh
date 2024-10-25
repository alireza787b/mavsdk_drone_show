#!/bin/bash

# Exit on any command failure
set -e

# Global variables
STARTUP_SCRIPT="$HOME/mavsdk_drone_show/multiple_sitl/startup_sitl.sh"
TEMPLATE_IMAGE="drone-template-1"

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

    printf "Creating container '%s'...\n" "$container_name"

    # Create an empty .hwID file for the container
    touch "$hwid_file"

    # Run the container and execute startup script
    docker run --name "$container_name" -d "$TEMPLATE_IMAGE" bash "$STARTUP_SCRIPT"

    printf "Container '%s' started. Waiting for initialization...\n" "$container_name"
    sleep 5  # Allow some time for initialization

    # Transfer the .hwID file to the container
    docker cp "$hwid_file" "${container_name}:/root/mavsdk_drone_show/"
    rm "$hwid_file"  # Clean up local .hwID file

    # Run the startup SITL script
    printf "Running '%s' in container '%s'...\n" "$STARTUP_SCRIPT" "$container_name"
    if ! docker exec "$container_name" bash "$STARTUP_SCRIPT"; then
        printf "Error: Failed to run '%s' in '%s'\n" "$STARTUP_SCRIPT" "$container_name" >&2
        docker stop "$container_name"  # Stop container if startup fails
        docker rm "$container_name"
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

    printf "All %d instances created and configured successfully.\n" "$num_instances"
}

# Validate input and ensure the startup script exists
validate_input "$1"
if [[ ! -f "$STARTUP_SCRIPT" ]]; then
    printf "Error: Startup script '%s' not found.\n" "$STARTUP_SCRIPT" >&2
    exit 1
fi

# Execute the main function
main "$1"
