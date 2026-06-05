# MDS Documentation

**Complete documentation index for the current MDS release**

Welcome to the MDS documentation. This index routes operators, maintainers, and AI agents to the right guide without duplicating setup steps on the landing page.

---

## 🚀 Getting Started

### Fastest Paths

| I want to... | Start with... |
|--------------|---------------|
| get a working SITL demo fast | [SITL Comprehensive Guide](guides/sitl-comprehensive.md) |
| run reusable end-to-end SITL regression suites | [SITL Validation Platform](guides/sitl-validation-platform.md) |
| understand the main dashboard and dispatch scope | [Dashboard Operator Guide](guides/dashboard-operator.md) |
| fly a Drone Show from the dashboard | [Drone Show Guide](features/drone-show.md) |
| run Smart Swarm from the dashboard | [Smart Swarm Guide](features/smart-swarm.md) |
| inspect Smart Swarm tracking quality | [Smart Swarm Tracking Analysis](guides/smart-swarm-tracking-analysis.md) |
| package runtime proof reports | [Runtime Evidence Reporting](guides/runtime-evidence-reporting.md) |
| plan QuickScout or Swarm Trajectory missions | [Mission Planning Workspace](features/mission-planning-workspace.md) |
| author, process, and launch a Swarm Trajectory mission | [Swarm Trajectory Guide](features/swarm-trajectory.md) |
| point MDS at a customer/private repo | [Custom Repo Workflow](guides/custom-repo-workflow.md) |
| understand what should sync fleet-wide versus stay local/secret | [Fleet Sync And Secrets](guides/fleet-sync-and-secrets.md) |
| inspect per-drone sync/auth/MAVLink/Smart-Wi-Fi posture | [Fleet Ops](guides/fleet-ops.md) |
| add or repair Wi-Fi profiles on a companion node | [Smart Wi-Fi Manager Dashboard](guides/smart-wifi-manager-dashboard.md) |
| enable optional dashboard login/API tokens | [GCS Auth Guide](guides/gcs-auth.md) |
| configure private SITL/container repo auth | [Custom SITL Auth Guide](guides/custom-sitl-auth.md) |
| install a GCS | [GCS Setup Guide](guides/gcs-setup.md) |
| deploy companion-computer hardware | [MDS Init Setup](guides/mds-init-setup.md) |
| use repeatable `make` shortcuts for common commands | [Operator Makefile](guides/operator-makefile.md) |
| build or redistribute a validated custom SITL image | [SITL Custom Release Workflow](guides/sitl-custom-release-workflow.md) |
| control local SITL containers from the dashboard | [SITL Control Guide](guides/sitl-control.md) |
| configure Mapbox-backed map views | [Mapbox Setup](guides/mapbox-setup.md) |
| inspect logs | [Logging System Guide](guides/logging-system.md) |
| use the Simurgh read-only assistant or MCP layer | [Simurgh Operator](guides/simurgh-operator.md) |
| review the Simurgh read-only checkpoint before action-enabled work | [Simurgh Read-Only Checkpoint](guides/simurgh-readonly-checkpoint.md) |
| connect n8n, Claude, VS Code, or custom agents through MCP | [Simurgh MCP Client Recipes](guides/simurgh-mcp-clients.md) |

### By Role

| Role | Read this first |
|------|-----------------|
| Tester / pilot / evaluator | [SITL Comprehensive Guide](guides/sitl-comprehensive.md) |
| Drone Show operator | [Drone Show Guide](features/drone-show.md) |
| Smart Swarm operator | [Smart Swarm Guide](features/smart-swarm.md) |
| SAR / surveillance operator | [QuickScout Guide](quickscout.md) |
| Swarm Trajectory operator | [Swarm Trajectory Guide](features/swarm-trajectory.md) |
| Deployment engineer | [GCS Setup Guide](guides/gcs-setup.md) and [MDS Init Setup](guides/mds-init-setup.md) |
| Customer maintainer | [Custom Repo Workflow](guides/custom-repo-workflow.md) |
| Fleet operator / deployment owner | [Fleet Sync And Secrets](guides/fleet-sync-and-secrets.md) |
| Fleet ops reviewer | [Fleet Ops](guides/fleet-ops.md) |
| Simurgh / MCP reviewer | [Simurgh Read-Only Checkpoint](guides/simurgh-readonly-checkpoint.md) and [Simurgh MCP Client Recipes](guides/simurgh-mcp-clients.md) |
| SITL release maintainer | [SITL Custom Release Workflow](guides/sitl-custom-release-workflow.md) |
| AI agent / maintainer | [Repo Agent Operating Spec](../AGENTS.md) |

