
<!DOCTYPE html>
<html>

<body>
   <h1>PX4 Based Drone Show and Smart Swarm cooperative missions using MAVSDK </h1>

Introduction to the Project
Welcome to our drone programming project, a wild and ongoing journey from the simple to the complex. We started with basic offboard trajectory following and creating static drone formations in the sky. Over time, we've ramped up to creating multiple dynamic shapes and orchestrating impressive sky drone shows using SkyBrush.

Our attention then turned to developing intelligent drone swarm behaviors based on a multi-level leader/follower model. With every version, we're pushing the envelope, enhancing the world of drone programming and swarm control bit by bit.

And here's the fun part, we're far from done. Every new release peels back another layer, revealing more complexities and pushing our abilities further. We're pretty stoked about what's coming up and we hope you're too!

We've built this project hoping it'll make a dent in the drone programming universe, enabling anyone to create breathtaking drone shows and foster a community where we share, learn, and grow together.

We encourage you to check out our previous versions to get a feel for our journey so far. And hey, we absolutely love hearing from you all - your thoughts, ideas, questions - bring 'em on! They fuel our drive to keep pushing. Enjoy exploring and happy coding!


<h2>Version 0.8: Major GUI Improvements and Enhanced Swarm Intelligence</h2>

<p>In version 0.8, we have made significant improvements to the GUI and drone dashboard, which is a web-based React application. We have also introduced smarter and smoother drone swarm behaviors using a Kalman Filter implementation. </p>

<a href="https://youtu.be/E0xijEuTKtU" target="_blank"><img src="https://github.com/alireza787b/mavsdk_drone_show/assets/30341941/823ddf04-78dd-47a9-9036-809cd8da1c5b" style="width=300px" /></a>

follow the <a href="https://alireza787b.github.io/mavsdk_drone_show/v08_doc_server.html" target="_blank"> step-by-step instructions </a> to run this version.

<h3><a href="https://youtu.be/E0xijEuTKtU">YouTube Demo of Version 0.8</a></h3>

<h3>New Features:</h3>

<ul>
  <li>Visually create/manage/import/export mission config file</li>
  <li>Visually create/manage/import/export swarm file</li>
  <li>Auto check for any position or config mismatch</li>
  <li>Auto convert SkyBrush CSV zip files to MAVSDK drone show template</li>
  <li>Docker optimization for running all your SITLs in the cloud in a few minutes</li>
  <li>MAVLink router installation script (only needed when running in the cloud)</li>
  <li>Auto startup scripts</li>
</ul>

<h3>Improvements:</h3>

<ul>
  <li>Huge improvements in GUI and drone dashboard</li>
  <li>3D environment improvement for multi drones </li>
  <li>Improved command handling to ensure each drone receives command</li>
  <li>Kalman Filter implementation for smarter and smoother drone following</li>
  <li>Many minor improvements and bug fixes</li>
</ul>

<h3>Known Bugs:</h3>

<ul>
  <li>Sometimes you need to refresh the page when a new drone is added to the system</li>
  <li>If relaying the MAVLink commands from the cloud, sometimes QGroundControl won't send</li>
  <li>When starting a swarm mission, you can no longer send any commands through the dashboard </li>
</ul>
<ul>
  <li>Docker Image for Drone Instance: <a href="https://www.mediafire.com/file/8i54nkdxt3abkd2/drone-template-1_19thsept2023.tar/file">Download Here</a></li>
  <li>Demo Video: Coming Soon (Placeholder for YouTube link)</li>
</ul>
<p>As always, we welcome your feedback, suggestions, and contributions!</p>


## Version 0.7: React GUI for Swarm Monitoring & Real-World and SITL Environment Scenario Automization Improvements

In version 0.7, we have implemented a React-based graphical user interface (GUI) for real-time drone swarm monitoring. This allows for an intuitive centralized dashboard to track and command multiple drones in a swarm. 

