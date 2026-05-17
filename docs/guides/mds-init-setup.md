# MDS Companion Node Setup Guide

Complete step-by-step guide for initializing a Linux-based companion computer for the MDS drone swarm platform.

## Overview

The `mds_node_init.sh` script is an enterprise-grade bootstrap system that configures a fresh companion-computer node for use in MDS drone swarm operations. It handles:

- System prerequisites and validation
- Repository cloning with SSH/HTTPS support (custom repo selection included)
- Hardware identity configuration
- Python virtual environment setup
- MAVSDK binary installation
- Systemd service installation
- Firewall configuration with SSH port detection
- NTP time synchronization
- Candidate announce to the GCS enrollment registry when the API is reachable
- Optional: NetBird VPN (official or self-hosted), Static IP, Smart Wi-Fi Manager

## Prerequisites

### Hardware Requirements

- Raspberry Pi 4 or 5 (4GB+ RAM recommended)
- Other Debian-family companion computers are also supported when they can host the same services and MAVLink routing stack
- 16GB+ SD card (32GB recommended)
- Stable power supply (5V 3A minimum)
- Network connection (Ethernet or WiFi)

### Software Requirements

- Raspberry Pi OS or another Debian-family Linux distribution (64-bit recommended)
- Python 3.11 or later (included in latest Raspberry Pi OS)
- Internet connectivity for package downloads

## Quick Start

### Option 1: One-Line Installation (Recommended)

Use this on a fresh companion-computer host that does not already have the MDS
repo cloned locally. This is the public bootstrap wrapper.

The fastest way to set up a fresh companion-computer node:

```bash
curl -fsSL https://raw.githubusercontent.com/alireza787b/mavsdk_drone_show/main/tools/install_companion.sh | sudo bash
```

By default the wrapper creates the `droneshow` runtime user and clones the repo
into `/home/droneshow/<repo-dir>`. Override those wrapper-level defaults with
`MDS_USER` and `MDS_INSTALL_DIR` if you need a different runtime identity or
install location:

```bash
curl -fsSL https://raw.githubusercontent.com/alireza787b/mavsdk_drone_show/main/tools/install_companion.sh | \
  sudo env MDS_USER=companion MDS_INSTALL_DIR=/srv/customer-mds bash -s -- -d 1 -y
```

When you run the wrapper from a local checkout instead of the raw GitHub URL, it
also loads repo defaults from `deployment/defaults.env` before applying any
environment overrides.

**With drone ID (non-interactive):**
```bash
curl -fsSL https://raw.githubusercontent.com/alireza787b/mavsdk_drone_show/main/tools/install_companion.sh | sudo bash -s -- -d 1 -y
```

**Using your own fork or org repo:**
```bash
curl -fsSL https://raw.githubusercontent.com/alireza787b/mavsdk_drone_show/main/tools/install_companion.sh | sudo bash -s -- --fork yourusername -d 1 -y
```

For confidentiality-sensitive customers, prefer an org-owned private repo instead of assuming a normal GitHub fork will be private.

**Using a customer org/private repo path:**
```bash
curl -fsSL https://raw.githubusercontent.com/alireza787b/mavsdk_drone_show/main/tools/install_companion.sh | sudo bash -s -- --fork yourorg/customer-mds --branch customer-demo -d 1 -y
```

For a first-time private SSH bootstrap, omit `-y` unless the deploy key is already authorized on GitHub. Non-interactive `-y` is safe only after that prerequisite is already satisfied.

**Using an explicit repository URL:**
```bash
curl -fsSL https://raw.githubusercontent.com/alireza787b/mavsdk_drone_show/main/tools/install_companion.sh | sudo bash -s -- --repo-url git@github.com:yourorg/customer-mds.git --branch customer-demo -d 1 -y
```

**Using a private HTTPS repository with a read-only token file:**
```bash
install -m 600 /dev/null /home/<mds-user>/.mds_git_read_token
printf '%s' 'YOUR_READ_ONLY_GITHUB_TOKEN' > /home/<mds-user>/.mds_git_read_token

curl -fsSL https://raw.githubusercontent.com/alireza787b/mavsdk_drone_show/main/tools/install_companion.sh | \
  sudo bash -s -- \
  --repo-url https://github.com/yourorg/customer-mds.git \
  --branch customer-demo \
  --git-auth-token-file /home/<mds-user>/.mds_git_read_token \
  -d 1 -y
```

**Using a private SSH repository with an existing read-only key:**
```bash
curl -fsSL https://raw.githubusercontent.com/alireza787b/mavsdk_drone_show/main/tools/install_companion.sh | \
  sudo bash -s -- \
  --repo-url git@github.com:yourorg/customer-mds.git \
  --branch customer-demo \
  --git-ssh-key-file /home/<mds-user>/.ssh/customer_git_read_key \
  -d 1 -y
```

