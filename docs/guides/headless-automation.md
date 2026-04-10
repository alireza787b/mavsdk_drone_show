# Headless Automation Guide

Guide for automated fleet provisioning, CI/CD integration, and batch deployment of MDS drones.

If your fleet follows a customer-owned repo or private branch, read [Custom Repo Workflow](custom-repo-workflow.md) first. This guide assumes you already know which repo/branch each target should follow.

## Overview

The `mds_node_init.sh` script supports fully automated, non-interactive installation for:

- Fleet provisioning of multiple drones
- CI/CD pipeline integration
- Unattended installations
- Image-based deployment

## Non-Interactive Mode

Enable non-interactive mode with the `-y` or `--yes` flag:

```bash
sudo ./tools/mds_node_init.sh -d 1 -y
```

### Requirements for Non-Interactive Mode

1. **Drone ID must be specified** via `-d` flag
2. **SSH key must already exist** if using SSH for git (or use `--https`)
3. **All required information** must be provided via CLI flags

### Recommended Flags for Automation

```bash
# Avoid SSH key prompts for unattended installs.
# Pin the repo and branch explicitly.
sudo ./tools/mds_node_init.sh \
    -d ${DRONE_ID} \
    --https \
    --repo-url https://github.com/YOURORG/YOURREPO.git \
    -b customer-demo \
    -y
```

## Fleet Provisioning

### Method 1: Script-Based Provisioning

Create a provisioning script for your fleet:

```bash
#!/bin/bash
# provision_drone.sh - Provision a single drone
# Usage: ./provision_drone.sh <DRONE_ID>

DRONE_ID="$1"

if [[ -z "$DRONE_ID" ]]; then
    echo "Usage: $0 <DRONE_ID>"
    exit 1
fi

# Clone repository if not exists
if [[ ! -d "/home/droneshow/mavsdk_drone_show" ]]; then
    sudo -u droneshow git clone \
        https://github.com/YOURORG/YOURREPO.git \
        /home/droneshow/mavsdk_drone_show
fi

cd /home/droneshow/mavsdk_drone_show

# Run initialization
sudo ./tools/mds_node_init.sh \
    -d "$DRONE_ID" \
    --https \
    --repo-url https://github.com/YOURORG/YOURREPO.git \
    --branch customer-demo \
    -y \
    2>&1 | tee "/var/log/mds/provision_${DRONE_ID}.log"

exit $?
```

### Method 2: SSH-Based Fleet Deployment

Deploy to multiple drones from a management host:

```bash
#!/bin/bash
# deploy_fleet.sh - Deploy to multiple drones

DRONES=(
    "drone01:192.168.1.101:1"
    "drone02:192.168.1.102:2"
    "drone03:192.168.1.103:3"
)

for entry in "${DRONES[@]}"; do
    IFS=':' read -r hostname ip drone_id <<< "$entry"

    echo "Deploying to $hostname (ID: $drone_id)..."

    ssh -o StrictHostKeyChecking=accept-new "droneshow@$ip" << EOF
        cd ~/mavsdk_drone_show
        git fetch origin customer-demo
        git checkout customer-demo
        git reset --hard origin/customer-demo
        sudo ./tools/mds_node_init.sh -d $drone_id --https --repo-url https://github.com/YOURORG/YOURREPO.git --branch customer-demo -y
EOF

    if [[ $? -eq 0 ]]; then
        echo "SUCCESS: $hostname"
    else
        echo "FAILED: $hostname"
    fi
done
```

### Method 3: Ansible Playbook

```yaml
# playbook.yml
---
- name: Provision MDS Drones
  hosts: drones
  become: yes
  vars:
    mds_repo: "https://github.com/YOURORG/YOURREPO.git"
    mds_branch: "customer-demo"

  tasks:
    - name: Ensure droneshow user exists
      user:
        name: droneshow
        groups: sudo
        shell: /bin/bash

    - name: Clone MDS repository
      git:
        repo: "{{ mds_repo }}"
        dest: /home/droneshow/mavsdk_drone_show
        version: "{{ mds_branch }}"
      become_user: droneshow

    - name: Run MDS initialization
      command: >
        ./tools/mds_node_init.sh
        -d {{ drone_id }}
        --https
        -y
      args:
        chdir: /home/droneshow/mavsdk_drone_show
      register: mds_init

    - name: Show initialization result
      debug:
        var: mds_init.stdout_lines
```

