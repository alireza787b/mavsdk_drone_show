# MDS - Mission-Directed Swarm

**Open-source MAVLink fleet operations for PX4 drones, SITL, drone shows, SAR, and cooperative autonomy.**

[![Version](https://img.shields.io/badge/version-5.4-blue.svg)](CHANGELOG.md)
[![License](https://img.shields.io/badge/license-PolyForm%20Dual-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](docs/guides/python-compatibility.md)
[![PX4](https://img.shields.io/badge/PX4-MAVLink-005CAF.svg)](https://px4.io/)
[![MAVSDK](https://img.shields.io/badge/MAVSDK-Python-21D4FD.svg)](https://mavsdk.mavlink.io/)

![MDS logo](assets/brand/mds-logo.svg)

MDS began as MAVSDK Drone Show and now covers a broader PX4-oriented fleet stack:
drone-side runtime, GCS/backend services, React operator dashboard, SITL, real
companion computers, sidecar connectivity, and mission execution workflows. It
is built to stay simple enough for a quick SITL demo while remaining structured
enough for serious multi-drone validation, operations, and custom deployments.

## What MDS Covers

- **Offline drone shows** with SkyBrush-imported trajectories and synchronized execution
- **Smart swarm missions** with live leader-follower coordination and runtime control
- **QuickScout SAR / recon** with multi-drone coverage planning and PX4 Mission Mode execution
- **Unified operations tooling** with SITL, GCS services, trajectory planning, and live/historical logs

MDS is a field-operations and research platform, not certified avionics. Flight
testing requires qualified operators, local aviation compliance, geofencing,
failsafe review, and independent safety validation.

## Start Here

| If you want to... | Start here |
|-------------------|------------|
| run the first demo quickly | [SITL Comprehensive Guide](docs/guides/sitl-comprehensive.md) |
| import and launch a drone show | [Drone Show Guide](docs/features/drone-show.md) |
| run Smart Swarm from the dashboard | [Smart Swarm Guide](docs/features/smart-swarm.md) |
| author, process, and launch a Swarm Trajectory mission | [Swarm Trajectory Guide](docs/features/swarm-trajectory.md) |
| point MDS at a customer/private repo | [Custom Repo Workflow](docs/guides/custom-repo-workflow.md) |
| install a GCS on a VPS or Ubuntu box | [GCS Setup Guide](docs/guides/gcs-setup.md) |
| deploy real drone hardware | [MDS Init Setup Guide](docs/guides/mds-init-setup.md) |
| build or ship a validated custom SITL image | [SITL Custom Release Workflow](docs/guides/sitl-custom-release-workflow.md) |
| browse everything else | [Documentation Index](docs/README.md) |

## Quick Demo

Start with the **[SITL Comprehensive Guide](docs/guides/sitl-comprehensive.md)**.
It covers the official SITL archive, validation, bootstrap, dashboard launch,
and the current dashboard-first SITL Control workflow.

For normal demos, use the dashboard **SITL Control** page to reconcile/start
SITL drones instead of copying low-level shell commands from the README. Shell
and `make` wrappers still exist for automation and advanced operators; see the
**[Operator Makefile Guide](docs/guides/operator-makefile.md)** when you need
scripted control.

The dashboard launcher keeps the FastAPI backend single-process by default, so
telemetry, heartbeats, command tracking, and other in-memory operational state
stay coherent during live SITL runs. Backend auto-reload is only for backend
code editing; the SITL guide covers that advanced mode.

For the stock official SITL package, Mission Config starts from the tracked Azadi Stadium demo origin in `data/origin.sitl.default.json`. If you later set a different origin in the dashboard or via the API, MDS writes a local runtime override to `data/origin.json` on that server. Remove that local file when you want the stock Azadi default to apply again.

For the default official HTTPS demo path, the GCS now treats git write-back as disabled by default (`MDS_GIT_AUTO_PUSH=false`). That keeps imports/config saves clean on read-only evaluation setups; move to the fork/SSH workflow when you want the GCS to commit and push changes.

If you skipped the bootstrap installer and do not have the repo yet, follow the
clone/bootstrap path in the SITL guide instead of copying ad-hoc commands from
the README.

For a first dashboard-driven Smart Swarm run after SITL launch:

1. open `Overview` and confirm the target drones show `READY` with live telemetry
2. open `Swarm Design` and review the saved follow chain / cluster layout
3. use `Formation Analysis` to choose the cluster you want to operate on
4. use `Smart Swarm Runtime` to verify the `Formation Preview` and live readiness snapshot
5. start `Selected Drone` or `Selected Cluster`, then use `Stop Swarm (Hold)`, `Land Swarm`, or `RTL Swarm` for explicit swarm-level control

The validated 5-drone Smart Swarm acceptance flow is documented in the Smart
Swarm and SITL guides, including the operator-safe dashboard path and the
automation validation helper for advanced users.

If you need your own fork, custom image, or a pinned redistribution workflow, do not improvise from the demo path. Use:

- **[Custom Repo Workflow](docs/guides/custom-repo-workflow.md)**
- **[Advanced SITL Guide](docs/guides/advanced-sitl.md)**
- **[SITL Custom Release Workflow](docs/guides/sitl-custom-release-workflow.md)**

These advanced and real-hardware paths require stronger PX4/Linux/networking knowledge plus licensing, regulatory, and operational review. If you need private assistance or deployment consulting, contact [Alireza on LinkedIn](https://www.linkedin.com/in/alireza787b/) or [p30planets@gmail.com](mailto:p30planets@gmail.com).

## More Guides

- **[Advanced SITL Guide](docs/guides/advanced-sitl.md)** for custom runtime env vars, mutable boot-sync behavior, and debug-oriented SITL tuning
- **[Logging System Guide](docs/guides/logging-system.md)** for live and historical GCS / drone logs
- **[QuickScout Guide](docs/quickscout.md)** for SAR / recon workflows
- **[Documentation Index](docs/README.md)** for the full map, APIs, archived notes, and deeper references

## Optional Ecosystem Tools

MDS can integrate optional companion-side tools when real hardware needs them:

- **[Smart Wi-Fi Manager](https://github.com/alireza787b/smart-wifi-manager)** for field Wi-Fi profile management on Linux companion computers
- **[MAVLink Anywhere](https://github.com/alireza787b/mavlink-anywhere)** for MAVLink routing over companion computers, LTE/Wi-Fi/VPN, UDP, and serial

They remain standalone projects and are not required for a first SITL demo.

## Product Highlights

- **Single operator surface**: React dashboard for monitoring, control, QuickScout, trajectory planning, and log review
- **Modern SITL workflow**: prebuilt PX4 Gazebo SITL image, fast container startup, and reproducible custom-image tooling
- **Operational visibility**: unified logging across GCS, drones, and frontend error reporting with exportable sessions
- **Drone Show pipeline**: staged SkyBrush ZIP import, processed trajectory plots, readiness gating, and synchronized launch control
- **Scalable architecture**: designed for anything from a small demo to large validated multi-container runs

## Roadmap Direction

Active and planned work is tracked in [ROADMAP.md](ROADMAP.md). Current research
directions include:

- MCP-compatible AI-agent workflows for drone swarms and fleet operations
- automated SAR, surveillance, and cooperative mission workflows
- PixEagle integration for vision-assisted swarm control
- GPS-denied and indoor swarm feasibility using AI/image-processing pipelines such as monocular vision
- future ArduPilot support exploration
- optimized minimal SIH Docker simulation for lightweight validation

## Dashboard Scope

The dashboard covers:

- live fleet monitoring and control
- mission upload and execution
- 3D trajectory planning
- QuickScout mission planning and monitoring
- live and historical Log Viewer workflows

Map-heavy features such as trajectory planning and QuickScout require a Mapbox token. See the relevant guides in [Documentation Index](docs/README.md).

## Videos

<table>
  <tr>
    <td align="center">
      <a href="https://www.youtube.com/watch?v=mta2ARQKWRQ">
        <img src="https://img.youtube.com/vi/mta2ARQKWRQ/mqdefault.jpg" alt="MDS 3 Complete Feature Showcase" width="220">
      </a>
      <br>
      <a href="https://www.youtube.com/watch?v=mta2ARQKWRQ">Feature Showcase</a>
    </td>
    <td align="center">
      <a href="https://www.youtube.com/watch?v=VsNs3kFKEvU">
        <img src="https://img.youtube.com/vi/VsNs3kFKEvU/mqdefault.jpg" alt="100-Drone SITL Test" width="220">
      </a>
      <br>
      <a href="https://www.youtube.com/watch?v=VsNs3kFKEvU">100-Drone SITL</a>
    </td>
    <td align="center">
      <a href="https://youtu.be/qRXE3LTd40c">
        <img src="https://img.youtube.com/vi/qRXE3LTd40c/mqdefault.jpg" alt="Smart Swarm Demo" width="220">
      </a>
      <br>
      <a href="https://youtu.be/qRXE3LTd40c">Smart Swarm Demo</a>
    </td>
  </tr>
</table>

- **Project history and walkthrough playlist:** [YouTube playlist](https://www.youtube.com/watch?v=dg5jyhV15S8&list=PLVZvZdBQdm_7ViwRhUFrmLFpFkP3VSakk&pp=sAgC)
- **MDS 5 walkthrough:** coming soon, to be linked here when published

## Documentation

- **[Documentation Index](docs/README.md)**: full guide map
- **[CHANGELOG.md](CHANGELOG.md)**: notable changes
- **[VERSIONING.md](docs/VERSIONING.md)**: release/version workflow
- **[Python Compatibility](docs/guides/python-compatibility.md)**: supported Python versions

## Licensing

MDS uses dual licensing:

- **PolyForm Noncommercial** for education, research, and other non-commercial use
- **PolyForm Small Business** for qualifying small commercial operators
- **Commercial license** for larger commercial deployments

See [LICENSE](LICENSE) and [LICENSE-COMMERCIAL.md](LICENSE-COMMERCIAL.md).

## Contact And Contributions

- **Commercial / deployment inquiries:** [p30planets@gmail.com](mailto:p30planets@gmail.com)
- **GitHub issues:** [bug reports and feature requests](https://github.com/alireza787b/mavsdk_drone_show/issues)
- **Contributing guide:** [CONTRIBUTING.md](CONTRIBUTING.md)

Contributors should start feature branches from `main`. Use short-lived feature or client branches for work-in-progress, then merge back to `main` only after SITL/hardware validation.

## Safety Note

Real-drone deployment requires appropriate flight-test discipline, regulatory compliance, and failsafe validation. Treat SITL success as a prerequisite, not as proof of real-world readiness.
