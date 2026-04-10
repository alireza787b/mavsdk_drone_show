# MDS Init Troubleshooting Guide

Solutions for common issues encountered during MDS companion-node bootstrap and initialization.

## Quick Diagnostics

### Check Installation Status

```bash
# View installation state
cat /var/lib/mds/init_state.json | jq

# View structured node identity
cat /etc/mds/node_identity.json | jq

# View installation log
cat /var/log/mds/mds_init.log

# Check service status
systemctl status coordinator
```

### Quick Health Check

```bash
./tools/recovery.sh health
```

## Common Issues

### Issue: "Permission denied" when running script

**Symptom:**
```
-bash: ./tools/mds_node_init.sh: Permission denied
```

**Solution:**
```bash
chmod +x tools/mds_node_init.sh
sudo ./tools/mds_node_init.sh
```

### Issue: "This script must be run as root"

**Symptom:**
```
Error: This script must be run as root (use sudo)
```

**Solution:**
```bash
sudo ./tools/mds_node_init.sh
```

### Issue: Script fails at SSH key generation

**Symptom:**
```
[!] Non-interactive mode: SSH key was just generated but not yet authorized on GitHub
```

**Solutions:**

1. **Use HTTPS instead (recommended for automation):**
   ```bash
   sudo ./tools/mds_node_init.sh -d 1 --https -y
   ```

2. **Add SSH key to GitHub first:**
   - Display the public key:
     ```bash
     cat /home/droneshow/.ssh/id_rsa_git_deploy.pub
     ```
   - Add to GitHub: Repository Settings → Deploy Keys
   - Run script again

### Issue: Git clone fails

**Symptom:**
```
[✗] Failed to clone repository
```

**Diagnosis:**
```bash
# Test network connectivity
ping github.com

# Check the configured repo / branch
grep '^MDS_REPO_URL=' /etc/mds/local.env
grep '^MDS_BRANCH=' /etc/mds/local.env

# Test git access (SSH)
ssh -T git@github.com

# Test git access using the configured remote
git ls-remote "$(grep '^MDS_REPO_URL=' /etc/mds/local.env | cut -d= -f2-)"
```

**Solutions:**

1. **Network issue:**
   ```bash
   # Check DNS
   nslookup github.com

   # Check firewall
   sudo ufw status
   ```

2. **SSH authentication issue:**
   ```bash
   # Use HTTPS instead
   sudo ./tools/mds_node_init.sh -d 1 --https -y
   ```

3. **Retry with verbose output:**
   ```bash
   sudo ./tools/mds_node_init.sh -d 1 --debug -y
   ```

4. **If this is a customer/private repo deployment:**
   - verify the repo URL in `/etc/mds/local.env`
   - verify the branch in `/etc/mds/local.env`
   - verify the credential path matches the chosen URL (`SSH` deploy key vs `HTTPS` token/read-only access)

### Issue: Python requirements installation fails

**Symptom:**
```
[✗] Failed to install requirements
```

**Diagnosis:**
```bash
# Check Python version
python3 --version

# Try manual install
cd ~/mavsdk_drone_show
./venv/bin/pip install -r requirements.txt
```

**Solutions:**

1. **Disk space issue:**
   ```bash
   df -h
   # If low, clean up
   sudo apt clean
   sudo apt autoremove
   ```

2. **Network timeout:**
   ```bash
   # Increase pip timeout
   ./venv/bin/pip install -r requirements.txt --timeout 120
   ```

3. **Broken venv:**
   ```bash
   rm -rf ~/mavsdk_drone_show/venv
   sudo ./tools/mds_node_init.sh --resume
   ```

### Issue: MAVSDK download fails

**Symptom:**
```
[✗] Failed to download MAVSDK binary
```

**Diagnosis:**
```bash
# Check architecture
uname -m

# Test download URL manually
curl -I https://github.com/mavlink/MAVSDK/releases/...
```

**Solutions:**

1. **Network issue:**
   - Check internet connectivity
   - Try again later (GitHub may have temporary issues)

2. **Manual download:**
   ```bash
   # Download on another machine and copy
   wget <MAVSDK_URL> -O /usr/local/bin/mavsdk_server
   chmod +x /usr/local/bin/mavsdk_server
   ```

3. **Skip and install later:**
   ```bash
   sudo ./tools/mds_node_init.sh -d 1 --skip-mavsdk -y
   ```

### Issue: Services fail to start

**Symptom:**
```
systemctl status coordinator
● coordinator.service - MDS Coordinator
   Loaded: loaded
   Active: failed
```

**Diagnosis:**
```bash
# View service logs
journalctl -u coordinator -n 50

# Check if venv exists
ls -la ~/mavsdk_drone_show/venv/bin/python
```

**Solutions:**

1. **Missing venv:**
   ```bash
   cd ~/mavsdk_drone_show
   python3 -m venv venv
   ./venv/bin/pip install -r requirements.txt
   sudo systemctl restart coordinator
   ```

2. **Missing config:**
   ```bash
   # Check local.env
   cat /etc/mds/local.env

   # Create if missing
   sudo ./tools/mds_node_init.sh -d 1 --resume
   ```