`install_companion.sh` is the public entrypoint for fresh hardware.
`install_mds_node.sh` remains an equivalent packaged entrypoint for automation
that already references the node-specific filename.

### Option 2: Manual Installation

Use this when the repo is already present on the node, or when you are
repairing, resuming, or deliberately re-running configuration on an existing
node.

### Which Script Should I Run?

| Scenario | Recommended entrypoint |
|------|--------------------------|
| Fresh OS image, no repo cloned yet | `install_companion.sh` (`install_mds_node.sh` also works) |
| Repo already cloned on the node | `mds_node_init.sh` |
| Resume or repair an interrupted init on the same node | `mds_node_init.sh --resume` |
| Provisioned node could not reach GCS during bootstrap | `mds_node_announce.sh` |
| Replace / recover / reassign a drone in the fleet manifest | Use **Fleet Enrollment** after announce; do not rerun full bootstrap unless the node itself needs reprovisioning |

#### Step 1: Prepare the OS Image

1. Prepare a supported Debian-family image for your companion computer
2. If you are using Raspberry Pi, [Raspberry Pi Imager](https://www.raspberrypi.com/software/) is the recommended path
3. Configure network access and SSH
4. Boot the companion computer

#### Step 2: Initial System Setup

SSH into the companion computer:

```bash
ssh pi@raspberrypi.local
```

Update the system:

```bash
sudo apt update && sudo apt upgrade -y
```

#### Step 3: Clone the Repository

Only do a manual clone if the repo is already present on the node or you are
deliberately repairing an existing checkout. Fresh hosts should start from the
official wrapper so first-time private deploy-key authorization happens before
the target repo clone.

Manual clone example for an already-provisioned host:

```bash
git clone -b customer-demo git@github.com:yourorg/customer-mds.git
cd customer-mds
```

#### Step 4: Run the Initialization Script

**Interactive mode (recommended for first-time setup):**

```bash
sudo ./tools/mds_node_init.sh
```

**Non-interactive mode with drone ID:**

```bash
sudo ./tools/mds_node_init.sh -d 1 -y
```

**Using your own fork or custom repo:**

```bash
sudo ./tools/mds_node_init.sh -d 1 --fork yourusername -y
```

Or fully explicit:

```bash
sudo ./tools/mds_node_init.sh -d 1 \
    --repo-url git@github.com:yourorg/customer-mds.git \
    --branch customer-demo \
    -y
```

Private read-only HTTPS is also supported explicitly:

```bash
sudo ./tools/mds_node_init.sh -d 1 \
    --repo-url https://github.com/yourorg/customer-mds.git \
    --branch customer-demo \
    --git-auth-token-file /home/droneshow/.mds_git_read_token \
    -y
```

Private read-only SSH is also supported explicitly:

```bash
sudo ./tools/mds_node_init.sh -d 1 \
    --repo-url git@github.com:yourorg/customer-mds.git \
    --branch customer-demo \
    --git-ssh-key-file /home/droneshow/.ssh/customer_git_read_key \
    -y
```

With an explicit GCS API URL for candidate announce:

```bash
sudo ./tools/mds_node_init.sh -d 1 \
    --gcs-api-url https://gcs.example/api \
    -y
```

## Initialization Phases

The script runs through these phases automatically:

| Phase | Description |
|-------|-------------|
| 1. Prerequisites | Validates system requirements, creates directories |
| 2. MAVLink Router Setup | Auto-configures `mavlink-anywhere` when requested, or preserves intentional manual routing |
| 3. Repository | Clones/updates repository, manages SSH keys |
| 4. Identity | Configures drone ID, `local.env`, and `node_identity.json` |
| 5. Environment | Sets up environment variables |
| 6. Firewall | Configures UFW rules for MDS services |
| 7. Python Environment | Creates venv, installs requirements |
| 8. MAVSDK | Downloads and installs MAVSDK binary |
| 9. Services | Installs and enables systemd services |
| 10. NTP | Configures time synchronization |
| 11. Netbird | (Optional) Configures VPN access |
| 12. Static IP | (Optional) Configures static IP address |
| 13. Connectivity Backend | (Optional) Installs Smart Wi-Fi Manager or keeps manual networking |
| 14. Verify | Final verification of installation |
| 15. Candidate Announce | Sends the node identity to the GCS enrollment registry when reachable |

## Common Setup Scenarios

### Scenario 1: Single Drone Setup

For a single drone with ID 1:

```bash
sudo ./tools/mds_node_init.sh -d 1 -y
```

### Scenario 2: Custom Repository

For using a forked repository or org-owned repo (simple shorthand):

```bash
sudo ./tools/mds_node_init.sh -d 1 --fork yourusername -y
```

Or with a customer org/private repo:

```bash
sudo ./tools/mds_node_init.sh -d 1 \
    --repo-url git@github.com:yourorg/customer-mds.git \
    --branch customer-demo \
    -y
```

For the full cross-target workflow, see [Custom Repo Workflow](custom-repo-workflow.md).

### Scenario 3: Full Setup with VPN and Static IP

```bash
sudo ./tools/mds_node_init.sh -d 5 \
    --netbird-key "YOUR_NETBIRD_SETUP_KEY" \
    --static-ip 192.168.1.105/24 \
    --gateway 192.168.1.1 \
    -y
```

NetBird is optional. For same-LAN or static-IP deployments, omit `--netbird-key` and use the node's reachable LAN IP for QGroundControl or for any explicit `--gcs-ip` push endpoint you intentionally configure.

### Scenario 4: Resume Interrupted Installation

If the script was interrupted, resume from the last checkpoint:

```bash
sudo ./tools/mds_node_init.sh --resume
```

### Scenario 5: Dry Run (Test Mode)

See what would happen without making changes:

```bash
sudo ./tools/mds_node_init.sh -d 1 --dry-run
```

### Scenario 6: Re-send Candidate Announce Only

If the node is provisioned but the GCS was unavailable during bootstrap:

```bash
sudo ./tools/mds_node_announce.sh --gcs-api-url http://192.0.2.75:5030
```

## Post-Installation

### Verify Installation

Check service status:

```bash
systemctl status coordinator
systemctl status git_sync_mds
```

## Enrollment Follow-Up

Bootstrap and candidate announce do not finish fleet enrollment on their own.
The announce payload includes the node's canonical `runtime_mode` from
`/etc/mds/node_identity.json`, so a SITL node cannot pollute the REAL enrollment
queue and a REAL node cannot pollute the SITL queue.

After the node appears in **Fleet Enrollment**:

1. accept, replace, or recover the candidate on GCS
2. commit/push the updated fleet repo state on GCS if auto-push is disabled
3. run a node repo sync before relying on the new assignment at runtime

Operational rule:
- GCS enrollment updates the fleet manifest immediately
- the node still runs from its local repo/config state until the sync step applies that change

Check the installation log:

```bash
cat /var/log/mds/mds_init.log
```

### Configure MAVLink Routing

Current best practice:

- use `mds_node_init.sh --mavlink-auto` for the default managed path
- keep the managed `mavlink-anywhere` repo/ref/install defaults in
  `deployment/defaults.env`
- use `/etc/mds/local.env` only for node-specific MAVLink ownership overrides
  when a board needs different runtime handling
- interactive bootstrap lets the operator choose between recommended defaults, a guided `mavlink-anywhere` wizard, or fully manual routing
- or provide explicit headless routing flags such as `--mavlink-uart` and
  `--mavlink-endpoints`
- use `--mavlink-input udp --mavlink-input-port ...` when the node should ingest MAVLink from a network source instead of a serial FC link
- use manual routing only when you intentionally manage `mavlink-anywhere`
  yourself

Managed examples:

```bash
sudo ./tools/mds_node_init.sh -d 1 --mavlink-auto --gcs-ip 192.0.2.75 -y
```

```bash
sudo ./tools/mds_node_init.sh \
  -d 1 \
  --mavlink-uart /dev/ttyS0 \
  --mavlink-ref v3.0.10 \
  --mavlink-endpoints "127.0.0.1:14540,127.0.0.1:14569,192.0.2.75:24550" \
  -y
```

```bash
sudo ./tools/mds_node_init.sh \
  -d 1 \
  --mavlink-input udp \
  --mavlink-input-port 14550 \
  --mavlink-endpoints "127.0.0.1:14540,127.0.0.1:14569,127.0.0.1:12550" \
  -y
```

If you intentionally keep routing manual, bootstrap and enrollment still work.
In that case, manage `mavlink-anywhere` yourself and keep that routing profile
documented for the fleet.

Managed runtime ownership and local overrides:

- `deployment/defaults.env`
  - `MDS_DEFAULT_MAVLINK_MANAGEMENT_MODE`
  - `MDS_DEFAULT_MAVLINK_ANYWHERE_REPO_URL_HTTPS`
  - `MDS_DEFAULT_MAVLINK_ANYWHERE_REF`
  - `MDS_DEFAULT_MAVLINK_ANYWHERE_INSTALL_DIR`
- `/etc/mds/local.env`
  - `MDS_MAVLINK_MANAGEMENT_MODE`
  - optional `MDS_MAVLINK_ANYWHERE_REPO_URL`
  - optional `MDS_MAVLINK_ANYWHERE_REF`
  - `MDS_MAVLINK_ANYWHERE_INSTALL_DIR`
  - `MDS_MAVLINK_ANYWHERE_DASHBOARD_LISTEN`
  - `MDS_MAVLINK_ANYWHERE_SKIP_DASHBOARD`

After changing only the managed runtime ownership settings on an existing node:

```bash
sudo ./tools/reconcile_mavlink_runtime.sh apply --force
```

Current `mavlink-anywhere` defaults include a device-side GCS listener on `14550/udp`, so the normal QGC workflow is to connect **to the node / CM4 IP on port 14550**. Add explicit `GCS_IP:24550` push endpoints only when you intentionally need remote push-mode delivery.

If you are using the Holybro Pixhawk RPi CM4 baseboard, the PX4/Holybro docs wire the CM4 to the FC through **TELEM2** and expect PX4 to use:

- `MAV_1_CONFIG = TELEM2 (102)`
- `MAV_1_MODE = Onboard (2)`
- `SER_TEL2_BAUD = 921600`

If you want the web dashboard reachable from the LAN or VPN, expose it explicitly:

```bash
sudo ./configure_mavlink_router.sh --install-dashboard \
  --dashboard-listen 0.0.0.0:9070
```

### Reboot

After installation, reboot to start all services:

```bash
sudo reboot
```

## Configuration Files

After installation, key configuration files are:

| File | Purpose |
|------|---------|
| `/etc/mds/local.env` | Per-node runtime overrides (hardware ID, GCS routing, optional GCS API URL, repo/branch overrides, etc.) |
| `/etc/mds/node_identity.json` | Structured machine-readable node manifest for automation, enrollment, and diagnostics |
| `/var/lib/mds/init_state.json` | Installation state tracking |
| `~/mavsdk_drone_show/config.json` | Fleet manifest source of truth for real-mode membership and per-node transport settings |
| `~/mavsdk_drone_show/swarm.json` | Smart Swarm / follow-chain source of truth for real mode |
| `~/mavsdk_drone_show/src/params.py` | Transitional code defaults and fallback values while the typed settings layer is rolled out |

### Source Of Truth

Use these ownership rules consistently:

- `config.json` / `swarm.json`: fleet manifest and mission-structure source of truth on GCS
- `Fleet Enrollment`: canonical workflow that mutates `config.json` for accept / replace / recover
- `/etc/mds/local.env`: node-local runtime identity and GCS routing source of truth on each companion computer
- `src/params.py`: fallback defaults only; not the normal operator customization point for real hardware
- See [Runtime Config Sources](runtime-config-sources.md) for the full precedence table and ownership model.

Practical consequence:

- changing `MDS_GCS_IP` or `MDS_GCS_API_BASE_URL` belongs in `/etc/mds/local.env`
- enrolling a new node belongs in `Fleet Enrollment`, which updates `config.json`
- replacing a failed airframe also belongs in `Fleet Enrollment`; replacement rewrites the affected `config.json` row and any relevant `swarm.json` references
- editing `src/params.py` should be reserved for code-level defaults that apply repo-wide, not for per-deployment runtime state

### Editing Local Configuration

To change drone-specific settings:

```bash
sudo nano /etc/mds/local.env
sudo systemctl restart coordinator
```

To preview or resend the candidate announce payload:

```bash
sudo ./tools/mds_node_announce.sh --dry-run --report-json -
```

## Troubleshooting

See [MDS Init Troubleshooting Guide](mds-init-troubleshooting.md) for common issues.

### Quick Fixes

**Script fails to start:**
```bash
chmod +x tools/mds_node_init.sh
```

**Permission denied:**
```bash
sudo ./tools/mds_node_init.sh
```

**Check installation state:**
```bash
cat /var/lib/mds/init_state.json | jq
```

## Next Steps

1. Confirm MAVLink routing mode (`--mavlink-auto`, explicit headless flags, or intentional manual mode)
2. Set up WiFi manager if using wireless networks
3. Test drone connectivity with the GCS
4. Run first system test

## Related Documentation

- [CLI Reference](mds-init-cli-reference.md) - All command-line options
- [Headless Automation](headless-automation.md) - Fleet provisioning
- [Troubleshooting](mds-init-troubleshooting.md) - Common issues
- [Service Architecture](raspberry-pi-services.md) - Systemd services

---

**Version:** 5.5 | **Last Updated:** 2026-05-17
