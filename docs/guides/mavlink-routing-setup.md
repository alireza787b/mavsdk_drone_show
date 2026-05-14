# MAVLink Routing Setup Guide

## Overview

mavsdk_drone_show requires **external MAVLink routing** via mavlink-anywhere or a custom router setup. The application no longer manages MAVLink routing internally - this provides better flexibility and allows multiple applications to share the MAVLink data stream.

## Architecture

### SITL/Docker Mode

In SITL mode, PX4 automatically streams MAVLink on two ports. MAVSDK connects directly to PX4, while other consumers receive data via the router:

```
                         PX4 SITL
                           │
          ┌────────────────┴────────────────┐
          │                                 │
          ▼                                 ▼
    Port 14540                        Port 14550
    (MAVSDK direct)                   (GCS output)
          │                                 │
          ▼                                 ▼
    ┌─────────────┐                 ┌───────────────┐
    │   MAVSDK    │                 │mavlink-routerd│
    │ coordinator │                 └───────┬───────┘
    └─────────────┘                         │
                           ┌────────────────┼────────────────┐
                           │                │                │
                           ▼                ▼                ▼
                    ┌───────────┐    ┌───────────┐    ┌───────────┐
                    │LocalMavlink│   │mavlink2rest│   │Remote GCS │
                    │  :12550   │    │  :14569   │    │  :24550   │
                    │(pymavlink)│    │(REST API) │    │   (QGC)   │
                    └───────────┘    └───────────┘    └───────────┘
```

### Real Hardware Mode

For real hardware, all MAVLink traffic flows through the router from the serial port:

```
                    Flight Controller (Pixhawk/PX4)
                              │
                         Serial UART
                              │
                    ┌─────────┴─────────┐
                    │  mavlink-routerd  │
                    └─────────┬─────────┘
                              │
     ┌────────────────────────┼────────────────────────┐
     │                        │                        │
     ▼                        ▼                        ▼
┌─────────────┐      ┌─────────────────┐      ┌─────────────┐
│   MAVSDK    │      │  mavlink2rest   │      │     GCS     │
│ :14540/UDP  │      │   :14569/UDP    │      │ :24550/UDP  │
└─────────────┘      └─────────────────┘      └─────────────┘
     │
     ▼
┌─────────────────────┐
│LocalMavlinkController│
│    :12550/UDP       │
└─────────────────────┘
```

## Port Reference

| Port  | Service               | Direction | Description                          |
|-------|-----------------------|-----------|--------------------------------------|
| 14540 | MAVSDK                | Local     | Direct PX4 connection (SITL) or routed (real HW) |
| 14550 | PX4 GCS Output / GCS Listen | Local / Network | PX4 SITL router input, or the default device-side GCS listener on real hardware |
| 12550 | LocalMavlinkController| Local     | pymavlink telemetry monitoring       |
| 14569 | mavlink2rest target   | Local     | Routed local endpoint for an optional mavlink2rest process |
| 24550 | Remote GCS Push       | Network   | Optional push-mode QGroundControl endpoint over VPN/WAN |
| 34550 | Router Listen         | Network   | Legacy server-side listen port       |

## Setup Options

### Option A: SITL/Docker Mode (Automatic)

For SITL containers, MAVLink routing is handled automatically by `startup_sitl.sh` which calls `tools/run_mavlink_router.sh`. No manual setup is required.

**Key points for SITL:**
- Docker SITL now standardizes on headless PX4 Gazebo Harmonic via `HEADLESS=1 make px4_sitl gz_x500`
- PX4 SITL automatically streams to port 14540 for MAVSDK and to a GCS UDP port that is usually 14550
- MAVSDK connects **directly** to PX4 on port 14540 (no routing needed)
- `startup_sitl.sh` expects the PX4 GCS UDP port to be `14550` and logs that expectation during startup
- If runtime inspection shows a different live PX4 GCS port, startup logs a warning and falls back to the detected port so mixed/legacy SITL images still keep telemetry alive
- Router takes the validated PX4 GCS port and distributes it to: 12550, 14569, and GCS_IP:24550
- The stock SITL workflow does **not** auto-start `mavlink2rest`; `14569` is simply the routed local endpoint you would use if you add that process yourself
- Remote GCS connects on port **24550** (not 14550)

If runtime inspection fails entirely, SITL falls back to `14550`. Advanced users can override detection explicitly:

```bash
export MDS_PX4_GCS_PORT=14550
```

### Option B: Real Hardware (Raspberry Pi) - Manual Setup

For real hardware deployment, you need to set up mavlink-anywhere as a systemd service.

If you are using the normal managed MDS bootstrap path, treat this document as
the ownership model and troubleshooting reference. The actual tool checkout/ref
should come from:

