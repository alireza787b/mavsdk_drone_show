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
wifi-manager.service ───────────────────► LED: BLUE (network init)
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

### 2. wifi-manager.service

**Purpose:** Establish WiFi network connection

**Location:** `tools/wifi-manager/wifi-manager.service`

**Key Configuration:**
- Type: simple
- Runs as root (for nmcli access)
- Has 60-second timeout to prevent boot hang
- Runs BEFORE network-online.target (it establishes the network)

**Configuration File:** `tools/wifi-manager/known_networks.conf`

### 3. git_sync_mds.service

**Purpose:** Synchronize code from git repository

**Location:** `tools/git_sync_mds/git_sync_mds.service`

**Key Configuration:**
- Type: oneshot with RemainAfterExit=yes
- 10-minute timeout for slow networks
- Runs as droneshow user
- Automatically detects and updates service files after pull
- Checks and updates pip requirements if changed

**Script:** `tools/update_repo_ssh.sh`

### 4. mavlink-router.service

**Purpose:** Route MAVLink from flight controller to applications

**Location:** Created by mavlink-anywhere (NOT in this repo)

**Note:** This service is managed by the mavlink-anywhere repository. It must be installed and configured separately using:
```bash
cd ~/mavlink-anywhere
sudo ./install_mavlink_router.sh
sudo ./configure_mavlink_router.sh
```

By default, current `mavlink-anywhere` installs a GCS listener on `14550/udp`, so QGroundControl normally connects to the Pi/CM4 IP on that port. If you are using the Holybro Pixhawk RPi CM4 baseboard, match PX4 `TELEM2` at `921600` on the FC side.

If you expose the web dashboard to the network, keep that explicit as well:

```bash
sudo ./configure_mavlink_router.sh --install-dashboard \
  --dashboard-listen 0.0.0.0:9070
```

### 5. coordinator.service

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
│  LAYER 1: GLOBAL DEFAULTS (in repo, git-synced)            │
│  └── src/params.py                                         │
│      Change here → ALL drones updated via git sync          │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  LAYER 2: LOCAL OVERRIDES (outside repo, preserved)        │
│  └── /etc/mds/local.env                                    │
│      Drone-specific settings (HW_ID, custom GCS IP, etc.)  │
│      NOT overwritten by git sync                           │
└─────────────────────────────────────────────────────────────┘
```

### Fleet-Wide Changes

To change ALL drones:
1. Edit `src/params.py`
2. `git commit && git push`
3. All drones auto-sync on next boot (or run `./tools/recovery.sh force-sync`)

### Per-Drone Changes

To change ONE drone:
1. SSH to the drone
2. Edit `/etc/mds/local.env`
3. `sudo systemctl restart coordinator`

### Local Configuration File

Location: `/etc/mds/local.env`

Template: `tools/local.env.template`

Example:
```bash
# Hardware ID (required)
MDS_HW_ID=42

# Override GCS IP for this drone only
MDS_GCS_IP=192.168.1.100

# Enable debug logging
MDS_LOG_LEVEL=DEBUG
```

## Installing Services

The services are installed by `tools/mds_node_init.sh` (the enterprise initialization script). To manually install:

```bash
# Copy service files
sudo cp tools/coordinator.service /etc/systemd/system/
sudo cp tools/git_sync_mds/git_sync_mds.service /etc/systemd/system/
sudo cp tools/wifi-manager/wifi-manager.service /etc/systemd/system/
sudo cp tools/led_indicator/led_indicator.service /etc/systemd/system/

# Reload and enable
sudo systemctl daemon-reload
sudo systemctl enable coordinator git_sync_mds wifi-manager led_indicator
```

## Troubleshooting

### Check Service Status

```bash
# Quick status
./tools/recovery.sh status

# Detailed status
systemctl status coordinator
systemctl status git_sync_mds
systemctl status wifi-manager
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

**WiFi not connecting:**
- Check known_networks.conf: `cat tools/wifi-manager/known_networks.conf`
- View WiFi logs: `journalctl -u wifi-manager`
- Reset network: `./tools/recovery.sh reset-net`

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
- **wifi-manager.service:** Runs as root (required for nmcli) but with timeout
- **git_sync_mds.service:** Runs as droneshow user, no elevated privileges
- **led_indicator.service:** Minimal capabilities (CAP_SYS_RAWIO for GPIO only)

## Service Dependencies

```
coordinator
├── Wants: network-online.target
├── Wants: mavlink-router.service
├── Wants: git_sync_mds.service
└── After: all above

git_sync_mds
├── Wants: network-online.target
└── After: wifi-manager.service

wifi-manager
├── After: basic.target
└── Before: network-online.target

led_indicator
├── After: sysinit.target
└── Before: basic.target
```

Note: `Wants=` is used instead of `Requires=` for graceful degradation. Services will start even if dependencies fail.
