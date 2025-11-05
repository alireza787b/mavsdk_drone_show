# Configuration CSV Migration Guide

## Configuration System Cleanup (v3.3+)

**Date:** November 2025
**Version:** 3.3
**Impact:** Medium - Requires CSV file updates and system restart

---

## Summary of Changes

The `config.csv` and `config_sitl.csv` files have been **simplified and modernized** to remove deprecated fields and centralize global configuration, while maintaining per-drone hardware flexibility.

### What Changed

**Old Format (10 columns - v3.2):**
```csv
hw_id,pos_id,x,y,ip,mavlink_port,debug_port,gcs_ip,serial_port,baudrate
```

**New Format (8 columns - v3.3):**
```csv
hw_id,pos_id,x,y,ip,mavlink_port,serial_port,baudrate
```

### Removed Columns

| Column | Reason for Removal | New Location |
|--------|-------------------|--------------|
| `debug_port` | Deprecated UDP telemetry feature no longer used | Removed entirely |
| `gcs_ip` | Same for all drones; causes configuration redundancy | Centralized in `src/params.py` with UI configuration |

### Key Improvements

✅ **Cleaner Configuration** - Reduced from 10 to 8 columns
✅ **GCS Configuration UI** - New "Configure GCS" button for centralized GCS IP management
✅ **Custom Hardware Options** - UI dropdowns now support custom serial ports and baudrates
✅ **Git Integration** - GCS configuration changes auto-commit to repository
✅ **No Backward Compatibility** - Only supports new 8-column format (clean break)

---

## Why This Change?

### Problems Addressed

**1. Redundant GCS IP Configuration**
- ❌ Old: GCS IP repeated in every drone row (same value 50+ times)
- ✅ New: Single GCS IP in `src/params.py`, editable via UI

**2. Deprecated Debug Port**
- ❌ Old: `debug_port` column unused (UDP telemetry deprecated in v2.0)
- ✅ New: Removed entirely, MAVLink port handles all telemetry

**3. Limited Hardware Flexibility**
- ❌ Old: Fixed dropdown options only
- ✅ New: "Custom" option allows any serial port or baudrate

---

## GCS IP Configuration (New Feature)

### Centralized Management

GCS IP is now configured in `src/params.py`:

```python
# ===================================================================================
# GCS (Ground Control Station) CONFIGURATION
# ===================================================================================
GCS_IP = "100.96.32.75"                # GCS IP address (★ CHANGE THIS FOR YOUR SETUP ★)
GCS_FLASK_PORT = 5000                  # GCS Flask backend port
connectivity_check_ip = GCS_IP         # Use GCS_IP for connectivity checks
connectivity_check_port = GCS_FLASK_PORT
```

### UI Configuration

**Mission Config Dashboard now includes a "Configure GCS" button:**

1. Click **"Configure GCS"** button (next to "Set Origin")
2. Enter new GCS IP address
3. System validates IP format (XXX.XXX.XXX.XXX, octets 0-255)
4. On save:
   - Updates `src/params.py` file
   - Commits changes to git repository
   - Shows warning about required restarts

**⚠️ Important:** After changing GCS IP:
- All drones must be restarted
- GCS server must be restarted
- Changes are committed to git automatically

### What GCS IP Controls

The GCS IP address is used by all drones for:
- **Heartbeat reporting** - Regular status updates to GCS
- **MAVLink routing** - Telemetry and command routing
- **Telemetry transmission** - Real-time position/battery data
- **Command reception** - Mission commands and controls

---

## Migration Instructions

### ⚠️ Breaking Change Notice

**Version 3.3 does NOT support backward compatibility.** The old 10-column format will be rejected.

You MUST migrate your CSV files before upgrading.

### Migration Steps

#### Step 1: Backup Existing Configuration

```bash
cd ~/mavsdk_drone_show
cp config.csv config.csv.v3.2.backup
cp config_sitl.csv config_sitl.csv.v3.2.backup
```

#### Step 2: Update config.csv Header

**Old header:**
```csv
hw_id,pos_id,x,y,ip,mavlink_port,debug_port,gcs_ip,serial_port,baudrate
```

**New header:**
```csv
hw_id,pos_id,x,y,ip,mavlink_port,serial_port,baudrate
```

#### Step 3: Remove debug_port and gcs_ip Columns

**Before (10 columns):**
```csv
hw_id,pos_id,x,y,ip,mavlink_port,debug_port,gcs_ip,serial_port,baudrate
1,1,-2.5,10.0,100.96.240.11,14551,13541,100.96.32.75,/dev/ttyS0,57600
2,2,-2.5,5.0,100.96.28.52,14552,13542,100.96.32.75,/dev/ttyAMA0,57600
```

