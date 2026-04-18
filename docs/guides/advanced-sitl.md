# Advanced SITL Configuration Guide

## Overview

This guide is for advanced users who want to use their own forked or customer-owned repository and custom Docker images with MDS SITL.

If you need a full release-maintenance workflow instead of just runtime overrides, also read [SITL Custom Release Workflow](sitl-custom-release-workflow.md). That guide covers the clean path for validated custom images, packaging, archive distribution, and large-fleet pinned deployments.

If the repo/branch must also work on GCS and real drones, start with [Custom Repo Workflow](custom-repo-workflow.md) first. This guide focuses only on the SITL side.

> **⚠️ Prerequisites Required:**
> - Good understanding of Git, Docker, and Linux
> - Experience with environment variables and bash commands
> - Ability to maintain forked repositories
> - `p7zip-full` for working with the distributed `.7z` image archives
> - `pv` if you want progress output while exporting large Docker images
> - Official `MEGAcmd` if you plan to upload authenticated MEGA artifacts for your own distribution workflow

> **⚠️ Important Warning:**
> Using custom repositories disconnects you from automatic MDS updates. You'll need to manually sync your repo with upstream changes.

---

## Method 1: Using Environment Variables (Easiest)

### Step 1: Set Your Configuration

Copy and paste these commands, replacing them with your repository details. For public GitHub repos, prefer HTTPS unless the container or build environment has working SSH keys. For private GitHub repos, plain HTTPS is not enough by itself: use authenticated HTTPS with `MDS_GIT_AUTH_TOKEN_FILE`, or provide a build/runtime environment that already has valid non-interactive Git credentials such as `MDS_GIT_SSH_KEY_FILE` for SSH runtime sync.

Do **not** point `MDS_DOCKER_IMAGE` at a custom tag yet unless that image already exists. The clean first pass is:

1. choose repo + branch
2. build the custom image
3. then export `MDS_DOCKER_IMAGE` to that built tag

```bash
# Set your custom repository configuration
export MDS_REPO_URL="https://github.com/YOURORG/YOURREPO.git"
export MDS_BRANCH="your-branch-name"

# Required for private GitHub repos
install -m 600 /dev/null ~/.mds_git_read_token
printf '%s' 'YOUR_READ_ONLY_GITHUB_TOKEN' > ~/.mds_git_read_token
export MDS_GIT_AUTH_TOKEN_FILE="$HOME/.mds_git_read_token"
# Optional; GitHub's default token username already works
# export MDS_GIT_AUTH_USERNAME="x-access-token"

# Save to file for future use (optional)
cat > ~/.mds_config << EOF
export MDS_REPO_URL="https://github.com/YOURORG/YOURREPO.git"
export MDS_BRANCH="your-branch-name"
export MDS_GIT_AUTH_TOKEN_FILE="$HOME/.mds_git_read_token"
EOF
```

### Optional: Override Docker SITL Runtime Defaults

`create_dockers.sh` forwards all host `MDS_*` variables into each container, so you can tune the active headless PX4 Gazebo Harmonic launcher without editing the image.

```bash
# Example runtime overrides for startup_sitl.sh
export MDS_PX4_GZ_TARGET="gz_x500"
export MDS_QT_QPA_PLATFORM="offscreen"
export MDS_GZ_PARTITION_PREFIX="px4_sim"
export MDS_SITL_PARAM_OVERRIDES="COM_RC_IN_MODE=4,NAV_RCL_ACT=0,NAV_DLL_ACT=0,COM_DL_LOSS_T=0,CBRK_SUPPLY_CHK=894281,SDLOG_MODE=0"
export MDS_SITL_GIT_SYNC=true
export MDS_SITL_REQUIREMENTS_SYNC=true
export MDS_SITL_FILE_LOG_MODE="bounded"
export MDS_SITL_FILE_LOG_MAX_BYTES=$((5 * 1024 * 1024))
export MDS_SITL_FILE_LOG_BACKUP_COUNT=1
export MDS_SITL_STRIP_PXH_PROMPTS=true
export MDS_SITL_WAIT_FOR_READY=true
export MDS_SITL_READY_TIMEOUT_SECONDS=60
export MDS_SITL_READY_POLL_INTERVAL_SECONDS=2
export MDS_SITL_DOCKER_RESTART_POLICY="unless-stopped"
export MDS_SITL_USE_HOST_STARTUP_SCRIPT=false
export MDS_SITL_SHARE_SWARM_TRAJECTORY=true
export MDS_SITL_KEEP_ARM_TOOLCHAIN=false

# Optional debugging / routing controls
export MDS_SITL_TRACE=0
export MDS_SITL_LOG_TAIL_LINES=40
export MDS_PX4_GCS_PORT=14550
```

