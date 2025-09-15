# MAVSDK Drone Show (MDS) – All-in-One Drone-Show & Smart Swarm Framework

MDS is a unified platform for PX4-based drone performances and intelligent swarm missions. Whether you want to run a pre-planned, decentralized drone show using SkyBrush outputs or orchestrate a live, collaborative swarm with leader–follower clustering (Kalman-filter enhanced, dynamic role changes, leader failover), MDS has you covered.

## Overview

MDS 3 combines three core components into a single, cohesive package:

1. **Drone Side**  
   - Runs on any Linux-based autopilot platform (e.g., Raspberry Pi, NVIDIA Jetson, or similar).  
   - Handles MAVSDK integration, local trajectory execution, failsafe monitoring, and dynamic formation logic.

2. **Cloud Side (Optional Backend)**  
   - Hosts the formation-planning engine, mission dispatcher, and WebSocket/MAVLink router.  
   - Provides global setpoint management, three-way startup handshake, and health-check services.  
   - Can be deployed on any cloud VM (Ubuntu 22.04 / 23.04 recommended) or on-premises server.

3. **Frontend (React Dashboard)**  
   - Full-featured React GUI for real-time monitoring and control.  
   - Upload offline “ShowMode” trajectories (CSV/JSON from SkyBrush), visualize live positions, assign leaders/followers, and trigger mission modes.  
   - Supports both Drone-Show mode (offline choreography) and Smart-Swarm mode (live clustering with Kalman filters, dynamic formation reshaping, and leader-failover).

In short, MDS 3 is **one package** that can be used for:
- **Offline Drone Shows**: Pre-planned, synchronized formations based on SkyBrush CSV outputs.
- **Smart Swarm Missions**: Cluster-based, fully decentralized leader–follower missions with robust failsafe handling, automatic leader re-election, and dynamic reconfiguration.

---

## Demo Videos