Inventory file:
```ini
# inventory.ini
[drones]
drone01 ansible_host=192.168.1.101 drone_id=1
drone02 ansible_host=192.168.1.102 drone_id=2
drone03 ansible_host=192.168.1.103 drone_id=3

[drones:vars]
ansible_user=droneshow
```

Run with:
```bash
ansible-playbook -i inventory.ini playbook.yml
```

## CI/CD Integration

### GitHub Actions Example

```yaml
# .github/workflows/deploy-drone.yml
name: Deploy to Drone

on:
  workflow_dispatch:
    inputs:
      drone_ip:
        description: 'Drone IP address'
        required: true
      drone_id:
        description: 'Drone hardware ID'
        required: true

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to drone
        uses: appleboy/ssh-action@master
        with:
          host: ${{ github.event.inputs.drone_ip }}
          username: droneshow
          key: ${{ secrets.DRONE_SSH_KEY }}
          script: |
            cd ~/mavsdk_drone_show
            git fetch origin customer-demo
            git checkout customer-demo
            git reset --hard origin/customer-demo
            sudo ./tools/mds_node_init.sh \
              -d ${{ github.event.inputs.drone_id }} \
              --https \
              --repo-url https://github.com/YOURORG/YOURREPO.git \
              --branch customer-demo \
              -y
```

### GitLab CI Example

```yaml
# .gitlab-ci.yml
deploy_drone:
  stage: deploy
  script:
    - ssh droneshow@${DRONE_IP} "
        cd ~/mavsdk_drone_show &&
        git fetch origin customer-demo &&
        git checkout customer-demo &&
        git reset --hard origin/customer-demo &&
        sudo ./tools/mds_node_init.sh -d ${DRONE_ID} --https --repo-url https://github.com/YOURORG/YOURREPO.git --branch customer-demo -y
      "
  only:
    - customer-demo
  when: manual
```

## Image-Based Deployment

### Creating a Golden Image

1. Set up a reference companion-computer node with base configuration:

```bash
# On reference Pi
sudo ./tools/mds_node_init.sh \
    -d 999 \              # Placeholder ID
    --https \
    --skip-netbird \      # Skip VPN (configure per-drone)
    --report-json /var/lib/mds/bootstrap-report.json \
    --announce-report-json /var/lib/mds/announce-report.json \
    -y
```

2. Clean up for imaging:

```bash
# Reset state for next boot
sudo rm /var/lib/mds/init_state.json
sudo rm /etc/mds/local.env
sudo rm -f /etc/mds/node_identity.json

# Clear machine-specific data
sudo rm -rf /home/droneshow/.ssh/id_rsa*
sudo truncate -s 0 /var/log/mds/*.log

# Clear bash history
history -c
rm ~/.bash_history
```

3. Create SD card image using your preferred tool.

### First-Boot Configuration

Create a first-boot script that runs on initial startup:

```bash
#!/bin/bash
# /etc/mds/first_boot.sh

# Check if already configured
if [[ -f /etc/mds/local.env ]]; then
    exit 0
fi

# Get drone ID from hostname or hardware
# Example: hostname "mds-drone-042" -> ID 42
DRONE_ID=$(hostname | grep -oP '\d+$')

if [[ -n "$DRONE_ID" ]]; then
    cd /home/droneshow/mavsdk_drone_show
    sudo ./tools/mds_node_init.sh -d "$DRONE_ID" --https --resume -y
fi
```

Add to systemd:

```ini
# /etc/systemd/system/mds-first-boot.service
[Unit]
Description=MDS First Boot Configuration
After=network-online.target
Wants=network-online.target
ConditionPathExists=!/etc/mds/local.env

[Service]
Type=oneshot
ExecStart=/etc/mds/first_boot.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

## Environment Variables for Automation

Set these before running the script:

```bash
export MDS_REPO_URL="https://github.com/myorg/customer-mds.git"
export MDS_BRANCH="production"
export MDS_GCS_IP="192.168.1.100"
export MDS_GCS_API_BASE_URL="http://192.168.1.100:5000"

