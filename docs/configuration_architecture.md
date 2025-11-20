# Configuration Architecture: Position Management

## Overview

This document explains the **single source of truth** architecture for drone position management in the MAVSDK Drone Show system.

**KEY PRINCIPLE**: Drone positions (x, y coordinates) are ALWAYS read from trajectory CSV files, never stored in config.csv.

---

## Architecture

### Before (❌ Deprecated - Old System)

```
config.csv:
hw_id, pos_id, x, y, ip, ...
1,     1,      -5.0, 2.5, 100.96.240.11, ...

Problem: Two sources of truth caused:
- Synchronization bugs (x,y becoming empty or wrong)
- Confusion about which source to use
- Redundant data updates on every save
```

### After (✅ Current System)

```
config.csv:
hw_id, pos_id, ip, mavlink_port, serial_port, baudrate
1,     1,      100.96.240.11, 14551, /dev/ttyS0, 57600

Positions come from:
shapes/swarm/processed/Drone 1.csv (first row: px, py)
```

**Single Source of Truth**: Trajectory CSV files

---

## Data Flow

### 1. Configuration Storage

**config.csv** contains:
- `hw_id`: Physical hardware identifier
- `pos_id`: Which trajectory/show to fly (points to "Drone {pos_id}.csv")
- `ip`: Drone network address
- `mavlink_port`: MAVLink communication port
- `serial_port`: Serial connection (e.g., /dev/ttyS0)
- `baudrate`: Serial baud rate (e.g., 57600)

**Trajectory Files** (`shapes/swarm/processed/Drone {pos_id}.csv`):
- First row contains: `px` (North), `py` (East), `pz` (Down)
- These are the ONLY source for position coordinates

### 2. Position Retrieval

**Backend API**:
```python
GET /get-drone-positions
Returns: [{"hw_id": 1, "pos_id": 1, "x": -5.0, "y": 2.5}, ...]
```

**How it works**:
1. Read config.csv to get hw_id → pos_id mapping
2. For each pos_id, read `Drone {pos_id}.csv` first row
3. Extract px (x/North) and py (y/East) coordinates
4. Return combined data with hw_id, pos_id, x, y

**Helper Functions**:
- `get_all_drone_positions()` in `gcs-server/config.py`
- `_get_expected_position_from_trajectory()` in `gcs-server/origin.py`

### 3. Role Swaps

**Normal**: hw_id = pos_id
→ Drone 1 flies Position 1's show

**Role Swap**: hw_id ≠ pos_id
→ Drone 7 flies Position 1's show (hw_id=7, pos_id=1)

**Use Cases**:
- Hardware replacement (broken drone)
- Testing/debugging
- Flexible swarm reconfiguration

---

## API Endpoints

### GET /get-config-data
Returns drone configuration (NO x,y fields).

```json
[
  {
    "hw_id": "1",
    "pos_id": "1",
    "ip": "100.96.240.11",
    "mavlink_port": "14551",
    "serial_port": "/dev/ttyS0",
    "baudrate": "57600"
  }
]
```

### GET /get-drone-positions
Returns positions for all drones from trajectory CSV files.

```json
[
  {
    "hw_id": 1,
    "pos_id": 1,
    "x": -5.0,  // From Drone 1.csv first row (px)
    "y": 2.5    // From Drone 1.csv first row (py)
  }
]
```

### POST /save-config-data
Saves configuration (x,y automatically stripped if present).

**Request**:
```json
[
  {
    "hw_id": "1",
    "pos_id": "1",
    "ip": "100.96.240.11",
    "mavlink_port": "14551",
    "serial_port": "/dev/ttyS0",
    "baudrate": "57600"
  }
]
```

### POST /validate-config
Validates configuration before saving. Checks:
- Duplicate pos_id values (collision risk)
- Missing trajectory files
- Role swaps (hw_id ≠ pos_id)

**Returns validation report** for review dialog.

### GET /get-trajectory-first-row?pos_id={id}
Gets position for single pos_id (used for individual updates).

```json
{
  "pos_id": 1,
  "north": -5.0,
  "east": 2.5,
  "source": "Drone 1.csv (first waypoint)"
}
```

---

## Frontend Implementation

### Configuration Page (MissionConfig.js)

**On Page Load**:
- Fetches config from `/get-config-data` (no x,y)
- Can optionally fetch positions from `/get-drone-positions` for display

**Editing Drones**:
- DroneConfigCard shows hw_id, pos_id, ip, etc.
- NO x,y input fields (removed)
- Positions displayed as read-only info (if needed)

