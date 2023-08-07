#!/bin/bash

# Function to handle SIGINT
cleanup() {
  echo "Received interrupt, terminating background processes..."
  kill $gazebo_pid $coordinator_pid
  exit 0
}

# Trap SIGINT
trap 'cleanup' INT


# Determine the directory path
DIRECTORY=~/mavsdk_drone_show

# Echo the directory being searched
echo "Looking for .hwID file in $DIRECTORY..."

# Wait for the .hwID file to exist
while [ ! -f "$DIRECTORY/*.hwID" ]
do
  echo "Waiting for hwID file..."
  sleep 1
done

# Once the .hwID file exists, continue with the rest of the script
echo "Found .hwID file, continuing with the script."
cd $DIRECTORY
echo "Stashing and pulling the latest changes from the repository..."
git stash
git pull

echo "Checking Python Requirements..."
pip install -r requirements.txt

echo "Running the set_sys_id.py script to set the MAV_SYS_ID..."
python3 $DIRECTORY/multiple_sitl/set_sys_id.py

# Start the px4_sitl gazebo process in the background
cd ~/PX4-Autopilot
HEADLESS=1 make px4_sitl gazebo &
gazebo_pid=$!

# Start the coordinator.py process in the background
cd ~/mavsdk_drone_show
python3 ~/mavsdk_drone_show/coordinator.py &
coordinator_pid=$!

tail -f /dev/null