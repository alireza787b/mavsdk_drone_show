#!/bin/bash

echo "Welcome to the SITL Startup Script for MAVSDK_Drone_Show!"
echo ""
echo "This script will do the following:"
echo "1. Wait for the .hwID file to be present."
echo "2. Pull the latest changes from the repository."
echo "3. Check Python requirements and install if necessary."
echo "4. Set the MAV_SYS_ID using set_sys_id.py."
echo "5. Start the SITL simulation process based on the chosen environment."
echo "6. Start the coordinator.py process."
echo ""
echo "Please wait as the script initializes the necessary components..."
echo ""

# Function to handle SIGINT
cleanup() {
  echo "Received interrupt, terminating background processes..."
  kill $simulation_pid
  exit 0
}

# Trap SIGINT
trap 'cleanup' INT

# Check if 'bc' is installed
if ! command -v bc &> /dev/null; then
    echo "WARNING: 'bc' is not installed. It's required for location offset calculations."
    echo "To install 'bc', run:"
    echo "sudo apt-get install bc"
    exit 1
fi

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

# Default position: Mehrabad Airport
DEFAULT_LAT=35.6857
DEFAULT_LON=51.3036
DEFAULT_ALT=1208

# Read hwID from the file
while [ ! -f ~/mavsdk_drone_show/*.hwID ]; do
  echo "Waiting for hwID file..."
  sleep 1
done

HWID=$(basename ~/mavsdk_drone_show/i.hwID)

# Fetch offsets for the current drone from config.csv
while IFS=, read -r hw_id pos_id x y ip mavlink_port debug_port gcs_ip; do
    if [ "$hw_id" == "$HWID" ]; then
        OFFSET_X=$x
        OFFSET_Y=$y
        break
    fi
done < ~/mavsdk_drone_show/config.csv

# Calculate new LAT and LON based on the offsets
NEW_LAT=$(echo "$DEFAULT_LAT + $OFFSET_X / 111111" | bc -l)
NEW_LON=$(echo "$DEFAULT_LON + $OFFSET_Y / (111111 * c($DEFAULT_LAT))" | bc -l)

# Modify the SIMULATION_COMMAND to initialize the drone at the calculated position
SIMULATION_COMMAND="$SIMULATION_COMMAND -l $NEW_LAT,$NEW_LON,$DEFAULT_ALT"

# Pull the latest repo changes
cd ~/mavsdk_drone_show
echo "Stashing and pulling the latest changes from the repository..."
git stash
git pull

# Check Python requirements
echo "Checking and installing Python Requirements..."
pip install -r requirements.txt

# Set the MAV_SYS_ID
echo "Running the set_sys_id.py script to set the MAV_SYS_ID..."
python3 ~/mavsdk_drone_show/multiple_sitl/set_sys_id.py

# Start the SITL simulation
echo "Starting the simulation process in a new terminal window..."
gnome-terminal -- bash -c "cd ~/PX4-Autopilot; hwid_file=\$(find ~/mavsdk_drone_show -name '*.hwID'); hwid=\$(echo \$hwid_file | cut -d'.' -f2); export px4_instance=\$hwid-1; $SIMULATION_COMMAND; bash" &
simulation_pid=$!

# Start the coordinator.py process
echo "Starting the coordinator.py process in another new terminal window..."
gnome-terminal -- bash -c "python3 ~/mavsdk_drone_show/coordinator.py; bash" &

echo "All processes have been initialized."
echo "Press Ctrl+C to stop the simulation process."
wait $simulation_pid