sudo -E ./tools/mds_node_init.sh -d 1 --https --report-json /var/lib/mds/bootstrap-report.json -y
```

Credential handling guidance:
- store Git HTTPS tokens, SSH deploy keys, and NetBird setup keys in Ansible Vault or your CI/CD secret store
- pass them into the bootstrap as environment variables, mounted files, or runtime inventory variables
- do not bake customer secrets into golden images, repo files, or shell history

Announce behavior guidance:
- the bootstrap now attempts a canonical candidate announce when it can resolve a GCS API URL
- `MDS_GCS_API_BASE_URL` is the most explicit automation-friendly way to control that endpoint
- if the GCS is unavailable during bootstrap, rerun:

```bash
sudo ./tools/mds_node_announce.sh --report-json /var/lib/mds/announce-report.json
```

## Verification and Monitoring

### Check Installation Status

```bash
# Check exit code
sudo ./tools/mds_node_init.sh -d 1 --https -y
echo "Exit code: $?"

# Check state file
cat /var/lib/mds/init_state.json | jq '.phases'
```

### Verify Services

```bash
# Check all MDS services
systemctl is-active coordinator git_sync_mds

# Get detailed status
./tools/recovery.sh status
```

### Automated Health Check

```bash
#!/bin/bash
# health_check.sh

SERVICES=(coordinator git_sync_mds)
FAILED=0

for svc in "${SERVICES[@]}"; do
    if ! systemctl is-active --quiet "$svc"; then
        echo "FAIL: $svc not running"
        FAILED=1
    fi
done

if [[ $FAILED -eq 0 ]]; then
    echo "OK: All services running"
fi

exit $FAILED
```

## Error Handling

### Exit Codes

| Code | Meaning | Action |
|------|---------|--------|
| 0 | Success | Continue |
| 1 | Failure | Check logs, retry |

### Retry Logic

```bash
#!/bin/bash
# retry_init.sh

MAX_RETRIES=3
RETRY_DELAY=30

for i in $(seq 1 $MAX_RETRIES); do
    echo "Attempt $i of $MAX_RETRIES..."

    sudo ./tools/mds_node_init.sh -d 1 --https -y

    if [[ $? -eq 0 ]]; then
        echo "Success!"
        exit 0
    fi

    if [[ $i -lt $MAX_RETRIES ]]; then
        echo "Retrying in ${RETRY_DELAY}s..."
        sleep $RETRY_DELAY
    fi
done

echo "Failed after $MAX_RETRIES attempts"
exit 1
```

### Log Collection

```bash
# Collect logs for troubleshooting
tar -czf "mds_logs_$(hostname)_$(date +%Y%m%d).tar.gz" \
    /var/log/mds/ \
    /var/lib/mds/init_state.json
```

## Security Considerations

### Secrets Management

Never commit secrets in scripts. Use:

1. **Environment variables** from CI/CD secrets
2. **HashiCorp Vault** or similar secrets manager
3. **Encrypted files** decrypted at runtime

Example with environment secrets:
```bash
# Netbird key from environment
sudo ./tools/mds_node_init.sh \
    -d 1 \
    --netbird-key "${NETBIRD_KEY}" \
    --https \
    -y
```

### SSH Key Management

For SSH-based deployments:

1. Use **dedicated deploy keys** per drone or fleet
2. **Rotate keys** periodically
3. **Limit key permissions** (read-only for code)

## Best Practices

1. **Always use `--https`** for automated deployments (no SSH prompts)
2. **Set explicit branch** with `-b` flag
3. **Log all output** for troubleshooting
4. **Verify exit codes** before proceeding
5. **Use state files** for idempotent deployments
6. **Test in dry-run mode** first: `--dry-run`

## Related Documentation

- [CLI Reference](mds-init-cli-reference.md) - All command options
- [Setup Guide](mds-init-setup.md) - Manual setup
- [Troubleshooting](mds-init-troubleshooting.md) - Common issues

---

**Version:** 4.0.0 | **Last Updated:** January 2026
