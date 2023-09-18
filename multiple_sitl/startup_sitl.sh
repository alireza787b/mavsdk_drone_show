#!/bin/bash

echo "Welcome to the SITL Startup Script for MAVSDK_Drone_Show!"
# ... [The rest of your introductory messages]

# Function to handle SIGINT
cleanup() {
  echo "Received interrupt, terminating background processes..."
  kill $simulation_pid
  kill $coordinator_pid
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
# DEFAULT_LAT=35.6857
# DEFAULT_LON=51.3036
# DEFAULT_ALT=1208

# Default position: Azadi Stadium
DEFAULT_LAT=35.725125060059966
DEFAULT_LON=51.27585107671351
DEFAULT_ALT=1278.5


# Read hwID from the file
while [ ! -f ~/mavsdk_drone_show/*.hwID ]; do
  echo "Waiting for hwID file..."
  sleep 1
done

HWID=$(basename ~/mavsdk_drone_show/*.hwID .hwID)  # Extract hwID without extension

# Fetch offsets for the current drone from config.csv
SCRIPT_DIR="$(dirname "$0")"
CONFIG_PATH="$SCRIPT_DIR/../config.csv"

# Check if the config file exists
if [ ! -f "$CONFIG_PATH" ]; then
    echo "ERROR: Cannot find config.csv at $CONFIG_PATH"
    exit 1
fi


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


# Initialize offsets with default values
OFFSET_X=0
OFFSET_Y=0

while IFS=, read -r hw_id pos_id x y ip mavlink_port debug_port gcs_ip; do
    if [ "$hw_id" == "$HWID" ]; then
        OFFSET_X=$x
        OFFSET_Y=$y
        break
    fi
done < "$CONFIG_PATH"

echo "DEBUG: Offset X = $OFFSET_X, Offset Y = $OFFSET_Y"

# Convert latitude from degrees to radians
LAT_RAD=$(echo "$DEFAULT_LAT * (3.141592653589793238 / 180)" | bc -l)

# Calculate km per degree for current latitude
M_PER_DEGREE=$(echo "111320 * c($LAT_RAD)" | bc -l)

# Calculate new LAT and LON based on the offsets
NEW_LAT=$(echo "$DEFAULT_LAT + $OFFSET_X / 111320" | bc -l)
NEW_LON=$(echo "$DEFAULT_LON + $OFFSET_Y / $M_PER_DEGREE" | bc -l)


echo "DEBUG: Calculated LAT = $NEW_LAT, LON = $NEW_LON"

# Export environment variables for PX4 SITL
export PX4_HOME_LAT="$NEW_LAT"
export PX4_HOME_LON="$NEW_LON"
export PX4_HOME_ALT="$DEFAULT_ALT"

# Continue with the simulation command
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

echo "DEBUG: SIMULATION_COMMAND = $SIMULATION_COMMAND"



# Start the SITL simulation in the background
echo "Starting the SITL simulation process..."
cd ~/PX4-Autopilot
hwid_file=$(find ~/mavsdk_drone_show -name '*.hwID')
hwid=$(echo $hwid_file | cut -d'.' -f2)
export px4_instance=$hwid-1

if [[ $SIMULATION_COMMAND == HEADLESS* ]]; then
    HEADLESS=1
    SIMULATION_COMMAND="make px4_sitl gazebo"
fi

export HEADLESS
$SIMULATION_COMMAND &


# Record the PID of the simulation process
simulation_pid=$!

# Start the coordinator.py process in the background
echo "Starting the coordinator.py process..."
cd ~/mavsdk_drone_show
python3 ~/mavsdk_drone_show/coordinator.py &

# Record the PID of the coordinator process
coordinator_pid=$!

echo "All processes have been initialized."
echo "Press Ctrl+C to stop the simulation and coordinator processes."

# Wait for the simulation to complete
wait $simulation_pid

# Keep the script running to maintain background processes
tail -f /dev/null
