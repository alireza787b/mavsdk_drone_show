
# MAVSDK Drone Show (MDS) - PX4-Based Drone Show and Smart Swarm Cooperative Missions

Welcome to the MAVSDK Drone Show (MDS) project—a cutting-edge platform for orchestrating PX4-based drone shows and intelligent swarm missions using MAVSDK. Our journey has taken us from simple offboard trajectory following to creating dynamic drone formations and advanced swarm behaviors. With every version, we're pushing the boundaries of drone programming and swarm control, aiming to make a significant impact in the drone programming universe.

## Introduction

The MDS project is an open-source initiative focused on enabling breathtaking drone shows and intelligent swarm missions. By leveraging the power of PX4, MAVSDK, and modern web technologies, we aim to provide a robust platform for drone enthusiasts, researchers, and industry professionals to explore, innovate, and contribute to the future of drone swarms.

## Project History

Our project has evolved significantly over time. Here's a brief overview of our journey:

- **Version 0.1:** Introduced project implementation. Single drone csv trajectory following script.
- **Version 0.2:** Introduced multiple drones executing offset and delayed csv trajectory following.
- **Version 0.3:** Introduced enhanced drone show control and optimizations, including SkyBrush CSV processing and code optimizations.
- **Version 0.4:** Implemented advanced swarm control with the addition of `Coordinator.py` and improved telemetry and command handling.
- **Version 0.5:** Stepped into real drone swarm capabilities with leader/follower missions and improved ground station data handling.
- **Version 0.6:** Enhanced complex leader/follower swarm control and introduced Docker-based SITL for efficient simulations.
- **Version 0.7:** Developed a React GUI for real-time swarm monitoring and automated the PX4 Docker environment startup and configuration.
- **Version 0.8:** Major GUI improvements, smarter drone swarm behaviors using Kalman Filter implementation, and Docker optimization for running SITLs in the cloud.

Each version has built upon the last, incorporating feedback, real-world testing, and technological advancements to push the project forward.

## What's New in Version 2.0

**Release Date:** November 2024

Version 2.0 marks a significant milestone in our project, incorporating extensive real-world testing and numerous enhancements to deliver a more robust and feature-rich platform.

### Major Updates

- **Enhanced React GUI:** Our web-based dashboard has been significantly improved for better user experience and real-time swarm monitoring.
- **Integrated Web Server:** Transitioned to a Flask-based web server for more efficient communication.
- **Eliminated UDP Dependencies:** Streamlined network communication by removing UDP, enhancing reliability.
- **Robust Drone Show Execution Script:** Improved scripts for executing drone shows, ensuring smoother operations.
- **Improved Command Handling:** Enhanced mechanisms to handle commands, especially when previous commands are still in execution.
- **Extensive Real-World Testing:** The platform has undergone rigorous testing in real-world scenarios to validate performance and reliability.
- **Docker-Based SITL Testing:** Simplified the process of setting up Software-In-The-Loop (SITL) simulations using Docker.

> **Note:** The swarm leader/follower functionality is currently under development and will be reintroduced in a future release.

<a  href="https://youtu.be/E0xijEuTKtU"  target="_blank"><img  src="https://github.com/alireza787b/mavsdk_drone_show/assets/30341941/823ddf04-78dd-47a9-9036-809cd8da1c5b"  style="width=300px"  /></a>

### Placeholder for Upcoming Demo Video

Stay tuned for our upcoming YouTube demo video showcasing the new features in Version 2.0.

## Features and Capabilities

- **Dynamic Drone Formations:** Create and manage multiple dynamic shapes and orchestrate impressive drone shows.
- **Advanced Swarm Intelligence:** Develop intelligent swarm behaviors with multi-level leader/follower models.
- **Web-Based Dashboard:** Monitor and control your drone swarm in real-time through an intuitive React GUI.
- **Automated Docker Environment:** Quickly set up your SITL environment using Docker for efficient testing and development.
- **Mission Configuration Tools:** Visually create, manage, import, and export mission configurations and swarm files.
- **SkyBrush Integration:** Seamlessly convert SkyBrush CSV files into the MAVSDK Drone Show template.
- **Robust Telemetry and Command Handling:** Improved mechanisms to ensure each drone receives commands reliably.

## Getting Started


### SITL Demo Installation Guide
To get started with the MAVSDK Drone Show project, please follow our comprehensive [SITL demo with Docker Guide](https://github.com/alireza787b/mavsdk_drone_show/blob/main/docs/v2.0_doc_sitl_demo.md).


### Real-World Installation Guide
*Documentation will be released...*
Implementing this project in the real world requires extensive knowledge and experience with drones, networking, and safety protocols. If you need assistance, please feel free to reach out.


## Roadmap and Future Work

We are committed to continuously improving the MAVSDK Drone Show project. Our roadmap includes:

- **Reintroducing Swarm Leader/Follower Functionality:** Enhancing swarm intelligence with improved leader/follower dynamics.
- **Advanced Command Handling:** Developing more robust command mechanisms to handle concurrent commands effectively.
- **Performance Optimizations:** Ongoing efforts to optimize performance, reliability, and security.
- **Community Contributions:** We welcome collaboration, suggestions, and contributions from the community to help drive this project forward.

## Contact and Contributions

We appreciate your interest in the MAVSDK Drone Show project. If you have any questions, suggestions, or need assistance, please feel free to contact us:

- **Email:** [p30planets@gmail.com](mailto:p30planets@gmail.com)
- **LinkedIn:** [Alireza Ghaderi](https://www.linkedin.com/in/alireza787b/)

We encourage contributions to the project. Please feel free to submit pull requests, report issues, or collaborate on new features.

## Disclaimer

**Using offboard mode with real drones involves risks and should be approached with caution.** Ensure you have the necessary expertise, understand safety implications, and consider failsafe scenarios before attempting to implement this project in real-world settings. Always prioritize safety and regulatory compliance.

## Additional Resources

- **GitHub Repository:** [MAVSDK Drone Show](https://github.com/alireza787b/mavsdk_drone_show)
- **SITL Test with Docker Guide:** [Setup Instructions](https://github.com/alireza787b/mavsdk_drone_show/blob/main/docs/v2.0_doc_sitl_demo.md)
- **YouTube Tutorials:**
  - [Project History and Tutorials](https://www.youtube.com/playlist?list=PLVZvZdBQdm_7ViwRhUFrmLFpFkP3VSakk)
  - [IoT-Based Telemetry and Video Drone Concepts](https://www.youtube.com/playlist?list=PLVZvZdBQdm_7E_wxfXWKyZoaK7yucl6w4)
- **MAVSDK Documentation:** [Official Docs](https://mavsdk.mavlink.io/main/en/)
- **PX4 Autopilot:** [Official Site](https://px4.io/)

---

© 2024 Alireza Ghaderi

This documentation is licensed under **CC BY-SA 4.0**. Feel free to reuse or modify according to the terms. Please attribute and link back to the original repository.

---