Notes:
- `startup_sitl.sh` always runs headless PX4 Gazebo Harmonic in Docker SITL.
- If `MDS_GZ_PARTITION` is unset, startup derives a unique Gazebo partition per drone from `MDS_GZ_PARTITION_PREFIX` and `hw_id`.
- SITL parameter overrides are passed to PX4 via `PX4_PARAM_*` environment variables at launch time, after the airframe defaults load.
- `SDLOG_MODE=0` keeps file-backed PX4 ULogs enabled in SITL so onboard log review and download workflows match real hardware more closely.
- Set `MDS_SITL_PARAM_OVERRIDES=none` if you intentionally want no SITL PX4 parameter overrides.
- `CBRK_SUPPLY_CHK=894281` is the PX4 circuit-breaker value for bypassing the supply check in SITL.
- `startup_sitl.sh` keeps runtime git sync enabled by default. Each container start fetches the requested branch, hard-resets the worktree, and cleans untracked MDS files while preserving runtime state such as `venv/`, `logs/`, `*.hwID`, and the baked `mavsdk_server`.
- `startup_sitl.sh` now validates the preserved `venv` before trusting it. If the interpreter version, site-packages layout, or core imports do not match, the container rebuilds the `venv` and re-syncs requirements automatically instead of running with a broken Python environment.
- `MDS_GIT_AUTH_TOKEN_FILE` is the preferred non-interactive path for private GitHub SITL runtime sync and image preparation. It is used only for git clone/fetch inside the containerized flow and is not written into the final flattened image.
- `MDS_GIT_SSH_KEY_FILE` is the SSH equivalent for mutable runtime sync when the host already has a deploy key or machine-user key that should be mounted into the SITL containers.
- `MDS_GIT_AUTH_TOKEN` still exists as a legacy fallback, but the preferred file-based path avoids placing the raw token in process arguments during containerized image prep/runtime.
- `MDS_SITL_GIT_SYNC=true` is a mutable latest-on-boot mode. It is convenient for active development and rapid rollout, but it is not a reproducible release mode because PX4, `mavsdk_server`, and system packages stay pinned in the image.
- Only the `mavsdk_drone_show` repo auto-syncs at container startup. PX4 and the baked `mavsdk_server` binary are intentionally pinned in the image and should be updated only through a validated image rebuild, not by runtime auto-pull.
- For validated production-style SITL releases, rebuild the image after approval so the baked repo commit, PX4 tree, and `mavsdk_server` version are all tested together. Leave `MDS_SITL_GIT_SYNC=true` only if you explicitly want mutable rollout behavior.
- Python dependencies are preinstalled in the image, then re-synced only when `requirements.txt` changes, when the `venv` marker is missing, or when runtime validation detects an unhealthy `venv`.
- Runtime file logs are bounded by default so containers stay small. Use `MDS_SITL_FILE_LOG_MODE=full` only when you intentionally want unrestricted debug logs.
- Common raw PX4 `pxh>` shell prompt noise is reduced in `sitl_simulation.log` by default so bounded logs stay readable, but you may still see occasional prompt variants in deep debug sessions.
- `startup_sitl.sh` also verifies that `mavsdk_server` exists in the repo root and will provision it automatically if a custom image is missing the binary.
- If you want to override the MAVSDK server binary at runtime, export `MDS_MAVSDK_VERSION` or `MDS_MAVSDK_URL` before launching `create_dockers.sh`. For large fleets, bake that override into the image instead of downloading on every container start.
- The image now keeps the real PX4 git checkout and submodule metadata intact. Image prep also writes PX4 provenance files into the repo root so you can audit what PX4 revision was baked into a release.
- Release image prep removes the PX4 ARM firmware toolchain by default because normal SITL runtime does not need it. If your custom image intentionally needs that toolchain, export `MDS_SITL_KEEP_ARM_TOOLCHAIN=true` before rebuilding.
- `create_dockers.sh` now waits for PX4, `mavlink-routerd`, and `coordinator.py` to be alive before it reports success. `startup_sitl.sh` runs as the container main process, and startup-wrapper logs are written to `logs/startup_sitl.log` inside each container.
- `create_dockers.sh` now uses the image-baked `startup_sitl.sh` by default so a validated image behaves consistently across hosts. Set `MDS_SITL_USE_HOST_STARTUP_SCRIPT=true` only for an explicit host-side debug override.
- `MDS_SITL_SHARE_SWARM_TRAJECTORY=true` now bind-mounts the host `shapes_sitl/swarm_trajectory/` workspace into each container through a dedicated runtime path. That keeps local Swarm Trajectory processing and same-host SITL execution consistent without making the container repo dirty.
- This shared workspace is intentionally SITL-only. Real drones and remote repos still rely on the normal git commit / push / sync workflow for mission-artifact propagation.
- Docker SITL containers now use Docker restart policy `unless-stopped` by default. Override it with `MDS_SITL_DOCKER_RESTART_POLICY` only if you intentionally want different lifecycle behavior.
- For large validated fleets, prefer a rebuilt image plus `MDS_SITL_GIT_SYNC=false` and usually `MDS_SITL_REQUIREMENTS_SYNC=false`. Mutable latest-on-boot sync is useful, but it scales poorly when 100+ containers all fetch from GitHub or re-sync Python dependencies at once.
- Running `HEADLESS=1 make px4_sitl gz_x500` manually inside the container is useful for raw PX4 debugging, but it bypasses `startup_sitl.sh`, so it will not apply the MDS `PX4_PARAM_*` overrides or `mavsdk_server` provisioning checks.
- The current stock SITL image does not auto-start `mavlink2rest`. The router still forwards MAVLink to `127.0.0.1:14569` for optional custom use, but `http://DRONE_IP:8088` should not be assumed in the default workflow.

