# MAVSDK Drone Show Documentation

**Complete documentation index for MDS 5.0**

Welcome to the MAVSDK Drone Show documentation! This index will help you find the right guide for your needs.

---

## 📋 Table of Contents

- [Getting Started](#-getting-started)
- [Setup Guides](#-setup-guides)
- [Features](#-features)
- [Configuration](#-configuration)
- [Hardware](#-hardware)
- [API & Integration](#-api--integration)
- [Version Management](#-version-management)
- [Archived Documentation](#-archived-documentation)

---

## 🚀 Getting Started

### New to MDS?

Start here to get your first drone show simulation running:

1. **[SITL Comprehensive Guide](guides/sitl-comprehensive.md)** - Recommended for first-time users
   - Complete step-by-step SITL setup
   - Single stable Mega archive name, `7z` validation/extraction, Docker setup, dashboard startup

2. **[Advanced SITL Guide](guides/advanced-sitl.md)** - Use this if you maintain your own fork or custom Docker image

3. **[SITL Custom Release Workflow](guides/sitl-custom-release-workflow.md)** - Use this if you need a validated custom image, package, or redistribution workflow

### Maintainers and AI Agents

- **[Repo Agent Operating Spec](../AGENTS.md)** - canonical machine-oriented operating loop for terminal AI agents; root vendor shims (`CLAUDE.md`, `GEMINI.md`) stay thin and point here
- **[AI Agent SITL Audit Loop](superpowers/specs/2026-03-26-ai-agent-sitl-audit-loop.md)** - deeper agent-only execution contract for reproduce, patch, validate, package, and handoff phases

### Project Videos

- **[Project history and walkthrough playlist](https://www.youtube.com/watch?v=dg5jyhV15S8&list=PLVZvZdBQdm_7ViwRhUFrmLFpFkP3VSakk&pp=sAgC)** - long-form project history, walkthroughs, and evolving demos

### Choose Your Path

| I want to... | Start with... |
|--------------|---------------|
| Try MDS quickly (SITL) | [SITL Comprehensive Guide](guides/sitl-comprehensive.md) |
| Import and fly a Drone Show | [Drone Show Guide](features/drone-show.md) |
| Run the first Smart Swarm operator flow in the dashboard | [Smart Swarm Guide](features/smart-swarm.md) |
| Set up GCS server | [GCS Setup Guide](guides/gcs-setup.md) |
| Run or tune live Smart Swarm missions | [Smart Swarm Guide](features/smart-swarm.md) |
| Deploy on Raspberry Pi | [MDS Init Setup](guides/mds-init-setup.md) |
| Customize deployment | [Advanced SITL Guide](guides/advanced-sitl.md) |
| Build or redistribute a custom SITL release | [SITL Custom Release Workflow](guides/sitl-custom-release-workflow.md) |
| Run QuickScout SAR / recon missions | [QuickScout Guide](quickscout.md) |
| Review live or historical operator logs | [Logging System Guide](guides/logging-system.md) |
| Understand features | [Features Section](#-features) |

---

## 📖 Setup Guides

### SITL (Simulation)

| Guide | Description | Audience |
|-------|-------------|----------|
| **[SITL Comprehensive](guides/sitl-comprehensive.md)** | Complete SITL setup from scratch | Beginners |
| **[Advanced SITL](guides/advanced-sitl.md)** | Custom configuration, environment variables, production deployments | Advanced users |
| **[SITL Custom Release Workflow](guides/sitl-custom-release-workflow.md)** | Fork maintenance, clean image rebuilds, package/archive distribution | Advanced users |

### Configuration

| Guide | Description |
|-------|-------------|
| **[Config JSON Format](guides/config-json-format.md)** | JSON config format reference (v4.0) |
| **[CSV Migration Guide](guides/csv-migration.md)** | Legacy: migrating from old CSV format |
| **[Python Compatibility](guides/python-compatibility.md)** | Python version requirements (3.11-3.13) |

---

## ✨ Features

Detailed documentation for MDS features:

| Feature | Description |
|---------|-------------|
| **[Drone Show](features/drone-show.md)** | SkyBrush ZIP import, control-mode selection, trigger timing, custom CSV distinction, and launch-readiness workflow |
| **[Smart Swarm](features/smart-swarm.md)** | Live leader-follower formations, runtime controls, failover behavior, first SITL flow, and validator tool |
| **[Swarm Trajectory](features/swarm-trajectory.md)** | Processed cluster trajectories, leader-follow offsets, plotting, and KML export |
| **[QuickScout](quickscout.md)** | Cooperative SAR/recon coverage planning, mission execution, and monitoring |
| **[Logging System](guides/logging-system.md)** | Unified logging, Log Viewer workflow, export, and operator/developer modes |
| **[Origin System](features/origin-system.md)** | Coordinate system implementation and global positioning |
| **[Control Modes and Coordinates](control-modes-and-coordinates.md)** | Comprehensive guide to control modes, coordinate systems, Phase 2 auto-correction, and time synchronization |

---

## ⚙️ Configuration

### Configuration Files

- **config.json** - Main drone configuration file (JSON format with Pydantic validation)
  - Hardware ID, Position ID, IP, MAVLink port, optional serial/baudrate, custom fields
  - See [Config JSON Format Reference](guides/config-json-format.md) for details

### Environment Variables

MDS supports environment variable overrides for advanced configuration:

| Variable | Purpose | Default |
|----------|---------|---------|
| `MDS_REPO_URL` | Custom git repository URL | Official repo |
| `MDS_BRANCH` | Custom git branch | `main-candidate` |
| `MDS_GIT_AUTO_PUSH` | Allow dashboard saves/imports to commit + push on the GCS | `true` in writable setups |
| `MDS_DOCKER_IMAGE` | Custom Docker image | Official image |
| `MDS_SITL_GIT_SYNC` | Pull/reset SITL repo on container startup (`true` = mutable latest-on-boot mode) | `true` |
| `MDS_SITL_REQUIREMENTS_SYNC` | Reinstall Python deps when `requirements.txt` changes | `true` |
| `MDS_SITL_FILE_LOG_MODE` | Runtime file log retention (`bounded`, `full`, `discard`) | `bounded` |
| `MDS_SITL_STRIP_PXH_PROMPTS` | Remove repetitive PX4 shell prompt noise from SITL logs | `true` |
| `MDS_SITL_WAIT_FOR_READY` | Wait for PX4, router, and coordinator before reporting container success | `true` |
| `MDS_SITL_READY_TIMEOUT_SECONDS` | Readiness timeout per launch batch | `60` |
| `MDS_SITL_READY_POLL_INTERVAL_SECONDS` | Readiness polling interval | `2` |
| `MDS_SITL_DOCKER_RESTART_POLICY` | Docker restart policy for SITL containers | `unless-stopped` |
| `MDS_SITL_USE_HOST_STARTUP_SCRIPT` | Use a host-mounted `startup_sitl.sh` override instead of the image-baked script | `false` |
| `MDS_SITL_KEEP_ARM_TOOLCHAIN` | Keep the PX4 ARM firmware toolchain in release images | `false` |
| `MDS_MAVSDK_VERSION` | Runtime or image-build MAVSDK server version override | unset |
| `MDS_MAVSDK_URL` | Runtime or image-build MAVSDK server URL override | unset |

See [Advanced SITL Guide](guides/advanced-sitl.md) for usage examples.

---

## 🔧 Hardware

### Supported Platforms

- Raspberry Pi (4 & 5)
- NVIDIA Jetson series
- Any Linux-based companion computer

### Hardware Setup Guides (Raspberry Pi)

| Guide | Description |
|-------|-------------|
| **[MDS Init Setup](guides/mds-init-setup.md)** | Complete step-by-step Raspberry Pi initialization |
| **[CLI Reference](guides/mds-init-cli-reference.md)** | All CLI arguments, environment variables, examples |
| **[Headless Automation](guides/headless-automation.md)** | Fleet provisioning, CI/CD, batch deployment |
| **[Troubleshooting](guides/mds-init-troubleshooting.md)** | Common issues, recovery procedures, FAQ |
| **[Service Architecture](guides/raspberry-pi-services.md)** | Systemd services, boot order, configuration |

### Hardware-Specific Configuration

| Platform | Serial Port | Baudrate | Guide Status |
|----------|-------------|----------|--------------|
| Raspberry Pi 4 | `/dev/ttyS0` | 57600 / 921600 | [MDS Init Setup](guides/mds-init-setup.md) |
| Raspberry Pi 5 | `/dev/ttyAMA0` | 57600 / 921600 | [MDS Init Setup](guides/mds-init-setup.md) |
| Jetson (Orin/Xavier) | `/dev/ttyTHS1` | 57600 / 921600 | *(Documentation TBD)* |

**Note:** Real hardware deployment requires professional expertise. See [Contact](../README.md#contact--contributions) for assistance.

---

## 🖥️ GCS Server Setup

### Ground Control Station

| Guide | Description |
|-------|-------------|
| **[GCS Setup Guide](guides/gcs-setup.md)** | Complete GCS server installation and configuration |
| **[NetBird VPN Setup](guides/netbird-setup.md)** | Secure networking between GCS and drones |

Quick start for VPS/Ubuntu:
```bash
curl -fsSL https://raw.githubusercontent.com/alireza787b/mavsdk_drone_show/main-candidate/tools/install_gcs.sh | sudo bash
```

Manual setup:
```bash
sudo ./tools/mds_gcs_init.sh
```

---

## 🔌 API & Integration

### Available APIs

- **FastAPI Backend** - High-performance REST API with WebSocket support
  - Health check: `/health`
  - API docs: `/docs` (Swagger UI)
  - See [GCS Setup Guide](guides/gcs-setup.md) for configuration
- **MAVLink2REST** - REST API for MAVLink messages
  - [Official Documentation](https://github.com/mavlink/mavlink2rest)
- **WebSocket** - Real-time telemetry streaming
  - Protocol documentation: *(TBD)*

### Integration Examples

*(Coming soon - integration examples with external tools and platforms)*

---

## 📦 Version Management

Understanding how MDS manages versions:

**[Versioning Guide](VERSIONING.md)** - Complete versioning workflow

Topics covered:
- Version numbering scheme (X.Y)
- How to bump versions
- Release process (main-candidate → main → GitHub release)
- Automated version synchronization
- Manual override capabilities

**Current Version:** 5.0

**Changelog:** See [CHANGELOG.md](../CHANGELOG.md) for complete version history.

---

## 📁 Archived Documentation

Historical documentation and implementation summaries are preserved for reference:

### Implementation Summaries

Detailed reports of major implementations and bug fixes (chronologically organized):

- [2025-09-04: Flight Mode Fix](archives/implementation-summaries/2025-09-04_flight-mode-fix.md)
- [2025-09-06: Mission State Rename](archives/implementation-summaries/2025-09-06_mission-state-rename.md)
- [2025-09-20: Robustness Summary](archives/implementation-summaries/2025-09-20_robustness-summary.md)
- [2025-09-20: Container Fixes](archives/implementation-summaries/2025-09-20_container-fixes.md)
- [2025-11-04: Processing Validation](archives/implementation-summaries/2025-11-04_processing-validation.md)
- [2025-11-05: Bug Fix Report](archives/implementation-summaries/2025-11-05_bug-fix-report.md)
- [2025-11-05: Implementation Summary](archives/implementation-summaries/2025-11-05_implementation-summary.md)
- [2025-11-06: Cleanup Summary](archives/implementation-summaries/2025-11-06_cleanup-summary.md)

### Deprecated Documentation

Older versions retained for historical reference:

- [DEPRECATED: Version 2.0 SITL Guide](archives/deprecated/DEPRECATED_v2.0_doc_sitl_demo.md)

### Legacy Documentation

Original documentation from early versions:

- Version 0.1 Documentation (PDF)
- Version 0.7 Documentation (HTML)
- Version 0.8 Server Documentation (HTML)

Located in: `archives/legacy-versions/`

---

## 🎯 Quick Navigation

### By User Type

**Beginners:**
1. Start with [SITL Comprehensive Guide](guides/sitl-comprehensive.md)
2. Review [Python Compatibility](guides/python-compatibility.md)
3. Explore [Features Documentation](#-features)

**Experienced Users:**
1. Check [Advanced SITL Guide](guides/advanced-sitl.md)
2. Review [Swarm Trajectory Features](features/swarm-trajectory.md)
3. Consult [API Documentation](#-api--integration)

**Developers/Contributors:**
1. Read [Versioning Guide](VERSIONING.md)
2. Review [Configuration Guides](#-configuration)
3. Check [Archived Implementation Summaries](#implementation-summaries)

---

## 🔍 Can't Find What You're Looking For?

- **Search the repository:** Use GitHub's search function
- **Check the main README:** [../README.md](../README.md)
- **Browse the codebase:** Inline documentation in source files
- **Ask for help:** See [Contact & Contributions](../README.md#contact--contributions)

---

## 📝 Contributing to Documentation

Documentation improvements are always welcome! If you:
- Found an error or outdated information
- Want to add a new guide
- Have suggestions for better organization

Please submit a pull request or open an issue on GitHub.

---

**Last Updated:** March 2026 (Version 5.0)

© 2025 Alireza Ghaderi | Licensed under CC BY-SA 4.0
