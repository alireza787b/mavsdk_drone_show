#!/bin/bash

# To run the script with graphics enabled, you would execute the script with the g argument, like this:

# bash
# Copy code
# ./startup.sh g
# To run without graphics, you would simply execute the script without any arguments:

# bash
# Copy code
# ./startup.sh

# Function to handle SIGINT
cleanup() {
  echo "Received interrupt, terminating background processes..."
  kill $gazebo_pid
  exit 0
}

# Trap SIGINT
trap 'cleanup' INT

# Check for the 'g' argument to enable or disable graphics
if [[ $1 == "g" ]]; then
  HEADLESS=0
  echo "Graphics enabled."
else
  HEADLESS=1
  echo "Graphics disabled."
fi

# Wait for the .hwID file to exist
while [ ! -f ~/mavsdk_drone_show/*.hwID ]
do
  echo "Waiting for hwID file..."
  sleep 1
done

echo "Found .hwID file, continuing with the script."
cd ~/mavsdk_drone_show
echo "Stashing and pulling the latest changes from the repository..."
git stash
git pull

echo "Checking Python Requirements..."
pip install -r requirements.txt

echo "Running the set_sys_id.py script to set the MAV_SYS_ID..."
python3 ~/mavsdk_drone_show/multiple_sitl/set_sys_id.py

echo "Starting the px4_sitl gazebo process..."
cd ~/PX4-Autopilot
hwid_file=$(find ~/mavsdk_drone_show -name '*.hwID')
hwid=$(echo $hwid_file | cut -d'.' -f2)
export px4_instance=$hwid-1
HEADLESS=$HEADLESS make px4_sitl gazebo &
gazebo_pid=$!

echo "Starting the coordinator.py process in a new terminal window..."
gnome-terminal -- python3 ~/mavsdk_drone_show/coordinator.py

echo "Press Ctrl+C to stop the gazebo process."
wait $gazebo_pid
