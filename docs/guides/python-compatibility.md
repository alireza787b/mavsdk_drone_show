# Python Version Compatibility

## Supported Python Versions

The reviewed MDS SDK platform matrix includes these CPython minor versions:

- **Python 3.11**
- **Python 3.12**
- **Python 3.13**

Linux x86_64 and aarch64 are the reviewed SDK wheel platforms. This is not a
claim that every OS, peripheral, complete dependency set or aircraft has been
flight-tested. A newer system Python does not automatically qualify.

## MAVSDK gRPC compatibility

The reviewed SDK pair is `mavsdk-grpc==4.0.5` (import `mavsdk_grpc`) and
`mavsdk_server v4.0.5`, with `grpcio==1.75.1` and `protobuf==6.33.5`.
The new native `mavsdk` v4 package is a different API and is not a substitute.
Use [MAVSDK updates](mavsdk-updates.md) for the pinned manifest, platform gates,
maintenance procedure and rollback boundaries. Python-version eligibility is
not by itself a claim of real-hardware validation on every architecture.

## Historical changes in Version 3.5

### Python 3.13 Compatibility Fixes

Earlier Python 3.13 compatibility work included:

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

### For Companion Nodes (Hardware)

Run the bootstrap script:

```bash
curl -fsSL https://raw.githubusercontent.com/alireza787b/mavsdk_drone_show/main/tools/install_companion.sh | sudo bash -s -- -d <drone_id> -y
```

The script will:
- Check your Python version automatically
- Install required system packages
- Create a virtual environment
- Install all Python dependencies

`install_companion.sh` is the public hardware-bootstrap entrypoint.
`install_mds_node.sh` remains an equivalent packaged entrypoint for automation
that intentionally references the node-specific filename.

### For SITL (Docker)

Use the current validated image from the SITL guide. Refreshed image preparation
provides CPython 3.12.16 under `/opt/mds-python/3.12.16` when the base has no
eligible interpreter. The image's OS Python may remain 3.10; do not replace it.
Startup validates the selected venv's own interpreter and dependency manifest.
An older image cannot acquire this interpreter by pulling source alone: load or
rebuild the validated replacement before enabling mutable SDK sync.

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

**Solution:** Update to the latest version and reinstall:

```bash
cd ~/mavsdk_drone_show
git pull origin main
sudo ./tools/mds_node_init.sh -d <your_drone_id> -y
```

### SDK protobuf/gRPC import errors

**Problem:** An independent protobuf/gRPC upgrade, old virtual environment, or
incorrect `mavsdk` distribution does not match the generated client.

**Solution:** Restore the exact reviewed dependency set, then perform a real
import/pair check. Do this during grounded maintenance, not live operation:

```bash
source ~/mavsdk_drone_show/venv/bin/activate
python -m pip install -r requirements-node.txt
python -m pip check
python tools/mavsdk_runtime.py python-check
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

**Last Updated:** November 2026
