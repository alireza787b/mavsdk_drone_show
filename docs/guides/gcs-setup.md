# GCS Server Setup Guide

**Complete guide for setting up the MDS Ground Control Station on Ubuntu/VPS**

---

## Table of Contents

- [Quick Start](#quick-start)
- [Repository Options](#repository-options)
- [Manual Setup](#manual-setup)
- [CLI Reference](#cli-reference)
- [Configuration Files](#configuration-files)
- [Firewall Ports](#firewall-ports)
- [Verification](#verification)
- [Troubleshooting](#troubleshooting)
- [Running the Dashboard](#running-the-dashboard)
- [VPN Networking](#vpn-networking)

---

## Quick Start

### One-Line Installation (Recommended)

The fastest way to set up a GCS server on a fresh Ubuntu VPS:

```bash
curl -fsSL https://raw.githubusercontent.com/alireza787b/mavsdk_drone_show/main-candidate/tools/install_gcs.sh | sudo bash
```

By default the wrapper clones into `~/mavsdk_drone_show` for the invoking user.
Override that wrapper-level default with `MDS_INSTALL_DIR` if your host layout
requires a different checkout path:

```bash
curl -fsSL https://raw.githubusercontent.com/alireza787b/mavsdk_drone_show/main-candidate/tools/install_gcs.sh | \
  sudo env MDS_INSTALL_DIR=/srv/customer-mds bash
```

When you run the wrapper from a local checkout instead of the raw GitHub URL, it
also loads repo defaults from `deployment/defaults.env` before applying any
environment overrides.

This script will:
- Detect your system and validate prerequisites
- Install all required dependencies (Python, Node.js, etc.)
- Clone the repository
- Set up the virtual environment
- Install npm dependencies
- Configure firewall rules
- Create system configuration files

If Node.js is installed through `nvm`, the dashboard launcher now discovers that toolchain automatically on headless VPS hosts. You do not need to manually source `nvm.sh` before running `app/linux_dashboard_start.sh`.

If you run this installer over non-interactive SSH, it now detects the missing TTY and switches to safe defaults automatically instead of prompting through `/dev/tty`.

---

## Repository Options

During installation, you'll choose between two repository options:

### Option 1: Default Repository (Testing/SITL)

Use the official MDS repository for testing and simulation:

```
github.com/alireza787b/mavsdk_drone_show
```

**Limitations:**
- Read-only access (unless you're a collaborator)
- Pulling updates still works, but write-backed custom git sync workflows are not enabled by default
- Suitable for SITL and testing only

The installer now also writes `MDS_GIT_AUTO_PUSH=false` for this HTTPS/read-only path, so show imports and config saves do not attempt a git push the repo cannot perform.

### Option 2: Your Own Repo Or Customer Org Repo (Production)

For production or customer-specific deployments, use a repo you control:

1. Either fork [mavsdk_drone_show](https://github.com/alireza787b/mavsdk_drone_show) or create/use an org-owned private repo.
   For confidentiality-sensitive customers, prefer an org-owned private repo instead of assuming a normal GitHub fork will be private.

2. Use the repo during installation:
   ```bash
   curl -fsSL ... | sudo bash -s -- --fork yourusername
   ```

   Customer org/private repo example:
   ```bash
   curl -fsSL ... | sudo bash -s -- --fork yourorg/customer-mds --branch customer-demo
   ```

   Or select option 2 during interactive setup.

3. **Benefits:**
   - Full write access
   - Git sync features enabled
   - Drones can pull updates from your GCS
   - Push configuration changes

### SSH Deploy Keys

For GCS write access (fork or collaborator), either let the installer manage the default key or point it at an existing write-capable SSH key:

1. Default managed mode: the installer generates a key at `~/.ssh/mds_gcs_deploy_key`
2. Existing-key mode: pass `--git-ssh-key-file /path/to/key` and the installer will reuse that key instead of generating a new one
2. Add the public key to your GitHub repository:
   - Go to Repository → Settings → Deploy keys → Add deploy key
   - **Enable "Allow write access"**
3. The installer verifies the connection before proceeding
   It now tests and pins the intended deploy key explicitly, so pre-existing `~/.ssh/config` GitHub identities do not silently hijack the repo connection.
   For a first-time private SSH bootstrap, non-interactive `-y` only works if that deploy key is already authorized on GitHub.
   After you authorize the deploy key, rerunning `mds_gcs_init.sh` with the same repo/branch updates `/etc/mds/gcs.env` to match, so the launcher and backend stay on the same source of truth.

Do not reuse this write-capable GCS key inside disposable SITL containers. Private SITL containers should use a separate read-only token/key as documented in [Custom SITL Auth Guide](custom-sitl-auth.md).

### Access Modes

| Mode | Write Access | Git Sync | Use Case |
|------|--------------|----------|----------|
| HTTPS (default repo) | No | Pull only, auto-push disabled | Testing, SITL |
| HTTPS (custom repo) | Manual push | Manual | Simple deployments, deploy-key-disabled private demos |
| SSH (custom repo) | Yes | Yes | Production shows |

For a full customer repo decision tree, see [Custom Repo Workflow](custom-repo-workflow.md).
For a private GitHub repo over HTTPS, use `--git-auth-token-file /path/to/read_only_token`; plain HTTPS alone is not sufficient. For private GitHub repo access over SSH, use `--git-ssh-key-file /path/to/private_key` when you want to reuse an existing repo-scoped or machine-user key. For SITL/private image auth, use [Custom SITL Auth Guide](custom-sitl-auth.md).

---

## Manual Setup

### Prerequisites

- **Operating System:** Ubuntu 20.04, 22.04, or 24.04 (recommended: 22.04)
- **Architecture:** x86_64 or arm64/aarch64
- **RAM:** Minimum 2GB, **Recommended 4GB+**
  > ⚠️ Systems with <4GB RAM may encounter npm "JavaScript heap out of memory" errors.
  > The dashboard `npm run build` script now sets a 4GB Node heap budget automatically and disables production sourcemaps to keep Hetzner/CI builds stable. Systems with <4GB RAM may still need swap.
- **Disk Space:** Minimum 5GB free
- **Network:** Internet access for package downloads
- **Privileges:** Root or sudo access

### Step-by-Step Installation

1. **Clone the repository:**
   ```bash
   git clone -b main-candidate https://github.com/alireza787b/mavsdk_drone_show.git
   cd mavsdk_drone_show
   ```

   Or clone the customer repo you intend to operate:
   ```bash
   git clone -b customer-demo git@github.com:yourorg/customer-mds.git
   cd customer-mds
   ```

2. **Run the GCS initialization script:**
   ```bash
   sudo ./tools/mds_gcs_init.sh
   ```

3. **Follow the interactive prompts to:**
   - Configure SSH deploy key (for git sync features) or use HTTPS
   - Set up Python virtual environment
   - Install npm dependencies
   - Configure firewall rules
   - Set up Mapbox token (optional, for map features; see [Mapbox Setup](mapbox-setup.md))

For customer/private repos, prefer a fully explicit command:

```bash
sudo ./tools/mds_gcs_init.sh \
  --repo-url git@github.com:yourorg/customer-mds.git \
  --branch customer-demo
```

---

## CLI Reference

### Mode Selection

| Option | Description |
|--------|-------------|
| `--configure` | Full setup mode (default) |
| `--run` | Start services only (skip setup) |

### Common Options

| Option | Description |
|--------|-------------|
| `--repo-url URL` | Use an explicit repository URL |
| `-y, --yes` | Non-interactive mode (accept defaults) |
| `--dry-run` | Preview changes without executing |
| `--resume` | Continue interrupted setup from last checkpoint |
| `--https` | Use HTTPS for repository (no SSH key needed) |
| `--force` | Force reinstallation, overwrite existing setup |
| `-v, --verbose` | Show detailed output |
| `--debug` | Show debug-level logging |

### Skip Options

| Option | Description |
|--------|-------------|
| `--skip-prereqs` | Skip prerequisite checks |
| `--skip-python` | Skip Python installation |
| `--skip-nodejs` | Skip Node.js installation |
| `--skip-repo` | Skip repository clone/update |
| `--skip-firewall` | Skip firewall configuration |
| `--skip-python-env` | Skip virtual environment setup |
| `--skip-nodejs-env` | Skip npm dependencies |
| `--skip-env-config` | Skip .env configuration |

### Examples

```bash
# Full interactive setup
sudo ./tools/mds_gcs_init.sh

# Non-interactive setup with HTTPS
sudo ./tools/mds_gcs_init.sh -y --https

# Explicit custom repo + branch
sudo ./tools/mds_gcs_init.sh --repo-url git@github.com:yourorg/customer-mds.git --branch customer-demo

# Explicit private HTTPS repo + token file
sudo ./tools/mds_gcs_init.sh --repo-url https://github.com/yourorg/customer-mds.git --branch customer-demo --git-auth-token-file /root/.mds_git_read_token

# Explicit private SSH repo + existing write-capable key
sudo ./tools/mds_gcs_init.sh --repo-url git@github.com:yourorg/customer-mds.git --branch customer-demo --git-ssh-key-file /root/.ssh/customer_gcs_write_key

# Dry run to preview changes
sudo ./tools/mds_gcs_init.sh --dry-run

# Resume interrupted installation
sudo ./tools/mds_gcs_init.sh --resume

# Skip firewall changes (if using external firewall)
sudo ./tools/mds_gcs_init.sh --skip-firewall

# Customer/private repo with write-back
sudo ./tools/mds_gcs_init.sh \
  --repo-url git@github.com:yourorg/customer-mds.git \
  --branch customer-demo \
  --git-ssh-key-file /root/.ssh/customer_gcs_write_key
```

---

## Configuration Files

### System Configuration

| File | Purpose |
|------|---------|
| `/etc/mds/gcs.env` | System-wide GCS configuration |
| `/var/lib/mds/gcs_init_state.json` | Installation state (for resume) |
| `/var/log/mds/mds_gcs_init.log` | Installation logs |

### Application Configuration

| File | Purpose |
|------|---------|
| `app/dashboard/drone-dashboard/.env` | Dashboard settings (Mapbox, ports) |
| `requirements.txt` | Python dependencies |
| `app/dashboard/drone-dashboard/package.json` | Node.js dependencies |

### Example `/etc/mds/gcs.env`

```bash
# MDS GCS Configuration
GCS_PORT=5000
GCS_BACKEND=fastapi

# Repository Settings
MDS_REPO_URL=git@github.com:yourorg/customer-mds.git
MDS_BRANCH=customer-demo
MDS_GIT_AUTO_PUSH=true
MDS_INSTALL_DIR=~/mavsdk_drone_show

# Dashboard Settings
DASHBOARD_PORT=3030

# Virtual Environment
VENV_PATH=~/mavsdk_drone_show/venv
```

Use [Runtime Config Sources](runtime-config-sources.md) as the source of truth
for what belongs in `/etc/mds/gcs.env`, what belongs in `/etc/mds/local.env`,
what belongs in repo files such as `deployment/defaults.env`, `config.json`,
`swarm.json`, and what still remains runtime policy in `src/params.py`.

`git_sync_mds.service` on the GCS host also reads `/etc/mds/gcs.env`, so repo,
branch, install-dir, and auth changes written by `mds_gcs_init.sh` are reused
by later boot-time/runtime sync without requiring a second hidden env file.
Fresh GCS bootstrap now reconciles that service as an explicit `services`
phase after `env_config`, so a new host does not need a separate manual
post-install repair to make self-update functional.

---

## Firewall Ports

### Ports Opened By `mds_gcs_init.sh`

| Port | Protocol | Purpose |
|------|----------|---------|
| 22 | TCP | SSH access |
| 5000 | TCP | GCS API Server (FastAPI) |
| 3030 | TCP | React Dashboard |
| 14550 | UDP | GCS MAVLink (from drones) |

### Optional Or Local-Only Ports

These are not opened by default anymore. Add them manually only when your workflow actually needs them:

| Port | Protocol | Purpose |
|------|----------|---------|
| 24550 | UDP | Remote GCS / QGroundControl via router or VPN |
| 34550 | UDP | Legacy server-side router listen port |
| 14540 | UDP | Local MAVSDK SDK endpoint |
| 12550 | UDP | Local telemetry endpoint |
| 14569 | UDP | Optional local `mavlink2rest` target |

### Manual Firewall Configuration

If you skipped firewall setup or need to configure manually:

```bash
# Using UFW
sudo ufw allow 22/tcp
sudo ufw allow 5000/tcp
sudo ufw allow 3030/tcp
sudo ufw allow 14550/udp
sudo ufw enable
```

If you intentionally use multi-GCS/QGroundControl or custom local consumers, open the extra UDP ports explicitly:

```bash
sudo ufw allow 24550/udp
sudo ufw allow 34550/udp
sudo ufw allow 14540/udp
sudo ufw allow 12550/udp
sudo ufw allow 14569/udp
```

---

## Verification

### Check Installation Status

```bash
# View state file
cat /var/lib/mds/gcs_init_state.json | jq .

# Check log file
tail -50 /var/log/mds/mds_gcs_init.log

# Verify Python environment
source ~/mavsdk_drone_show/venv/bin/activate
python -c "import fastapi; print('FastAPI OK')"
python -c "import mavsdk; print('MAVSDK OK')"

# Verify Node.js environment
ls ~/mavsdk_drone_show/app/dashboard/drone-dashboard/node_modules | head -5

# Verify GCS git mode
grep '^MDS_GIT_AUTO_PUSH=' /etc/mds/gcs.env
```

Expect `MDS_GIT_AUTO_PUSH=false` on read-only HTTPS demo setups and `true` only when authenticated write access is already verified.

### Run Diagnostic Check

```bash
cd ~/mavsdk_drone_show/app
./linux_dashboard_start.sh --check
```

---

## Troubleshooting

### SSH Key Issues

**Problem:** SSH authentication fails when cloning repository.

**Solutions:**
1. **Use HTTPS instead:**
   ```bash
   sudo ./tools/mds_gcs_init.sh --https
   ```

2. **Verify deploy key is added to GitHub:**
   - Go to repository Settings > Deploy keys
   - Ensure the key from `~/.ssh/mds_gcs_deploy_key.pub` is added
   - Check "Allow write access" is enabled

3. **Test SSH connection:**
   ```bash
   ssh -T git@github.com
   ```

4. **Verify the configured repo and branch, not just GitHub in general:**
   ```bash
   grep '^MDS_REPO_URL=' /etc/mds/gcs.env
   grep '^MDS_BRANCH=' /etc/mds/gcs.env
   git -C ~/mavsdk_drone_show remote -v
   git -C ~/mavsdk_drone_show branch --show-current
   ```

### Port Conflicts

**Problem:** Port already in use error.

**Solution:**
```bash
# Find process using port
sudo lsof -i :5000
# or
sudo netstat -tlnp | grep 5000

# Kill the process
sudo kill -9 <PID>
```

### Python Environment Issues

**Problem:** Virtual environment creation fails.

**Solutions:**
1. **Install Python venv module:**
   ```bash
   sudo apt-get install python3.11-venv
   ```

2. **Remove corrupted venv and retry:**
   ```bash
   rm -rf ~/mavsdk_drone_show/venv
   sudo ./tools/mds_gcs_init.sh --resume
   ```

### npm Install Failures

**Problem:** `npm ci` fails.

**Solutions:**
1. **Clear npm cache:**
   ```bash
   npm cache clean --force
   ```

2. **Remove node_modules and retry with the lockfile:**
   ```bash
   rm -rf ~/mavsdk_drone_show/app/dashboard/drone-dashboard/node_modules
   cd ~/mavsdk_drone_show/app/dashboard/drone-dashboard
   npm ci --no-audit --no-fund
   ```

3. **If `npm ci` still fails, fix the repo state instead of mutating it on the server:**
   - ensure `package.json` and `package-lock.json` are committed together
   - pull the latest branch state
   - only use `MDS_ALLOW_NPM_INSTALL_FALLBACK=true` for an intentional one-off emergency fallback

### Resume Interrupted Installation

If installation was interrupted:
```bash
sudo ./tools/mds_gcs_init.sh --resume
```

This will continue from the last completed phase.

---

## Running the Dashboard

After successful installation, start the dashboard:

### Quick Start

```bash
cd ~/mavsdk_drone_show/app

# SITL mode (simulation) - development mode, runs in tmux by default
# React hot-reloads; backend stays single-process unless you explicitly enable MDS_GCS_BACKEND_RELOAD=true
./linux_dashboard_start.sh --sitl

# Real mode (hardware drones)
./linux_dashboard_start.sh --real
```

### Common Options

| Option | Description |
|--------|-------------|
| `--sitl` | Simulation mode (no real drones) |
| `--real` | Hardware mode (real drones) |
| `--prod` | Production mode (optimized builds) |
| `--dev` | Development mode (hot reload) |
| `--rebuild` | Force rebuild React app |
| `--status` | Show current status |
| `-n` | Do NOT use tmux |
| `--help` | Show all options |

### Examples

```bash
# Development with simulation
./linux_dashboard_start.sh --sitl

# Production with simulation
./linux_dashboard_start.sh --prod --sitl

# Production with real drones
./linux_dashboard_start.sh --prod --real

# Check status
./linux_dashboard_start.sh --status
```

Operational note: the FastAPI backend currently keeps heartbeats, command tracking, telemetry polling, and other live runtime state in process memory. For that reason:
- `--prod` intentionally runs a single Gunicorn worker
- `--sitl` / `--dev` now keep the backend single-process by default as well
- backend auto-reload is an explicit debug override only: `export MDS_GCS_BACKEND_RELOAD=true`
- when you change host-local runtime mode, use Runtime Admin or relaunch the
  canonical launcher so the process restarts cleanly in the target mode instead
  of trying to mix SITL and real heartbeats in one long-lived backend process

### Runtime Admin

The dashboard Runtime Admin page is the host-local control surface for the GCS
process. It is intentionally narrow:

- save host-local mode (`MDS_MODE`) and git auto-push posture
- show running vs configured drift
- schedule a controlled relaunch through the canonical launcher
- expose repo/auth, MAVLink, and connectivity health summaries with guide links

Current operator rules:

- use Runtime Admin for host-local GCS behavior only
- use fleet config / swarm config for git-tracked fleet desired state
- do not treat Runtime Admin as the place to edit raw GitHub secrets
- use the built-in `Update GCS` action only for safe fast-forward runtime
  updates; it intentionally blocks launcher, frontend, tooling, and dependency
  changes so those still go through the manual update path

When switching between SITL and real mode:

- save the desired mode first
- apply the restart so the backend comes back up cleanly in the new mode
- stop old SITL containers if you are leaving SITL; the backend now fences
  mode-mismatched heartbeats at intake, but explicit cleanup is still the right
  operational practice

When using the constrained GCS self-update path:

- the checkout must be clean and tracking a remote branch
- the fetched upstream must be fast-forward-only
- pending changes must stay off blocked surfaces such as:
  - `app/`
  - `tools/`
  - dependency manifests like `package.json`, `requirements*.txt`,
    `pyproject.toml`
- Runtime Admin will refuse those blocked updates and tell the operator to use
  the manual update workflow instead

### Managing the Services

```bash
# View running services (tmux)
tmux attach -t MDS-GCS

# Detach from tmux: Ctrl+B, then D

# Stop all services
tmux kill-session -t MDS-GCS
```

### Access Points

After starting:
- **React Dashboard:** http://YOUR_SERVER_IP:3030
- **GCS API Server:** http://YOUR_SERVER_IP:5000
- **API Health Check:** http://YOUR_SERVER_IP:5000/api/v1/system/health

---

---

## VPN Networking

For drones to communicate with your GCS over the internet, both must be on the same VPN network.

### Recommended: NetBird

NetBird provides secure, easy-to-setup networking:

```bash
# Install on GCS
curl -fsSL https://pkgs.netbird.io/install.sh | sh
sudo netbird up
```

After connecting:
1. Note your NetBird IP (typically `100.x.x.x`)
2. Use this IP as `GCS_IP` when configuring drones
3. Install NetBird on each drone and connect to the same network

See [NetBird Setup Guide](netbird-setup.md) for detailed instructions.

### Network Architecture

```
GCS Server (100.64.0.1) ◄──NetBird VPN──► Drone 1 (100.64.0.2)
                        ◄──────────────► Drone 2 (100.64.0.3)
                        ◄──────────────► Drone N (100.64.0.N)
```

---

## Next Steps

1. **Configure Mapbox Token** (optional): Edit `.env` file to add your Mapbox access token for map features
2. **Set up VPN Networking**: See [NetBird Setup](netbird-setup.md) for secure drone-GCS communication
3. **Set up MAVLink Routing**: See [MAVLink Routing Setup](mavlink-routing-setup.md)
4. **Configure Companion Nodes**: See [MDS Init Setup](mds-init-setup.md) for companion-computer hardware
5. **Review Runtime Config Ownership**: See [Runtime Config Sources](runtime-config-sources.md)
6. **Review Fleet Sync / Secret Handling**: See [Fleet Sync And Secrets](fleet-sync-and-secrets.md)
7. **Review SITL Guide**: See [SITL Comprehensive Guide](sitl-comprehensive.md) for simulation testing

---

**Last Updated:** March 2026 (Version 5.0)