Additionally, we have further optimized and automated the PX4 Docker environment startup and configuration. These improvements enhance the user experience and streamline swarm orchestration.

<a href="https://youtu.be/II7JxeEIBso" target="_blank"><img src="https://github.com/alireza787b/mavsdk_drone_show/assets/30341941/0d5d3630-e843-49c5-8bab-159a2bdeb81e" style="width=300px" /></a>


<h3><a href="https://youtu.be/II7JxeEIBso">YouTube Demo of Version 0.7</a></h3>

**New Features:**

- Implemented React GUI for real-time swarm monitoring
- Automated PX4 Docker and virtual machine environment startup and configuration
- Automized scenario with startup scripts both for SITL environment and Real Drone Hardware
- Optimized codebase and fixed bugs
- Added documentation

As always, we welcome your feedback, suggestions, and contributions!

## Version 0.6: Enhanced Complex Leader/Follower Swarm Control & Docker-Based SITL 
As we progress in our drone programming journey, version 0.6 of our project brings more advanced features and improvements, with enhanced swarm control and dockerized SITL demonstrations. In this release, we aim to increase efficiency and automation in managing larger numbers of drones with complex mission dynamics. The demonstration of these features can be found in the link to the YouTube video below.
<a href="https://youtu.be/VTyb1E_ueIk" target="_blank"><img src="https://github.com/alireza787b/mavsdk_drone_show/assets/30341941/b83db91f-25bc-4e5b-bb4e-e108a12abaf6" style="width=300px" /></a>
<h3><a href="https://youtu.be/VTyb1E_ueIk">YouTube Tutorial Demonstrating Enhanced Leader/Follower Swarm Control & Docker-Based SITL V0.6</a></h3>


Changelogs:
<ul>
<li>Improved CDH subsystem, telemetry, and command handling for supporting a larger number of drones</li>
<li>Optimized main code and transitioned structures to classes</li>
<li>Fixed bugs for smoother operations</li>
<li>Automated mav_sys_id and hwID file generation</li>
<li>Enabled Docker instances auto-creation for each drone</li>
<li>Automatic initialization of each instance for user-friendly operation</li>
</ul>
For demonstrations, we've run two demos:
<ul>
<li>1. Single group, single leader 11 followers with a fixed layout arrangement.</li>
<li>2. Three groups, three leaders, each group has three followers maintaining a fixed layout, and each group can be controlled independently.</li>

</ul>
Docker Image Backupfile. You can import it easily using Portainer and create drone instances from that. It includes PX4 SITL, JMAVSIM, Gazebo, MAVLink Router,mavsdk, Mavsdk_drone_show , ...
<br />
https://www.mediafire.com/file/g9m5gyx4ru8ndzv/drone-template-1.tar/file



## Version 0.5: Implementing Leader Follower Swarm Mission
In this release, we're stepping beyond simple drone shows and implementing real drone swarm capabilities, like leader/follower missions, using PX4 and MAVSDK in Python. v0.5 introduces the following features and improvements:
<a href="https://youtu.be/_W_DosoVbrU" target="_blank"><img src="https://github.com/alireza787b/mavsdk_drone_show/assets/30341941/69415901-1926-42fe-bde0-5cbe78a144c3" style="width=300px" /></a>
<h3><a href="https://youtu.be/_W_DosoVbrU">YouTube Tutorial Demonstrating Leader Follower Swarm PX4 V0.5</a></h3>
v0.5 Changelogs:
<ul>
<li>Node-to-node telemetry and communication using the new CDH subsystem</li>
<li>Added swarm.csv to arrange our swarm mission prototype</li>
<li>Improved ground station data handling and reporting</li>
<li>Improved coordinator app and bug fixes</li>
<li>Improved logging and debugging capabilities</li>
<li>Improved Threads management in Coordinator App</li>
<li>Improved error reporting and handling</li>
</ul>
Limitations in v0.5
<ul>
<li>I haven't implemented considerations for telemetry and command acknowledgment yet. will be implemented soon.</li>
<li>No Smoothing and Estimation algorithm for the following setpoints has been implemented yet. will be quickly implemented.</li>
</ul>
We're excited to continue developing this project and exploring the possibilities of drone swarm intelligence. As always, we welcome collaboration, suggestions, and questions from the community.

