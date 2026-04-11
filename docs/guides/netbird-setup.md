# NetBird VPN Setup Guide

**Secure networking for MDS Ground Control Station and drones**

---

## Overview

For drones to communicate with your GCS server over the internet, both the GCS and all drones must be connected to the same VPN network. NetBird provides a secure, easy-to-setup solution for this.

---

## Why NetBird?

- **Zero-trust networking**: Secure peer-to-peer connections
- **Easy setup**: No complex firewall or port forwarding required
- **Cross-platform**: Works on Linux, Windows, macOS, Raspberry Pi
- **Self-hosted option**: Run your own management server
- **Free tier available**: Suitable for small drone fleets

---

## Setup Options

### Option 1: NetBird Cloud (Recommended for Getting Started)

1. **Create an account** at [https://netbird.io](https://netbird.io)

2. **Install NetBird on GCS Server**:
   ```bash
   curl -fsSL https://pkgs.netbird.io/install.sh | sh
   ```

3. **Connect to your network**:
   ```bash
   sudo netbird up
   ```

   Follow the browser prompt to authenticate.

4. **Note your NetBird IP**:
   ```bash
   netbird status
   ```

   Your NetBird IP will look like `100.x.x.x`

### Option 2: Self-Hosted NetBird Server

For production deployments or if you need full control:

1. **Deploy NetBird Management Server**:
   See [NetBird self-hosting guide](https://docs.netbird.io/selfhosted/selfhosted-guide)

2. **Configure your GCS and drones** to connect to your self-hosted server

### Option 3: NetBird on GCS Machine

You can run the NetBird management server on the same machine as your GCS:

1. Follow the [Docker deployment guide](https://docs.netbird.io/selfhosted/selfhosted-guide#quick-start-with-zitadel)

2. This creates an all-in-one server for small deployments

---

## Configuring Drones

After your GCS is connected to NetBird:

1. **Install NetBird on each Raspberry Pi drone**:
   ```bash
   curl -fsSL https://pkgs.netbird.io/install.sh | sh
   sudo netbird up
   ```

2. **Configure the node runtime to use the GCS overlay IP**:

   Preferred source of truth:
   - `/etc/mds/local.env` on the node
   - `/etc/mds/gcs.env` on GCS

   Example:
   ```bash
   sudo sed -i 's/^MDS_GCS_IP=.*/MDS_GCS_IP=100.x.x.x/' /etc/mds/local.env
   ```

   `src/params.py` is fallback-only. Do not use it as the normal deployment customization path.

3. **Verify connectivity**:
   ```bash
   ping 100.x.x.x  # GCS NetBird IP
   ```

---

## Network Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           NetBird Network                                   │
│                        (100.x.x.x subnet)                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐      │
│  │   GCS Server    │     │    Drone 1      │     │    Drone 2      │      │
│  │  100.64.0.1     │◄───►│  100.64.0.2     │◄───►│  100.64.0.3     │      │
│  │                 │     │                 │     │                 │      │
│  │  - Dashboard    │     │  - MAVLink      │     │  - MAVLink      │      │
│  │  - GCS API      │     │  - Telemetry    │     │  - Telemetry    │      │
│  │  - Git Server   │     │  - Commands     │     │  - Commands     │      │
│  └─────────────────┘     └─────────────────┘     └─────────────────┘      │
│                                                                             │
│  Communication over encrypted WireGuard tunnels                            │
│  No port forwarding required                                               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Ports Used Over VPN

Once connected via NetBird, these ports are used for communication:

| Port | Protocol | Direction | Purpose |
|------|----------|-----------|---------|
| 5000 | TCP | GCS←Drone | GCS API Server |
| 14550 | UDP | GCS←Drone | MAVLink telemetry |
| 7070 | TCP | GCS←Drone | Drone status API |

---

## Troubleshooting

### Connection Issues

**Check NetBird status**:
```bash
netbird status
```

**Restart NetBird**:
```bash
sudo netbird down && sudo netbird up
```

**Check peer connections**:
```bash
netbird status --detail
```

### Firewall Issues

NetBird uses WireGuard which requires UDP port 51820. Ensure this is allowed:

```bash
# On GCS server (if UFW is active)
sudo ufw allow 51820/udp comment "NetBird/WireGuard"
```

### DNS Resolution

If using hostnames, ensure NetBird DNS is working:

```bash
netbird dns list
```

---

## Security Best Practices

1. **Use access control lists** to restrict which devices can communicate
2. **Enable MFA** on your NetBird dashboard account
3. **Regularly rotate setup keys** for new device enrollments
4. **Monitor connected devices** in the NetBird dashboard
5. **Use separate networks** for testing and production

---

## Alternative VPN Solutions

While NetBird is recommended, other options include:

- **Tailscale**: Similar to NetBird, easy setup
- **ZeroTier**: Another peer-to-peer VPN option
- **WireGuard**: Manual setup, more control
- **OpenVPN**: Traditional VPN, requires more configuration

---

## Resources

- [NetBird Documentation](https://docs.netbird.io)
- [NetBird GitHub](https://github.com/netbirdio/netbird)
- [WireGuard Protocol](https://www.wireguard.com)

---

**Last Updated:** February 2026 (Version 4.4.0)
