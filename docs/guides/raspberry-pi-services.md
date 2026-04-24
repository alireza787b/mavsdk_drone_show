# Companion Node Service Architecture

This guide documents the systemd service architecture for MDS drones running on companion-computer hardware.

## Service Boot Order

```
sysinit.target
    │
    ▼
led_indicator.service ──────────────────► LED: RED (boot started)
    │
    ▼
basic.target
    │
    ▼
network-online.target
    │
    ▼
git_sync_mds.service ───────────────────► LED: CYAN (syncing)
    │                                     │
    │  Success: LED GREEN flash           │
    │  Failure: LED YELLOW (cached)       │
    ▼                                     │
mavlink-router.service (from mavlink-anywhere)
    │
    ▼
coordinator.service ────────────────────► LED: WHITE → GREEN/PURPLE
```

## Services Overview

### 1. led_indicator.service

**Purpose:** Set initial boot LED to RED

**Location:** `tools/led_indicator/led_indicator.service`

**Key Configuration:**
- Type: oneshot (runs once at boot)
- Runs early (before basic.target)
- Sets LED to BOOT_STARTED state

### 2. git_sync_mds.service

**Purpose:** Synchronize code from git repository

**Location:** `tools/git_sync_mds/git_sync_mds.service`

**Key Configuration:**
- Type: oneshot with RemainAfterExit=yes
- 10-minute timeout for slow networks
- Runs as droneshow user
- Automatically detects and updates service files after pull
- Validates rendered service units before installing them
- Reconciles the managed `mavlink-anywhere` runtime when the node keeps
  `MDS_MAVLINK_MANAGEMENT_MODE=managed`
- Checks and updates pip requirements if changed
- Schedules a delayed coordinator restart only when the synced change affects
  the live runtime

**Script:** `tools/update_repo_ssh.sh`

**Safe post-sync behavior:**
- changed `git_sync_mds.service` unit:
  - install if valid, reload systemd, apply on next sync invocation
- changed `led_indicator.service` unit:
  - install if valid, reload systemd, apply on next boot
- changed coordinator runtime code / unit / requirements:
  - queue a delayed coordinator restart so the pull converges to the new runtime
  - do not restart every service blindly

### 3. mavlink-router.service

**Purpose:** Route MAVLink from flight controller to applications

**Location:** Created by mavlink-anywhere (NOT in this repo)

**Note:** In the normal managed path, `tools/mds_node_init.sh --mavlink-auto` installs and configures this service for you. Manual `mavlink-anywhere` setup remains supported when you intentionally want to own the routing profile yourself:
```bash
cd ~/mavlink-anywhere
sudo ./install_mavlink_router.sh
sudo ./configure_mavlink_router.sh
```

By default, current `mavlink-anywhere` installs a GCS listener on `14550/udp`, so QGroundControl normally connects to the node / CM4 IP on that port. If you are using the Holybro Pixhawk RPi CM4 baseboard, match PX4 `TELEM2` at `921600` on the FC side.

If you expose the web dashboard to the network, keep that explicit as well:

```bash
sudo ./configure_mavlink_router.sh --install-dashboard \
  --dashboard-listen 0.0.0.0:9070
```

### 4. coordinator.service

**Purpose:** Main drone swarm coordination application

**Location:** `tools/coordinator.service`

**Key Configuration:**
- Type: simple
- Runs as droneshow user
- Depends on git_sync_mds (soft dependency with Wants=)
- Has restart limits (5 restarts per 10 minutes)
- Security hardened (reduced capabilities, PrivateTmp, NoNewPrivileges)
- Resource limits (512MB memory, 65536 file descriptors)

## Configuration Management

### Layered Configuration Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 1: DEPLOYMENT DEFAULTS (in repo, git-synced)        │
│  └── deployment/defaults.env                               │
│      Repo/branch/channel/tool defaults for the fleet       │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  LAYER 2: FLEET DESIRED STATE (in repo, git-synced)        │
│  └── config.json / swarm.json / optional tool profiles     │
│      Fleet membership, swarm topology, repo-owned profiles │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  LAYER 3: LOCAL OVERRIDES (outside repo, preserved)        │
│  └── /etc/mds/local.env                                    │
│      Node identity, host-specific overrides, secret paths  │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  LAYER 4: RUNTIME FALLBACK POLICY                          │
│  └── src/params.py                                         │
│      Last-resort defaults only, not the normal config UI   │
└─────────────────────────────────────────────────────────────┘
```

### Source Of Truth

Use these ownership rules:

1. `config.json` / `swarm.json`
   Fleet membership and swarm topology on GCS.

2. `deployment/defaults.env`
   Repo-owned deployment defaults for repo/branch/GCS/connectivity selection.

3. `/etc/mds/local.env`
   Per-node runtime overrides such as `MDS_HW_ID`, `MDS_GCS_IP`,
   `MDS_CONNECTIVITY_BACKEND`, optional Smart Wi-Fi Manager settings, and
   managed MAVLink Anywhere ownership settings.

4. `src/params.py`
   Runtime fallback policy only. Do not treat it as the normal customization layer.

### Fleet-Wide Changes

To change the real fleet manifest:
1. Edit `config.json` / `swarm.json` on GCS, or use the dashboard / Fleet Enrollment workflow
2. `git commit && git push` if auto-push is disabled
3. Sync the affected nodes so their local repo state matches the GCS manifest

### Per-Node Runtime Changes

To change one companion computer's runtime routing or identity:
1. SSH to the node
2. Edit `/etc/mds/local.env`
3. `sudo systemctl restart coordinator`
4. If connectivity settings changed: `sudo ./tools/reconcile_connectivity.sh apply --force`
5. If managed MAVLink Anywhere ownership changed:
   `sudo ./tools/reconcile_mavlink_runtime.sh apply --force`

Note:
- ordinary git-synced runtime code changes no longer require a separate manual
  `systemctl restart coordinator` just to pick up the new revision
- host-local env changes still do require an explicit restart or re-apply step

### Local Configuration File

Location: `/etc/mds/local.env`

Template: `tools/local.env.template`

Example:
```bash
# Hardware ID (required)
MDS_HW_ID=42

