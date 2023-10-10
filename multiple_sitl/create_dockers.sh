#!/bin/bash

# Get the number of instances as input
num_instances=$1

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

    # Run the Docker container
    docker run --name drone-$i -d drone-template-1 bash /root/mavsdk_drone_show/multiple_sitl/startup_sitl.sh

    # Give Docker a moment to get the container up and running
    sleep 3

    # Copy the .hwID file to the Docker container
    docker cp $i.hwID drone-$i:/root/mavsdk_drone_show/

    # Remove the local .hwID file
    rm $i.hwID
done
