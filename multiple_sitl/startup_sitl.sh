#!/bin/bash

# Determine the user's home directory and set the mavsdk_drone_show directory path
USER_HOME=$(eval echo ~$SUDO_USER)
DIRECTORY="$USER_HOME/mavsdk_drone_show"

# Check if the directory exists
if [ ! -d "$DIRECTORY" ]; then
  echo "Directory not found at $DIRECTORY. Exiting."
  exit 1
fi

echo "Found directory at $DIRECTORY"


# Wait for the .hwID file to exist
while [ ! -f $DIRECTORY/*.hwID ]
do
  echo "Waiting for hwID file in $DIRECTORY..."
  sleep 1
done

echo "Found .hwID file, continuing with the script."
cd $DIRECTORY
echo "Stashing and pulling the latest changes from the repository..."
git stash
git pull

echo "Checking Python Requirements..."
pip install -r requirements.txt

echo "Running the set_sys_id.py script to set the MAV_SYS_ID..."
python3 $DIRECTORY/multiple_sitl/set_sys_id.py

echo "Starting the px4_sitl gazebo process..."
cd ~/PX4-Autopilot
hwid_file=$(find $DIRECTORY -name '*.hwID')
hwid=$(echo $hwid_file | cut -d'.' -f2)
export px4_instance=$((hwid-1))
HEADLESS=1 make px4_sitl gazebo &

echo "Starting the coordinator.py process..."
cd $DIRECTORY
python3 $DIRECTORY/coordinator.py &

tail -f /dev/null