### Step 2: Build Custom Docker Image (If Needed)

Before this step, make sure the official base image already exists locally as `mavsdk-drone-show-sitl:latest`.
If it does not, follow [SITL Comprehensive Guide](sitl-comprehensive.md) first and load the official archive.

```bash
# If you need a custom Docker image with your repository:
cd /path/to/mavsdk_drone_show
bash tools/build_custom_image.sh

# After the image exists, point future launches at it
export MDS_DOCKER_IMAGE="your-custom-image:latest"
echo 'export MDS_DOCKER_IMAGE="your-custom-image:latest"' >> ~/.mds_config
```

`tools/build_custom_image.sh` ensures `/root/mavsdk_drone_show/mavsdk_server` exists in the final image. It now really does honor exported `MDS_MAVSDK_VERSION` and `MDS_MAVSDK_URL` during image preparation, so you can bake a pinned MAVSDK binary into the image instead of downloading it at container boot. If you build images manually by copying only git-tracked files into a container, you must preserve or re-download `mavsdk_server` or takeoff/mission scripts will fail at runtime. For public GitHub repos, both the runtime launcher and image builder retry over HTTPS automatically if an SSH GitHub URL fails inside the container. For private GitHub repos, export `MDS_GIT_AUTH_TOKEN_FILE` for image builds; for mutable runtime sync, you can also mount `MDS_GIT_SSH_KEY_FILE` when the host already has a valid non-interactive SSH key.
`tools/build_custom_image.sh` now builds a clean custom image without `docker commit`. It prepares a shallow repo checkout for your selected branch, pre-installs the Python venv, preserves runtime git sync for later container startups, and flattens the final filesystem into a fresh image layer stack.

### Step 3: Deploy Your Drones

```bash
# Load your configuration (if saved to file)
source ~/.mds_config

# Deploy drones with your custom configuration
# Only set MDS_DOCKER_IMAGE here if the custom image already exists.
bash multiple_sitl/create_dockers.sh 5

# Start dashboard (development mode by default)
bash app/linux_dashboard_start.sh --sitl

# Production-style launch if needed
# bash app/linux_dashboard_start.sh --prod --sitl

# FastAPI production intentionally stays single-worker until backend state is externalized.

# Optional on smaller VPSes: give the React production build more heap
# export MDS_REACT_BUILD_MAX_OLD_SPACE_SIZE=4096
```