- fleet defaults in `deployment/defaults.env`
- optional node override in `/etc/mds/local.env`

Current sidecar policy defaults include:

- `MDS_DEFAULT_MAVLINK_MANAGEMENT_MODE=local`
- `MDS_DEFAULT_MAVLINK_ANYWHERE_REF=v3.0.10`
- `MDS_DEFAULT_MAVLINK_ANYWHERE_INSTALL_DIR=/opt/mavlink-anywhere`

Use Fleet Ops MAVLink to inspect profile drift and to dry-run/apply endpoint
policy baselines. The default `local` mode keeps node-local MAVLink Anywhere
dashboard/CLI settings authoritative until a fleet endpoint baseline is
explicitly configured.

#### Prerequisites

- Raspberry Pi with serial UART enabled
- Serial console DISABLED (required for MAVLink on /dev/ttyS0)
- Flight controller connected via serial cable

#### Step 1: Enable UART and Disable Serial Console

```bash
sudo raspi-config
# Interface Options → Serial Port →
#   "Login shell over serial?" → NO
#   "Enable serial hardware?" → YES
# Reboot after making changes
```

#### Step 2: Install mavlink-anywhere

```bash
cd ~
git clone https://github.com/alireza787b/mavlink-anywhere.git
cd mavlink-anywhere
git checkout v3.0.10
chmod +x install_mavlink_router.sh
sudo ./install_mavlink_router.sh
```

**Note**: This builds mavlink-router from source. Takes approximately 10 minutes on Raspberry Pi.

#### Step 3: Configure Routing Endpoints

```bash
sudo ./configure_mavlink_router.sh
```

When prompted, enter:
- **UART device**: `/dev/ttyS0` (Pi Zero/3/4) or `/dev/ttyAMA0` (older Pi)
- **Baud rate**: must match the FC MAVLink serial port setting
- **UDP endpoints**: `127.0.0.1:14540 127.0.0.1:14569 127.0.0.1:12550`

`mavlink-anywhere` automatically adds a default **server-mode** listener on `0.0.0.0:14550` for ground stations. This is the normal same-LAN / same-VPN workflow:

- QGroundControl creates a UDP link to `<device-ip>:14550`
- QGC sends first, so `mavlink-router` learns the active remote peer
- No device-side pre-configuration of the GCS IP is required

If you also want an explicit push endpoint to a remote VPN GCS, add it as an extra UDP endpoint:

```text
127.0.0.1:14540 127.0.0.1:14569 127.0.0.1:12550 192.168.1.100:24550
```

**Important**: Always include the three local service endpoints:
- `127.0.0.1:14540` - MAVSDK (coordinator.py)
- `127.0.0.1:14569` - mavlink2rest
- `127.0.0.1:12550` - LocalMavlinkController (pymavlink telemetry)

Add `GCS_IP:24550` only when you intentionally want device-side push to a known remote GCS.

### RTK / QGroundControl Multi-Vehicle Notes

PX4 RTK corrections are transported over MAVLink as `GPS_RTCM_DATA`.
QGroundControl reads the base-station RTCM stream and sends those messages over
the active vehicle link. PX4 then forwards the RTCM payload to the rover GPS
over the existing GPS data path; no dedicated RTCM serial channel is required on
the autopilot side once `GPS_RTCM_DATA` reaches PX4.

For a two-drone hardware test:

- each flight controller must have a unique `MAV_SYS_ID` (`1` for HW1, `2` for
  HW2 is the simple MDS-aligned convention)
- `MAV_SYS_ID` is reboot-required in PX4, so apply it before field testing
- use MAVLink 2 end-to-end where possible; PX4 documentation notes RTK uplink
  is roughly 300 B/s with MAVLink 2 and higher with MAVLink 1
- server-mode `14550` is enough when QGroundControl connects to each node IP
  and sends first
- add explicit `GCS_IP:24550` push endpoints only when you want each node to
  push to a known GCS IP; do not add duplicate push endpoints blindly
- if RTK does not converge, verify that QGC sees both vehicles as distinct
  system IDs and that RTCM traffic is visible on the MAVLink route

References:

- PX4 RTK GNSS/GPS integration:
  https://docs.px4.io/v1.15/en/advanced/rtk_gps.html
- PX4 `MAV_SYS_ID` parameter:
  https://docs.px4.io/v1.15/en/advanced_config/parameter_reference.html#MAV_SYS_ID

#### Holybro Pixhawk RPi CM4 Baseboard Note

For the Holybro Pixhawk RPi CM4 baseboard, official Holybro/PX4 docs state that the CM4 is internally connected to the flight controller through **TELEM2**, and PX4 should use:

- `MAV_1_CONFIG = TELEM2 (102)`
- `MAV_1_MODE = Onboard (2)`
- `SER_TEL2_BAUD = 921600`

