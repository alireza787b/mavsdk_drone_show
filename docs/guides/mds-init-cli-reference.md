# MDS Init CLI Reference

Complete reference for all command-line arguments and environment variables for `mds_node_init.sh`, the companion-node bootstrap entrypoint.

## Synopsis

```bash
sudo ./tools/mds_node_init.sh [OPTIONS]
```

## Required Parameters

These parameters are required but can be provided interactively if omitted:

| Option | Description |
|--------|-------------|
| `-d, --drone-id ID` | Hardware ID for this drone (1-999) |

## Repository Options

| Option | Description | Default |
|--------|-------------|---------|
| `-r, --repo-url URL` | Git repository URL | `git@github.com:alireza787b/mavsdk_drone_show.git` |
| `-b, --branch BRANCH` | Git branch to use | `main-candidate` |
| `--fork OWNER[/REPO]` | Use GitHub fork shorthand (`OWNER/mavsdk_drone_show`) or explicit owner/repo path | - |
| `--https` | Use HTTPS instead of SSH for git operations | SSH |

## Optional Components

| Option | Description |
|--------|-------------|
| `--netbird-key KEY` | Netbird VPN setup key |
| `--netbird-url URL` | Netbird management URL |
| `--static-ip IP/CIDR` | Static IP address (e.g., `192.168.1.42/24`) |
| `--gateway IP` | Gateway for static IP |
| `--gcs-ip IP` | Override GCS IP address |
| `--gcs-api-url URL` | Override GCS API base URL used for candidate announce |

## MAVSDK Options

| Option | Description | Default |
|--------|-------------|---------|
| `--mavsdk-version VERSION` | Specific MAVSDK version (e.g., `v3.15.0`) | Auto-detect latest |
| `--mavsdk-url URL` | Direct URL to MAVSDK binary (overrides version) | - |

## MAVLink Routing Options

| Option | Description | Default |
|--------|-------------|---------|
| `--mavlink-auto` | Managed routing path with recommended defaults: UART auto-detect, standard local fanout, optional GCS push when `--gcs-ip` is set | off |
| `--mavlink-skip` | Skip MAVLink routing setup entirely | off |
| `--mavlink-uart DEVICE` | Explicit FC-facing serial device for headless UART setup | auto-detect in managed mode |
| `--mavlink-baud RATE` | Serial baud rate for the MAVLink input | `57600` |
| `--mavlink-endpoints LIST` | Comma-separated routed outputs | `127.0.0.1:14540,127.0.0.1:14569,127.0.0.1:12550` |
| `--mavlink-input TYPE` | MAVLink input source for headless config: `uart` or `udp` | `uart` |
| `--mavlink-input-port PORT` | UDP input port when `--mavlink-input udp` is used | `14550` |

## Skip Flags

Use these flags to skip specific phases:

| Flag | Description |
|------|-------------|
| `--skip-firewall` | Skip UFW firewall configuration |
| `--skip-netbird` | Skip Netbird VPN setup |
| `--skip-ntp` | Skip NTP time synchronization |
| `--skip-services` | Skip systemd service installation |
| `--skip-mavsdk` | Skip MAVSDK binary download |
| `--skip-venv` | Skip Python virtual environment setup |

## Control Options

| Option | Description |
|--------|-------------|
| `-y, --yes` | Non-interactive mode (use defaults, no prompts) |
| `--dry-run` | Show what would be done without making changes |
| `--report-json PATH` | Write a machine-readable bootstrap report to `PATH` (`-` prints JSON to stdout) |
| `--announce-report-json PATH` | Write a machine-readable candidate-announce report to `PATH` (`-` prints JSON to stdout) |
| `--announce-timeout SEC` | Candidate-announce HTTP timeout in seconds |
| `--resume` | Resume from last checkpoint |
| `--force` | Force re-run all phases (ignore state) |
| `-v, --verbose` | Verbose output |
| `--debug` | Debug output (very verbose) |
| `-h, --help` | Show help message |

## Environment Variables

The script respects these environment variables (override CLI defaults):

| Variable | Purpose | Default |
|----------|---------|---------|
| `MDS_REPO_URL` | Override repository URL | CLI or default |
| `MDS_BRANCH` | Override git branch | CLI or default |
| `MDS_GCS_IP` | Override node-local GCS control IP | `/etc/mds/local.env`, then environment, then `src/params.py` fallback |
| `MDS_GCS_API_BASE_URL` | Override candidate-announce API base URL | Explicit value, otherwise derived from `MDS_GCS_IP` |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error or phase failure |

