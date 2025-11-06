# MAVSDK Drone Show (MDS)

**All-in-One Drone Show & Smart Swarm Framework for PX4**

[![Version](https://img.shields.io/badge/version-3.6-blue.svg)](CHANGELOG.md)
[![License](https://img.shields.io/badge/license-CC%20BY--SA%204.0-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](docs/guides/python-compatibility.md)

MDS is a unified platform for PX4-based drone performances and intelligent swarm missions. Whether you want to run pre-planned, decentralized drone shows using SkyBrush outputs or orchestrate live, collaborative swarms with leader–follower clustering, MDS has you covered.

---

## Table of Contents

- [Overview](#overview)
- [Demo Videos](#demo-videos)
- [Key Features](#key-features)
- [Getting Started](#getting-started)
  - [Python Requirements](#python-requirements)
  - [Quick Start (SITL Demo)](#quick-start-sitl-demo)
  - [Advanced Configuration](#advanced-configuration)
  - [Real Hardware Deployment](#real-hardware-deployment)
- [Documentation](#documentation)
- [Version & Changelog](#version--changelog)
- [Commercial Support](#-commercial-support--custom-implementation)
- [Contact & Contributions](#contact--contributions)
- [Disclaimer](#disclaimer)
- [Additional Resources](#additional-resources)
- [License](#license)

---

## Overview

MDS 3 combines three core components into a single, cohesive package:

### 1. Drone Side
- Runs on any Linux-based autopilot platform (Raspberry Pi, NVIDIA Jetson, or similar)
- Handles MAVSDK integration, local trajectory execution, and failsafe monitoring
- Dynamic formation logic and autonomous operation

### 2. Cloud Side (Optional Backend)
- Hosts formation-planning engine, mission dispatcher, and WebSocket/MAVLink router
- Provides global setpoint management, three-way startup handshake, and health-check services
- Deploy on cloud VM (Ubuntu 22.04/23.04) or on-premises server

### 3. Frontend (React Dashboard)
- Full-featured React GUI for real-time monitoring and control
- Upload offline "ShowMode" trajectories (CSV/JSON from SkyBrush)
- Visualize live positions, assign leaders/followers, and trigger mission modes
- **3D Trajectory Planning** with interactive waypoints and terrain elevation
- Supports both Drone-Show mode and Smart-Swarm mode

**In short, MDS 3 is one package for:**
- **Offline Drone Shows**: Pre-planned, synchronized formations from SkyBrush CSV
- **Smart Swarm Missions**: Decentralized leader–follower missions with robust failsafe handling

---

## Demo Videos

### MDS 3 Complete Feature Showcase
**3D Drone Swarms in Action | Mission Planning + Autonomous Clustered Formation**

[![MDS 3 Complete Feature Showcase](https://img.youtube.com/vi/mta2ARQKWRQ/maxresdefault.jpg)](https://www.youtube.com/watch?v=mta2ARQKWRQ)

### 100-Drone SITL Test (Version 2)
**Large-Scale Cloud Simulation**

[![100-Drone SITL Test](https://img.youtube.com/vi/VsNs3kFKEvU/maxresdefault.jpg)](https://www.youtube.com/watch?v=VsNs3kFKEvU)

### Smart Swarm Mode Demo
**Live Leader-Follower Clustering**

[![Smart Swarm Mode Demo](https://img.youtube.com/vi/qRXE3LTd40c/maxresdefault.jpg)](https://youtu.be/qRXE3LTd40c)

---

## Key Features

### All-in-One Architecture
- Shared Docker image and codebase for offline shows and live swarm missions
- Single command-line interface and unified React dashboard
- Streamlined deployment workflow

### Offline Drone-Show Mode
- Converts SkyBrush CSV/JSON into MAVSDK-compatible "ShowMode" files
- Global setpoint propagation for perfect synchronization (10–100+ drones)
- Preflight sanity checks (battery, GPS lock, ESC health)

### Smart Swarm Mode (Live, Decentralized)
- Clustered leader–follower architecture with Kalman-filter state estimation
- Automatic leader failure detection and re-election
- Dynamic formation reshaping and per-drone role changes
- In-flight failsafe monitors for communication, altimeter, ESC health

### Stable Startup Handshake
- Three-way acknowledgement chain (Drone ⇄ PX4 ⇄ MAVSDK ⇄ GCS)
- "OK-to-Start" broadcast prevents premature launches
- Guaranteed readiness before takeoff

### Robustness & Performance
- Race-condition fixes under high CPU load
- Emergency-land command reliability during mode transitions
- Network buffer tuning for large-scale simulations (100+ drones)

### Professional React Dashboard
- Live monitoring: position, battery, mode, failsafe status per drone
- Mission upload interface for offline trajectories or real-time swarm commands
- **3D Trajectory Planning**: Interactive waypoint creation with real terrain elevation
  - Professional trajectory management with speed optimization
  - Requires Mapbox access token for full functionality
- Formation editor (drag-and-drop) - coming soon
- REST API endpoints via MAVLink2REST

### Automated Docker Environment
- Prebuilt image includes: PX4 1.16, MAVSDK, MAVLink Router, MAVLink2REST, Gazebo
- Auto hardware-ID detection
- Dynamic container creation scripts

### Mission Configuration Tools
- SkyBrush CSV → MDS converter script
- JSON-based mission/formation files with validators
- Parameter tuning utilities for leader election, Kalman filters, failsafe timeouts

---

## Getting Started

### Python Requirements

**MDS requires Python 3.11, 3.12, or 3.13.** The latest Raspberry Pi OS includes Python 3.13 and is fully supported.

📖 See [Python Compatibility Guide](docs/guides/python-compatibility.md) for details and troubleshooting.

### Quick Start (SITL Demo)

The fastest way to try MDS is with our SITL (Software-In-The-Loop) demo:

📖 **[SITL Demo Guide](docs/guides/sitl-comprehensive.md)** - Complete step-by-step setup

This guide covers:
- Docker image pull/load commands
- Environment setup (`setup_environment.sh`, `create_dockers.sh`)
- Network, MAVLink Router, Netbird VPN configuration
- React dashboard startup (`linux_dashboard_start.sh --sitl`)
- Uploading offline trajectories or launching live swarm missions
- 3D Trajectory Planning setup (add Mapbox access token to `.env`)

**Quick Start Option:**
📖 **[Quick Start Guide](docs/quickstart/sitl-demo.md)** - Essential steps only (condensed version)

### Advanced Configuration

For custom repositories, production SITL deployments, or advanced scenarios:

📖 **[Advanced SITL Guide](docs/guides/advanced-sitl.md)** - Custom configuration and environment variables

> ⚠️ **Advanced configuration requires good understanding of Git, Docker, and Linux**

### Real Hardware Deployment

**⚠️ IMPORTANT:** Deploying MDS on real drones requires:
- Deep understanding of flight control systems and safety protocols
- Aviation regulations compliance
- Extensive testing in controlled environments
- Professional drone operation knowledge and certifications
- Additional hardware setup, networking, and safety configurations

**For real hardware deployment assistance, see the [Contact](#contact--contributions) section.**

---

## Documentation

### 📚 Documentation Index

All project documentation is organized in the `docs/` folder:

📖 **[Documentation Index](docs/README.md)** - Complete guide to all available documentation

### Quick Links

| Category | Description | Link |
|----------|-------------|------|
| **Quick Start** | Fast SITL demo setup | [docs/quickstart/](docs/quickstart/) |
| **Guides** | Comprehensive setup and configuration | [docs/guides/](docs/guides/) |
| **Features** | Detailed feature documentation | [docs/features/](docs/features/) |
| **Hardware** | Hardware-specific guides | [docs/hardware/](docs/hardware/) |
| **API** | API documentation | [docs/api/](docs/api/) |
| **Versioning** | Version management workflow | [docs/VERSIONING.md](docs/VERSIONING.md) |

### Key Guides

- **[SITL Comprehensive Guide](docs/guides/sitl-comprehensive.md)** - Full SITL setup and usage
- **[Advanced SITL Configuration](docs/guides/advanced-sitl.md)** - Custom deployments
- **[CSV Migration Guide](docs/guides/csv-migration.md)** - Configuration format migration
- **[Python Compatibility](docs/guides/python-compatibility.md)** - Python version requirements
- **[Swarm Trajectory Feature](docs/features/swarm-trajectory.md)** - Smart swarm capabilities
- **[Origin System](docs/features/origin-system.md)** - Coordinate system implementation

---

## Version & Changelog

**Current Version: 3.6** (November 2025)

Major updates in this version:
- Documentation restructure and professional organization
- Unified versioning system across entire project
- Enhanced GCS configuration with .env auto-update
- Production-ready UI/UX improvements
- Dark mode fixes and accessibility improvements

📖 **[Full Changelog](CHANGELOG.md)** - Complete version history from v0.1 to current

📖 **[Versioning Guide](docs/VERSIONING.md)** - How we manage versions and releases

---

## 🏢 Commercial Support & Custom Implementation

**The basic SITL demo is designed for evaluation and learning.** For companies and organizations requiring production deployments, custom features, or hardware implementation:

### Services Available

- ✈️ **Custom SITL Features** - Specialized simulation scenarios and advanced functionality
- 🚁 **Hardware Implementation** - Real drone deployment with safety protocols and regulatory compliance
- 🏢 **Enterprise Integration** - Custom APIs, cloud integration, fleet management systems
- 📊 **Performance Optimization** - Large-scale swarm optimization and mission planning
- 🔧 **Training & Support** - Team training and ongoing technical support
- 🎯 **Custom Mission Types** - Specialized applications beyond standard formations

**Professional implementation contracts available for real-world deployments.**

---

## Contact & Contributions

We welcome contributions, bug reports, feature suggestions, and commercial inquiries:

- **Email:** [p30planets@gmail.com](mailto:p30planets@gmail.com)
- **LinkedIn:** [Alireza Ghaderi](https://www.linkedin.com/in/alireza787b/)
- **GitHub Issues:** [Report bugs or request features](https://github.com/alireza787b/mavsdk_drone_show/issues)

### Contributing

We welcome code, documentation improvements, Docker recipes, and new swarm algorithms:

1. Fork the repository
2. Create a feature branch from `main-candidate`
3. Make your changes with clear commit messages
4. Submit a pull request with detailed description

See our [Contributing Guide](CONTRIBUTING.md) for more details.

---

## Disclaimer

**⚠️ SAFETY WARNING**

Using offboard mode or live swarm control on real drones carries significant risk. Before attempting any real-world flights:

- Ensure you have the necessary expertise and certifications
- Understand all safety implications and failure modes
- Implement robust failsafe procedures
- Prioritize regulatory compliance and flight safety
- Conduct extensive testing in controlled environments
- Follow all local aviation regulations and laws

**The maintainers assume no liability for damage, injury, or legal consequences resulting from use of this software.**

---

## Additional Resources

### Official Documentation
- **GitHub Repository:** [https://github.com/alireza787b/mavsdk_drone_show](https://github.com/alireza787b/mavsdk_drone_show)
- **SITL Demo Guide:** [docs/guides/sitl-comprehensive.md](docs/guides/sitl-comprehensive.md)
- **Documentation Index:** [docs/README.md](docs/README.md)

### YouTube Tutorials
- [Project History & Tutorials Playlist](https://www.youtube.com/playlist?list=PLVZvZdBQdm_7ViwRhUFrmLFpFkP3VSakk)
- [IoT-Based Telemetry & Video Drone Concepts](https://www.youtube.com/playlist?list=PLVZvZdBQdm_7E_wxfXWKyZoaK7yucl6w4)

### Related Technologies
- **MAVSDK Documentation:** [https://mavsdk.mavlink.io/](https://mavsdk.mavlink.io/)
- **PX4 Autopilot:** [https://px4.io/](https://px4.io/)
- **Netbird VPN:** [https://docs.netbird.io/](https://docs.netbird.io/)
- **MAVLink2REST:** [https://github.com/mavlink/mavlink2rest](https://github.com/mavlink/mavlink2rest)
- **SkyBrush Drone Show Tool:** [https://skybrush.io/](https://skybrush.io/)

---

## License

© 2025 Alireza Ghaderi

Licensed under **[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)** (Creative Commons Attribution-ShareAlike 4.0 International)

You are free to:
- **Share** - copy and redistribute the material
- **Adapt** - remix, transform, and build upon the material

Under the following terms:
- **Attribution** - give appropriate credit and link to the original repository
- **ShareAlike** - distribute your contributions under the same license

---

**⭐ If you find this project useful, please consider giving it a star on GitHub!**