On the CM4 side, the matching serial device is typically `/dev/serial0` or `/dev/ttyS0` at **921600**.

#### Step 4: Enable and Start Service

```bash
sudo systemctl daemon-reload
sudo systemctl enable mavlink-router
sudo systemctl start mavlink-router
```

#### Step 5: Verify Service is Running

```bash
sudo systemctl status mavlink-router
# Should show "active (running)"

# Check logs for MAVLink activity
sudo journalctl -u mavlink-router -f
```

## Manual Configuration (Alternative)

If you prefer manual configuration, create `/etc/mavlink-router/main.conf`.
The example below matches the Holybro Pixhawk RPi CM4 baseboard serial path (`TELEM2`/`921600`):

```ini
[General]
TcpServerPort=5760
ReportStats=false

[UartEndpoint uart]
Device=/dev/ttyS0
Baud=921600

[UdpEndpoint gcs_listen]
Mode=server
Address=0.0.0.0
Port=14550

[UdpEndpoint mavsdk]
Mode=normal
Address=127.0.0.1
Port=14540

[UdpEndpoint local_mavlink]
Mode=normal
Address=127.0.0.1
Port=12550

[UdpEndpoint mavlink2rest]
Mode=normal
Address=127.0.0.1
Port=14569

[UdpEndpoint gcs]
Mode=normal
Address=192.168.1.100
Port=24550
```

Replace `192.168.1.100` with your actual remote GCS IP address only if you want push-mode delivery. For the built-in listener workflow, QGC should connect to the device IP on port **14550**.

### Dashboard Exposure

The `mavlink-anywhere` dashboard binds to `127.0.0.1:9070` by default. If you want LAN/VPN browser access, expose it explicitly:

```bash
sudo ./configure_mavlink_router.sh --install-dashboard \
  --dashboard-listen 0.0.0.0:9070
```

If the node is using Fleet Ops ownership for `mavlink-anywhere`, keep the
runtime checkout/ref inside MDS defaults and use the reconcile helper after a
local override change:

```bash
sudo ./tools/reconcile_mavlink_runtime.sh status
sudo ./tools/reconcile_mavlink_runtime.sh apply --force
```

Fleet Ops MAVLink profile reconcile preserves hardware source settings by
default: serial device, baud, UDP input source, PX4 port, and board-specific
router constraints are node overlays, not fleet endpoint policy.

## Troubleshooting

### No MAVLink Data

1. **Check serial cable connection** - Ensure TX/RX are crossed correctly
2. **Verify baud rate** - Must match the PX4 MAVLink serial port. Holybro Pixhawk RPi CM4 baseboard typically uses `TELEM2` at `921600`
3. **Check UART permissions** - `ls -l /dev/ttyS0` should show `crw-rw----`
4. **Check QGC mode** - for the default listener workflow, QGC must point to `<device-ip>:14550`

### Permission Denied on Serial Port

Add user to dialout group:
```bash
sudo usermod -a -G dialout $USER
# Log out and back in for changes to take effect
```

### Service Won't Start

Check configuration syntax:
```bash
cat /etc/mavlink-router/main.conf
mavlink-routerd --conf /etc/mavlink-router/main.conf
```

### Port Already in Use

Check for conflicting processes:
```bash
sudo netstat -tulpn | grep -E "14540|14550|14569|12550|24550"
```

### QGroundControl Does Not Connect Even on the Same LAN

This is usually not a firewall problem by itself. `mavlink-router` UDP **server mode** can only send replies after the remote peer sends first.

Use a manual QGC UDP link pointed at `<device-ip>:14550`. Do not expect a passive listener on the desktop alone to be enough.

### coordinator.py Can't Connect to MAVSDK

1. Verify mavlink-router is running: `systemctl status mavlink-router`
2. Check port 14540 is receiving data: `sudo tcpdump -i lo udp port 14540`
3. Ensure `Params.mavsdk_port` matches the router config (default: 14540)

## Migration Notes

Prior to this change, mavsdk_drone_show used an internal `MavlinkManager` class that spawned `mavlink-routerd` as a subprocess. This was removed because:

1. **Conflict potential** - Multiple apps fighting for serial port access
2. **No sharing** - Only one consumer per endpoint
3. **Tight coupling** - Application responsible for system-level routing

With external routing:
1. **Multiple consumers** - QGC, mavlink2rest, custom tools can all receive data
2. **System-level config** - Persists across app restarts
3. **Separation of concerns** - Routing is infrastructure, not app logic

## See Also

- [mavlink-anywhere GitHub](https://github.com/alireza787b/mavlink-anywhere)
- [mavlink-router Documentation](https://github.com/mavlink-router/mavlink-router)
- [SITL Comprehensive Guide](./sitl-comprehensive.md)
