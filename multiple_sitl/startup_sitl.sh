#!/bin/bash

# To run the script with gazebo classic graphics enabled, you would execute the script with the g argument, like this:
# ./startup.sh g

# To run without graphics (headless), you can either provide the h argument or no arguments:
# ./startup.sh h
# OR simply
# ./startup.sh

# To run with jmavsim, you would execute the script with the j argument:
# ./startup.sh j

# Function to handle SIGINT
cleanup() {
  echo "Received interrupt, terminating background processes..."
  kill $simulation_pid
  exit 0
}

# Trap SIGINT
trap 'cleanup' INT

# Determine the command based on the provided argument
case $1 in
  g)
    SIMULATION_COMMAND="make px4_sitl gazebo"
    echo "Graphics enabled."
    ;;
  j)
    SIMULATION_COMMAND="make px4_sitl jmavsim"
    echo "Using jmavsim."
    ;;
  h|*)
    SIMULATION_COMMAND="HEADLESS=1 make px4_sitl gazebo"
    echo "Graphics disabled."
    ;;
esac

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

echo "Starting the simulation process in a new terminal window..."
gnome-terminal -- bash -c "cd ~/PX4-Autopilot; hwid_file=\$(find ~/mavsdk_drone_show -name '*.hwID'); hwid=\$(echo \$hwid_file | cut -d'.' -f2); export px4_instance=\$hwid-1; $SIMULATION_COMMAND; bash" &
simulation_pid=$!

echo "Starting the coordinator.py process in another new terminal window..."
gnome-terminal -- bash -c "python3 ~/mavsdk_drone_show/coordinator.py; bash" &

echo "Press Ctrl+C to stop the simulation process."
wait $simulation_pid
