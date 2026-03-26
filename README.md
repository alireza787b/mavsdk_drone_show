# MAVSDK Drone Show (MDS)

**All-in-One PX4 Framework for Drone Shows, Smart Swarms, and SAR**

[![Version](https://img.shields.io/badge/version-5.0-blue.svg)](CHANGELOG.md)
[![License](https://img.shields.io/badge/license-PolyForm%20Dual-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](docs/guides/python-compatibility.md)

MDS combines the drone-side runtime, GCS/backend services, and React operator dashboard into one PX4-oriented stack. It is built to stay simple enough for a quick SITL demo while remaining structured enough for serious multi-drone validation, operations, and custom deployments.

## What MDS Covers

- **Offline drone shows** with SkyBrush-imported trajectories and synchronized execution
- **Smart swarm missions** with live leader-follower coordination and runtime control
- **QuickScout SAR / recon** with multi-drone coverage planning and PX4 Mission Mode execution
- **Unified operations tooling** with SITL, GCS services, trajectory planning, and live/historical logs

## Quick Demo

For a normal first run, use the official SITL archive and the full guide:

- **[SITL Comprehensive Guide](docs/guides/sitl-comprehensive.md)** for the current MEGA download, archive validation, extraction, GCS bootstrap, and container launch flow

Once the official image is loaded and the GCS bootstrap is complete, the minimal 2-drone demo path is:

```bash
cd ~/mavsdk_drone_show
bash multiple_sitl/create_dockers.sh 2
bash app/linux_dashboard_start.sh --sitl
```

Then open `http://<host>:3030`.

For the stock official SITL package, Mission Config starts from the tracked Azadi Stadium demo origin in `data/origin.sitl.default.json`. If you later set a different origin in the dashboard or via the API, MDS writes a local runtime override to `data/origin.json` on that server. Remove that local file when you want the stock Azadi default to apply again.

For the default official HTTPS demo path, the GCS now treats git write-back as disabled by default (`MDS_GIT_AUTO_PUSH=false`). That keeps imports/config saves clean on read-only evaluation setups; move to the fork/SSH workflow when you want the GCS to commit and push changes.

If you skipped the bootstrap installer and do not have the repo yet:

```bash
git clone -b main-candidate https://github.com/alireza787b/mavsdk_drone_show.git
cd mavsdk_drone_show
```

For a first dashboard-driven Smart Swarm run after SITL launch:

1. open `Overview` and confirm the target drones show `READY` with live telemetry
2. open `Swarm Design` and review the saved follow chain / cluster layout
3. use `Formation Analysis` to choose the cluster you want to operate on
4. use `Smart Swarm Runtime` to verify the `Formation Preview` and live readiness snapshot
5. start `Selected Drone` or `Selected Cluster`, then use `Stop Swarm (Hold)`, `Land Swarm`, or `RTL Swarm` for explicit swarm-level control

For the validated 5-drone Smart Swarm acceptance flow after a SITL launch, use:

```bash
python3 tools/validate_smart_swarm_runtime.py
```

If you need your own fork, custom image, or a pinned redistribution workflow, do not improvise from the demo path. Use:

- **[Custom Repo Workflow](docs/guides/custom-repo-workflow.md)**
- **[Advanced SITL Guide](docs/guides/advanced-sitl.md)**
- **[SITL Custom Release Workflow](docs/guides/sitl-custom-release-workflow.md)**

## Choose A Path

| Goal | Start Here |
|------|------------|
| Run a quick SITL demo | [SITL Comprehensive Guide](docs/guides/sitl-comprehensive.md) |
| Import and launch a Drone Show | [Drone Show Guide](docs/features/drone-show.md) |
| Run MDS from a customer org or private repo | [Custom Repo Workflow](docs/guides/custom-repo-workflow.md) |
| Maintain a custom SITL image | [Advanced SITL Guide](docs/guides/advanced-sitl.md) |
| Build and redistribute a validated custom SITL release | [SITL Custom Release Workflow](docs/guides/sitl-custom-release-workflow.md) |
| Set up a VPS / Ubuntu GCS server | [GCS Setup Guide](docs/guides/gcs-setup.md) |
| Deploy on Raspberry Pi hardware | [MDS Init Setup Guide](docs/guides/mds-init-setup.md) |
| Run QuickScout SAR / recon workflows | [QuickScout Guide](docs/quickscout.md) |
| Review live or historical GCS / drone logs | [Logging System Guide](docs/guides/logging-system.md) |
| Explore the full docs map | [Documentation Index](docs/README.md) |

## Product Highlights

- **Single operator surface**: React dashboard for monitoring, control, QuickScout, trajectory planning, and log review
- **Modern SITL workflow**: prebuilt PX4 Gazebo SITL image, fast container startup, and reproducible custom-image tooling
- **Operational visibility**: unified logging across GCS, drones, and frontend error reporting with exportable sessions
- **Drone Show pipeline**: staged SkyBrush ZIP import, processed trajectory plots, readiness gating, and synchronized launch control
- **Scalable architecture**: designed for anything from a small demo to large validated multi-container runs

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

Contributors should branch from `main-candidate`. Public-facing `main` is kept aligned after validation.

## Safety Note

Real-drone deployment requires appropriate flight-test discipline, regulatory compliance, and failsafe validation. Treat SITL success as a prerequisite, not as proof of real-world readiness.