**After (8 columns):**
```csv
hw_id,pos_id,x,y,ip,mavlink_port,serial_port,baudrate
1,1,-2.5,10.0,100.96.240.11,14551,/dev/ttyS0,57600
2,2,-2.5,5.0,100.96.28.52,14552,/dev/ttyAMA0,57600
```

#### Step 4: Update GCS IP in params.py

Edit `src/params.py` and set your GCS IP:

```python
GCS_IP = "100.96.32.75"  # ← Update this to your GCS server IP
```

Or use the UI after deployment (Configure GCS button).

#### Step 5: Update config_sitl.csv

Same process for SITL configuration:

```csv
hw_id,pos_id,x,y,ip,mavlink_port,serial_port,baudrate
1,1,-13.5,13.5,172.18.0.2,14563,N/A,N/A
2,2,-13.5,10.5,172.18.0.3,14564,N/A,N/A
```

#### Step 6: Test Configuration

```bash
python3 test_config_simple.py
```

#### Step 7: Restart Services

```bash
sudo systemctl restart coordinator
sudo systemctl restart gcs-server
```

---

## Example Configurations

### Example 1: Homogeneous Fleet (All RP4)

```csv
hw_id,pos_id,x,y,ip,mavlink_port,serial_port,baudrate
1,1,0,0,100.96.1.10,14551,/dev/ttyS0,57600
2,2,5,0,100.96.1.11,14552,/dev/ttyS0,57600
3,3,10,0,100.96.1.12,14553,/dev/ttyS0,57600
```

### Example 2: Mixed Fleet (RP4 + RP5)

```csv
hw_id,pos_id,x,y,ip,mavlink_port,serial_port,baudrate
1,1,0,0,100.96.1.10,14551,/dev/ttyS0,57600
2,2,5,0,100.96.1.11,14552,/dev/ttyAMA0,57600
3,3,10,0,100.96.1.12,14553,/dev/ttyS0,57600
4,4,15,0,100.96.1.13,14554,/dev/ttyAMA0,57600
```

### Example 3: High-Performance Setup (Jetson)

```csv
hw_id,pos_id,x,y,ip,mavlink_port,serial_port,baudrate
1,1,0,0,100.96.1.10,14551,/dev/ttyTHS1,921600
2,2,5,0,100.96.1.11,14552,/dev/ttyTHS1,921600
```

### Example 4: Custom Serial Configuration

```csv
hw_id,pos_id,x,y,ip,mavlink_port,serial_port,baudrate
1,1,0,0,100.96.1.10,14551,/dev/ttyUSB0,38400
2,2,5,0,100.96.1.11,14552,/dev/ttyACM0,115200
```

### Example 5: SITL Configuration

```csv
hw_id,pos_id,x,y,ip,mavlink_port,serial_port,baudrate
1,1,-13.5,13.5,172.18.0.2,14563,N/A,N/A
2,2,-13.5,10.5,172.18.0.3,14564,N/A,N/A
```

---

## Mission Config UI Updates

### GCS Configuration Dialog

**New "Configure GCS" Button:**
- Located at top of Mission Config page (next to "Set Origin")
- Opens modal dialog for GCS IP configuration
- Validates IP format in real-time
- Shows current IP and warnings about restart requirements
- Auto-commits changes to git repository

### Drone Configuration Cards

**Read-Only View:**
- Shows serial port and baudrate for each drone
- GCS IP no longer displayed (redundant - same for all)
- Debug port removed (deprecated feature)

**Edit Mode:**
Dropdown selectors with custom options:

**Serial Port Options:**
- `/dev/ttyS0` (Raspberry Pi 4)
- `/dev/ttyAMA0` (Raspberry Pi 5)
- `/dev/ttyTHS1` (Jetson)
- `N/A` (SITL/Simulation)
- **Custom...** ← NEW! Enter any serial port path

**Baudrate Options:**
- `9600`
- `57600` (Standard) ← Default
- `115200` (High Speed)
- `921600` (Very High Speed)
- `N/A` (SITL/Simulation)
- **Custom...** ← NEW! Enter any baudrate value

### Adding New Drones

When clicking "Add New Drone", the system automatically sets:
- `serial_port`: `/dev/ttyS0` (default for RP4)
- `baudrate`: `57600` (standard)
- No gcs_ip or debug_port (removed)

---

## Hardware Reference

### Common Serial Port Mappings

