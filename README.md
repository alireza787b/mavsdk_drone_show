# mavsdk_drone_show
Single Drone Show Basics using MAVSDK Offboard Control


**Drone Show Basics with Custom Shapes using MAVSDK Offboard Control

This repository provides a tutorial on creating a captivating drone show with custom shapes using MAVSDK's offboard control. The tutorial showcases the basics of offboard mode in PX4 and demonstrates its capabilities with a single drone. Please note that the current implementation in MAVSDK does not support feedforwarding acceleration while setting position and velocity in offboard mode. However, this tutorial serves as a starting point to understand offboard control and its potential for coordinating drone shows.

**Introduction:
MAVSDK (MAVLink SDK) is a powerful tool for interacting with drones using the MAVLink communication protocol. This tutorial focuses on the offboard mode in PX4, which enables external systems to directly control a drone's position and velocity. Offboard mode allows for autonomous flight and finds applications in research, development, and testing scenarios.

https://mavsdk.mavlink.io/main/en/


**Prerequisites:
To run the code and follow along with the tutorial, ensure that you have the following prerequisites in place:

Python: Install Python and the required dependencies for running the scripts.
PX4 Development Environment for SITL: Set up a PX4 Software-in-the-Loop simulation environment on either Ubuntu or WSL-2. For detailed instructions, refer to the tutorial available on our YouTube channel.
MAVSDK: Install MAVSDK, which provides the necessary libraries for communication with the drone. Detailed installation and setup instructions can be found in our MAVSDK tutorial video on YouTube.
Note: When using offboard mode with a real drone, it is essential to have a companion computer (such as a Raspberry Pi) onboard the drone or a reliable telemetry system. Please exercise caution and ensure you have the necessary expertise and understanding of offboard mode before attempting to use it with a real drone. Consider safety measures and be prepared for failsafe scenarios.

Tutorial Highlights:
In this tutorial, we will guide you through a simulated environment using SITL PX4 in Gazebo. The demonstration includes a single drone performing captivating shapes such as circles, squares, hearts, and even a helix. While the current implementation in MAVSDK may not provide the same level of performance as using MAVROS with feedforwarded accelerations, this tutorial serves as an educational starting point for understanding offboard control.

Make sure to check out the complete code, resources, and sample CSV files in our GitHub repository. Additionally, we invite you to subscribe to our YouTube channel for more exciting tutorials and drone-related content.

Youtube Tutorial on how to build you WSL-2 PX4 Development Environemnt:
https://www.youtube.com/watch?v=iVU8ZNoMn_U

Youtube Tutorial on how to install and start with MAVSDK:
https://www.youtube.com/watch?v=SM0WtREzqqE


my PX4 Development Youtube Playlist:
https://www.youtube.com/watch?v=p0WAPgaa7Rs&list=PLVZvZdBQdm_67sRE_2xUMxYhM41z00Ciz


[Usage:
](https://www.youtube.com/watch?v=p0WAPgaa7Rs&list=PLVZvZdBQdm_67sRE_2xUMxYhM41z00Ciz)Follow the Youtube Tutorial for this project:
Link will be published soon!!

you can use csvCreator.py to create differnt shape setpoints. active.csv and a screenshot of drone 3D trajectory will be saved to shapes folder.
next step is to run offboard_from_csv.py and see the drone following the actions.




**Disclaimer:
**Using offboard mode with a real drone involves risks and should be approached with caution. Understand the safety implications, consider failsafe scenarios, and ensure you have the necessary expertise before using offboard mode in a real-world setting.