---

## Method 2: Using HTTPS Repository (No SSH Keys)

If you don't want to set up SSH keys:

```bash
# Use HTTPS URL instead
export MDS_REPO_URL="https://github.com/YOURORG/YOURREPO.git"
export MDS_BRANCH="your-branch-name"

# Deploy
bash multiple_sitl/create_dockers.sh 5
```

---

## Method 3: Command Line Arguments

Some scripts support direct arguments:

```bash
# Dashboard with custom branch
# This performs a repo sync to the requested branch before startup.
bash app/linux_dashboard_start.sh --sitl -b your-branch-name

# Build custom image with arguments
bash tools/build_custom_image.sh "https://github.com/YOURORG/YOURREPO.git" "your-branch"
```

---

## Common Examples

### Example 1: Company Fork

```bash
export MDS_REPO_URL="https://github.com/mycompany/mds-fork.git"
export MDS_BRANCH="production"
export MDS_DOCKER_IMAGE="mycompany-mds-sitl:v1.0"

bash tools/build_custom_image.sh
bash multiple_sitl/create_dockers.sh 10
```

### Example 2: Development Branch

```bash
export MDS_REPO_URL="https://github.com/myusername/mds-dev.git"
export MDS_BRANCH="feature-branch"

bash multiple_sitl/create_dockers.sh 3
```

### Example 3: Different Environments

```bash
# Development
export MDS_REPO_URL="https://github.com/company/mds.git"
export MDS_BRANCH="develop"
bash multiple_sitl/create_dockers.sh 2

# Production
export MDS_REPO_URL="https://github.com/company/mds.git"
export MDS_BRANCH="production"
bash multiple_sitl/create_dockers.sh 20
```

---

## Getting Help

### Check Script Options

Most scripts have help:

```bash
bash tools/build_custom_image.sh --help
bash multiple_sitl/create_dockers.sh --help
bash app/linux_dashboard_start.sh --help
```

### Verify Your Configuration

```bash
# Check what will be used
echo "Repository: $MDS_REPO_URL"
echo "Branch: $MDS_BRANCH"
echo "Docker Image: $MDS_DOCKER_IMAGE"

# Test repository access
git ls-remote "$MDS_REPO_URL"
```

### Check Container Status

```bash
# See running containers
docker ps

# Check container repository
docker exec drone-1 bash -c "cd /root/mavsdk_drone_show && git remote -v"
```

---

## Troubleshooting

### Problem: SSH Authentication Failed

**Solution:** Use HTTPS instead, or let public GitHub SSH URLs auto-fallback inside the container:
```bash
export MDS_REPO_URL="https://github.com/YOURORG/YOURREPO.git"
```

For a private repo, the fallback only works if the resulting HTTPS access is also authenticated.

### Problem: Docker Image Not Found

**Solution:** Build the image first:
```bash
bash tools/build_custom_image.sh
```

### Problem: Containers Using Wrong Repository

**Solution:** Check environment variables are set:
```bash
echo $MDS_REPO_URL
echo $MDS_BRANCH
```

---

## Docker Container Development Workflow

**⚠️ IMPORTANT:** This section is ONLY for creating custom Docker images. For actual SITL drone operations, always use `bash multiple_sitl/create_dockers.sh` which handles hwid generation and proper drone setup.

For advanced users who want to maintain custom images:

### Step 1: Develop In Your Fork Or Working Tree

```bash
cd /path/to/mavsdk_drone_show
git remote set-url origin https://github.com/YOURORG/YOURREPO.git
git checkout your-branch
# edit, commit, and push your changes in git first
```

### Step 2: Build A Clean Image From Git

```bash
# Rebuild from your committed fork/branch
bash tools/build_custom_image.sh "https://github.com/YOURORG/YOURREPO.git" "your-branch" "mycompany-mds-sitl:v5-custom"
```

This is the recommended workflow. It keeps the resulting image reproducible and avoids container-local edits that would be overwritten by startup git sync. For the full validated release flow, including packaging and redistribution, see [SITL Custom Release Workflow](sitl-custom-release-workflow.md).

### Step 3: Optional Container Debugging

```bash
# Temporary shell for debugging only, not as the source of truth
sudo docker run -it --rm --name my-drone-debug mycompany-mds-sitl:v5-custom /bin/bash
```

