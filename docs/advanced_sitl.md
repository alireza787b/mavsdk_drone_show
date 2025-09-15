# Advanced SITL Configuration Guide

## Overview

This guide is for advanced users who want to use their own forked repository or custom Docker images with MDS SITL.

> **⚠️ Prerequisites Required:**
> - Good understanding of Git, Docker, and Linux
> - Experience with environment variables and bash commands
> - Ability to maintain forked repositories

> **⚠️ Important Warning:**
> Using custom repositories disconnects you from automatic MDS updates. You'll need to manually sync your fork with upstream changes.

---

## Method 1: Using Environment Variables (Easiest)

### Step 1: Set Your Configuration

Copy and paste these commands, replacing with your repository details:

```bash
# Set your custom repository configuration
export MDS_REPO_URL="git@github.com:YOURORG/YOURREPO.git"
export MDS_BRANCH="your-branch-name"
export MDS_DOCKER_IMAGE="your-custom-image:latest"

# Save to file for future use (optional)
cat > ~/.mds_config << EOF
export MDS_REPO_URL="git@github.com:YOURORG/YOURREPO.git"
export MDS_BRANCH="your-branch-name"
export MDS_DOCKER_IMAGE="your-custom-image:latest"
EOF
```

### Step 2: Build Custom Docker Image (If Needed)

```bash
# If you need a custom Docker image with your repository:
cd /path/to/mavsdk_drone_show
bash tools/build_custom_image.sh
```

### Step 3: Deploy Your Drones

```bash
# Load your configuration (if saved to file)
source ~/.mds_config

# Deploy drones with your custom configuration
bash multiple_sitl/create_dockers.sh 5

# Start dashboard
bash app/linux_dashboard_start.sh --sitl
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
bash app/linux_dashboard_start.sh --sitl -b your-branch-name

# Build custom image with arguments
bash tools/build_custom_image.sh "git@github.com:YOURORG/YOURREPO.git" "your-branch"
```

---

## Common Examples

### Example 1: Company Fork

```bash
export MDS_REPO_URL="git@github.com:mycompany/mds-fork.git"
export MDS_BRANCH="production"
export MDS_DOCKER_IMAGE="mycompany-drone:v1.0"

bash tools/build_custom_image.sh
bash multiple_sitl/create_dockers.sh 10
```

### Example 2: Development Branch

```bash
export MDS_REPO_URL="git@github.com:myusername/mds-dev.git"
export MDS_BRANCH="feature-branch"

bash multiple_sitl/create_dockers.sh 3
```

### Example 3: Different Environments

```bash
# Development
export MDS_REPO_URL="git@github.com:company/mds.git"
export MDS_BRANCH="develop"
bash multiple_sitl/create_dockers.sh 2

# Production
export MDS_REPO_URL="git@github.com:company/mds.git"
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

**Solution:** Use HTTPS instead:
```bash
export MDS_REPO_URL="https://github.com/YOURORG/YOURREPO.git"
```

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

## Support

For help with advanced configuration:
- **Email:** [p30planets@gmail.com](mailto:p30planets@gmail.com)
- **LinkedIn:** [Alireza Ghaderi](https://www.linkedin.com/in/alireza787b/)

---

*Back to: [Main SITL Guide](sitl_demo_docker.md)*