## Version 0.4: Advanced Swarm Control and Feature Enhancements

In version 0.4, we've made some major enhancements that will significantly improve the capabilities of our Drone Show system:
<a href="https://youtu.be/BD600ca_Qtw" target="_blank"><img src="https://github.com/alireza787b/mavsdk_drone_show/assets/30341941/3ccb0199-c338-4da1-ad4f-905a818af289" style="width=300px" /></a>
  
<h3><a href="https://youtu.be/BD600ca_Qtw">YouTube Tutorial Demonstrating Coordinated SITL Real-World Scenario V0.4</a></h3>

- **Coordinator.py:** This Python script acts as the conductor of our drone orchestra, managing a host of tasks:
  - Synchronizes each drone's system time with a global clock.
  - Downloads the configuration file (`config.csv`) from our web server to ensure that each drone follows the most up-to-date flight plan.
  - Initiates the MAVLink-router (please ensure to download and install it separately from [here](https://github.com/mavlink-router/mavlink-router)).
  - Manages MAVLink routing between serial, UDP, GCS, and the Swarm Control app.
  - Generates telemetry packets about the state of each drone, which are sent to the Swarm Control app.
  - Listens to command packets from the ground station, which set a future trigger time for coordinated show starts.
  
- **Debug_gcs_test.py:** This Python script provides the interface for ground control, with the following responsibilities:
  - Listens to telemetry from all drones, decoding and displaying the packets in real time.
  - Can initiate a "trigger" command, setting a future timestamp for each drone and altering their states for coordinated maneuvers.
  - While currently a command-line app, it is designed with a future graphical user interface (GUI) in mind.

- **Multi-Drone Testing:** To demonstrate the system's capabilities, we've configured a four-drone test. Each drone operates on its own VMware node with individual PX4 SITL instances running in JMAVSim. Meanwhile, the ground station (Swarm Control app) runs on a Windows system, receiving telemetry from all drones and issuing commands.

- **Bug Fixes and Documentation:** Various bugs identified in previous versions have been fixed, and we've added substantial documentation to help users understand the functionality better and resolve potential issues.


   <h3>Version 0.3: Enhanced Drone Show Control and Optimizations</h3>
  <a href="https://youtu.be/wctmCIzpMpY" target="_blank"><img src="https://github.com/alireza787b/mavsdk_drone_show/assets/30341941/668b1713-62f1-4c06-886f-8d4ae870e115" style="width="100px" /></a>
   <p>With the new v0.3 update, we have made significant improvements and added several new features:</p>
   <ul>
     <li><strong>Skybrush CSV Processing:</strong> We've added the ability to process Skybrush CSV files and convert them into our template. This feature also includes creating acceleration and velocities for improved path following. A detailed video tutorial for this is available on our YouTube channel .</li>
      <li><a href="https://youtu.be/wctmCIzpMpY">YouTube Tutorial on "Using Sky Brush and Blender for PX4 MAVSDK Drone Shows: Improving our Drone Show Project"</a></li>
     <li><strong>Coordinator.py:</strong> This new script manages and times the mission and state telemetry, enhancing the control of the drone show.</li>
     <li><strong>Merged Control Files:</strong> We have merged the multiple and single, as well as real and simulation mode control files for a more streamlined user experience.</li>
     <li><strong>Code Optimization:</strong> The code has been optimized for better performance and readability.</li>
     <li><strong>Bug Fixes:</strong> Various bugs have been identified and resolved in this update.</li>
   </ul>
   


   <p>As always, exercise caution and ensure you have the necessary expertise before using offboard mode in a real-world setting. Happy drone programming!</p>

  <h2>Introduction:</h2>
  <p>MAVSDK (MAVLink SDK) is a powerful tool for interacting with drones using the MAVLink communication protocol. This tutorial focuses on the offboard mode in PX4, which enables external systems to directly control a drone's position and velocity. Offboard mode allows for autonomous flight and finds applications in research, development, and testing scenarios.</p>
<a href="https://mavsdk.mavlink.io/main/en/">MAVSDK Documentation</a>

  <h2>Prerequisites:</h2>
  <p>To run the code and follow along with the tutorial, ensure that you have the following prerequisites in place:</p>
  <ul>
    <li>Python: Install Python and the required dependencies for running the scripts.</li>
    <li>PX4 Development Environment for SITL: Set up a PX4 Software-in-the-Loop simulation environment on either Ubuntu or WSL-2. For detailed instructions, refer to the tutorial available on our YouTube channel.</li>
    <li>MAVSDK: Install MAVSDK, which provides the necessary libraries for communication with the drone. Detailed installation and setup instructions can be found in our MAVSDK tutorial video on YouTube.</li>
    <li>MAVLink-router (please ensure to download and install it separately from <a href="https://github.com/mavlink-router/mavlink-router" target="_blank"> here </a>.</li>
  </ul>
  <p>Note: When using offboard mode with a real drone, it is essential to have a companion computer (such as a Raspberry Pi) onboard the drone or a reliable telemetry system. Please exercise caution and ensure you have the necessary expertise and understanding of offboard mode before attempting to use it with a real drone. Consider safety measures and be prepared for failsafe scenarios.</p>
  <h2>Tutorial Highlights:</h2>
  <p>In this tutorial, we will guide you through a simulated environment using SITL PX4 in Gazebo. The demonstration includes a single drone performing captivating shapes such as circles, squares, hearts, and even a helix. While the current implementation in MAVSDK may not provide the same level of performance as using MAVROS with feedforwarded accelerations, this tutorial serves as an educational starting point for understanding offboard control.</p>
  <p>Make sure to check out the complete code, resources, and sample CSV files in our GitHub repository. Additionally, we invite you to subscribe to our YouTube channel for more exciting tutorials and drone-related content.</p>
  <h3>Useful Tutorials:</h3>
  <ul>
    <li><a href="https://www.youtube.com/watch?v=iVU8ZNoMn_U">YouTube Tutorial on how to build your WSL-2 PX4 Development Environment</a></li>
    <li><a href="https://www.youtube.com/watch?v=SM0WtREzqqE">YouTube Tutorial on how to install and start with MAVSDK</a></li>
    <li><a href="https://www.youtube.com/watch?v=p0WAPgaa7Rs&list=PLVZvZdBQdm_67sRE_2xUMxYhM41z00Ciz">My PX4 Development YouTube Playlist</a></li>
    <li><a href="https://youtu.be/Wtxsv9mLkEU">Multiple Drone Show Youtube Demo</a></li>

  </ul>
  <h2>Usage:</h2>
  <p>Follow the YouTube Tutorial for this project:</p>
  <ul>
        <li><a href="https://www.youtube.com/watch?v=dg5jyhV15S8">Youtube Demo for this Repository</a></li>
  </ul>

  <p>You can use csvCreator.py to create different shape setpoints. active.csv and a screenshot of the drone's 3D trajectory will be saved to the shapes folder. The next step is to run offboard_from_csv.py and see the drone following the actions.</p>
  <h2>Disclaimer:</h2>
  <p><strong>Using offboard mode with a real drone involves risks and should be approached with caution.</strong> Understand the safety implications, consider failsafe scenarios, and ensure you have the necessary expertise before using offboard mode in a real-world setting.</p>
</body>
</html>