**Saving Changes**:
1. User clicks "Save & Commit to Git"
2. `/validate-config` called → returns report
3. SaveReviewDialog shows changes/warnings
4. User confirms → `/save-config-data` called
5. Success toast reminds: **"Reboot drones to apply changes"**

### UI Features

**Reset to Default Button**:
- Sets pos_id = hw_id for all drones
- Shows preview of changes before applying
- Changes not saved until "Save & Commit"

**Role Swap Warnings**:
- Banner shows first 3 role swaps
- "and X more" link opens modal with full list
- Clear visual indicators on drone cards

**Validation**:
- Duplicate pos_id → COLLISION RISK warning
- Missing trajectory files → Blocks save
- Requires acknowledgment for risky operations

---

## Code Locations

### Backend (Python)
- `gcs-server/config.py`:
  - `CONFIG_COLUMNS` (x,y removed)
  - `get_all_drone_positions()`
  - `validate_and_process_config()`

- `gcs-server/routes.py`:
  - `/get-drone-positions` endpoint
  - `/save-config-data` endpoint
  - `/validate-config` endpoint

- `gcs-server/origin.py`:
  - `_get_expected_position_from_trajectory()`

- `drone_show.py`:
  - Uses trajectory CSV first row (calls `read_trajectory_file()`)

### Frontend (React)
- `src/utilities/missionConfigUtilities.js`:
  - `handleSaveChangesToServer()` (x,y removed)
  - `validateConfigWithBackend()` (x,y removed)

- `src/components/DroneConfigCard.js`:
  - Edit form (x,y inputs removed)
  - Accept auto/HB pos_id (simplified - no x,y fetch)

- `src/components/SaveReviewDialog.js`:
  - Shows validation warnings
  - NO x,y update section (removed)

- `src/pages/MissionConfig.js`:
  - Reset to Default handler
  - Role Swap modal

---

## Migration Guide

### For Existing Deployments

**Before updating**:
1. Backup `config.csv`
2. Ensure all trajectory CSV files exist in `shapes/swarm/processed/`

**After updating**:
1. Old `config.csv` with x,y columns will work (backend strips x,y on save)
2. First save will migrate to new format automatically
3. Hard refresh browser (Ctrl+Shift+R) to clear cached UI

**Verification**:
```bash
# Check config.csv header
head -1 config.csv
# Should show: hw_id,pos_id,ip,mavlink_port,serial_port,baudrate

# Test API
curl http://localhost:5002/get-drone-positions
# Should return positions from trajectory files
```

---

## Best Practices

### Adding New Drones
1. Add row to config.csv with hw_id, pos_id, ip, etc.
2. Ensure trajectory file exists: `shapes/swarm/processed/Drone {pos_id}.csv`
3. Position comes automatically from trajectory file

### Changing Drone Positions
1. Edit trajectory CSV file (Drone Show Designer tool)
2. Upload new show → trajectory files updated
3. Positions automatically reflect new trajectories
4. NO manual x,y updates needed

### Role Swaps
1. Change pos_id in config (e.g., hw_id=7, pos_id=1)
2. Drone 7 will fly Position 1's trajectory
3. Position comes from Drone 1.csv (pos_id source)

### Debugging Position Issues
1. Check trajectory file exists: `ls shapes/swarm/processed/Drone {pos_id}.csv`
2. Check first row: `head -2 shapes/swarm/processed/Drone {pos_id}.csv`
3. Call API: `curl http://localhost:5002/get-drone-positions`
4. Compare with expected values

---

## Benefits

✅ **Single Source of Truth**: No synchronization bugs
✅ **Automatic Updates**: Change trajectory → positions update
✅ **Less Confusion**: Clear where positions come from
✅ **Cleaner Code**: Removed redundant x,y handling
✅ **Better UX**: Simplified UI, clear validation
✅ **Robust**: Falsy value bugs eliminated

---

## Common Questions

**Q: Where are drone positions stored?**
A: In trajectory CSV files (`shapes/swarm/processed/Drone {pos_id}.csv` first row).

**Q: Why remove x,y from config.csv?**
A: They were redundant, caused sync bugs, and confused users about source of truth.

**Q: How do I change a drone's position?**
A: Edit the trajectory CSV file for that pos_id (via Drone Show Designer).

**Q: What if I change pos_id?**
A: The drone will fly the new pos_id's trajectory. Position comes from that trajectory's CSV file.

**Q: Can I still do role swaps?**
A: Yes! Set hw_id ≠ pos_id. The drone flies the pos_id's trajectory, not its own.

**Q: How do I revert to old system?**
A: Not recommended. The old x,y fields caused bugs. Use trajectory CSV as source of truth.

---

**Last Updated**: 2025-11-20
**Version**: 2.0 (Single Source of Truth Architecture)
