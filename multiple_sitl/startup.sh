#!/bin/bash

cd ~/mavsdk_drone_show
git pull
python3 ~/mavsdk_drone_show/coordinator.py &

cd ~/PX4-Autopilot
HEADLESS=1 make px4_sitl gazebo &

tail -f /dev/null
