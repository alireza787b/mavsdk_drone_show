# Configuration CSV Migration Guide

## Hardware-Specific Configuration Update (v3.2+)

**Date:** November 2025
**Version:** 3.2
**Impact:** Medium - Requires CSV file updates

---

## Summary of Changes

The `config.csv` and `config_sitl.csv` files have been enhanced to support **per-drone hardware configuration**, enabling mixed hardware fleets (Raspberry Pi 4, Raspberry Pi 5, Jetson, etc.) to operate seamlessly from a single repository.

### What Changed

**Before (8 columns):**
```csv
hw_id,pos_id,x,y,ip,mavlink_port,debug_port,gcs_ip
```

**After (10 columns):**
```csv
hw_id,pos_id,x,y,ip,mavlink_port,debug_port,gcs_ip,serial_port,baudrate
```

### New Columns

| Column | Description | Example Values | Required |
|--------|-------------|----------------|----------|
| `serial_port` | Serial device path for MAVLink connection | `/dev/ttyS0`, `/dev/ttyAMA0`, `/dev/ttyTHS1`, `N/A` | Yes |
| `baudrate` | Serial connection baudrate | `57600`, `115200`, `921600`, `N/A` | Yes |

---

## Why This Change?

### Problem
Previously, the serial port configuration was hardcoded in `src/params.py`:
```python
serial_mavlink_port = '/dev/ttyS0'  # Only works for RP4
serial_baudrate = 57600
```

This caused issues when:
- ✗ Deploying to Raspberry Pi 5 (needs `/dev/ttyAMA0`)
- ✗ Mixing hardware types in the same fleet
- ✗ Using custom baudrates for specific hardware

### Solution
Now each drone can specify its own hardware configuration in `config.csv`, enabling:
- ✓ Mixed hardware fleets (RP4 + RP5 + Jetson)
- ✓ Per-drone serial port configuration
- ✓ Per-drone baudrate settings
- ✓ Clean SITL/real hardware separation

---

## Hardware Reference

### Common Serial Port Mappings

| Hardware Platform | Serial Port | Default Baudrate | Notes |
|-------------------|-------------|------------------|-------|
| **Raspberry Pi 4** | `/dev/ttyS0` | 57600 | Standard UART |
| **Raspberry Pi 5** | `/dev/ttyAMA0` | 57600 | New UART mapping |
| **Raspberry Pi Zero** | `/dev/ttyS0` | 57600 | Same as RP4 |
| **NVIDIA Jetson** | `/dev/ttyTHS1` | 921600 | High-speed UART |
| **SITL/Simulation** | `N/A` | `N/A` | Not used in simulation |

### Common Baudrates

| Baudrate | Use Case | Compatibility |
|----------|----------|---------------|
| **9600** | Very slow (debugging) | Universal |
| **57600** | Standard (default) | Most common |
| **115200** | High speed | Most modern hardware |
| **921600** | Very high speed | Jetson, high-performance systems |

---

## Migration Instructions

### For New Installations

**No action required!** The updated CSV files are already in the repository with default values.

### For Existing Deployments

#### Option A: Automatic Migration (Recommended)

The system includes **automatic backward compatibility**:

1. **Upload old 8-column CSV** via Mission Config UI
2. System automatically detects old format
3. Adds default values: `serial_port=/dev/ttyS0`, `baudrate=57600`
4. Shows migration notice to user
5. Save to upgrade to new format

#### Option B: Manual Migration

**Step 1: Backup existing files**
```bash
cd ~/mavsdk_drone_show
cp config.csv config.csv.old
cp config_sitl.csv config_sitl.csv.old
```

**Step 2: Add new columns to config.csv (real hardware)**

Edit `config.csv` and:
1. Update header row to include `serial_port,baudrate`
2. Add values to each drone row

**Example:**
```csv
hw_id,pos_id,x,y,ip,mavlink_port,debug_port,gcs_ip,serial_port,baudrate
1,1,-2.5,10.0,100.96.240.11,14551,13541,100.96.32.75,/dev/ttyS0,57600
2,2,-2.5,5.0,100.96.28.52,14552,13542,100.96.32.75,/dev/ttyAMA0,57600
```

**Step 3: Add new columns to config_sitl.csv (simulation)**