### Maintainers and AI Agents

- **[Repo Agent Operating Spec](../AGENTS.md)** - canonical machine-oriented operating loop for terminal AI agents; root vendor shims (`CLAUDE.md`, `GEMINI.md`) stay thin and point here
- **[AI Agent Context Index](superpowers/README.md)** - index for machine-oriented specs and plans without cluttering the normal operator docs
- **[AI Agent SITL Audit Loop](superpowers/specs/2026-03-26-ai-agent-sitl-audit-loop.md)** - deeper agent-only execution contract for reproduce, patch, validate, package, and handoff phases
- **[Frontend Design System](guides/frontend-design-system.md)** - canonical operator UI/UX, action-density, map/globe, and route-doc standards for maintainers and AI agents
- **[Frontend UI Audit Guide](guides/frontend-ui-audit.md)** - predeploy UI/UX cleanup guardrails, route-doc mapping rules, and audit command
- **[GCS Auth Guide](guides/gcs-auth.md)** - optional dashboard login, roles, token management, bootstrap flags, and SSH recovery
- **[SITL Validation Platform](guides/sitl-validation-platform.md)** - canonical reusable runtime-acceptance suite for maintainers, CI, and AI agents across same-host and split-root validation layouts
- **[Smart Swarm Tracking Analysis](guides/smart-swarm-tracking-analysis.md)** - expected vs actual follower tracking proof for leader jogs and frame changes
- **[Runtime Evidence Reporting](guides/runtime-evidence-reporting.md)** - generic Markdown/HTML/PDF package generation for accepted validation runs without customer-specific leakage
- **[Mission Planning Workspace](features/mission-planning-workspace.md)** - shared QuickScout and Swarm Trajectory planning rules, altitude/terrain doctrine, and job/error policy
- **[Simurgh Operator](guides/simurgh-operator.md)** - dashboard assistant, provider, MCP, policy, and validation guide
- **[Simurgh Read-Only Checkpoint](guides/simurgh-readonly-checkpoint.md)** - current read-only capabilities, safety boundary, validation gate, and action-enabled roadmap
- **[Simurgh MCP Client Recipes](guides/simurgh-mcp-clients.md)** - n8n, Claude, VS Code, and custom-agent connection guidance

### Project Videos

