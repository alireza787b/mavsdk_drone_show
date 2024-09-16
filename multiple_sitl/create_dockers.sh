#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Enable debug mode for easier troubleshooting (optional)
# set -x

# Function to display usage information
usage() {
    echo "Usage: $0 <number_of_instances>"
    exit 1
}

# Check if the number of instances is provided
if [ -z "$1" ]; then
    echo "Error: Number of instances not provided."
    usage
fi

NUM_INSTANCES=$1

# Validate that NUM_INSTANCES is a positive integer
if ! [[ "$NUM_INSTANCES" =~ ^[1-9][0-9]*$ ]]; then
    echo "Error: Number of instances must be a positive integer."
    usage
fi

# Function to create and configure a single Docker container instance
create_instance() {
    local instance_num=$1
    local container_name="drone-$instance_num"
    local hwid_file="${instance_num}.hwID"
    local template_image="drone-template-1"
    local startup_script="/root/mavsdk_drone_show/multiple_sitl/startup_sitl.sh"

    echo "Creating instance ${container_name}..."

    # Create an empty .hwID file
    touch "$hwid_file"

    # Run the Docker container in detached mode
    docker run --name "$container_name" -d "$template_image" bash "$startup_script"

    echo "Container ${container_name} started. Waiting for initialization..."

    # Wait briefly to allow the container to initialize
    sleep 5

    # Copy the .hwID file into the container
    docker cp "$hwid_file" "${container_name}:/root/mavsdk_drone_show/"

    # Remove the local .hwID file
    rm "$hwid_file"

    # Stop the container to modify its services
    echo "Stopping container ${container_name} to modify services..."
    docker stop "$container_name"

    # Remove the coordinator.service from the container
    echo "Removing coordinator.service from ${container_name}..."
    docker start "$container_name" >/dev/null
    docker exec "$container_name" bash -c "systemctl stop coordinator.service || true"
    docker exec "$container_name" bash -c "systemctl disable coordinator.service || true"
    docker exec "$container_name" rm -f /etc/systemd/system/coordinator.service

    # Run the startup_sitl.sh script
    echo "Running startup_sitl.sh in ${container_name}..."
    docker exec "$container_name" bash "$startup_script"

    # Re-add the coordinator.service
    echo "Re-adding and starting coordinator.service in ${container_name}..."
    docker exec "$container_name" bash -c "systemctl enable coordinator.service"
    docker exec "$container_name" bash -c "systemctl start coordinator.service"

    # Commit the changes to the container (optional)
    # docker commit "$container_name" "${container_name}-configured"

    echo "Instance ${container_name} configured successfully."
}

# Loop to create the specified number of instances
for ((i=1; i<=NUM_INSTANCES; i++)); do
    create_instance "$i"
done

echo "All ${NUM_INSTANCES} instances created and configured successfully."