Use `N/A` for SITL since serial ports aren't used:
```csv
hw_id,pos_id,x,y,ip,mavlink_port,debug_port,gcs_ip,serial_port,baudrate
1,1,-13.5,13.5,172.18.0.2,14563,13553,172.18.0.1,N/A,N/A
```

**Step 4: Verify with test script**
```bash
python3 test_config_simple.py
```

**Step 5: Restart services**
```bash
sudo systemctl restart coordinator
sudo systemctl restart gcs-server
```

---

## Mission Config UI Updates

The **Mission Config** page now includes hardware configuration fields:

### Read-Only View
- Displays serial port and baudrate for each drone
- Shows current hardware configuration at a glance

### Edit Mode
New dropdown selectors:

**Serial Port Options:**
- `/dev/ttyS0` (Raspberry Pi 4)
- `/dev/ttyAMA0` (Raspberry Pi 5)
- `/dev/ttyTHS1` (Jetson)
- `N/A` (SITL/Simulation)

**Baudrate Options:**
- `9600`
- `57600` (Standard) ← Default
- `115200` (High Speed)
- `921600` (Very High Speed)
- `N/A` (SITL/Simulation)

### Adding New Drones

When clicking "Add New Drone", the system automatically sets:
- `serial_port`: `/dev/ttyS0` (default for RP4)
- `baudrate`: `57600` (standard)

You can then edit these values per-drone as needed.

---

## Example Configurations

### Example 1: Homogeneous Fleet (All RP4)

```csv
hw_id,pos_id,x,y,ip,mavlink_port,debug_port,gcs_ip,serial_port,baudrate
1,1,0,0,100.96.1.10,14551,13541,100.96.32.75,/dev/ttyS0,57600
2,2,5,0,100.96.1.11,14552,13542,100.96.32.75,/dev/ttyS0,57600
3,3,10,0,100.96.1.12,14553,13543,100.96.32.75,/dev/ttyS0,57600
```

### Example 2: Mixed Fleet (RP4 + RP5)

```csv
hw_id,pos_id,x,y,ip,mavlink_port,debug_port,gcs_ip,serial_port,baudrate
1,1,0,0,100.96.1.10,14551,13541,100.96.32.75,/dev/ttyS0,57600
2,2,5,0,100.96.1.11,14552,13542,100.96.32.75,/dev/ttyAMA0,57600
3,3,10,0,100.96.1.12,14553,13543,100.96.32.75,/dev/ttyS0,57600
4,4,15,0,100.96.1.13,14554,13544,100.96.32.75,/dev/ttyAMA0,57600
```

### Example 3: High-Performance Setup (Jetson)

```csv
hw_id,pos_id,x,y,ip,mavlink_port,debug_port,gcs_ip,serial_port,baudrate
1,1,0,0,100.96.1.10,14551,13541,100.96.32.75,/dev/ttyTHS1,921600
```

### Example 4: SITL Configuration

```csv
hw_id,pos_id,x,y,ip,mavlink_port,debug_port,gcs_ip,serial_port,baudrate
1,1,-13.5,13.5,172.18.0.2,14563,13553,172.18.0.1,N/A,N/A
2,2,-13.5,10.5,172.18.0.3,14564,13554,172.18.0.1,N/A,N/A
```

---

## Files Modified

### Backend (Python)

1. **gcs-server/config.py** (Line 17)
   - Updated `CONFIG_COLUMNS` to include `'serial_port'` and `'baudrate'`

2. **functions/read_config.py** (Lines 1-41)
   - Added backward compatibility for 8 vs 10 column formats
   - Returns dict instead of Drone object

3. **src/drone_config.py** (Lines 213-246)
   - Added `get_serial_port()` method
   - Added `get_baudrate()` method
   - Fallback to `Params` defaults if columns missing

### Frontend (JavaScript/React)

4. **missionConfigUtilities.js**
   - Updated `expectedFields` array (Line 10)
   - Enhanced `parseCSV()` with backward compatibility (Lines 86-148)
   - Updated `exportConfig()` to include new columns (Lines 163-177)

5. **MissionConfig.js** (Lines 206-218)
   - Added defaults to `addNewDrone()` function

6. **DroneConfigCard.js**
   - Added read-only display fields (Lines 368-376)
   - Added edit form dropdowns (Lines 736-771)

### Configuration Files

