#!/bin/bash

# Wait for the .hwID file to exist
while [ ! -f ~/mavsdk_drone_show/*.hwID ]
do
  echo "Waiting for hwID file..."
  sleep 1
done

# Once the .hwID file exists, continue with the rest of the script
echo "Found .hwID file, continuing with the script."
cd ~/mavsdk_drone_show
echo "Stashing and pulling the latest changes from the repository..."
git stash
git pull

echo "Running the set_sys_id.py script to set the MAV_SYS_ID..."
python3 ~/mavsdk_drone_show/multiple_sitl/set_sys_id.py

# Start the px4_sitl gazebo process in the background
echo "Starting the px4_sitl gazebo process..."
cd ~/PX4-Autopilot
hwid_file=$(find ~/mavsdk_drone_show -name '*.hwID')
hwid=$(echo $hwid_file | cut -d'.' -f2)
export px4_instance=$hwid
HEADLESS=1 make px4_sitl gazebo &

# Start the coordinator.py process in the background
echo "Starting the coordinator.py process..."
cd ~/mavsdk_drone_show
python3 ~/mavsdk_drone_show/coordinator.py &

tail -f /dev/null
