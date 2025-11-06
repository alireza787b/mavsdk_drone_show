# Changelog

All notable changes to MAVSDK Drone Show (MDS) project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project uses simple two-part versioning: `X.Y` (Major.Minor).

---

## [3.6] - 2025-11-06

### Added
- **Documentation Restructure**: Comprehensive reorganization of all project documentation
  - Created organized folder structure: `docs/quickstart/`, `docs/guides/`, `docs/features/`, `docs/hardware/`, `docs/api/`
  - Created `docs/archives/` for historical documentation and implementation summaries
  - New documentation index at `docs/README.md` for easy navigation
- **Versioning System**: Unified version management across entire project
  - Single source of truth: `VERSION` file in project root
  - Automated version synchronization script: `tools/version_sync.py`
  - Dynamic version display in dashboard with git commit hash
  - Versioning workflow guide at `docs/VERSIONING.md`
- **CHANGELOG.md**: Separate, structured changelog following Keep a Changelog format
- **GCS Configuration Enhancements**:
  - Dashboard .env file auto-update feature for GCS IP changes
  - Checkbox option to update `REACT_APP_SERVER_URL` when changing GCS IP
  - User warnings about rebuild requirements and server location
- **UI/UX Production Improvements**:
  - Origin coordinate display with responsive multi-line layout
  - GPS coordinates truncated to 6 decimal places (0.11m accuracy)
  - Modal dialogs now center on viewport instead of container
  - Comprehensive toast notifications for save operations with git status
  - Save button renamed to "Save & Commit to Git" for clarity

### Changed
- **README.md**: Cleaned and streamlined for professional presentation
  - Added table of contents
  - Removed embedded version history (moved to CHANGELOG.md)
  - Better separation of quick start vs comprehensive guides
  - Improved navigation and structure
- **Documentation Organization**:
  - Moved implementation summaries to `docs/archives/implementation-summaries/`
  - Moved legacy docs (v2.0, HTML, PDF) to `docs/archives/`
  - Renamed and relocated current docs to new folder structure
  - Dashboard README customized for MDS (was generic Create React App template)
- **Dark Mode Fixes**:
  - Fixed unreadable metric boxes in ManageDroneShow page
  - Replaced MUI inline styles with CSS variables for theme compatibility
  - Added 80+ lines of dark mode compatible CSS
- **Version Display**: Dashboard sidebar now shows `v3.6 (git-hash)` dynamically

### Fixed
- GCS configuration dialog showing empty "Current IP" field (nested data structure issue)
- GCS IP not differentiating between SITL mode (172.18.0.1) and Real mode (100.96.32.75)
- Confirmation dialogs requiring scroll to see (viewport centering issue)
- No visual feedback during configuration save/commit operations
- Origin GPS coordinates overflowing container
- Dark mode color accessibility in VisualizationSection components

---

## [3.5] - 2025-09

### Added
- **Professional React Dashboard** with expert portal-based UI/UX using React Portal architecture
- **3D Trajectory Planning** with interactive waypoint creation, terrain elevation, and speed optimization
- **Enhanced Mobile Responsiveness** with touch-friendly interface and responsive design
- **Smart Swarm Trajectory Processing** with cluster leader management and dynamic formation reshaping
- **Expert Tab Navigation** with professional mission operations interface
- **Advanced UI/UX Improvements** with modal overlays, responsive design, and touch-friendly controls

### Changed
- Complete dashboard redesign with modern React patterns

### Fixed
- Multiple bug fixes and performance improvements for production deployment

---

## [3.0] - 2025-06

### Added
- **Smart Swarm Leader–Follower System**: Fully operational with leader failover, auto re-election, and seamless follower sync
- **Global Mode Setpoints**: Unified approach for both offline and live missions
- **Enhanced Failsafe Checks**: Comprehensive preflight health checks and in-flight monitoring
- **Stable Startup Sequence**: Three-way handshake mechanism ("OK-to-Start" broadcast)
- **Unified All-in-One System**: Single platform for both drone shows and live swarm operations

### Fixed
- Race condition issues under high CPU load (GUIDED → AUTO transitions)
- Emergency-land command reliability during mode transitions
- Network buffer tuning for large-scale simulations (100+ drones)

---

## [2.0] - 2024-11

### Added
- Enhanced React GUI with improved user experience
- Robust Flask backend architecture
- Comprehensive drone-show scripts
- Docker SITL environment for testing
- [100-Drone SITL Test Video](https://www.youtube.com/watch?v=VsNs3kFKEvU)

### Changed
- Major GUI overhaul
- Backend infrastructure improvements

---

## [1.5] - 2023-08

### Added
- Mission configuration tools
- SkyBrush CSV converter utility
- Expanded MAVLink2REST integration

---

## [1.0] - 2023-03

### Added
- **Stable Release Milestone**
- Flask web server implementation
- Professional API structure

### Removed
- UDP dependencies (replaced with more reliable protocols)

---

## [0.8] - 2022-09

### Added
- Major GUI enhancements
- Kalman-filter–based swarm behaviors
- Optimized cloud SITL performance

---

## [0.7] - 2022-04

### Added
- React GUI for real-time swarm monitoring
- Docker automation for PX4 SITL environments

---

## [0.6] - 2021-12

### Added
- Complex leader/follower swarm control capabilities
- Docker-based SITL environment

---

## [0.5] - 2021-07

### Added
- Basic leader/follower missions on real hardware
- Enhanced GCS data handling

---

## [0.4] - 2021-02

### Added
- `Coordinator.py` for advanced swarm coordination
- Improved telemetry and command systems

---

## [0.3] - 2020-10

### Added
- SkyBrush CSV processing integration
- Code optimizations for drone show performances

---

## [0.2] - 2020-06

### Added
- Multi-drone support with offset/delayed CSV trajectories

---

## [0.1] - 2020-03

### Added
- Initial release
- Single-drone CSV trajectory following
- Basic MAVSDK integration

---

## Release Types

- **Major Version (X.0)**: Significant architectural changes, breaking changes, or major new features
- **Minor Version (X.Y)**: New features, improvements, and non-breaking changes

---

© 2025 Alireza Ghaderi | Licensed under CC BY-SA 4.0