| Hardware Platform | Serial Port | Default Baudrate | Notes |
|-------------------|-------------|------------------|-------|
| **Raspberry Pi 4** | `/dev/ttyS0` | 57600 | Standard UART |
| **Raspberry Pi 5** | `/dev/ttyAMA0` | 57600 | New UART mapping |
| **Raspberry Pi Zero** | `/dev/ttyS0` | 57600 | Same as RP4 |
| **NVIDIA Jetson** | `/dev/ttyTHS1` | 921600 | High-speed UART |
| **USB Serial Adapter** | `/dev/ttyUSB0` | Variable | Check adapter specs |
| **Arduino/Custom** | `/dev/ttyACM0` | Variable | Device-specific |
| **SITL/Simulation** | `N/A` | `N/A` | Not used in simulation |

### Common Baudrates

| Baudrate | Use Case | Compatibility |
|----------|----------|---------------|
| **9600** | Very slow (debugging) | Universal |
| **38400** | Custom hardware | Some devices |
| **57600** | Standard (default) | Most common |
| **115200** | High speed | Most modern hardware |
| **921600** | Very high speed | Jetson, high-performance systems |

---

## Files Modified

### Backend (Python)

1. **gcs-server/config.py** (Line 17)
   - Updated `CONFIG_COLUMNS` to 8 columns (removed debug_port, gcs_ip)

2. **gcs-server/gcs_config_updater.py** (NEW FILE)
   - Module for safe programmatic editing of `src/params.py`
   - IP validation and Python syntax checking

3. **gcs-server/routes.py** (Lines 1373-1489)
   - Added `/get-gcs-config` endpoint
   - Added `/save-gcs-config` endpoint with git commit support

4. **src/params.py** (Lines 64-80)
   - Added comprehensive GCS IP configuration section
   - Centralized GCS_IP variable

5. **src/heartbeat_sender.py** (Lines 22-23)
   - Use centralized `Params.GCS_IP` instead of per-drone config

6. **src/mavlink_manager.py** (Lines 38, 40)
   - Use `Params.GCS_IP` for MAVLink routing endpoints

7. **src/flask_handler.py** (Lines 325-331)
   - Use `Params.GCS_IP` for origin fetching

8. **src/drone_communicator.py** (Lines 299-300, 334)
   - Use `Params.GCS_IP` for telemetry and broadcast
   - Updated to use mavlink_port instead of debug_port

9. **src/drone.py** (Lines 13-14)
   - Removed debug_port and gcs_ip attributes

10. **actions.py** (Lines 199-200)
    - Removed gcs_ip from drone_config dict

### Frontend (JavaScript/React)

11. **app/dashboard/drone-dashboard/src/components/GcsConfigModal.js** (NEW FILE)
    - React modal component for GCS IP configuration
    - Real-time validation and warnings

12. **app/dashboard/drone-dashboard/src/styles/GcsConfigModal.css** (NEW FILE)
    - Styling for GCS configuration modal

13. **app/dashboard/drone-dashboard/src/components/ControlButtons.js**
    - Added "Configure GCS" button with server icon
    - Added `openGcsConfigModal` prop

14. **app/dashboard/drone-dashboard/src/pages/MissionConfig.js**
    - Integrated GcsConfigModal component
    - Added GCS config state management
    - Added handleGcsConfigSubmit handler
    - Fixed heartbeat detection bug (lines 161-162)

15. **app/dashboard/drone-dashboard/src/components/DroneConfigCard.js**
    - Removed GCS IP display and edit fields
    - Removed debug_port display and edit fields
    - Removed validation for removed fields
    - Added "Custom" option to serial_port dropdown with text input
    - Added "Custom" option to baudrate dropdown with text input

16. **app/dashboard/drone-dashboard/src/utilities/missionConfigUtilities.js**
    - Updated to 8-column format
    - Removed backward compatibility (clean break)
    - Updated expectedFields array
    - Simplified parseCSV (only supports new format)
    - Updated exportConfig for 8 columns

### Configuration Files

17. **config.csv**
    - Reduced from 10 to 8 columns
    - Removed debug_port and gcs_ip columns

18. **config_sitl.csv**
    - Reduced from 10 to 8 columns
    - Removed debug_port and gcs_ip columns

---

## Troubleshooting

### Issue: CSV upload fails with "Invalid CSV format"

**Cause:** Using old 10-column format or incorrect header

**Solution:**
1. Ensure header is exactly: `hw_id,pos_id,x,y,ip,mavlink_port,serial_port,baudrate`
2. No spaces around commas
3. All rows must have exactly 8 columns
4. Remove debug_port and gcs_ip columns from old CSV