# Override GCS IP for this drone only
MDS_GCS_IP=192.168.1.100

# Keep mavlink-anywhere managed, but pin this node to a specific release
MDS_MAVLINK_MANAGEMENT_MODE=managed
MDS_MAVLINK_ANYWHERE_REF=v3.0.8

# Enable debug logging
MDS_LOG_LEVEL=DEBUG
```

## Installing Services

The services are installed by `tools/mds_node_init.sh` (the enterprise initialization script). To manually install:

```bash
# Copy core MDS service files
sudo cp tools/coordinator.service /etc/systemd/system/
sudo cp tools/git_sync_mds/git_sync_mds.service /etc/systemd/system/
sudo cp tools/led_indicator/led_indicator.service /etc/systemd/system/

# Reload and enable
sudo systemctl daemon-reload
sudo systemctl enable coordinator git_sync_mds led_indicator
```

If you want an optional managed Wi-Fi backend, install the external public tool:

```bash
git clone https://github.com/alireza787b/smart-wifi-manager.git
cd smart-wifi-manager
sudo ./install.sh --dashboard-listen 0.0.0.0:9080
sudo ./configure_smart_wifi_manager.sh
```

## Troubleshooting

### Check Service Status

```bash
# Quick status
./tools/recovery.sh status

# Detailed status
systemctl status coordinator
systemctl status git_sync_mds
systemctl status smart-wifi-manager   # only if selected
```

### View Logs

```bash
# Recent logs from all services
./tools/recovery.sh logs

# Specific service logs
journalctl -u coordinator -f
journalctl -u git_sync_mds --since "10 minutes ago"
```

### Common Issues

**Coordinator won't start:**
- Check `journalctl -u coordinator`
- Verify venv exists: `ls -la ~/mavsdk_drone_show/venv/bin/python`
- Check config.json exists

**Git sync fails:**
- Check network: `ping github.com`
- Check SSH keys: `ssh -T git@github.com`
- Force retry: `./tools/recovery.sh force-sync`

**Optional Smart Wi-Fi Manager not converging:**
- Check status: `sudo /opt/smart-wifi-manager/configure_smart_wifi_manager.sh --help`
- View logs: `journalctl -u smart-wifi-manager`
- Re-apply node connectivity policy: `sudo ./tools/reconcile_connectivity.sh apply --force`

**Managed mavlink-anywhere not converging:**
- Check status: `sudo ./tools/reconcile_mavlink_runtime.sh status`
- Re-apply managed runtime ownership: `sudo ./tools/reconcile_mavlink_runtime.sh apply --force`
- If `/etc/mavlink-router/main.conf` is missing, rerun bootstrap or explicitly
  reconfigure the node's router profile with the correct UART / UDP input

**LED not working:**
- Test LED: `./tools/recovery.sh led-test`
- Check GPIO permissions
- Verify LED library: `pip show rpi-ws281x`

## Recovery Tool

Use `./tools/recovery.sh` for diagnostics and recovery:

```bash
./tools/recovery.sh status      # Service status
./tools/recovery.sh health      # Full health check
./tools/recovery.sh logs        # Recent logs
./tools/recovery.sh restart     # Restart coordinator
./tools/recovery.sh force-sync  # Force git sync
./tools/recovery.sh led-test    # Test LED colors
```

## Security Considerations

The services are configured with security best practices:

- **coordinator.service:** Reduced capabilities (no CAP_SYS_BOOT, CAP_SYS_TIME), PrivateTmp, NoNewPrivileges
- **git_sync_mds.service:** Runs as droneshow user, no elevated privileges
- **led_indicator.service:** Minimal capabilities (CAP_SYS_RAWIO for GPIO only)
- **smart-wifi-manager.service:** Optional external connectivity runtime; review its own docs before enabling on a production node

## Service Dependencies

```
coordinator
├── Wants: network-online.target
├── Wants: mavlink-router.service
├── Wants: git_sync_mds.service
└── After: all above

git_sync_mds
├── Wants: network-online.target
└── After: network-online.target

smart-wifi-manager (optional external service)
├── Manages Wi-Fi independently of core MDS services
└── Is reconciled by tools/reconcile_connectivity.sh when selected

led_indicator
├── After: sysinit.target
└── Before: basic.target
```

Note: `Wants=` is used instead of `Requires=` for graceful degradation. Services will start even if dependencies fail.
