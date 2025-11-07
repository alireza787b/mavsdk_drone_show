# Python Version Compatibility

## Supported Python Versions

MAVSDK Drone Show (MDS) supports the following Python versions:

- ✅ **Python 3.11** (Recommended for stability)
- ✅ **Python 3.12**
- ✅ **Python 3.13** (Latest - fully supported as of MDS v3.5)

## What Changed in Version 3.5

### Python 3.13 Compatibility Fixes

The latest Raspberry Pi OS now ships with Python 3.13. We've updated MDS to work perfectly with this version:

1. **Removed deprecated packages**
   - Removed `asyncio` package (built into Python since 3.4)

2. **Upgraded key dependencies**
   - `pandas`: 2.2.2 → 2.3.3 (Python 3.13 support)
   - `protobuf`: 3.20.1 → 5.29.4 (Python 3.13 support + better performance)

3. **Improved installation script**
   - Added Python version detection
   - Added required system dependencies
   - Fixed dependency installation issues

## Installation

### For Raspberry Pi (Hardware)

Run the setup script:

```bash
bash tools/raspberry_setup.sh -d <drone_id> -k <netbird_key>
```

The script will:
- Check your Python version automatically
- Install required system packages
- Create a virtual environment
- Install all Python dependencies

### For SITL (Docker)

Docker images already include all dependencies. No action needed.

## Troubleshooting

### Error: "Incompatible Python Version"

**Problem:** You have Python 3.10 or older.

**Solution:**
1. **Recommended:** Update to latest Raspberry Pi OS (includes Python 3.13)
2. **Alternative:** Install Python 3.11+ manually:
   ```bash
   sudo apt-get install python3.11 python3.11-venv python3.11-dev
   ```

### Error: "pip install" fails with compilation errors

**Problem:** Missing system dependencies.

**Solution:** The setup script now installs these automatically. If you're installing manually:

```bash
sudo apt-get update
sudo apt-get install -y \
    python3-dev \
    build-essential \
    libgfortran5 \
    libopenblas-dev \
    libatlas-base-dev \
    libxml2-dev \
    libxslt-dev
```

### Error: Packages missing at runtime

**Problem:** Older versions of the setup script used `--no-deps` flag.

**Solution:** Update to latest version and reinstall:

```bash
cd ~/mavsdk_drone_show
git pull origin main-candidate
bash tools/raspberry_setup.sh -d <your_drone_id> -k <your_key>
```

### Performance Issues

**Problem:** Slow performance on Python 3.13.

**Solution:** Ensure you're using protobuf 5.29.4 or newer:

```bash
source ~/mavsdk_drone_show/venv/bin/activate
pip install --upgrade protobuf>=5.29.4
```

## Checking Your Python Version

```bash
python3 --version
```

Expected output:
- `Python 3.11.x` ✅
- `Python 3.12.x` ✅
- `Python 3.13.x` ✅
- `Python 3.10.x` ❌ (too old)

## Need Help?

If you encounter issues:

1. Check this guide first
2. Review the installation logs
3. Open an issue on [GitHub](https://github.com/alireza787b/mavsdk_drone_show/issues)
4. Contact: p30planets@gmail.com

---

**Last Updated:** January 2025
**MDS Version:** 3.5+