3. **Wrong permissions:**
   ```bash
   sudo chown -R droneshow:droneshow ~/mavsdk_drone_show
   ```

### Issue: State file corrupted

**Symptom:**
```
jq: parse error: ...
```

**Solution:**
```bash
# Script auto-recovers, but to manually reset:
sudo rm /var/lib/mds/init_state.json
sudo ./tools/mds_node_init.sh -d 1 -y
```

### Issue: Resume doesn't work

**Symptom:**
Script starts from beginning despite `--resume` flag.

**Diagnosis:**
```bash
cat /var/lib/mds/init_state.json
```

**Solutions:**

1. **State file missing:**
   ```bash
   # Normal - means no previous run or was reset
   # Run without --resume
   sudo ./tools/mds_node_init.sh -d 1 -y
   ```

2. **Force fresh start:**
   ```bash
   sudo ./tools/mds_node_init.sh -d 1 --force -y
   ```

### Issue: Firewall blocks services

**Symptom:**
Cannot connect to drone from GCS.

**Diagnosis:**
```bash
sudo ufw status verbose
```

**Solution:**
```bash
# Reset firewall to MDS defaults
sudo ./tools/mds_node_init.sh --resume

# Or manually open ports
sudo ufw allow 5000/tcp    # Flask backend
sudo ufw allow 14540/udp   # MAVLink
sudo ufw allow 14550/udp   # MAVLink
```

### Issue: Wrong drone ID

**Symptom:**
Drone shows up with incorrect ID in GCS.

**Solution:**
```bash
# Edit local.env
sudo nano /etc/mds/local.env
# Change MDS_HW_ID=X to correct value

# Restart services
sudo systemctl restart coordinator
```

## Recovery Procedures

### Full Reset

Complete reinstallation:

```bash
# Stop services
sudo systemctl stop coordinator git_sync_mds

# Remove state
sudo rm -rf /var/lib/mds
sudo rm -rf /etc/mds

# Remove venv
rm -rf ~/mavsdk_drone_show/venv

# Fresh install
sudo ./tools/mds_node_init.sh -d 1 -y
```

### Partial Reset

Re-run specific phases:

```bash
# Edit state to mark phase as pending
sudo nano /var/lib/mds/init_state.json
# Change "completed" to "pending" for desired phase

# Resume
sudo ./tools/mds_node_init.sh --resume
```

### Service Recovery

```bash
# Restart all MDS services
sudo systemctl restart coordinator git_sync_mds

# Check status
./tools/recovery.sh status
```

## Logs and Debugging

### Log Locations

| Log | Purpose |
|-----|---------|
| `/var/log/mds/mds_init.log` | Installation log |
| `journalctl -u coordinator` | Coordinator service |
| `journalctl -u git_sync_mds` | Git sync service |
| `/var/log/syslog` | System messages |

### Enable Debug Mode

```bash
sudo ./tools/mds_node_init.sh -d 1 --debug -y
```

### Collect Diagnostics

```bash
# Create diagnostic bundle
tar -czf mds_diagnostics.tar.gz \
    /var/log/mds/ \
    /var/lib/mds/ \
    /etc/mds/ \
    ~/mavsdk_drone_show/config.json
```

## FAQ

### Q: Can I run the script multiple times?

**A:** Yes. The script is idempotent - it skips completed phases and only runs what's needed. Use `--force` to re-run everything.

### Q: How do I change the drone ID after installation?

**A:** Edit `/etc/mds/local.env` and change `MDS_HW_ID`, then restart the coordinator service.

### Q: Why does the script need root access?

**A:** It installs system packages, configures systemd services, and modifies system configuration files. The actual MDS application runs as the `droneshow` user.

### Q: Can I use a different user than droneshow?

**A:** Currently the username is hardcoded. This is planned for a future release (see backlog item P2.3).

### Q: How do I update to a new version?

**A:**
```bash
cd ~/mavsdk_drone_show
git pull
sudo ./tools/mds_node_init.sh --resume
```

### Q: What if my companion computer doesn't have internet?

**A:** You'll need to:
1. Download packages on another machine
2. Transfer them to the Pi
3. Install manually or use `--skip-*` flags

### Q: Can I run this on Jetson?

**A:** The script is designed for Debian-family companion computers and works best when the required services and MAVLink routing stack are available. Some board-specific features (GPIO, serial console auto-fixes, etc.) may still require hardware-specific review.

## Getting Help

If you can't resolve an issue:

1. **Check the logs** in `/var/log/mds/`
2. **Run with `--debug`** for detailed output
3. **Create a diagnostic bundle** (see above)
4. **Open an issue** on [GitHub](https://github.com/alireza787b/mavsdk_drone_show/issues)
5. **Contact support** (see README for contact info)

## Related Documentation

- [Setup Guide](mds-init-setup.md) - Installation instructions
- [CLI Reference](mds-init-cli-reference.md) - All options
- [Service Architecture](raspberry-pi-services.md) - Service details

---

**Version:** 4.0.0 | **Last Updated:** January 2026