## Usage Examples

### Basic Setup

Interactive mode with prompts:
```bash
sudo ./tools/mds_node_init.sh
```

Non-interactive with drone ID:
```bash
sudo ./tools/mds_node_init.sh -d 1 -y
```

### Repository Configuration

Using HTTPS (no SSH key needed):
```bash
sudo ./tools/mds_node_init.sh -d 1 --https -y
```

Using your own fork (simple method):
```bash
sudo ./tools/mds_node_init.sh -d 1 --fork yourusername -y
```

Using a customer org/private repo path:
```bash
sudo ./tools/mds_node_init.sh -d 1 --fork yourorg/customer-mds -y
```

Custom repository and branch:
```bash
sudo ./tools/mds_node_init.sh -d 1 \
    -r git@github.com:yourorg/customer-mds.git \
    -b customer-demo \
    -y
```

### Network Configuration

With static IP:
```bash
sudo ./tools/mds_node_init.sh -d 5 \
    --static-ip 192.168.1.105/24 \
    --gateway 192.168.1.1 \
    -y
```

With Netbird VPN:
```bash
sudo ./tools/mds_node_init.sh -d 5 \
    --netbird-key "nkey-XXXXX" \
    -y
```

Full network setup:
```bash
sudo ./tools/mds_node_init.sh -d 5 \
    --netbird-key "nkey-XXXXX" \
    --static-ip 192.168.1.105/24 \
    --gateway 192.168.1.1 \
    --gcs-ip 192.168.1.100 \
    -y
```

Explicit candidate-announce API URL:
```bash
sudo ./tools/mds_node_init.sh -d 5 \
    --gcs-api-url https://gcs.example/api \
    --announce-report-json /var/lib/mds/announce-report.json \
    -y
```

### MAVSDK Configuration

Specific MAVSDK version:
```bash
sudo ./tools/mds_node_init.sh -d 1 \
    --mavsdk-version v3.15.0 \
    -y
```

Direct MAVSDK URL:
```bash
sudo ./tools/mds_node_init.sh -d 1 \
    --mavsdk-url "https://example.com/mavsdk_server" \
    -y
```

### MAVLink Routing

Managed defaults:
```bash
sudo ./tools/mds_node_init.sh -d 1 --mavlink-auto --gcs-ip 100.96.32.75 -y
```

Headless UART routing:
```bash
sudo ./tools/mds_node_init.sh -d 1 \
    --mavlink-uart /dev/ttyS0 \
    --mavlink-baud 57600 \
    --mavlink-endpoints "127.0.0.1:14540,127.0.0.1:14569,127.0.0.1:12550" \
    -y
```

Headless UDP-input routing:
```bash
sudo ./tools/mds_node_init.sh -d 1 \
    --mavlink-input udp \
    --mavlink-input-port 14550 \
    --mavlink-endpoints "127.0.0.1:14540,127.0.0.1:14569,127.0.0.1:12550" \
    -y
```

Operator note:
- interactive mode presents a guided routing choice
- `--mavlink-auto` does not prompt; it applies the recommended UART-first defaults
- use manual `mavlink-anywhere` only when you intentionally own that routing profile outside MDS bootstrap

### Selective Installation

Skip firewall and NTP:
```bash
sudo ./tools/mds_node_init.sh -d 1 \
    --skip-firewall \
    --skip-ntp \
    -y
```

Only repository and identity (minimal):
```bash
sudo ./tools/mds_node_init.sh -d 1 \
    --skip-firewall \
    --skip-netbird \
    --skip-ntp \
    --skip-services \
    --skip-mavsdk \
    --skip-venv \
    -y
```

### Testing and Debugging

Dry run (preview changes):
```bash
sudo ./tools/mds_node_init.sh -d 1 --dry-run
```

Verbose output:
```bash
sudo ./tools/mds_node_init.sh -d 1 -v -y
```

Debug output:
```bash
sudo ./tools/mds_node_init.sh -d 1 --debug -y
```

### Recovery

Resume interrupted installation:
```bash
sudo ./tools/mds_node_init.sh --resume
```

Force complete reinstall:
```bash
sudo ./tools/mds_node_init.sh -d 1 --force -y
```

