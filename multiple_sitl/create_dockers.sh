#!/bin/bash

# *****************************************************************************************
# Docker Initialization Script for MAVSDK_Drone_Show SITL Instances
# Author: Alireza Ghaderi
# GitHub: https://github.com/alireza787b/mavsdk_drone_show
# Date: April 2024
#
# This script automates the creation and setup of multiple Docker containers for simulating
# different SITL (Software in the Loop) instances of the MAVSDK_Drone_Show project. It 
# initializes each container with a specific branch of the project repository, facilitating
# parallel simulations with varied code bases.
#
# Usage:
# ./create_docker.sh <number_of_instances> [branch_name]
#
# Arguments:
#   number_of_instances - Required. Specifies the number of Docker containers to create.
#   branch_name - Optional. Specifies the GitHub branch to be used for each container. Defaults to 'main'.
#
# Requirements:
#   Docker must be installed and running on the host machine. The script assumes access to
#   a Docker image named 'drone-template-1' that is pre-configured to run the SITL simulations.
#
# Example:
#   To create 5 containers using the 'development' branch of the repository:
#   ./create_docker.sh 5 development
#
# Note:
#   This script will create an empty '.hwID' file for each container, copy it to the container,
#   and then clean up by removing the file locally. It uses a basic loop and assumes that each
#   container is named sequentially as 'drone-1', 'drone-2', etc.
# *****************************************************************************************

echo "Welcome to the Docker Initialization Script for MAVSDK_Drone_Show!"

# Get the number of instances as input
num_instances=$1
branch_name=${2:-main}  # Default to 'main' if no branch is specified

# Check if the number of instances is provided
if [ -z "$num_instances" ]
then
    echo "Please provide the number of instances as argument"
    exit 1
fi

# Loop to create instances
for (( i=1; i<=$num_instances; i++ ))
do
    echo "Creating instance drone-$i"

    # Create an empty .hwID file in your local directory
    touch $i.hwID

    # Run the Docker container, pass the branch name to the startup script
    docker run --name drone-$i -d drone-template-1 bash /root/mavsdk_drone_show/multiple_sitl/startup_sitl.sh '' $branch_name

    # Give Docker a moment to get the container up and running
    sleep 3

    # Copy the .hwID file to the Docker container
    docker cp $i.hwID drone-$i:/root/mavsdk_drone_show/

    # Remove the local .hwID file
    rm $i.hwID
done
