#!/bin/bash


cd ~/PX4-Autopilot
HEADLESS=1 make px4_sitl gazebo &

cd ~/mavsdk_drone_show
git pull
python3 ~/mavsdk_drone_show/coordinator.py &


tail -f /dev/null
