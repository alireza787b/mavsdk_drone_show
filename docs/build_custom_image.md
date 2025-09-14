# MDS Custom Docker Image Builder

This script (`tools/build_custom_image.sh`) automates the creation of custom Docker images for advanced MDS deployments.

## Overview

The build script takes a base MDS Docker image and customizes it with your specific repository and branch configuration, eliminating the need for manual Docker container modifications.

## Quick Usage

```bash
# Navigate to MDS directory
cd /path/to/mavsdk_drone_show

# Basic usage (uses environment variables or defaults)
bash tools/build_custom_image.sh

# Specify repository and branch
bash tools/build_custom_image.sh git@github.com:company/fork.git production

# Full specification with custom image name
bash tools/build_custom_image.sh git@github.com:company/fork.git production company-drone:v1.0

# Get detailed help
bash tools/build_custom_image.sh --help
```

## Environment Variables

The script supports environment variable configuration:

```bash
export MDS_REPO_URL="git@github.com:company/fork.git"
export MDS_BRANCH="production"
export MDS_DOCKER_IMAGE="company-drone:v1.0"

# Then run with defaults
bash tools/build_custom_image.sh
```

| Variable | Purpose | Default |
|----------|---------|---------|
| `MDS_REPO_URL` | Git repository URL (SSH or HTTPS) | `git@github.com:alireza787b/mavsdk_drone_show.git` |
| `MDS_BRANCH` | Git branch name | `main-candidate` |
| `MDS_DOCKER_IMAGE` | Target Docker image name | `drone-template:custom` |

## Prerequisites

- ✅ Base Docker image `drone-template:latest` must be loaded
- ✅ Git access to the specified repository (SSH keys configured if using SSH URLs)
- ✅ Docker daemon running with appropriate permissions
- ✅ Network connectivity to access the repository

## What the Script Does

1. **Creates temporary container** from base image
2. **Updates repository configuration** inside container
3. **Switches to your branch** and pulls latest changes
4. **Commits customized container** as new image
5. **Cleans up temporary containers** automatically

## Complete Documentation

For comprehensive deployment workflows and examples:

📖 **[Advanced Deployment Guide](advanced_deployment.md)** - Complete step-by-step implementation

## Troubleshooting

### Common Issues

**Script fails with "base image not found":**
```bash
# Ensure base image is loaded
docker images | grep drone-template
# If not found, load it:
docker load < drone-template-v3.tar
```

**Git authentication errors:**
```bash
# For SSH URLs, test git access:
ssh -T git@github.com

# Alternative: Use HTTPS URLs (no SSH keys needed)
bash tools/build_custom_image.sh https://github.com/company/fork.git production
```

**Verbose debugging:**
```bash
bash tools/build_custom_image.sh --verbose
```

---

## Related Documentation

- 📖 [Main SITL Guide](sitl_demo_docker.md) - Getting started with MDS
- 📖 [Advanced Deployment Guide](advanced_deployment.md) - Complete customization workflow
- 📁 [Tools Directory](../tools/) - All MDS automation scripts