- **V2 Drone Show & SITL Setup**  
  100-Drone SITL Test in Clustered Cloud Servers | MDS Mavsdk Drone Show Version 2  
  [![100-Drone SITL Test](https://img.youtube.com/vi/VsNs3kFKEvU/maxresdefault.jpg)](https://www.youtube.com/watch?v=VsNs3kFKEvU)

- **Smart Swarm Mode Demo**  
  [![Smart Swarm Mode Demo](https://img.youtube.com/vi/qRXE3LTd40c/maxresdefault.jpg)](https://youtu.be/qRXE3LTd40c)


---

## Key Features

- **All-in-One Architecture**  
  - Shared Docker image and codebase for both offline shows and live swarm missions.  
  - Single command-line interface and unified React dashboard.

- **Offline Drone-Show Mode**  
  - Converts SkyBrush CSV/JSON into MAVSDK-compatible “ShowMode” files.  
  - Global setpoint propagation ensures perfect synchronization across 10–100+ SITL instances or real drones.  
  - Preflight sanity checks (battery, GPS lock, ESC health) before arming.

- **Smart Swarm Mode (Live, Decentralized)**  
  - Clustered leader–follower architecture with Kalman-filter–enhanced state estimation.  
  - Automatic leader failure detection and re-election based on configurable metrics (battery level, signal strength, drone ID).  
  - Dynamic formation reshaping and per-drone role changes on-the-fly.  
  - In-flight failsafe monitors communication timeouts, altimeter discrepancies, ESC reboots → automatic Return-to-Home or Loiter.

- **Stable Startup Handshake**  
  - Three-way acknowledgement chain (Drone ⇄ PX4, PX4 ⇄ MAVSDK, MAVSDK ⇄ GCS) to guarantee all SITL instances or hardware drones are ready before takeoff.  
  - “OK-to-Start” broadcast from the cloud backend prevents premature launches.

- **Robustness & Performance**  
  - Race-condition fixes under high CPU load (ensures correct GUIDED → AUTO transitions).  
  - Emergency-land command reliability during mode transitions.  
  - Network buffer tuning for large-scale simulations (100+ drones) using MAVLink Router.  

- **React Dashboard (Frontend)**  
  - Live position, battery, mode, and failsafe status for each drone.  
  - Mission upload interface for offline trajectories or real-time swarm commands.  
  - **3D Trajectory Planning** - Interactive waypoint creation with real terrain elevation, speed optimization, and professional trajectory management (requires Mapbox access token for full functionality).  
  - Formation editor (drag-and-drop) for offline shows (coming soon).  
  - REST API endpoints via MAVLink2REST for external integrations.

- **Automated Docker Environment**  
  - Prebuilt Docker image includes PX4 1.16, MAVSDK Drone Show, MAVLink Router, MAVLink2REST, Gazebo, and all SITL dependencies.  
  - Auto hardware-ID detection and dynamic container creation scripts.

- **Mission Configuration Tools**  
  - SkyBrush CSV → MDS template converter script.  
  - JSON-based mission/formation files with built-in validators.  
  - Parameter‐tuning utilities for leader election thresholds, Kalman filter gains, and failsafe timeouts.

---

## Brief History & Changelog

- **Version 0.1 (Mar 2020)**  
  - Single-drone CSV trajectory following.

- **Version 0.2 (Jun 2020)**  
  - Multi-drone offset/delayed CSV trajectories.

- **Version 0.3 (Oct 2020)**  
  - SkyBrush CSV processing; code optimizations for drone shows.

- **Version 0.4 (Feb 2021)**  
  - Introduced `Coordinator.py` for advanced swarm; improved telemetry/commands.

- **Version 0.5 (Jul 2021)**  
  - Basic leader/follower missions on hardware; enhanced GCS data handling.

- **Version 0.6 (Dec 2021)**  
  - Complex leader/follower swarm control; Docker-based SITL environment.

- **Version 0.7 (Apr 2022)**  
  - React GUI for real-time swarm monitoring; Docker automation for PX4 SITL.

- **Version 0.8 (Sep 2022)**  
  - Major GUI enhancements; Kalman-filter–based swarm behaviors; optimized cloud SITL.

- **Version 1.0 (Mar 2023)**  
  - Stable release; Flask web server; removed UDP dependencies.

- **Version 1.5 (Aug 2023)**  
  - Mission config tools; SkyBrush converter; expanded MAVLink2REST.

- **Version 2.0 (Nov 2024)**  
  - Enhanced React GUI, Flask backend, robust drone-show scripts, Docker SITL.  
  - [100-Drone SITL Test Video](https://www.youtube.com/watch?v=VsNs3kFKEvU)  

- **Version 3.0 (Jun 2025)**  
  - **Smart Swarm Leader–Follower** fully operational (leader failover, auto re-election, seamless follower sync).  
  - **Global Mode Setpoints** for unified offline & live missions.  
  - **Enhanced Failsafe Checks** (preflight health checks, in-flight monitoring).  
  - **Stable Startup Sequence** (three-way handshake, “OK-to-Start”).  
  - **Robustness & Bug Fixes** (race conditions, emergency-land reliability, network buffer tuning).  
  - **Unified All-in-One System** for both drone shows and live swarm.  
  - **Smart Swarm Clustered Leader–Follower Video**  
  [![Smart Swarm Clustered Leader–Follower](https://img.youtube.com/vi/qRXE3LTd40c/maxresdefault.jpg)](https://youtu.be/qRXE3LTd40c)

---

## Getting Started

### Quick Start Guide

All the detailed setup instructions—downloading the Docker image, creating SITL instances, running both Drone-Show and Smart Swarm modes—live available in [docs/sitl_demo_docker.md](https://github.com/alireza787b/mavsdk_drone_show/blob/main-candidate/docs/sitl_demo_docker.md):



> **Note:** The main guide covers:
> - Docker image pull/load commands
> - `setup_environment.sh` and `create_dockers.sh` usage
> - Network, MAVLink Router, Netbird VPN setup
> - React dashboard startup (`linux_dashboard_start.sh --sitl`)
> - How to upload offline trajectories or launch live swarm missions
> - **3D Trajectory Planning Setup**: For full terrain visualization and elevation features, add your free Mapbox access token to `.env` (see `.env.bak` for reference)

### Advanced SITL Configuration

For custom repositories or production SITL deployments:

📖 **[Advanced SITL Guide](docs/advanced_sitl.md)** - Simple copy-paste commands for custom configuration

> **⚠️ Advanced configuration requires good understanding of Git, Docker, and Linux**

### Real Hardware Deployment

**⚠️ IMPORTANT:** Deploying MDS on real drones and hardware requires:
- Deep understanding of flight control systems, safety protocols, and aviation regulations
- Extensive testing in controlled environments before any real-world use
- Professional drone operation knowledge and certifications
- Additional hardware setup, networking, and safety configurations

**For real hardware deployment assistance, contact:**
- **Email:** [p30planets@gmail.com](mailto:p30planets@gmail.com)
- **LinkedIn:** [Alireza Ghaderi](https://www.linkedin.com/in/alireza787b/)  



---

## 🏢 Commercial Support & Custom Implementation

**The basic SITL demo is designed for evaluation and learning.** For companies and organizations requiring production deployments, custom features, or hardware implementation:

**Services Available:**
- ✈️ **Custom SITL Features** - Specialized simulation scenarios and advanced functionality
- 🚁 **Hardware Implementation** - Real drone deployment with safety protocols and regulatory compliance
- 🏢 **Enterprise Integration** - Custom APIs, cloud integration, fleet management systems
- 📊 **Performance Optimization** - Large-scale swarm optimization and mission planning
- 🔧 **Training & Support** - Team training and ongoing technical support
- 🎯 **Custom Mission Types** - Specialized applications beyond standard formations

**Professional implementation contracts available for real-world deployments.**

---

## Contact & Contributions

If you run into issues, have suggestions, want to contribute new features or need help with your custom business requirements:

* **Email:** [p30planets@gmail.com](mailto:p30planets@gmail.com)
* **LinkedIn:** [Alireza Ghaderi](https://www.linkedin.com/in/alireza787b/)

We welcome code, documentation improvements, Docker recipes, CVs, and new swarm algorithms. Please fork the repo, branch from `v3.0`, and submit pull requests with detailed descriptions.

---

## Disclaimer

**Using offboard mode or live swarm control on real drones carries risk.** Ensure you have the necessary expertise, understand safety implications, and implement robust failsafe procedures before attempting any real-world flights. Always prioritize regulatory compliance and flight safety.

---

## Additional Resources

* **GitHub Repository (v3.0):**
  [https://github.com/alireza787b/mavsdk\_drone\_show](https://github.com/alireza787b/mavsdk_drone_show)

* **SITL Demo with Docker Guide:**
   * [docs/sitl_demo_docker.md](https://github.com/alireza787b/mavsdk_drone_show/blob/main-candidate/docs/sitl_demo_docker.md)

* **YouTube Tutorials:**

  * [Project History & Tutorials](https://www.youtube.com/playlist?list=PLVZvZdBQdm_7ViwRhUFrmLFpFkP3VSakk)
  * [IoT-Based Telemetry & Video Drone Concepts](https://www.youtube.com/playlist?list=PLVZvZdBQdm_7E_wxfXWKyZoaK7yucl6w4)

* **MAVSDK Documentation:**
  [https://mavsdk.mavlink.io/](https://mavsdk.mavlink.io/)

* **PX4 Autopilot:**
  [https://px4.io/](https://px4.io/)

* **Netbird VPN Docs:**
  [https://docs.netbird.io/](https://docs.netbird.io/)

* **MAVLink2REST Documentation:**
  [https://github.com/mavlink/mavlink2rest](https://github.com/mavlink/mavlink2rest)

* **SkyBrush Drone Show Tool:**
  [https://skybrush.io/](https://skybrush.io/)

---

© 2025 Alireza Ghaderi
Licensed under **CC BY-SA 4.0**. Feel free to reuse or modify under the terms; please attribute and link back to the original repository.
