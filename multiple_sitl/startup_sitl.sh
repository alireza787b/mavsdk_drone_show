#!/bin/bash

# Wait for the .hwID file to exist
while [ ! -f /root/mavsdk_drone_show/*.hwID ]
do
  sleep 1
done

# Once the .hwID file exists, continue with the rest of the script
cd ~/mavsdk_drone_show
git pull
hwid_file=$(find . -name '*.hwID')
hwid=$(cat "$hwid_file")

# Append the MAV_SYS_ID parameter to the rcS file
#echo "param set MAV_SYS_ID $hwid" >> ~/PX4-Autopilot/build/px4_sitl_default/etc/init.d-posix/rcS

# Start the px4_sitl gazebo process in the background
cd ~/PX4-Autopilot
HEADLESS=1 make px4_sitl gazebo &

# Start the coordinator.py process in the background
cd ~/mavsdk_drone_show
python3 ~/mavsdk_drone_show/coordinator.py &

tail -f /dev/null