## State Management

The script maintains state in `/var/lib/mds/init_state.json`:

```json
{
  "version": "4.4.0",
  "started_at": "2026-01-24T12:00:00+00:00",
  "drone_id": 1,
  "phases": {
    "prereqs": {"status": "completed", "timestamp": "..."},
    "repository": {"status": "completed", "timestamp": "..."}
  },
  "values": {
    "repo_url": "git@github.com:...",
    "python_version": "3.13.0"
  }
}
```

### View State

```bash
cat /var/lib/mds/init_state.json | jq
```

### Reset State

```bash
sudo rm /var/lib/mds/init_state.json
sudo ./tools/mds_node_init.sh -d 1 -y
```

## Configuration Paths

| Path | Description |
|------|-------------|
| `/etc/mds/local.env` | Per-node runtime overrides |
| `/etc/mds/node_identity.json` | Structured node manifest for automation, enrollment, and diagnostics |

## Candidate Announce Helper

The bootstrap can announce directly to the GCS enrollment registry when a GCS
API URL or `MDS_GCS_IP` is available. You can also re-run that discovery step
later without repeating the whole bootstrap:

```bash
sudo ./tools/mds_node_announce.sh --gcs-api-url http://100.96.32.75:5000
sudo ./tools/mds_node_announce.sh --dry-run --report-json -
```

URL resolution order:

1. `--gcs-api-url`
2. `MDS_GCS_API_BASE_URL`
3. `MDS_GCS_API_BASE_URL` from `/etc/mds/local.env`
4. `MDS_GCS_IP` / `--gcs-ip` with default port `5000`
| `/var/lib/mds/init_state.json` | Installation state |
| `/var/log/mds/mds_init.log` | Installation log |
| `/home/droneshow/mavsdk_drone_show/` | MDS installation directory |
| `/home/droneshow/mavsdk_drone_show/venv/` | Python virtual environment |

## Breaking Changes from v3.x

The following changes affect users upgrading from older versions:

| Change | Migration |
|--------|-----------|
| `raspberry_setup.sh` retired | Use `mds_node_init.sh` instead |
| `--skip-gpio` removed | GPIO always configured |
| `--skip-sudoers` removed | Sudoers always configured |
| `-u/--management-url` renamed | Use `--netbird-url` |
| `--ssh-key-path` removed | Uses standard location |

## Related Documentation

- [Setup Guide](mds-init-setup.md) - Step-by-step instructions
- [Headless Automation](headless-automation.md) - Fleet deployment
- [Troubleshooting](mds-init-troubleshooting.md) - Common issues

## Bootstrap Installer (`install_companion.sh`)

For fresh companion-computer installations, use the bootstrap installer:

```bash
curl -fsSL https://raw.githubusercontent.com/alireza787b/mavsdk_drone_show/main-candidate/tools/install_companion.sh | sudo bash
```

`install_mds_node.sh` remains supported as a compatibility alias.

To emit a machine-readable report for Ansible or an AI agent:

```bash
sudo ./tools/mds_node_init.sh -d 12 --https --report-json /var/lib/mds/bootstrap-report.json -y
```

### Bootstrap-Specific Options

| Option | Description |
|--------|-------------|
| `--branch BRANCH` | Git branch to clone |
| `--repo-url URL` | Use an explicit repository URL |
| `--fork OWNER[/REPO]` | Use GitHub fork shorthand or explicit owner/repo path |
| `-h, --help` | Show bootstrap help |

All other options are passed through to `mds_node_init.sh`.

### Bootstrap Examples

```bash
# Basic installation (interactive)
curl -fsSL ... | sudo bash

# With drone ID
curl -fsSL ... | sudo bash -s -- -d 1 -y

# Using your fork
curl -fsSL ... | sudo bash -s -- --fork yourusername -d 1 -y

# Using a customer org/private repo path
curl -fsSL ... | sudo bash -s -- --fork yourorg/customer-mds -d 1 -y

# Using an explicit repository URL
curl -fsSL ... | sudo bash -s -- --repo-url git@github.com:yourorg/customer-mds.git --branch customer-demo -d 1 -y

# Custom branch with VPN
curl -fsSL ... | sudo bash -s -- --branch develop -d 1 --netbird-key "XXXXX" -y
```

---

**Version:** 4.5.0 | **Last Updated:** April 2026