### Issue: Drones can't connect to GCS after upgrade

**Cause:** GCS IP not configured in params.py

**Solution:**
1. Check `src/params.py` has correct GCS_IP
2. Or use "Configure GCS" button in UI to set it
3. Restart all drones and GCS server after change

### Issue: Drone not connecting to Pixhawk

**Cause:** Wrong serial port configured

**Solution:**
1. Check hardware type:
   ```bash
   cat /proc/cpuinfo | grep "Model"
   ```
2. Update `serial_port` in config.csv:
   - Raspberry Pi 4/Zero: `/dev/ttyS0`
   - Raspberry Pi 5: `/dev/ttyAMA0`
   - Jetson: `/dev/ttyTHS1`
3. Or use "Custom" option for non-standard ports

### Issue: MAVLink connection timeout

**Cause:** Wrong baudrate

**Solution:**
1. Check Pixhawk telem port baudrate (usually 57600)
2. Match `baudrate` in config.csv to Pixhawk setting
3. Or use "Custom" option for non-standard baudrates

### Issue: GCS configuration not saving

**Cause:** Git repository not initialized or permissions issue

**Solution:**
1. Check git status: `git status`
2. Ensure write permissions: `ls -la src/params.py`
3. Check Flask logs for error messages

### Issue: Custom serial port or baudrate not working in UI

**Cause:** Old cached frontend build

**Solution:**
1. Rebuild frontend:
   ```bash
   cd app/dashboard/drone-dashboard
   npm run build
   ```
2. Clear browser cache
3. Restart GCS server

---

## Testing Checklist

### Before Deployment

- [ ] Backup existing CSV files
- [ ] Remove debug_port and gcs_ip columns from CSV
- [ ] Update GCS_IP in src/params.py
- [ ] Verify hardware type for each drone
- [ ] Update serial ports accordingly
- [ ] Run `python3 test_config_simple.py`
- [ ] Test CSV upload in Mission Config UI
- [ ] Test "Configure GCS" button
- [ ] Verify custom serial port/baudrate options work
- [ ] Export CSV and verify 8 columns

### After Deployment

- [ ] Verify drones connect to Pixhawk
- [ ] Check MAVLink telemetry streaming
- [ ] Verify drones can reach GCS IP
- [ ] Test GCS configuration change via UI
- [ ] Verify git commit works for GCS changes
- [ ] Test mission execution
- [ ] Test mixed hardware fleet (if applicable)

---

## FAQ

**Q: Can I still use the old 10-column format?**
A: No. Version 3.3 removes backward compatibility. You must migrate to 8 columns.

**Q: Where do I set the GCS IP now?**
A: Either edit `src/params.py` directly or use the "Configure GCS" button in the Mission Config UI.

**Q: What happened to debug_port?**
A: Removed. It was for deprecated UDP telemetry. All telemetry now uses MAVLink port.

**Q: Can I use custom serial ports not in the dropdown?**
A: Yes! Select "Custom..." option and enter any serial port path.

**Q: Will changing GCS IP via UI work immediately?**
A: No. All drones and GCS server must be restarted after GCS IP change.

**Q: Can I mix RP4 and RP5 in the same fleet?**
A: Yes! Set different `serial_port` values per drone in config.csv.

**Q: What if I have a custom baudrate like 38400?**
A: Use the "Custom..." option in the baudrate dropdown and enter your value.

**Q: Will this affect my existing trajectories?**
A: No. This only affects hardware/network configuration, not trajectory data.

**Q: Are GCS configuration changes tracked in git?**
A: Yes. The UI automatically commits changes to params.py with a descriptive message.

**Q: Can I revert a GCS IP change?**
A: Yes. Use git to revert the commit or manually edit src/params.py.

---

## Support

If you encounter issues during migration:

1. Check backup files: `config.csv.v3.2.backup`
2. Run test script: `python3 test_config_simple.py`
3. Review Flask logs: `journalctl -u gcs-server -f`
4. Check browser console for frontend errors
5. Consult example configurations in this guide
6. Report issues: https://github.com/alireza787b/mavsdk_drone_show/issues

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| **3.3** | **Nov 2025** | **Removed debug_port and gcs_ip; added GCS configuration UI; custom hardware options** |
| 3.2 | Nov 2025 | Added `serial_port` and `baudrate` columns (10 columns total) |
| 3.1 | Earlier | Added environment variable support for Git config |
| 3.0 | Earlier | Initial multi-drone support |

---

**End of Migration Guide**