7. **config.csv**
   - Added `serial_port` and `baudrate` columns
   - Set all drones to `/dev/ttyS0` and `57600` (default for RP4)

8. **config_sitl.csv**
   - Added `serial_port` and `baudrate` columns
   - Set all drones to `N/A` (not used in simulation)

---

## Backward Compatibility

### Automatic Detection

The system automatically detects old vs new CSV format:

```javascript
// Frontend (missionConfigUtilities.js)
const header = rows[0].trim();
const isOldFormat = header === "hw_id,pos_id,x,y,ip,mavlink_port,debug_port,gcs_ip";
const isNewFormat = header === "hw_id,pos_id,x,y,ip,mavlink_port,debug_port,gcs_ip,serial_port,baudrate";
```

### Migration Flow

1. User uploads old 8-column CSV
2. System shows toast: "Legacy CSV format detected. Serial port and baudrate will be set to defaults."
3. System auto-adds `/dev/ttyS0` and `57600` to all drones
4. User can save to persist new format

### Fallback Behavior

If columns missing from config, accessor methods fall back to global defaults:

```python
# src/drone_config.py
def get_serial_port(self):
    if self.config and 'serial_port' in self.config:
        return self.config['serial_port']
    return Params.serial_mavlink_port  # Fallback to /dev/ttyS0
```

---

## Troubleshooting

### Issue: CSV upload fails with "Invalid CSV format"

**Cause:** Header row doesn't match expected format

**Solution:**
1. Ensure header is exactly: `hw_id,pos_id,x,y,ip,mavlink_port,debug_port,gcs_ip,serial_port,baudrate`
2. No spaces around commas
3. All rows must have same number of columns

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

### Issue: MAVLink connection timeout

**Cause:** Wrong baudrate

**Solution:**
1. Check Pixhawk telem port baudrate (usually 57600)
2. Match `baudrate` in config.csv to Pixhawk setting
3. Common values: 57600, 115200, 921600

### Issue: SITL mode shows serial port errors

**Cause:** SITL trying to use serial port config

**Solution:**
Ensure `config_sitl.csv` has `N/A` values:
```csv
...,N/A,N/A
```

---

## Testing Checklist

### Before Deployment

- [ ] Run `python3 test_config_simple.py` (should pass all tests)
- [ ] Backup existing CSV files
- [ ] Verify hardware type for each drone (RP4 vs RP5 vs Jetson)
- [ ] Update serial ports accordingly
- [ ] Test CSV upload in Mission Config UI
- [ ] Verify new columns displayed correctly
- [ ] Test adding new drone (should have defaults)
- [ ] Export CSV and verify 10 columns present

### After Deployment

- [ ] Verify drones connect to Pixhawk
- [ ] Check MAVLink telemetry streaming
- [ ] Test mission execution
- [ ] Verify git auto-commit works with new CSV format
- [ ] Test mixed hardware fleet (if applicable)

---

## FAQ

**Q: Do I need to update my CSV files immediately?**
A: No. The system supports both old (8-column) and new (10-column) formats. However, you should update to take advantage of per-drone hardware configuration.

**Q: What happens if I don't specify serial_port/baudrate?**
A: The system falls back to global defaults from `src/params.py` (`/dev/ttyS0` @ `57600`).

**Q: Can I mix RP4 and RP5 in the same fleet?**
A: Yes! That's the whole point of this update. Just set different `serial_port` values per drone.

**Q: Will this affect my existing trajectories or missions?**
A: No. This only affects hardware configuration, not trajectory data.

**Q: How do I know which serial port my hardware uses?**
A: Check `/proc/cpuinfo` or consult the hardware reference table in this guide.

**Q: Can I use custom baudrates?**
A: Yes, but ensure your Pixhawk is configured for the same baudrate.

---

## Support

If you encounter issues during migration:

1. Check the test script output: `python3 test_config_simple.py`
2. Review backup files: `config.csv.backup`, `config_sitl.csv.backup`
3. Consult the example configurations in this guide
4. Report issues at: https://github.com/alireza787b/mavsdk_drone_show/issues

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 3.2 | Nov 2025 | Added `serial_port` and `baudrate` columns to config.csv |
| 3.1 | Earlier | Added environment variable support for Git config |
| 3.0 | Earlier | Initial multi-drone support |

---

**End of Migration Guide**
