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

## Docker Container Development Workflow

**⚠️ IMPORTANT:** This section is ONLY for creating custom Docker images. For actual SITL drone operations, always use `bash multiple_sitl/create_dockers.sh` which handles hwid generation and proper drone setup.

For advanced users who want to develop inside containers and maintain custom images:

### Step 1: Create Development Container

```bash
# Create a template container directly (avoid create_dockers.sh to prevent hwid generation)
sudo docker run -it --name my-drone-dev drone-template:latest /bin/bash
```

### Step 2: Make Your Changes Inside Container

```bash
# Inside container - make your changes:
cd /root/mavsdk_drone_show

# Update to your repository if needed
git remote set-url origin git@github.com:YOURORG/YOURREPO.git
git pull origin your-branch

# Edit files, test changes, debug issues
# Install new packages, modify configuration
# Make any customizations you need
```

### Step 3: Commit Your Changes

```bash
# Exit the container first
exit

# Commit container to new image version
docker commit -m "Updated custom drone image" my-drone-dev drone-template:v3.1

# Tag as latest (optional)
docker tag drone-template:v3.1 drone-template:latest
```

### Step 4: Export Container (Optional)

```bash
# Export to tar file for backup/distribution
docker save -o ~/drone-template_v3.tar drone-template:v3.1

# Or compress with 7z for smaller size
docker save drone-template:v3.1 | 7z a -si ~/drone-template_v3.7z
```

### Step 5: Use Your Custom Image for Real SITL Operations

```bash
# Set your custom image for future SITL deployments
export MDS_DOCKER_IMAGE="drone-template:v3.1"

# NOW use create_dockers.sh for actual SITL drone operations
# (This will properly generate hwid and configure each drone)
bash multiple_sitl/create_dockers.sh 5
```

### Regular Maintenance Workflow

```bash
# Start your development container again (for image updates only)
sudo docker run -it --name my-drone-dev-v2 drone-template:latest /bin/bash

# Make updates inside container
cd /root/mavsdk_drone_show
git pull

# Exit and commit new version
exit
docker commit -m "Updated to latest version" my-drone-dev-v2 drone-template:v3.2
docker tag drone-template:v3.2 drone-template:latest

# Clean up old containers
docker rm my-drone-dev my-drone-dev-v2
```

> **💡 Pro Tip:** This workflow is for customizing Docker images only. For actual SITL drone operations, always use `bash multiple_sitl/create_dockers.sh` which handles proper drone setup, hwid generation, and network configuration.

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

*Back to: [Main SITL Guide](sitl_demo_docker.md)*