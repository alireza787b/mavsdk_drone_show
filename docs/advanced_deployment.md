# Advanced MDS Deployment & Customization Guide

## Overview

This guide provides step-by-step instructions for advanced users who need to deploy MDS (MAVSDK Drone Show) with custom repositories, configurations, or in production environments.

> **⚠️ Prerequisites Required**
>
> This guide assumes you have:
> - **Strong understanding of Git, Docker, and Linux systems**
> - **Experience with environment variables and container orchestration**
> - **Ability to maintain independent repository forks and syncing**
> - **DevOps/IT expertise for production deployments**
>
> **🚨 Important Warning:**
> Advanced customization **disconnects you from automatic MDS updates**. You'll need to manually sync your fork with upstream changes and maintain your custom Docker images.

---

## Table of Contents

1. [Understanding the Problem](#understanding-the-problem)
2. [MDS Repository Configuration System](#mds-repository-configuration-system)
3. [Environment Variables Reference](#environment-variables-reference)
4. [Step-by-Step Implementation Guide](#step-by-step-implementation-guide)
5. [Production Deployment Scenarios](#production-deployment-scenarios)
6. [Maintenance and Updates](#maintenance-and-updates)
7. [Troubleshooting](#troubleshooting)
8. [Best Practices](#best-practices)

---

## Understanding the Problem

### Default MDS Behavior

By default, MDS is configured to work with the main repository:
- **Repository:** `git@github.com:alireza787b/mavsdk_drone_show.git`
- **Branch:** `main-candidate`
- **Docker Image:** `drone-template:latest`

This configuration is hardcoded in multiple files across the codebase, making it difficult for organizations to:
- Use their own forked repositories
- Deploy custom branches for different environments (dev/staging/prod)
- Maintain separate configurations for different teams
- Integrate with existing CI/CD pipelines

### The Solution: Environment Variable Configuration System

MDS v3.1+ introduces a professional environment variable configuration system that allows:
- ✅ **Runtime repository configuration** without modifying code
- ✅ **Multiple deployment environments** using the same codebase
- ✅ **Custom Docker image integration** for enterprise deployments
- ✅ **100% backward compatibility** for existing users

---

## MDS Repository Configuration System

### Architecture Overview

The new system uses a hierarchical configuration approach:

```
1. Environment Variables (Highest Priority)
   ↓
2. Built-in Defaults (Fallback)
   ↓
3. 100% Backward Compatibility (No env vars = original behavior)
```

### Components Affected

The following MDS components now support environment variable configuration:

| Component | File | Purpose |
|-----------|------|---------|
| **Python Core** | `src/params.py` | Core parameter management for all Python modules |
| **Docker Containers** | `multiple_sitl/startup_sitl.sh` | Container startup and repository sync |
| **Container Creation** | `multiple_sitl/create_dockers.sh` | Docker image selection and env var passing |
| **Hardware Deployment** | `tools/raspberry_setup.sh` | Raspberry Pi and hardware setup |
| **HTTPS Git Updates** | `tools/update_repo_https.sh` | Repository updates via HTTPS |
| **Dashboard Launcher** | `app/linux_dashboard_start.sh` | GCS dashboard with branch selection |

---

## Environment Variables Reference

### Primary Configuration Variables

| Variable | Purpose | Format | Default |
|----------|---------|---------|---------|
| `MDS_REPO_URL` | Git repository URL | SSH: `git@github.com:org/repo.git`<br>HTTPS: `https://github.com/org/repo.git` | `git@github.com:alireza787b/mavsdk_drone_show.git` |
| `MDS_BRANCH` | Git branch name | Any valid branch name | `main-candidate` |
| `MDS_DOCKER_IMAGE` | Docker image name | `name:tag` format | `drone-template:latest` |

### Usage Examples

```bash
# SSH Repository (requires SSH keys)
export MDS_REPO_URL="git@github.com:mycompany/drone-fork.git"
export MDS_BRANCH="production"
export MDS_DOCKER_IMAGE="mycompany-drone:v1.0"

# HTTPS Repository (no SSH keys needed)
export MDS_REPO_URL="https://github.com/mycompany/drone-fork.git"
export MDS_BRANCH="staging"
export MDS_DOCKER_IMAGE="staging-drone:latest"

# Mixed Configuration (some custom, some default)
export MDS_REPO_URL="git@github.com:mycompany/drone-fork.git"
# MDS_BRANCH will use default: main-candidate
# MDS_DOCKER_IMAGE will use default: drone-template:latest
```

---

## Step-by-Step Implementation Guide

### Phase 1: Repository Preparation

#### Step 1: Fork the MDS Repository

1. **Navigate to the main MDS repository:**
   ```
   https://github.com/alireza787b/mavsdk_drone_show
   ```

2. **Click "Fork" in the top-right corner**
   - Choose your organization or personal account
   - Keep the repository name or customize it
   - Clone all branches (recommended)

3. **Clone your fork locally:**
   ```bash
   git clone git@github.com:YOURORG/YOURREPO.git
   cd YOURREPO
   ```

4. **Set up upstream remote (for future syncing):**
   ```bash
   git remote add upstream git@github.com:alireza787b/mavsdk_drone_show.git
   git remote -v  # Verify remotes are set correctly
   ```

#### Step 2: Create and Customize Your Branch

1. **Create your deployment branch:**
   ```bash
   # Create from main-candidate (recommended)
   git checkout main-candidate
   git pull upstream main-candidate
   git checkout -b production-v1

   # Or create from main
   git checkout main
   git pull upstream main
   git checkout -b staging-v1
   ```

2. **Make your customizations:**
   ```bash
   # Example customizations:
   # - Modify flight parameters in config files
   # - Update drone show choreography
   # - Add custom telemetry endpoints
   # - Integrate with your monitoring systems

   # Commit your changes
   git add .
   git commit -m "Add production customizations for Company X deployment"
   git push origin production-v1
   ```

### Phase 2: Custom Docker Image Creation

#### Step 3: Prepare Your Environment

1. **Ensure you have the base Docker image:**
   ```bash
   # Download the base image (if not already done)
   # Follow the main guide: docs/sitl_demo_docker.md
   docker load < drone-template-v3.tar
   docker images | grep drone-template  # Verify image loaded
   ```

2. **Set your environment variables:**
   ```bash
   # Create a deployment configuration script
   cat > ~/.mds_config << 'EOF'
   # MDS Advanced Deployment Configuration
   export MDS_REPO_URL="git@github.com:YOURORG/YOURREPO.git"
   export MDS_BRANCH="production-v1"
   export MDS_DOCKER_IMAGE="yourcompany-drone:v1.0"
   EOF

   # Load the configuration
   source ~/.mds_config
   echo "Configuration loaded:"
   echo "  MDS_REPO_URL: $MDS_REPO_URL"
   echo "  MDS_BRANCH: $MDS_BRANCH"
   echo "  MDS_DOCKER_IMAGE: $MDS_DOCKER_IMAGE"
   ```

#### Step 4: Build Your Custom Docker Image

1. **Use the automated build script:**
   ```bash
   cd /path/to/your/mds/clone
   bash tools/build_custom_image.sh \
     "$MDS_REPO_URL" \
     "$MDS_BRANCH" \
     "$MDS_DOCKER_IMAGE"
   ```

   📖 **For detailed build script options and troubleshooting:** [Build Script Documentation](build_custom_image.md)

2. **Verify the image was created:**
   ```bash
   docker images | grep yourcompany-drone
   # Should show your custom image with the specified tag
   ```

3. **Test the custom image (optional):**
   ```bash
   # Test run a container to verify it works
   docker run --name test-custom -d "$MDS_DOCKER_IMAGE" tail -f /dev/null
   docker exec test-custom bash -c "cd /root/mavsdk_drone_show && git remote -v && git branch"
   docker rm -f test-custom
   ```

### Phase 3: Deployment

#### Step 5: Deploy with Custom Configuration

1. **Load your environment configuration:**
   ```bash
   source ~/.mds_config
   ```

2. **Deploy your drone fleet:**
   ```bash
   cd /path/to/your/mds/clone

   # Deploy 5 drones with your custom configuration
   bash multiple_sitl/create_dockers.sh 5
   ```

3. **Start the GCS dashboard:**
   ```bash
   # The dashboard will automatically use your custom branch
   bash app/linux_dashboard_start.sh --sitl
   ```

4. **Verify deployment:**
   ```bash
   # Check that containers are using your custom image
   docker ps --format "table {{.Names}}\t{{.Image}}"

   # Verify containers are using your repository
   docker exec drone-1 bash -c "cd /root/mavsdk_drone_show && git remote -v"
   ```

---

## Production Deployment Scenarios

### Scenario 1: Multi-Environment Deployment

**Use Case:** Separate dev/staging/prod environments

```bash
# Development Environment
export MDS_REPO_URL="git@github.com:mycompany/mds-fork.git"
export MDS_BRANCH="develop"
export MDS_DOCKER_IMAGE="mycompany-drone:dev"
bash multiple_sitl/create_dockers.sh 2  # Small dev deployment

# Staging Environment
export MDS_REPO_URL="git@github.com:mycompany/mds-fork.git"
export MDS_BRANCH="staging"
export MDS_DOCKER_IMAGE="mycompany-drone:staging"
bash multiple_sitl/create_dockers.sh 10  # Medium staging deployment

# Production Environment
export MDS_REPO_URL="git@github.com:mycompany/mds-fork.git"
export MDS_BRANCH="production"
export MDS_DOCKER_IMAGE="mycompany-drone:v1.0"
bash multiple_sitl/create_dockers.sh 50  # Large production deployment
```

### Scenario 2: Multi-Organization Deployment

**Use Case:** Different teams or clients using the same server

```bash
# Team A Deployment
export MDS_REPO_URL="git@github.com:team-a/mds-custom.git"
export MDS_BRANCH="team-a-config"
export MDS_DOCKER_IMAGE="team-a-drone:latest"
bash multiple_sitl/create_dockers.sh 20 --subnet 172.18.0.0/24 --start-id 1

# Team B Deployment (different subnet to avoid conflicts)
export MDS_REPO_URL="git@github.com:team-b/mds-custom.git"
export MDS_BRANCH="team-b-config"
export MDS_DOCKER_IMAGE="team-b-drone:latest"
bash multiple_sitl/create_dockers.sh 15 --subnet 172.19.0.0/24 --start-id 101
```

### Scenario 3: CI/CD Integration

**Use Case:** Automated deployments via Jenkins, GitHub Actions, etc.

```bash
# .env file for CI/CD
MDS_REPO_URL=${CI_REPOSITORY_URL}
MDS_BRANCH=${CI_COMMIT_REF_NAME}
MDS_DOCKER_IMAGE=${CI_PROJECT_NAME}-drone:${CI_COMMIT_SHORT_SHA}

# CI/CD Pipeline Step
export $(cat .env | xargs)
bash tools/build_custom_image.sh
bash multiple_sitl/create_dockers.sh ${DRONE_COUNT:-10}
```

---

## Maintenance and Updates

### Keeping Your Fork Synchronized

1. **Regular upstream syncing (recommended monthly):**
   ```bash
   cd /path/to/your/fork
   git fetch upstream
   git checkout main-candidate  # or your main branch
   git merge upstream/main-candidate

   # Resolve any conflicts if they occur
   # Test thoroughly before deploying

   git push origin main-candidate
   ```

2. **Update your deployment branches:**
   ```bash
   git checkout production-v1
   git merge main-candidate  # Integrate upstream changes
   # Resolve conflicts, test, then push
   git push origin production-v1
   ```

3. **Rebuild custom Docker images:**
   ```bash
   # After updating your repository, rebuild images
   source ~/.mds_config
   bash tools/build_custom_image.sh
   ```

### Monitoring and Logging

1. **Container health monitoring:**
   ```bash
   # Check all drone containers
   docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"

   # Monitor resource usage
   docker stats --no-stream
   ```

2. **Repository status verification:**
   ```bash
   # Verify all containers are using correct repository/branch
   for container in $(docker ps --format "{{.Names}}" | grep drone-); do
     echo "=== $container ==="
     docker exec $container bash -c "cd /root/mavsdk_drone_show && git remote -v && git branch --show-current"
   done
   ```

---

## Troubleshooting

### Common Issues and Solutions

#### Issue 1: SSH Key Authentication Problems

**Symptoms:** Git clone/pull failures with SSH URLs

**Solutions:**
1. **Ensure SSH keys are available in Docker images:**
   ```bash
   # Test SSH access to your repository
   ssh -T git@github.com

   # If failed, add SSH keys to the Docker image during build
   # Advanced: Mount SSH keys as volumes (security considerations apply)
   ```

2. **Use HTTPS URLs instead:**
   ```bash
   export MDS_REPO_URL="https://github.com/yourorg/yourrepo.git"
   # HTTPS doesn't require SSH key setup
   ```

#### Issue 2: Environment Variables Not Inherited

**Symptoms:** Containers using default repository despite setting env vars

**Solutions:**
1. **Verify environment variables before deployment:**
   ```bash
   echo "MDS_REPO_URL: $MDS_REPO_URL"
   echo "MDS_BRANCH: $MDS_BRANCH"
   echo "MDS_DOCKER_IMAGE: $MDS_DOCKER_IMAGE"
   ```

2. **Check Docker env var passing:**
   ```bash
   # Verify containers receive the environment variables
   docker exec drone-1 env | grep MDS_
   ```

#### Issue 3: Git Conflicts During Updates

**Symptoms:** Merge conflicts when syncing with upstream

**Solutions:**
1. **Create backup before merging:**
   ```bash
   git checkout -b backup-$(date +%Y%m%d)
   git checkout production-v1
   ```

2. **Use rebase strategy for cleaner history:**
   ```bash
   git rebase upstream/main-candidate
   # Resolve conflicts interactively
   ```

#### Issue 4: Docker Image Build Failures

**Symptoms:** Custom image creation fails

**Solutions:**
1. **Check base image availability:**
   ```bash
   docker images | grep drone-template
   # Ensure base image exists
   ```

2. **Verify network connectivity:**
   ```bash
   # Test repository access
   git ls-remote "$MDS_REPO_URL"
   ```

3. **Use verbose mode for debugging:**
   ```bash
   bash tools/build_custom_image.sh --verbose
   ```

---

## Best Practices

### Security Considerations

1. **SSH Key Management:**
   - Use deploy keys for repository access
   - Rotate keys regularly
   - Never embed private keys in Docker images

2. **Environment Variables:**
   - Use secrets management for sensitive values
   - Don't log environment variables in production
   - Consider using Docker secrets or external config management

3. **Network Security:**
   - Use custom Docker networks with appropriate isolation
   - Configure firewall rules for drone communication ports
   - Monitor container network traffic

### Operational Excellence

1. **Configuration Management:**
   ```bash
   # Use configuration files instead of inline env vars
   cat > production.env << 'EOF'
   MDS_REPO_URL=git@github.com:mycompany/mds-prod.git
   MDS_BRANCH=production-v2.1
   MDS_DOCKER_IMAGE=mycompany-drone:v2.1.0
   EOF

   # Load configuration
   set -a && source production.env && set +a
   ```

2. **Version Management:**
   - Tag your repository releases: `git tag v1.0.0`
   - Use semantic versioning for Docker images
   - Maintain changelog for your customizations

3. **Testing Strategy:**
   - Always test custom configurations in staging first
   - Run integration tests before production deployment
   - Keep rollback procedures documented

4. **Documentation:**
   - Document your customizations and deployment procedures
   - Maintain runbooks for common operational tasks
   - Keep team contacts and escalation procedures updated

### Performance Optimization

1. **Resource Management:**
   ```bash
   # Monitor resource usage during deployment
   bash multiple_sitl/create_dockers.sh 10 --verbose

   # Adjust based on server capacity
   # Rule of thumb: 1 CPU core + 1GB RAM per 2-3 drone instances
   ```

2. **Network Optimization:**
   - Use appropriate Docker network subnets
   - Configure DNS resolution for better performance
   - Monitor network latency between containers

---

## Advanced Topics

### Custom Docker Image Optimization

For organizations requiring highly customized images:

```bash
# Create a custom Dockerfile extending the base image
cat > Dockerfile.custom << 'EOF'
FROM drone-template:latest

# Add your customizations
RUN apt-get update && apt-get install -y your-custom-packages
COPY custom-configs/ /root/mavsdk_drone_show/
COPY custom-scripts/ /usr/local/bin/

# Set custom environment defaults
ENV COMPANY_CONFIG=production
ENV CUSTOM_PARAM=value

# Custom initialization script
COPY init-custom.sh /root/
RUN chmod +x /root/init-custom.sh
EOF

# Build your custom base image
docker build -t mycompany-drone-base:v1.0 -f Dockerfile.custom .

# Use your custom base instead of the standard template
export MDS_DOCKER_IMAGE="mycompany-drone-base:v1.0"
```

### Integration with External Systems

```bash
# Example: Integration with monitoring systems
export MONITORING_ENDPOINT="https://metrics.company.com/api/v1/metrics"
export ALERT_WEBHOOK="https://alerts.company.com/webhook/mds"

# Example: Custom logging configuration
export LOG_AGGREGATOR="syslog://logs.company.com:514"
export LOG_LEVEL="INFO"

# These can be used in your custom startup scripts
```

---

## Support and Community

### Getting Help

1. **Primary Documentation:** [Main SITL Guide](sitl_demo_docker.md)
2. **GitHub Issues:** [Report Issues](https://github.com/alireza787b/mavsdk_drone_show/issues)
3. **Professional Support:**
   - LinkedIn: [Alireza Ghaderi](https://www.linkedin.com/in/alireza787b/)
   - Email: [p30planets@gmail.com](mailto:p30planets@gmail.com)

### Contributing Back

If you develop improvements that would benefit the wider community:

1. **Create feature branches for contributions:**
   ```bash
   git checkout -b feature/improved-logging
   # Make improvements
   git commit -m "Improve logging system for production deployments"
   ```

2. **Submit pull requests to the main repository:**
   - Keep changes focused and well-documented
   - Include tests and documentation updates
   - Follow the project's coding standards

---

## Conclusion

The MDS advanced deployment system provides enterprise-grade flexibility while maintaining simplicity for basic users. By following this guide, you can:

- ✅ Deploy MDS with your custom repositories and configurations
- ✅ Maintain multiple environments with different settings
- ✅ Integrate with existing CI/CD and monitoring systems
- ✅ Scale deployments across multiple teams and organizations

Remember that with great power comes great responsibility - advanced deployments require ongoing maintenance, monitoring, and synchronization with upstream updates.

**Happy flying with your customized MDS deployment! 🚁**

---

*Last updated: January 2025 | MDS Version: 3.1+ | Guide Version: 1.0*