- **[Project history and walkthrough playlist](https://www.youtube.com/watch?v=dg5jyhV15S8&list=PLVZvZdBQdm_7ViwRhUFrmLFpFkP3VSakk&pp=sAgC)** - long-form project history, walkthroughs, and evolving demos

### Core Secondary Guides

- **[Advanced SITL Guide](guides/advanced-sitl.md)** - custom runtime env vars, debug-oriented SITL tuning, and mutable boot-sync behavior
- **[Dashboard Operator Guide](guides/dashboard-operator.md)** - main dashboard status model, dispatch scope behavior, and SITL/REAL safety reminders
- **[Custom SITL Auth Guide](guides/custom-sitl-auth.md)** - official/public/private repo auth split for GCS write access, SITL read access, and image-prep credentials
- **[Smart Wi-Fi Manager Dashboard](guides/smart-wifi-manager-dashboard.md)** - node-local Wi-Fi profile add/edit/remove workflow and field-safe recovery guidance
- **[SITL Control Guide](guides/sitl-control.md)** - dashboard-based local SITL lifecycle control, image save flow, and operator-focused container management
- **[Mapbox Setup](guides/mapbox-setup.md)** - optional Mapbox token setup and fallback behavior for map views
- **[Telemetry Altitude Policy](guides/telemetry-altitude-policy.md)** - display altitude ordering and map-trusted position rules
- **[SITL Validation Platform](guides/sitl-validation-platform.md)** - reusable end-to-end validation templates, plan files, and artifacts
- **[Smart Swarm Tracking Analysis](guides/smart-swarm-tracking-analysis.md)** - dedicated follower-tracking capture and plots built on the Smart Swarm websocket stream
- **[Runtime Evidence Reporting](guides/runtime-evidence-reporting.md)** - package accepted run summaries, metrics, visuals, logs, and optional PDFs in a customer-neutral format
- **[Operator Makefile](guides/operator-makefile.md)** - thin root `make` command wrappers for common launcher, bootstrap, fleet-sync, SITL, and validation workflows
- **`tools/sitl_plans/`** - checked-in named SITL scenario library for maintainers, CI, and AI agents
- **[QuickScout Guide](quickscout.md)** - SAR / recon workflows
- **[Versioning Guide](VERSIONING.md)** - release flow and version management
- **[Python Compatibility](guides/python-compatibility.md)** - supported Python versions

---

## 📖 Setup Guides

### SITL (Simulation)

| Guide | Description | Audience |
|-------|-------------|----------|
| **[SITL Comprehensive](guides/sitl-comprehensive.md)** | Complete SITL setup from scratch | Beginners |
| **[SITL Validation Platform](guides/sitl-validation-platform.md)** | Reusable end-to-end SITL regression templates, plans, and artifacts | Maintainers / CI / AI agents |
| **[Smart Swarm Tracking Analysis](guides/smart-swarm-tracking-analysis.md)** | Expected vs actual follower tracking proof during leader jogs and frame changes | Maintainers / evaluators |
| **[Runtime Evidence Reporting](guides/runtime-evidence-reporting.md)** | Customer-neutral report/PDF package generation from accepted run summaries, metrics, visuals, and logs | Maintainers / evaluators |
| **[SITL Control](guides/sitl-control.md)** | Dashboard-driven local SITL lifecycle control, reconcile, logs, and image save workflow | Operators / maintainers |
| **[Custom Repo Workflow](guides/custom-repo-workflow.md)** | Customer repo/branch selection across GCS, drones, and SITL | Advanced users |
| **[Custom SITL Auth](guides/custom-sitl-auth.md)** | GCS write credential, SITL read credential, and image-prep auth split for public/private repos | Advanced users / AI agents |
| **[Advanced SITL](guides/advanced-sitl.md)** | Custom configuration, environment variables, production deployments | Advanced users |
| **[SITL Custom Release Workflow](guides/sitl-custom-release-workflow.md)** | Fork maintenance, clean image rebuilds, package/archive distribution | Advanced users |

### Configuration

| Guide | Description |
|-------|-------------|
| **[Config JSON Format](guides/config-json-format.md)** | JSON config format reference (v4.0) |
| **[Repo Asset Layout](guides/repo-asset-layout.md)** | Authoritative home for live config, repo-backed presets, runtime state, and generated mission artifacts |
| **[CSV Migration Guide](guides/csv-migration.md)** | Legacy: migrating from old CSV format |
| **[Python Compatibility](guides/python-compatibility.md)** | Python version requirements (3.11-3.13) |

---

## ✨ Features

Detailed documentation for MDS features:

| Feature | Description |
|---------|-------------|
| **[Drone Show](features/drone-show.md)** | SkyBrush ZIP import, control-mode selection, trigger timing, custom CSV distinction, and launch-readiness workflow |
| **[Smart Swarm](features/smart-swarm.md)** | Live leader-follower formations, runtime controls, failover behavior, first SITL flow, and validator tool |
| **[Smart Swarm Tracking Analysis](guides/smart-swarm-tracking-analysis.md)** | Capture expected vs actual follower tracking during leader jogs and frame changes |
| **[Mission Planning Workspace](features/mission-planning-workspace.md)** | Shared QuickScout and Swarm Trajectory planning UI doctrine, altitude/terrain behavior, degraded-state handling, and job/progress policy |
| **[Swarm Trajectory](features/swarm-trajectory.md)** | Single-page leader-route authoring, validation, preview, processing, commit/transfer, and Dashboard Mission Type 4 workflow for leader/follower trajectories |
| **[QuickScout](quickscout.md)** | SAR/recon point dispatch, last-known point, polygon area search, multi-vertex corridor planning, launch review, and monitoring |
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
| `MDS_BRANCH` | Custom git branch | `main` |
| `MDS_GIT_AUTH_TOKEN_FILE` | Preferred read-only GitHub HTTPS token file for private SITL/image-prep/GCS read setups | unset |
| `MDS_GIT_SSH_KEY_FILE` | Optional SSH private key file for private GitHub SSH runtime sync | unset |
| `MDS_GIT_AUTO_PUSH` | Allow dashboard saves/imports to commit + push on the GCS | `true` in writable setups |
| `MDS_DEFAULT_DOCKER_IMAGE` | Git-tracked deployment default SITL image from `deployment/defaults.env` | `catchadrone-mds-sitl:latest` |
| `MDS_DOCKER_IMAGE` | Host-local SITL image override | deployment profile image |
| `MDS_SITL_GIT_SYNC` | Pull/reset SITL repo on container startup (`true` = mutable latest-on-boot mode) | `true` |
| `MDS_SITL_GIT_SYNC_PREFLIGHT` | Validate repo/branch/read credential before creating SITL containers | `true` |
| `MDS_SITL_REQUIREMENTS_SYNC` | Reinstall Python deps when `requirements.txt` changes | `true` |
| `MDS_SITL_FILE_LOG_MODE` | Runtime file log retention (`bounded`, `full`, `discard`) | `bounded` |
| `MDS_SITL_STRIP_PXH_PROMPTS` | Remove repetitive PX4 shell prompt noise from SITL logs | `true` |
| `MDS_SITL_WAIT_FOR_READY` | Wait for PX4, router, and coordinator before reporting container success | `true` |
| `MDS_SITL_READY_TIMEOUT_SECONDS` | Readiness timeout per launch batch | `60` |
| `MDS_SITL_READY_POLL_INTERVAL_SECONDS` | Readiness polling interval | `2` |
| `MDS_SITL_DOCKER_RESTART_POLICY` | Docker restart policy for SITL containers | `unless-stopped` |
| `MDS_SITL_USE_HOST_STARTUP_SCRIPT` | Override SITL bootstrap source (`true` = host-mounted current repo script, `false` = image-baked script). If unset, mutable `MDS_SITL_GIT_SYNC=true` now defaults to host override while pinned `false` stays image-baked. | `auto` |
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

### Hardware Setup Guides

| Guide | Description |
|-------|-------------|
| **[MDS Init Setup](guides/mds-init-setup.md)** | Complete step-by-step companion-node bootstrap (`install_companion.sh` / `mds_node_init.sh`) |
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
curl -fsSL https://raw.githubusercontent.com/alireza787b/mavsdk_drone_show/main/tools/install_gcs.sh | sudo bash
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
- Release process (validated `main` commit → GitHub release)
- Automated version synchronization
- Manual override capabilities

**Current Version:** 5.5

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

- [DEPRECATED: Version 2.0 SITL Guide](archives/deprecated/DEPRECATED_v2.0_doc_sitl_demo.md) - historical only, do not use for current SITL/custom-image workflows

### Legacy Documentation

Original documentation from early versions:

- Version 0.1 Documentation (PDF)
- Version 0.7 Documentation (HTML)
- Version 0.8 Server Documentation (HTML)

Located in: `archives/legacy-versions/`

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

**Last Updated:** May 2026 (Version 5.5)

© 2025 Alireza Ghaderi | Licensed under CC BY-SA 4.0
