
# MDS Simulation Server Setup Guide

## Introduction

Welcome to the MDS Simulation Server Setup Guide. This is the validated first-run path for loading the official SITL image, bootstrapping the GCS, and launching a quick demo on a fresh Ubuntu VPS.

> **Scope**
>
> This guide is the official quick-start for evaluation, demos, and repeatable SITL validation on a clean server.
> For custom images, fork maintenance, or customer-specific redistribution, use [Advanced SITL Configuration](advanced-sitl.md) and [SITL Custom Release Workflow](sitl-custom-release-workflow.md).
>
> Advanced customization and real-hardware deployment require solid PX4/Linux/networking knowledge plus licensing, regulatory, and operational review. For private assistance or deployment consulting, contact [Alireza on LinkedIn](https://www.linkedin.com/in/alireza787b/) or [p30planets@gmail.com](mailto:p30planets@gmail.com).

This same stack also powers multiple operator modes. Use this SITL guide first, then branch into the mode-specific docs you need:

- **[Drone Show](../features/drone-show.md)** for SkyBrush ZIP import, show processing, and synchronized launch control
- **[Smart Swarm](../features/smart-swarm.md)** for live leader-follower runtime operations
- **[Swarm Trajectory](../features/swarm-trajectory.md)** for cluster trajectory generation and analysis
- **[QuickScout](../quickscout.md)** for SAR / recon planning and mission execution
- Additional modes may be added over time; new audited guides should appear in the [Documentation Index](../README.md)

For a step-by-step walkthrough beginning with version 0.1, use the [project YouTube playlist](https://www.youtube.com/watch?v=dg5jyhV15S8&list=PLVZvZdBQdm_7ViwRhUFrmLFpFkP3VSakk&pp=sAgC).


## Watch the Setup Video

Check out our detailed **100-Drone SITL Test in Clustered Cloud Servers** video for a visual guide on setting up and running the simulation.

[![100-Drone SITL Test](https://img.youtube.com/vi/VsNs3kFKEvU/maxresdefault.jpg)](https://www.youtube.com/watch?v=VsNs3kFKEvU)


## Smart Swarm Clustered Leader–Follower Video

If you are interested in how cooperative missions and “Smart Swarm” mode works, check this video:  
[![Smart Swarm Clustered Leader–Follower](https://img.youtube.com/vi/qRXE3LTd40c/maxresdefault.jpg)](https://youtu.be/qRXE3LTd40c)


## Resource Allocation

The minimum resource allocation required for running two drone instances is **2 CPU cores and 4 GB of RAM**.

- For testing, start with at least 2 CPUs and 4GB RAM.
- Increase resources proportional to the number of drones being simulated.
- Each drone instance requires significant compute for SITL, so plan accordingly.
- A good starting point is **1 core and 0.5 ~ 1GB RAM per drone**.

## Initial Server Setup

Create a Virtual Machine (VM) based on your requirements. For example, using Linode, choose sufficient resources based on the number of drones you want to simulate.

**Recommended OS:** Ubuntu 22.04 or 24.04.

### Pointing a Domain or Subdomain (Optional)

Although optional, it's highly recommended to point a domain or subdomain to your drone server for ease of access and identification. You can use your existing domain or purchase a new one. If you are running on a local system, it is not needed.

**Setting Up Cloudflare:**

1. Go to [Cloudflare's website](https://www.cloudflare.com/) and sign up for a free account if you don't have one already.
	* Cloudflare will serve in this project is as a DNS (Domain Name System) management service.
2. After logging in, click on **'Add a Site'** to add your domain to Cloudflare.
3. Follow the on-screen instructions to verify ownership and import existing DNS settings (if applicable).
4. Once the domain is added, proceed to the DNS management section.

**How to Add an A Record in Cloudflare:**

1. Log in to your Cloudflare account if you are not already logged in.
2. Navigate to the **'DNS'** tab.
3. Click on **'Add Record'**.
4. Select **'A'** in the **'Type'** dropdown.
5. Enter **'drone'** in the **'Name'** field to create a subdomain like `drone.yourdomain.com`.
6. Enter your server IP address in the **'IPv4 Address'** field.
7. Ensure the **'Proxy Status'** is set to **'DNS Only'**.
8. Click **'Save'**.

> **Tip:** If you prefer, you can also continue to use the IP address of the server or Reverse DNS URLs.

## Server Configuration: Basic Setup

### Access to Your Server Using SSH

```bash
ssh root@your_server_ip
```

### Package and Software Installation

First, install the base packages required for the SITL workflow, then install the official `MEGAcmd` Ubuntu package from MEGA so downloads and archive operations use one consistent client:

```bash
sudo apt update
sudo apt install -y curl python3 python3-venv python3-pip tmux lsof git p7zip-full
curl -fsSLo /tmp/megacmd-xUbuntu_24.04_amd64.deb \
  https://mega.nz/linux/repo/xUbuntu_24.04/amd64/megacmd-xUbuntu_24.04_amd64.deb
sudo apt install -y /tmp/megacmd-xUbuntu_24.04_amd64.deb
```

#### Downloading the Official SITL Docker Image

The current SITL image is **temporarily** distributed from MEGA rather than GitHub Releases. If you prefer, you can also download the same `.7z` archive manually in a browser on the same machine, then continue with the exact same `7z` and `docker load` steps below.

The public archive keeps one stable filename:
- `mavsdk-drone-show-sitl-image.7z`

Do **not** look for version numbers in the filename. Release versioning lives in the Docker tags restored by `docker load`.

```bash
cd ~
# Public Mega download via the official MEGAcmd client; large archives may take several minutes.
mega-get 'https://mega.nz/file/OW4gmZLT#Kg0LgBjcGBHI25EUQgwG14wL_kLJ4b4uIQybcrMcRDs' .
# Validate the archive before extracting it.
7z t mavsdk-drone-show-sitl-image.7z
# Extraction also takes time on large images.
7z x mavsdk-drone-show-sitl-image.7z
```

After extraction you should have:
- `mavsdk-drone-show-sitl-image.7z` - compressed archive from Mega
- `mavsdk-drone-show-sitl-image.tar` - Docker image tar produced by `7z`

> **Notes**
> - This guide standardizes on the official `MEGAcmd` client for both public downloads and authenticated archive operations.
> - If you already downloaded the `.7z` in a browser, skip `mega-get` and continue with `7z t`, `7z x`, and `docker load`.
> - If MEGA free-tier throttling blocks the public download, sign in and retry with `mega-login`.
> - The public link may change over time, but the archive filename stays stable.
> - The official HTTPS/demo bootstrap path keeps `MDS_GIT_AUTO_PUSH=false` by default, so first-time imports/config saves stay clean on read-only evaluation setups.

### Docker Installation

Install Docker:

```bash
sudo apt install -y docker.io
```

Load the extracted image into Docker:

```bash
# Large image imports may take several minutes.
docker load -i mavsdk-drone-show-sitl-image.tar
```

The archive already contains the official Docker tags. After `docker load`, confirm them with:

```bash
docker image ls mavsdk-drone-show-sitl
```

You should see the current official tags, including:
- `mavsdk-drone-show-sitl:latest`
- `mavsdk-drone-show-sitl:v5`

After a successful `docker load`, you can reclaim several GB on smaller VPSes by deleting the temporary archive files:

```bash
rm -f ~/mavsdk-drone-show-sitl-image.tar ~/mavsdk-drone-show-sitl-image.7z
```

> **Important:** `create_dockers.sh` now defaults to `mavsdk-drone-show-sitl:latest`, so no manual retagging is required when you use the official archive. The archive filename stays stable; Docker tags carry the release version.
>
> **Still supported for advanced users:** This does **not** remove custom image or custom repository support. If you need your own fork, branch, or image tag, keep using `MDS_DOCKER_IMAGE`, `MDS_REPO_URL`, and `MDS_BRANCH` as documented in [Advanced SITL Configuration](advanced-sitl.md).
>
> **Need a custom release workflow?** See [SITL Custom Release Workflow](sitl-custom-release-workflow.md) for the clean path to maintain your own fork, rebuild a validated image, package it, and redistribute it without relying on ad hoc container edits.
>
> **Large-fleet note:** for validated demo/production runs with many containers, prefer a rebuilt image plus `MDS_SITL_GIT_SYNC=false` and usually `MDS_SITL_REQUIREMENTS_SYNC=false` so startup does not fan out into one remote git fetch or Python re-sync per container.
>
> **Regression note:** the reusable all-mode operator regression on Hetzner is now validated in that pinned-image mode. For repeatable acceptance gates on a persistent VPS, rebuild the image for the target commit, recreate the fleet from that image, and keep both boot-sync flags off during the run.

#### Image Features and Components

This custom image is a plug-and-play solution built on Ubuntu 22.04. It includes:

- **PX4 SITL with Gazebo Harmonic support**
- **mavsdk_drone_show** preloaded as a shallow git checkout so each container can sync the latest branch state on startup
- **Python virtual environment** prebuilt from `requirements.txt` for faster container startup
- **mavlink-router**
- **mavlink2rest-ready routing target** on `127.0.0.1:14569` for optional future use
- **Gazebo Sim (`gz`)**
- **SITL workflow dependencies**
- **All other necessary dependencies**

Moreover, it has an auto hardware ID detection and instance creation system for automated drone instance creation.

> **Current Docker SITL standard**
> - `startup_sitl.sh` now launches **headless PX4 Gazebo Harmonic** with `HEADLESS=1 make px4_sitl gz_x500`
> - the image keeps one prebuilt PX4 SITL build tree, the real PX4 git checkout plus submodule metadata, one baked `mavsdk_server` binary, and one prebuilt Python venv; old release layer history is flattened out during packaging
> - release image prep removes the PX4 ARM firmware toolchain by default to save space because it is not required for normal SITL runtime; set `MDS_SITL_KEEP_ARM_TOOLCHAIN=true` before rebuilding if you intentionally need that toolchain in a custom image
> - each container can still fetch and hard-reset to the latest configured MDS branch on startup, and that sync now also cleans untracked MDS files while preserving runtime artifacts such as `venv/`, `logs/`, `*.hwID`, and the baked `mavsdk_server`
> - PX4 and the baked `mavsdk_server` binary are pinned inside the image and are updated only through a validated image rebuild; they are not auto-pulled during container startup
> - `MDS_SITL_GIT_SYNC=true` is a mutable latest-on-boot mode. It is convenient for active development, but it is not the same as a reproducible validated release because the runtime MDS checkout may move ahead of the pinned PX4/image contents
> - for promotion-grade regression runs on a long-lived host, do not mix an older baked image with boot-time repo sync to a newer commit; use a fresh image rebuild plus `MDS_SITL_GIT_SYNC=false` and usually `MDS_SITL_REQUIREMENTS_SYNC=false`
> - image prep writes build metadata and PX4 provenance into the repo root so startup logs can show what was baked into the image
> - `requirements.txt` changes trigger a venv sync automatically; unchanged requirements do not reinstall on every boot
> - runtime file logs are bounded by default so containers stay small, common PX4 `pxh>` prompt noise is reduced in the raw SITL log, and those logs disappear when the container is removed
> - `QT_QPA_PLATFORM=offscreen` is set automatically for headless runs
> - each drone gets its own Gazebo transport partition by default to avoid cross-container interference
> - legacy Gazebo Classic / jMAVSim modes are no longer the supported Docker SITL path
> - `create_dockers.sh` now waits for PX4, `mavlink-routerd`, and `coordinator.py` before it reports a container as ready; `startup_sitl.sh` runs as the container main process with Docker restart policy `unless-stopped` by default, and startup-wrapper diagnostics are written to `logs/startup_sitl.log`
> - the default launcher now uses the image-baked `startup_sitl.sh` for reproducible release behavior; set `MDS_SITL_USE_HOST_STARTUP_SCRIPT=true` only when you intentionally want a host-side debug override

#### Need Custom Repository or Advanced Configuration?

The default setup works perfectly for demos and testing. For advanced users who need custom repositories or production deployments:

📖 **[Advanced SITL Configuration Guide](advanced-sitl.md)** - Custom repository setup with simple copy-paste commands

> **⚠️ Note:** Advanced configuration requires good understanding of Git, Docker, and Linux. Contact [p30planets@gmail.com](mailto:p30planets@gmail.com) for help.

### Portainer Installation (Optional but Highly Recommended)

Install Portainer:

```bash
docker volume create portainer_data
docker run -d -p 8000:8000 -p 9443:9443 --name portainer --restart=always \
  -v /var/run/docker.sock:/var/run/docker.sock -v portainer_data:/data portainer/portainer-ce:latest
```

Access Portainer via the browser using your domain, IP address, or the reverse DNS provided by your hosting service like Linode. e.g., `https://drone.YOUR_DOMAIN.com:9443`

## Drone Configuration and Setup

### GCS Server Setup

#### Option A: Automated Setup (Recommended)

The bootstrap installer handles Python, Node.js, venv, npm, firewall, repository setup, and configuration:

```bash
curl -fsSL https://raw.githubusercontent.com/alireza787b/mavsdk_drone_show/main-candidate/tools/install_gcs.sh | sudo bash
```

See the [GCS Setup Guide](gcs-setup.md) for full details and CLI options (for example `--dry-run`, `-y`, or `--fork`).

Notes:
- This installer now handles headless SSH sessions cleanly. If no interactive TTY is available, it automatically switches to non-interactive defaults instead of trying to read from `/dev/tty`.
- After the installer finishes and you launch the dashboard, give the backend a few seconds to come up before treating a first `curl` failure as a problem. The quickest readiness check is:
  ```bash
  curl http://127.0.0.1:5000/api/v1/system/health
  ```

#### Option B: Manual Setup

If you prefer to set things up manually:

> **Important:** the manual path assumes a working Python `3.11+` interpreter.
> On Ubuntu 22.04, `python3` is often still `3.10`, so prefer **Option A** on a fresh VPS unless you have already installed Python 3.11 or newer yourself.

```bash
cd ~
git clone https://github.com/alireza787b/mavsdk_drone_show
cd mavsdk_drone_show
git checkout main-candidate
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Install Node.js (Node.js 22 LTS recommended via [nvm](https://nodejs.org/en/download/package-manager); Node.js 20 is still tolerated if you need it), then:

```bash
cd ~/mavsdk_drone_show/app/dashboard/drone-dashboard
npm ci
```

#### Start the Dashboard

```bash
bash ~/mavsdk_drone_show/app/linux_dashboard_start.sh --sitl
```

- `--sitl` by itself starts the dashboard in **development mode**: React `npm start` on port `3030` plus FastAPI with auto-reload on port `5000`.
- `--sitl` by itself starts the dashboard in **development mode**: React `npm start` on port `3030` plus FastAPI on port `5000`, but the backend now stays single-process by default so telemetry, heartbeats, command tracking, and other in-memory runtime state remain coherent during live SITL operations.
- Backend auto-reload is now an explicit debug override only. Set `export MDS_GCS_BACKEND_RELOAD=true` only when you are actively editing backend Python code and accept that live operational state may become inconsistent while reload is enabled.
- Use `bash ~/mavsdk_drone_show/app/linux_dashboard_start.sh --prod --sitl` when you want the optimized production-style launch instead.
- Production currently uses a single Gunicorn worker on purpose because heartbeat state, command tracking, and background pollers still live in process memory.
- Production serves the React build with SPA route fallback, so direct browser refresh on routes like `/logs` or `/mission-config` keeps working.
- On smaller VPSes, raise the React build heap before `--prod` if needed:
  `export MDS_REACT_BUILD_MAX_OLD_SPACE_SIZE=4096`
- Console logs now default to `INFO` for both `--sitl` and `--prod`; session/file logs still keep `DEBUG`. If you need deeper live console tracing, set `export MDS_GCS_CONSOLE_LOG_LEVEL=DEBUG` before launch.
- The launcher uses `npm ci` by default and refuses to mutate `package-lock.json` with `npm install` unless you explicitly opt in with `MDS_ALLOW_NPM_INSTALL_FALLBACK=true`.
- Raw Uvicorn/Gunicorn access logs are disabled by default because MDS already emits structured API request logs. Re-enable them only when you explicitly need that extra layer with `export MDS_GCS_ACCESS_LOGS=true`.
- The dashboard auto-detects the server IP from the browser URL — no manual IP configuration needed.
- To override the IP: use `--overwrite-ip "YOUR_SERVER_IP"` or edit the `.env` file.
- The official stock SITL package now auto-seeds a default launch origin from `data/origin.sitl.default.json` (Azadi Stadium). That gives first-time testers an immediate green Mission Config baseline without a manual `PUT /api/v1/origin`.
- If you later change origin from the dashboard or API, MDS writes a local runtime override to `data/origin.json`. That file is intentionally untracked and overrides the packaged SITL default on that server until you replace or remove it.
- If you want to return a server back to the stock Azadi demo baseline, delete the local `data/origin.json` override and restart the normal SITL flow.

You should now be able to access the GUI via a browser using your domain, IP, or reverse DNS (if set). E.g., `http://drone.YOUR_DOMAIN.com:3030`

> **Note:** If you can't access the page, make sure your firewall rules allow communication on ports **3030** (dashboard), **5000** (GCS API), and **14550/udp** (MAVLink). See the [GCS Setup Guide](gcs-setup.md#firewall-ports) for the full port list.

### Mission Configuration and Customization (Optional)

You can configure your mission, swarm design, or drone show using SkyBrush or similar tools.

If you are running the default mutable latest-on-boot mode with `MDS_SITL_GIT_SYNC=true`, container startup fetches and hard-resets the MDS repo to the configured branch, so uncommitted container-local edits are disposable by design.

For the stock official SITL package, Mission Config initially uses the tracked Azadi Stadium demo origin. That is just the packaged first-run baseline for repeatable validation. Operators can still set a different origin in the UI/API at any time, which creates a local `data/origin.json` runtime override on that server.

For an official or validated release workflow, do **not** rely on in-container edits. Commit changes to git first, rebuild or release a clean image, and then redeploy containers from that image. See [SITL Custom Release Workflow](sitl-custom-release-workflow.md) if you maintain your own fork or customer-specific image.

The following section covers the standard flow for launching SITL drone instances, with an optional note for multi-server scaling.

---

### Run Drone Instances


1. **SSH into Your Server:**

    Open a terminal and connect to your server via SSH:

    ```bash
    ssh root@Your_Server_IP
    ```

2. **Navigate to the Repository Directory:**

    Once connected, navigate to the project directory:

    ```bash
    cd ~/mavsdk_drone_show
    ```

3. **Create Drone Instances:**

    Use the `create_dockers.sh` script to create the desired number of drone instances. Replace `<number_of_instances>` with the number of drones you wish to deploy.

    ```bash
    bash multiple_sitl/create_dockers.sh <number_of_instances>
    ```

    **Example:** To create **2** drone instances:

    ```bash
    bash multiple_sitl/create_dockers.sh 2
    ```

    **Explanation:** The script `create_dockers.sh` initializes Docker containers representing your simulated drones. Each container forwards the active `MDS_*` runtime variables, bind-mounts only per-drone runtime state such as the generated `.hwID` file, and launches the image-baked `startup_sitl.sh` as the container's main process by default. That startup path can optionally hard-reset the MDS repo to the latest configured branch, re-syncs the Python venv only if `requirements.txt` changed, verifies the baked `mavsdk_server` binary, starts headless PX4 `gz_x500`, applies any SITL PX4 parameter overrides via launch-time `PX4_PARAM_*` environment variables, validates PX4 startup, and brings up MAVLink routing plus `coordinator.py`. Use `MDS_SITL_USE_HOST_STARTUP_SCRIPT=true` only when you intentionally want a host-side debug override instead of the image-baked startup path.

    > **Hints:** For debugging purposes, use the `--verbose` flag to create a single drone and view detailed logs.

    ```bash
    sudo bash multiple_sitl/create_dockers.sh 1 --verbose
    ```

### Advanced: Multi-Server Deployment (Optional)

For advanced users aiming to deploy drones across multiple servers (VPS) to scale up the simulation, follow these guidelines:

Each server should operate within a distinct Docker network subnet to prevent IP conflicts. By default, the script uses `172.18.0.0/24`. Subsequent servers can utilize `172.19.0.0/24`, `172.20.0.0/24`, etc. (We will keep the GCS centralized on first VPS)
  ```bash
   bash multiple_sitl/create_dockers.sh 50 --subnet 172.18.0.0/24 --start-id 1 --start-ip 2 # On server 1
   bash multiple_sitl/create_dockers.sh 50 --subnet 172.19.0.0/24 --start-id 51 --start-ip 2 # On server 2
  ```

> **Important:** the stock SITL files in this repo define only 5 drones by default:
> - `config_sitl.json`
> - `swarm_sitl.json`
>
> Creating 50+ containers requires matching expanded SITL config/swarm files and usually a validated custom image or fork workflow. Do not assume `create_dockers.sh 50` alone is sufficient on the stock 5-drone config.
> Use [Advanced SITL Configuration](advanced-sitl.md) for that path.

- `--subnet SUBNET`: (Optional) Specify a custom Docker network subnet. Defaults to `172.18.0.0/24` if not provided.
- `--start-id START_ID`: (Optional) Define the starting drone ID. Defaults to `1` if not specified.
- `--start-ip START_IP`: (Optional) Set the starting IP address's last octet within the subnet. Defaults to `2` to avoid reserved IPs.

> **Note:** Ensure that each server's subnet does not overlap with others to prevent network conflicts.
To enable communication between drones across different subnets (i.e., different servers), set up a network routing solution such as Netbird managed routing.



### Netbird VPN Setup (Optional for External QGroundControl / Remote GCS Streaming)

This section is **not** required for the normal first-run SITL path in this guide.

Docker SITL already handles the internal routing between the GCS and the drone containers through `startup_sitl.sh`. Only use the NetBird / external MAVLink routing path when you intentionally want a separate remote QGroundControl or another external GCS to receive forwarded MAVLink traffic from this server.

Netbird is a zero-config VPN solution that allows you to easily and securely connect your devices, including your server and local PC. This is especially useful if you want to set up a Ground Control Station (e.g., QGroundControl) on your local PC or smartphone and monitor your drone's data in real-time. Netbird is recommended for this setup to ensure efficient and secure data transmission.

#### Why Use Netbird?

While you have the option to use port forwarding, ZeroTier, or even VNC for a server remote desktop (not recommended), Netbird stands out for its ease of use, reliability, security, and ability to self-host.

#### Local vs. Server Setup

Netbird is primarily needed if you are running your GCS and webserver on a remote server (like in this example in the cloud). If you are running everything locally, you won't need to set up Netbird.

#### How to Install Netbird

##### Remote-Side Installation

Open a new terminal tab and SSH into your server:

```bash
ssh root@Your_Server_IP
```

Once connected, run the following command:

```bash
curl -fsSL https://pkgs.netbird.io/install.sh | sh
```

##### Authenticate and Join Netbird Network

Run:

```bash
sudo netbird up
```

If you are running your own self-hosted Netbird server, add `--management-url YOUR_NETBIRD_SERVER_URL` to the above command.

On your server terminal, you will be provided with a join request link. Copy this link and open it on your local PC or smartphone, logging in with the same account you used to set up Netbird on your PC. This ensures both the server and your local PC are on the same network with assigned Netbird IPs.

##### Client-Side Installation

To receive MAVLink packets on your local machine and use a GCS like QGroundControl, you will need to install Netbird on your local device. Netbird is available for a wide range of platforms including Windows, macOS, Linux, Android, and iOS.

Follow the installation guidelines for your specific platform from the [Netbird official download page](https://docs.netbird.io/how-to/installation).

##### Login and Join Network

After installation, open Netbird and hit "connect". You might need to login using the same account credentials you used for the server-side installation. This action will automatically join your device to your Netbird network and assign a unique Netbird IP address to your device.

##### Manage Your Network

You can manage your devices, check their statuses, and even revoke access via the [Netbird admin panel](https://app.netbird.io/) or your own domain if you self-hosted Netbird.

To access each drone container node, you can create a route on Docker subnet "172.17.0.0/16" on the server node from the Netbird management panel.

#### Test Connections

```bash
# On the local system
ping SERVER_GCS_NETBIRD_IP

# On the server
ping LOCAL_GCS_NETBIRD_IP
```

Running these ping tests ensures that both the server and local machines are connected within the Netbird network. If the pings are successful, you can proceed to set up the MAVLink routing.

#### Using MAVLink Router

MAVLink Router serves as a middleware to forward MAVLink packets between different endpoints. In this setup, it's essential for routing MAVLink data from your server GCS to your local GCS.

##### Why Use MAVLink Router?

When your drones are being managed by a GCS on the server, the MAVLink data packets they generate are initially sent to that server-side GCS. However, you may also want this data to be accessible on a local GCS for easier monitoring and control. MAVLink Router allows you to achieve this by routing these data packets to another GCS located on your local machine or your smartphone.

##### Installing MAVLink Router

Before we proceed with the MAVLink routing, we first need to ensure MAVLink Router is installed on the server. Follow these steps to install MAVLink Router:

```bash
git clone https://github.com/alireza787b/mavlink-anywhere
cd mavlink-anywhere
sudo ./install_mavlink_router.sh
```

This installs the current recommended MAVLink Router helper. For the complete routing model and current port expectations, see [MAVLink Routing Setup](mavlink-routing-setup.md).

##### Understanding the Command

```bash
mavlink-routerd -e LOCAL_GCS_NETBIRD_IP:24550 0.0.0.0:34550
```

Here's what each parameter means:

- `-e LOCAL_GCS_NETBIRD_IP:24550`: This specifies the endpoint where MAVLink messages will be forwarded. Replace `LOCAL_GCS_NETBIRD_IP` with the Netbird IP of your local machine. The port `24550` is where your local GCS is listening for incoming MAVLink messages.
- `0.0.0.0:34550`: This is the port on the server where the MAVLink messages are received from the drones. In this example, it's port `34550`.
> **Note:** You might need to open these ports in your firewall (eg. ufw or iptables):
```bash
sudo ufw allow 14550/udp
sudo ufw allow 24550/udp
sudo ufw allow 34550/udp
sudo ufw allow 5000
sudo ufw allow 3030
```
or
```bash
sudo iptables -A INPUT -p udp --dport 14550 -j ACCEPT
sudo iptables -A INPUT -p udp --dport 24550 -j ACCEPT
sudo iptables -A INPUT -p udp --dport 34550 -j ACCEPT
sudo iptables -A INPUT -p udp --dport 5000 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 5000 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 3030 -j ACCEPT
sudo iptables-save | sudo tee /etc/iptables/rules.v4
```



##### Ports Configuration

In the given command, MAVLink messages are being sent initially on port `34550` to the first GCS (server-side), and then routed to port `24550` for the second GCS (local). These port numbers can be modified in the `params.py` file as per your requirements.

#### QGroundControl Settings

On your local GCS, open QGroundControl and navigate to **'Application Settings'** > **'Comm Links'**. Create a new comm link, name it (e.g., **'server1'**), check the **'High Latency'** mode, set the connection type to **'UDP'**, set the port to **`24550`**, and add the server (`SERVER_GCS_NETBIRD_IP`). Save and select this comm link to connect. All your drones should now be auto-detected.

#### Using MAVLink2REST
The current Docker SITL workflow does **not** auto-start a per-drone `mavlink2rest` server. The router still forwards MAVLink to `127.0.0.1:14569` so a future or custom `mavlink2rest` process can subscribe there, but you should **not** assume `http://DRONE_IP:8088` is available from the stock image today. If you intentionally add `mavlink2rest`, use the routed local endpoint and review the upstream [MAVLink2REST documentation](https://github.com/mavlink/mavlink2rest) for the expected process and REST port behavior.


## Clean-Up

Once you are done, head over to the Portainer container menu and remove the drone instances you created. This will help save disk resources.

### Troubleshooting

If you encounter any issues during this setup, here are some common troubleshooting steps:

- Ensure both the server and the local PC are connected to the same Netbird network.
- Check the Netbird admin interface to confirm that your devices are online.
- If pings are unsuccessful, verify firewall rules and consult Netbird documentation for network issues.

## Conclusion

Congratulations, you've successfully set up a drone swarm SITL on a remote server! You're now able to:

- Access the swarm dashboard
- Monitor ongoing missions
- Trigger new missions
- Upload and modify missions
- And much more!

### Caveats and Future Work

Please note that this project is still in its early development phases. Many aspects have not been designed with security or performance in mind. Your contributions to improve these aspects are welcome. Feel free to collaborate, post recommendations, or [report issues](https://github.com/alireza787b/mavsdk_drone_show/issues).

### Warning

While SITL simulations are great for testing, they are not a substitute for real-world validation. **Do not use this software in real-world applications unless you have conducted extensive tests in SITL and are confident about the network, drone hardware, and environment you're operating in.** Even then, proceed with the utmost caution and at your own risk and be prepared with failsafe scenarios.

We are committed to regularly updating this project to make it a reliable product soon. Thank you for your interest, and happy flying!

## Smart Swarm Notes

Smart Swarm is the live leader-follower mission mode in MDS. For the current operator model, failover behavior, and runtime control surface, use the dedicated guide:

- [Smart Swarm Guide](../features/smart-swarm.md)

Current behavior summary:

- single-drone commands remain scoped to the addressed drone
- swarm-level intent should use the `Smart Swarm Runtime` controls on the `Swarm Design` page
- use `Overview` to confirm live `READY` state before you start Smart Swarm from the dashboard
- use `Formation Analysis` to choose a specific cluster; `All executable clusters` is plot-only and does not become one fleet-wide runtime target
- followers do not silently stop just because one unrelated drone receives an individual override
- if the addressed drone is a leader or relay leader, followers can still react through leader-loss logic
- leader-loss handling now defaults to an `upstream_or_hold` policy instead of jumping across unrelated drones

If you want the validated 5-drone Smart Swarm acceptance run from the command line after launching SITL, use:

```bash
python3 tools/validate_smart_swarm_runtime.py
```

If you are chaining multiple mission-family validators on the same SITL fleet, reset the fleet back onto its intended launch geometry before the next Drone Show run. Smart Swarm and Swarm Trajectory can leave drones idle at non-show positions, which is operationally valid for those modes but should fail Drone Show launch readiness. On a clean demo stack, the simplest reset is to recreate the containers from the same repo/branch source:

```bash
bash multiple_sitl/create_dockers.sh 3
```

For the reusable operator-grade validation platform, including standalone action
controls (TAKEOFF, HOLD, Precision Move completion, Precision Move interrupt via
HOLD, RTL override, LAND cleanup), Mission Config/origin validation, built-in
templates, JSON plan files, deterministic artifacts, and the
runtime-vs-validator repo split, use:

- [SITL Validation Platform](sitl-validation-platform.md)

If you want the default operator regression suite, use:

```bash
python3 tools/run_sitl_validation_suite.py \
  --base-url http://127.0.0.1:5000 \
  --validator-root ~/mavsdk_drone_show \
  --repo-root ~/mavsdk_drone_show \
  --drone-ids 1 2 3
```

That default template now includes:

- Mission Config / origin validation
- a protective reset before Drone Show
- Drone Show
- standalone action controls, including Precision Move and HOLD interrupt coverage
- Smart Swarm
- Swarm Trajectory

To run only the configuration/origin gate:

```bash
python3 tools/run_sitl_validation_suite.py \
  --template config_only \
  --base-url http://127.0.0.1:5000 \
  --validator-root ~/mavsdk_drone_show \
  --repo-root ~/mavsdk_drone_show \
  --drone-ids 1 2 3
```

To run only the mission-family regression without the standalone action drill or
the configuration gate:

```bash
python3 tools/run_sitl_validation_suite.py \
  --template mission_regression \
  --base-url http://127.0.0.1:5000 \
  --validator-root ~/mavsdk_drone_show \
  --repo-root ~/mavsdk_drone_show \
  --drone-ids 1 2 3
```

If the validator tooling is being executed from a temporary checkout but the
live GCS and SITL runtime are using a different repo path, pass both roots
explicitly so Swarm Trajectory processing, configuration cleanup, and final
reset target the same runtime tree:

```bash
python3 tools/run_sitl_validation_suite.py \
  --base-url http://127.0.0.1:5000 \
  --validator-root /root/mavsdk_drone_show_validator_sync \
  --repo-root /root/mavsdk_drone_show_main_candidate_runtime_live \
  --drone-ids 1 2 3
```

The validation platform is not tied to one VPS layout. Use:

- one shared path when the validator tools and live runtime are on the same host
- split `validator_root` and `repo_root` when you need a temporary tooling checkout
- a remote `--base-url` when the validator is not running on the same host as the GCS

Plain synced validator copies are supported. A real git checkout still gives
better provenance in `suite-summary.json`, but it is not required.

For serious regression runs, the container policy is:

- recreate the fleet at the start
- let the suite recreate again before any later Drone Show leg that follows a different mission family
- let the suite recreate again at the end

That is the clean acceptance-grade default. Reusing already-running containers
is only recommended for narrow local debugging when you intentionally accept the
inherited runtime state.

QuickScout is now available as a dedicated reusable SITL gate and is included
in the current `mission_regression` and `operator_regression` bundles. The
stable gate remains intentionally bounded to the launch / hold / resume-policy /
abort lifecycle rather than broader evidence workflows.

If you want checked-in named scenarios instead of remembering plan-file paths,
the suite now ships with a bundled plan library under `tools/sitl_plans/`.

List the bundled plans:

```bash
python3 tools/run_sitl_validation_suite.py --list-bundled-plans
```

Run one by name:

```bash
python3 tools/run_sitl_validation_suite.py \
  --plan-name actions_core \
  --base-url http://127.0.0.1:5000 \
  --validator-root ~/mavsdk_drone_show \
  --repo-root ~/mavsdk_drone_show \
  --drone-ids 1 2 3
```

Current stable bundled scenarios include:

- `config_roundtrip`
- `config_then_drone_show`
- `drone_show_matrix`
- `actions_core`
- `smart_swarm_runtime`
- `swarm_trajectory_short_profile`
- `quickscout_runtime`
- `mission_regression`
- `operator_regression`

Validated advanced bundled scenarios now include:

- `integrated_mixed_mode`
- `quickscout_multi_runtime`
- `advanced_operator_regression`

Harder simultaneous mixed-mode and fault-injection scenarios are still tracked
as deferred work until they stay deterministic enough for routine use.


## Additional Resources

For more detailed information, you can consult the following:

- [Portainer Guide by Network Chuck](https://www.youtube.com/watch?v=iX0HbrfRyvc)
- [My YouTube Playlist on Project History](https://www.youtube.com/playlist?list=PLVZvZdBQdm_7ViwRhUFrmLFpFkP3VSakk)
- [My GitHub Repository](https://github.com/alireza787b/mavsdk_drone_show)
- [Netbird Knowledge Base](https://docs.netbird.io/)
- [MAVLink Official Documentation](https://mavlink.io/en/)
- [QGroundControl Documentation](https://docs.qgroundcontrol.com/master/en/)

For more tutorials, code samples, and ways to contact me, check out the following resources:

- Email: [p30planets@gmail.com](mailto:p30planets@gmail.com)
- [My LinkedIn Profile](https://www.linkedin.com/in/alireza787b/)

---

© 2025 Alireza Ghaderi

[mavsdk_drone_show](https://github.com/alireza787b/mavsdk_drone_show) - [Alireza Ghaderi](https://www.linkedin.com/in/alireza787b/)

This documentation is licensed under **CC BY-SA 4.0**. Feel free to reuse or modify according to the terms. Please attribute and link back to the original repository.