If you debug inside a container, treat any edits there as disposable unless you copy them back into git and rebuild the image cleanly.

### Step 4: Export Container (Optional)

```bash
# Install optional helper tools if needed
sudo apt install -y p7zip-full pv

cd ~

# Export to tar file for backup/distribution
docker save mycompany-mds-sitl:v5-custom mycompany-mds-sitl:latest | pv > mycompany-mds-sitl-image.tar

# Optional: compress the tar afterwards for storage or sharing
7z a mycompany-mds-sitl-image.7z mycompany-mds-sitl-image.tar

# Verify the compressed archive before uploading or sharing it
7z t mycompany-mds-sitl-image.7z
```

For repeatable official-style packaging, prefer the helper script:

```bash
bash tools/package_sitl_image.sh --image-repo mycompany-mds-sitl --version-tag v5-custom
```

That helper keeps a stable archive basename, exports the Docker tags inside the tar, verifies the generated `.7z` automatically, writes checksum/manifest files, and deletes the raw `.tar` afterwards unless you pass `--keep-tar`.

If you need to rebuild and package a clean flattened release in one step, use:

```bash
bash tools/release_sitl_image.sh \
  --base-image mavsdk-drone-show-sitl:latest \
  --image-repo mycompany-mds-sitl \
  --version-tag v5-custom \
  --repo-url "https://github.com/YOURORG/YOURREPO.git" \
  --branch "your-branch" \
  --package
```

If you publish archives for other users, keep one stable archive filename and let Docker tags carry the actual release version.

### Step 5: Use Your Custom Image for Real SITL Operations

```bash
# Set your custom image for future SITL deployments
export MDS_DOCKER_IMAGE="mycompany-mds-sitl:v5-custom"

# NOW use create_dockers.sh for actual SITL drone operations
# (This will properly generate hwid and configure each drone)
bash multiple_sitl/create_dockers.sh 5
```

### Regular Maintenance Workflow

```bash
# Update your repo or branch first, then rebuild a clean image
cd /path/to/mavsdk_drone_show
git pull --ff-only

export MDS_REPO_URL="https://github.com/mycompany/mds-fork.git"
export MDS_BRANCH="production"

bash tools/build_custom_image.sh "$MDS_REPO_URL" "$MDS_BRANCH" "mycompany-mds-sitl:v5-custom-2"
```

> **Current official release tag:** the validated shared SITL image is published as `mavsdk-drone-show-sitl:v5` and also tagged as `mavsdk-drone-show-sitl:latest`.

> **Best practice:** keep custom image creation reproducible. Avoid using `docker commit` or hand-edited running containers as your normal release workflow, because they hide state and are overwritten by startup sync.
>
> For actual SITL drone operations, always use `bash multiple_sitl/create_dockers.sh` which handles proper drone setup, hwid generation, and network configuration.

---

## Commercial Support & Custom Implementation

### For Companies and Real-World Deployments

The basic SITL demo is designed for evaluation and learning. For production deployments, custom features, or hardware implementation, professional support is available:

**Services Available:**
- ✈️ **Custom SITL Features** - Specialized simulation scenarios and advanced functionality
- 🚁 **Hardware Implementation** - Real drone deployment with safety protocols
- 🏢 **Enterprise Integration** - Custom APIs, cloud integration, fleet management
- 📊 **Performance Optimization** - Large-scale swarm optimization and mission planning
- 🔧 **Training & Support** - Team training and ongoing technical support
- 🎯 **Custom Mission Types** - Specialized applications beyond standard formations

**Contact for Professional Implementation:**
- **Email:** [p30planets@gmail.com](mailto:p30planets@gmail.com)
- **LinkedIn:** [Alireza Ghaderi](https://www.linkedin.com/in/alireza787b/)

> **🏢 Note for Companies:** Real-world drone deployments require aviation compliance, safety protocols, and specialized expertise. Contact us for professional consultation and implementation contracts.

---

## Support

For help with advanced configuration:
- **Email:** [p30planets@gmail.com](mailto:p30planets@gmail.com)
- **LinkedIn:** [Alireza Ghaderi](https://www.linkedin.com/in/alireza787b/)

---

*Back to: [Main SITL Guide](sitl-comprehensive.md)*
