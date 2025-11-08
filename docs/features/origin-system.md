# Origin System Implementation Guide
## Complete Reference for Drone Show Coordinate System Enhancement

**Document Version:** 1.0
**Date:** November 3, 2025
**Status:** Phase 1 Complete - Backend & Frontend Implemented
**Next Phase:** Integration with drone_show.py execution loop

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Critical Coordinate System Analysis](#critical-coordinate-system-analysis)
3. [Phase 1: What Was Implemented](#phase-1-what-was-implemented)
4. [drone_show.py Current Implementation Analysis](#drone_showpy-current-implementation-analysis)
5. [Phase 2: Integration Goals](#phase-2-integration-goals)
6. [Challenges and Constraints](#challenges-and-constraints)
7. [Technical Architecture](#technical-architecture)
8. [API Reference](#api-reference)
9. [Testing Strategy](#testing-strategy)
10. [Glossary of Terms](#glossary-of-terms)

---

## Executive Summary

### What Was Done in Phase 1

A comprehensive origin coordinate system was implemented for a professional drone show project, fixing critical coordinate bugs and adding altitude support. The system allows operators to:

1. **Set a global origin** (lat, lon, altitude MSL) for the entire drone formation
2. **Monitor real-time position deviations** between expected and actual drone positions
3. **View GPS quality indicators** (satellite count, HDOP, status)
4. **Use a professional tabbed UI** for launch planning and live monitoring

### Critical Bug Fixed

**OriginModal.js lines 128-129**: Coordinates were swapped - was sending `intended_east=drone.x`, `intended_north=drone.y`. Now correctly sends `intended_north=drone.x`, `intended_east=drone.y` to match the config.csv schema where **x=North, y=East** (NED coordinate system).

### Why This Matters

The current drone show execution (drone_show.py) assumes drones are **perfectly placed** by the operator at their intended launch positions. If there are:
- GPS drift
- Operator placement errors
- Ground slope/altitude differences

The show can go wrong because the execution loop zeros out CSV offsets from the assumed-perfect initial position.

**Phase 2 Goal**: Integrate this origin system into drone_show.py to enable a new mode where drones use **precise global corrections** after initial climb, ensuring the formation executes exactly as designed regardless of initial placement accuracy.

---

## Critical Coordinate System Analysis

### The Ground Truth: config.csv Schema

```csv
hw_id,pos_id,x,y,ip,mavlink_port,debug_port,gcs_ip
1,1,10.5,5.2,192.168.1.101,14551,13541,192.168.1.1
```

**Definitive Mapping:**
- `x` column = **North** (meters)
- `y` column = **East** (meters)
- This is **NED coordinate system** (North-East-Down)

### Evidence Trail

1. **InitialLaunchPlot.js:91-92** - UI plot correctly uses:
   ```javascript
   const n = parseFloat(drone.x); // North
   const e = parseFloat(drone.y); // East
   ```

2. **drone_show.py:207-208** - Execution correctly reads:
   ```python
   initial_x = float(row["x"])  # North
   initial_y = float(row["y"])  # East
   ```

3. **Trajectory CSV files** - Also use NED where px=North, py=East, pz=Down

### The Coordinate Systems in Play

There are **THREE distinct coordinate systems** in this project:

#### 1. Config.csv Coordinates (NED Ground Truth)
- **x = North** (meters)
- **y = East** (meters)
- Stored in `config.csv`
- Represents desired launch positions relative to formation origin
- Used by: UI plots, backend calculations, trajectory planning

#### 2. PX4 GPS Global Origin (MAVLink Convention)
- Set by PX4 autopilot at **first GPS lock** or when armed
- Used for **LOCAL_POSITION_NED ↔ GPS** conversions
- Retrieved via `drone.telemetry.get_gps_global_origin()`
- **NOT the same as formation origin** (critical distinction!)
- This is the autopilot's internal reference frame

#### 3. Formation Global Origin (Our New System)
- Manually set by operator via OriginModal
- Represents the **formation's** (0,0,0) point in GPS coordinates
- Includes altitude MSL for sloped terrain
- Used to calculate expected GPS positions for each drone
- Stored in `gcs-server/origin.json`

### Critical Distinction to Avoid Confusion

```
PX4 GPS Origin ≠ Formation Origin ≠ Launch Position

PX4 GPS Origin:       Where PX4 thinks (0,0,0) is (auto-set at first GPS lock)
Formation Origin:     Where WE want (0,0,0) to be (manually set)
Launch Position:      Where a specific drone should physically be (calculated)
```

### Coordinate Transformation Flow

```
Formation Space (config.csv)
    x=North, y=East (meters from formation origin)
              ↓
    Apply pymap3d.ned2geodetic()
              ↓
GPS Coordinates (WGS84)
    latitude, longitude, altitude MSL
              ↓
    Send to drone as setpoint
              ↓
Offboard Mode Execution
    (Local NED or Global LLA, configurable)
```

---

## Phase 1: What Was Implemented

### Backend Changes (Python)

#### 1. Fixed Coordinate Bugs

**File:** `gcs-server/origin.py`

**Changes:**
- Fixed misleading comments in `calculate_position_deviations()` lines 92-93
- Clarified that x=North, y=East (code was correct, comments were wrong)

**Before:**
```python
# WARNING: These comments were backwards!
config_x = float(drone.get('x', 0))  # x is East  ❌ WRONG COMMENT
config_y = float(drone.get('y', 0))  # y is North ❌ WRONG COMMENT
```

**After:**
```python
# Corrected comments
config_north = float(drone.get('x', 0))  # x is North ✅
config_east = float(drone.get('y', 0))   # y is East  ✅
```

**File:** `app/dashboard/drone-dashboard/src/components/OriginModal.js`

**Critical Bug Fix (lines 128-129, 137-138):**
```javascript
// BEFORE (BUG):
intended_east: parseFloat(drone.x) || 0,   // ❌ WRONG
intended_north: parseFloat(drone.y) || 0,  // ❌ WRONG

// AFTER (FIXED):
intended_north: parseFloat(drone.x) || 0,  // ✅ x is North
intended_east: parseFloat(drone.y) || 0,   // ✅ y is East
```

#### 2. Altitude Support (v2 Schema)

**File:** `gcs-server/origin.py`

**Schema Evolution:**

**v1 (Old):**
```json
{
  "lat": 37.7749,
  "lon": -122.4194
}
```

**v2 (New):**
```json
{
  "lat": 37.7749,
  "lon": -122.4194,
  "alt": 45.5,
  "alt_source": "drone_telemetry",
  "timestamp": "2025-11-03T10:30:45.123456",
  "version": 2
}
```

**Auto-Migration:** Old origin.json files automatically upgrade to v2 on first load, with `alt=0` (ground level default).

**Why Altitude Matters:**
- Professional shows often operate on **sloped terrain**
- GPS altitude (MSL) affects coordinate transformations
- Without altitude, calculations assume flat ground at sea level
- Altitude from drone telemetry is most accurate (GPS-derived)

#### 3. New API Endpoint: `/get-desired-launch-positions`

**Purpose:** Calculate GPS coordinates for each drone's intended launch position.

**Method:** GET

**Response Structure:**
```json
{
  "success": true,
  "origin": {
    "lat": 37.7749,
    "lon": -122.4194,
    "alt": 45.5,
    "source": "drone_telemetry"
  },
  "positions": [
    {
      "hw_id": "1",
      "pos_id": "1",
      "config_north": 10.5,
      "config_east": 5.2,
      "desired_lat": 37.774995,
      "desired_lon": -122.419334,
      "desired_alt": 45.5
    }
  ],
  "formation_stats": {
    "total_drones": 10,
    "extent_north_south": 25.3,
    "extent_east_west": 18.7,
    "max_distance_from_origin": 31.2,
    "formation_diameter": 62.4
  },
  "heading": 0
}
```

**Coordinate Conversion:**
Uses `pymap3d.ned2geodetic()` for coordinate transformations:

```python
import pymap3d as pm

launch_lat, launch_lon, launch_alt = pm.ned2geodetic(
    config_north,  # meters north of origin
    config_east,   # meters east of origin
    0,             # altitude offset (0 for ground level)
    origin_lat,    # formation origin latitude
    origin_lon,    # formation origin longitude
    origin_alt     # formation origin altitude MSL
)
```

**Why pymap3d?**
- Same library used in drone_show.py for consistency
- Accurate for distances up to ~100km
- Handles Earth curvature and ellipsoid corrections
- WGS84 geodetic standard

#### 4. Refactored Endpoint: `/get-position-deviations`

**Purpose:** Professional position monitoring with GPS quality and status.

**Method:** GET

**Response Structure:**
```json
{
  "success": true,
  "origin": {
    "lat": 37.7749,
    "lon": -122.4194,
    "alt": 45.5
  },
  "deviations": {
    "1": {
      "hw_id": "1",
      "expected": {
        "lat": 37.774995,
        "lon": -122.419334,
        "alt": 45.5,
        "north": 10.5,
        "east": 5.2
      },
      "current": {
        "lat": 37.774993,
        "lon": -122.419332,
        "alt": 46.2,
        "north": 10.3,
        "east": 5.1,
        "gps_quality": "excellent",
        "satellites": 18,
        "hdop": 0.7
      },
      "deviation": {
        "north": -0.2,
        "east": -0.1,
        "horizontal": 0.22,
        "vertical": 0.7,
        "total_3d": 0.73
      },
      "status": "ok",
      "message": "Position within acceptable tolerance"
    }
  },
  "summary": {
    "total_drones": 10,
    "online": 8,
    "status_counts": {
      "ok": 6,
      "warning": 2,
      "error": 0,
      "no_telemetry": 2
    },
    "best_deviation": 0.15,
    "worst_deviation": 2.34,
    "average_deviation": 0.87
  },
  "timestamp": "2025-11-03T10:30:45.123456"
}
```

**GPS Quality Classification:**
```python
def classify_gps_quality(satellites, hdop):
    if satellites >= 10 and hdop <= 1.0:
        return "excellent"
    elif satellites >= 8 and hdop <= 2.0:
        return "good"
    elif satellites >= 6 and hdop <= 5.0:
        return "fair"
    elif satellites >= 4:
        return "poor"
    else:
        return "no_fix"
```

**Status Classification:**
```python
def classify_status(horizontal_deviation):
    if horizontal_deviation < 2.0:
        return "ok"         # Green
    elif horizontal_deviation < 5.0:
        return "warning"    # Orange
    else:
        return "error"      # Red
```

**Deviation Calculations:**
```python
# Horizontal deviation (2D)
horizontal_deviation = sqrt(north_dev² + east_dev²)

# Vertical deviation (altitude)
vertical_deviation = abs(expected_alt - current_alt)

# Total 3D deviation
total_3d_deviation = sqrt(north_dev² + east_dev² + vertical_dev²)
```

#### 5. Updated Endpoints: `/set-origin` and `/get-origin`

**Both now support altitude field with backwards compatibility.**

**Set Origin:**
```python
POST /set-origin
{
  "lat": 37.7749,
  "lon": -122.4194,
  "alt": 45.5,           # Optional, defaults to 0
  "alt_source": "manual" # "manual", "drone_telemetry", or "gps_lock"
}
```

**Get Origin:**
```python
GET /get-origin
Response:
{
  "lat": 37.7749,
  "lon": -122.4194,
  "alt": 45.5,
  "alt_source": "drone_telemetry",
  "timestamp": "2025-11-03T10:30:45.123456",
  "version": 2
}
```

### Frontend Changes (React)

#### 1. Enhanced OriginModal.js

**New Features:**
- Altitude MSL input field in manual mode
- Auto-capture altitude from drone telemetry in drone mode
- Display altitude in computed origin results
- Backwards compatible (altitude optional)

**Manual Mode UI:**
```jsx
<label style={{marginTop: '1rem'}}>
  Altitude MSL (optional, meters):
  <input
    type="number"
    step="0.1"
    value={altitude}
    onChange={(e) => setAltitude(e.target.value)}
    placeholder="Ground level (default: 0m)"
  />
</label>
```

**Drone Mode Auto-Capture:**
```jsx
useEffect(() => {
  if (mode === 'drone' && selectedDrone) {
    const telemetry = telemetryData[selectedDrone.hw_id];
    if (telemetry?.altitude !== undefined) {
      setAltitude(telemetry.altitude.toString());
      setAltitudeSource('drone_telemetry');
    }
  }
}, [mode, selectedDrone, telemetryData]);
```

#### 2. New Component: PositionTabs.js

**Purpose:** Tabbed interface for Launch Plot and Position Monitoring.

**Features:**
- Clean tab navigation with active indicators
- Badge indicators showing warnings/errors count
- Smooth animations
- Responsive design

**Tab Structure:**
```jsx
<PositionTabs>
  <Tab name="launch">
    📍 Launch Plot
    <InitialLaunchPlot />
  </Tab>
  <Tab name="deviation">
    📊 Position Monitoring [🟡2] [🔴0]
    <DeviationView />
  </Tab>
</PositionTabs>
```

**Badge Logic:**
```jsx
const warnings = Object.values(deviationData.deviations || {})
  .filter(d => d.status === 'warning').length;

const errors = Object.values(deviationData.deviations || {})
  .filter(d => d.status === 'error').length;
```

#### 3. New Component: DeviationView.js

**Purpose:** Real-time position monitoring with expected vs actual visualization.

**Key Features:**

**Auto-Refresh Mechanism:**
```jsx
useEffect(() => {
  if (!autoRefresh || !onRefresh) return;

  const interval = setInterval(() => {
    onRefresh();
    setLastUpdate(new Date());
  }, 5000); // Refresh every 5 seconds

  return () => clearInterval(interval);
}, [autoRefresh, onRefresh]);
```

**Three-Layer Plotly Visualization:**

1. **Expected Positions** (solid blue circles)
   ```javascript
   marker: {
     size: 18,
     color: '#3498db',
     symbol: 'circle'
   }
   ```

2. **Current Positions** (outlined, color-coded by status)
   ```javascript
   marker: {
     size: 24,
     color: statusColors[status], // green/orange/red/gray
     symbol: 'circle-open',
     line: { width: 4 }
   }
   ```

3. **Deviation Vectors** (lines from expected to current)
   ```javascript
   mode: 'lines',
   line: {
     color: 'rgba(231, 76, 60, 0.5)',
     width: 2
   }
   ```

**Rich Hover Tooltips:**
```javascript
hovertemplate:
  'Drone: %{customdata.hw_id}<br>' +
  'Expected: (%{customdata.exp_n:.2f}m N, %{customdata.exp_e:.2f}m E)<br>' +
  'Current: (%{customdata.cur_n:.2f}m N, %{customdata.cur_e:.2f}m E)<br>' +
  'Deviation: %{customdata.deviation:.2f}m<br>' +
  'GPS: %{customdata.satellites} sats, HDOP %{customdata.hdop:.1f}<br>' +
  'Quality: %{customdata.gps_quality}<br>' +
  '<extra></extra>'
```

**Summary Statistics Header:**
```jsx
<div className="deviation-summary">
  <StatCard type="success" value={online} label="Online" />
  <StatCard type="success" value={okCount} label="OK" />
  <StatCard type="warning" value={warningCount} label="Warnings" />
  <StatCard type="error" value={errorCount} label="Errors" />
  <StatCard value={avgDeviation} label="Avg Dev (m)" />
  <StatCard value={worstDeviation} label="Worst (m)" />
</div>
```

#### 4. Updated MissionConfig.js

**Integration:**
```jsx
import PositionTabs from '../components/PositionTabs';

// Manual refresh handler
const handleManualRefresh = () => {
  if (!originAvailable) {
    toast.warning('Origin must be set before fetching position deviations.');
    return;
  }

  const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');
  axios.get(`${backendURL}/get-position-deviations`)
    .then((response) => setDeviationData(response.data))
    .catch((error) => {
      console.error('Error fetching position deviations:', error);
      toast.error('Failed to refresh position data.');
    });
};

// Replace InitialLaunchPlot with PositionTabs
<PositionTabs
  drones={configData}
  deviationData={deviationData}
  origin={origin}
  forwardHeading={forwardHeading}
  onDroneClick={setEditingDroneId}
  onRefresh={handleManualRefresh}
/>
```

#### 5. Professional CSS Styling

**Design Token System:**
- Follows existing `DesignTokens.css` patterns
- Dark/light theme support via CSS variables
- Responsive breakpoints for mobile/tablet/desktop
- Accessibility features (reduced motion support)

**Key Styling Features:**

**PositionTabs.css:**
- Clean tab navigation with hover effects
- Active tab indicator with bottom border
- Badge animations (pulse effect)
- Fade-in transitions for tab content

**DeviationView.css:**
- Stat card grid with hover lift effect
- Status-based color coding
- Professional legend with color markers
- Loading state animations
- Responsive grid (auto-fit minmax)

**Color Coding:**
```css
.marker.current.ok { border-color: #27ae60; }      /* Green */
.marker.current.warning { border-color: #f39c12; } /* Orange */
.marker.current.error { border-color: #e74c3c; }   /* Red */
```

### Commits Created

**Commit 1:** `17a0d07c` - feat: Fix origin system coordinate bugs and add altitude support
- Backend implementation (Python)
- 493 insertions, 35 deletions
- Files: origin.py, routes.py, OriginModal.js

**Commit 2:** `3b29fa9d` - feat: Add professional position monitoring UI with tabbed interface
- Frontend implementation (React)
- 1084 insertions, 12 deletions
- Files: PositionTabs.js, DeviationView.js, *.css, MissionConfig.js

---

## drone_show.py Current Implementation Analysis

### High-Level Architecture

The `drone_show.py` script orchestrates autonomous drone shows with these key phases:

```
1. Initialization → 2. Pre-flight → 3. Arm/Offboard → 4. Initial Climb → 5. Trajectory → 6. Landing
```

### Critical Components for Phase 2

#### 1. Launch Position Handling (Lines 184-236)

**Function:** `read_config()`

```python
def read_config(filename: str) -> Drone:
    """
    Read the drone configuration from a CSV file.
    This CSV is assumed to store real NED coordinates directly:
      - initial_x => North
      - initial_y => East
    """
    # ...
    initial_x = float(row["x"])  # North
    initial_y = float(row["y"])  # East

    drone = Drone(
        hw_id, pos_id,
        initial_x, initial_y,  # ← Launch offsets
        ip, mavlink_port, debug_port, gcs_ip
    )
```

**What It Does:**
- Reads config.csv
- Extracts `x` (North) and `y` (East) as **launch position offsets**
- These represent where the drone **should be** relative to formation origin

**Current Assumption:** Operator places drone exactly at `(initial_x, initial_y)`.

#### 2. Trajectory Loading (Lines 370-537)

**Function:** `read_trajectory_file()`

**Two Modes Controlled by `auto_launch_position` Parameter:**

**Mode A: Auto Launch Position = True**
```python
if auto_launch_position:
    # Extract initial positions from first waypoint
    init_n, init_e, init_d = extract_initial_positions(rows[0])

    # Adjust ALL waypoints so first waypoint becomes (0,0,0)
    waypoints = adjust_waypoints(waypoints, init_n, init_e, init_d)
```

**Mode B: Auto Launch Position = False** (DEFAULT)
```python
else:
    # Use config.csv initial_x, initial_y
    # Shift trajectory so it starts from config position
    waypoints = adjust_waypoints(waypoints, initial_x, initial_y, 0.0)
```

**Critical Insight:** Both modes **zero out** offsets by subtracting initial positions. This means trajectory execution always starts from (0,0,0) in NED frame.

#### 3. Initial Position Drift Correction (Lines 1099-1140)

**Function:** `compute_position_drift()`

```python
async def compute_position_drift():
    """
    Compute initial position drift using LOCAL_POSITION_NED from the drone's API.
    The NED origin is automatically set when the drone arms (matches GPS_GLOBAL_ORIGIN).

    Returns:
        PositionNedYaw: Drift in NED coordinates or None if unavailable
    """
    response = requests.get(
        f"http://localhost:{Params.drones_flask_port}/get-local-position-ned",
        timeout=2
    )

    if response.status_code == 200:
        ned_data = response.json()
        drift = PositionNedYaw(
            north_m=ned_data['x'],  # How far north from PX4's origin
            east_m=ned_data['y'],   # How far east from PX4's origin
            down_m=ned_data['z'],   # How far down from PX4's origin
            yaw_deg=0.0
        )
        return drift
```

**What This Captures:**
- At arming time, PX4 sets its GPS origin (wherever the drone is)
- This function reads the drone's position relative to **PX4's origin**
- If `ENABLE_INITIAL_POSITION_CORRECTION = True`, this drift is **added** to all waypoints

**Current Behavior (if enabled):**
```python
if Params.ENABLE_INITIAL_POSITION_CORRECTION and initial_position_drift:
    px = raw_px + initial_position_drift.north_m  # Shift trajectory
    py = raw_py + initial_position_drift.east_m
    pz = raw_pz + initial_position_drift.down_m
```

**Problem:** This correction is based on PX4's auto-set origin, **not** the formation origin we want.

#### 4. GPS Origin vs Formation Origin (Lines 942-1032)

**Function:** `pre_flight_checks()`

```python
async def pre_flight_checks(drone: System):
    """
    Perform pre-flight checks to ensure the drone is ready for flight, including:
    - Checking the health of the global and home position via MAVSDK
    - Fetching the GPS global origin using MAVSDK when health is valid
    """
    # ...

    # Get PX4's GPS origin
    origin = await drone.telemetry.get_gps_global_origin()
    gps_origin = {
        'latitude': origin.latitude_deg,
        'longitude': origin.longitude_deg,
        'altitude': origin.altitude_m
    }

    # This is PX4's internal origin, NOT formation origin
    return gps_origin
```

**Critical Distinction:**

```
PX4 GPS Origin (gps_origin returned here):
  ├─ Set by PX4 at first GPS lock or arming
  ├─ Used for LOCAL_POSITION_NED ↔ GPS conversions internally
  └─ NOT under our control

Formation Origin (from origin.json):
  ├─ Set by operator via OriginModal
  ├─ Defines where (0,0,0) should be for the formation
  └─ Used to calculate expected GPS positions
```

**These are NOT the same and must not be confused!**

#### 5. Coordinate Transformation for Global Setpoints (Lines 705-728)

**In `perform_trajectory()` function:**

```python
# Calculate GPS coordinates from NED setpoint
lla_lat, lla_lon, lla_alt = pm.ned2geodetic(
    px, py, pz,                    # NED position from CSV
    launch_lat, launch_lon, launch_alt  # Drone's launch GPS position
)

if Params.USE_GLOBAL_SETPOINTS:
    # Send GLOBAL setpoint (lat, lon, alt, yaw)
    gp = PositionGlobalYaw(
        lla_lat, lla_lon, lla_alt,
        raw_yaw,
        PositionGlobalYaw.AltitudeType.AMSL
    )
    await drone.offboard.set_position_global(gp)
else:
    # Send LOCAL NED setpoint
    ln = PositionNedYaw(px, py, pz, raw_yaw)
    await drone.offboard.set_position_ned(ln)
```

**What This Does:**
- `USE_GLOBAL_SETPOINTS = False`: Sends local NED positions (default)
- `USE_GLOBAL_SETPOINTS = True`: Converts to GPS and sends global positions

**Launch Position Capture (Lines 1432-1447):**
```python
# Capture launch position from telemetry
async for pos in drone.telemetry.position():
    launch_lat = pos.latitude_deg
    launch_lon = pos.longitude_deg
    launch_alt = pos.absolute_altitude_m
    break
```

**Current Behavior:**
- `launch_lat/lon/alt` = **where the drone currently is** when script starts
- This is used as the reference point for coordinate conversions
- **Assumes** drone is at the correct position already

#### 6. Current Parameter Modes

**From `src/params.py` (referenced but not shown):**

```python
# Positioning modes
AUTO_LAUNCH_POSITION = False  # Use config.csv positions vs first waypoint
ENABLE_INITIAL_POSITION_CORRECTION = True  # Apply PX4 origin drift

# Offboard mode
USE_GLOBAL_SETPOINTS = False  # Local NED vs Global GPS setpoints

# Global position requirements
REQUIRE_GLOBAL_POSITION = True  # Require GPS lock for pre-flight
```

### The Core Problem

**Current Flow (Simplified):**

```
1. Operator places drone (assume it's at correct position)
2. Script reads config.csv: initial_x=10.5, initial_y=5.2
3. Script captures launch_lat/lon/alt = wherever drone is now
4. Trajectory CSV is loaded and adjusted to start from (0,0,0)
5. During execution:
   - If USE_GLOBAL_SETPOINTS=False: Sends NED positions relative to launch point
   - If USE_GLOBAL_SETPOINTS=True: Converts NED to GPS using launch_lat/lon/alt
6. Result: Show executes from wherever drones actually are
```

**If Drones Are Misplaced:**
- GPS drift moves drone 2m east → show formation shifts 2m east
- Operator places drone wrong → entire show offset
- Sloped ground → altitude errors
- No feedback that placement was wrong

### What Phase 2 Needs to Implement

**New Mode: Global Correction (Origin-Based Execution)**

```
1. Operator places drones (doesn't need to be perfect)
2. Script reads config.csv: initial_x=10.5, initial_y=5.2
3. Script reads formation origin: origin_lat, origin_lon, origin_alt
4. Calculate expected GPS position for this drone:
   expected_lat, expected_lon, expected_alt = ned2geodetic(
       initial_x, initial_y, 0,
       origin_lat, origin_lon, origin_alt
   )
5. Capture actual launch position: launch_lat, launch_lon, launch_alt
6. Calculate position error:
   error_north, error_east, error_down = geodetic2ned(
       launch_lat, launch_lon, launch_alt,
       expected_lat, expected_lon, expected_alt
   )
7. During initial climb: Move from current position
8. After initial climb: Correct to expected position
9. Execute trajectory from corrected position
```

**Benefits:**
- Formation executes correctly even with placement errors
- GPS drift compensated
- Altitude corrections for sloped terrain
- Real-time monitoring shows corrections being applied

---

## Phase 2: Integration Goals

### Primary Objective

Integrate the origin system into `drone_show.py` to enable **origin-based execution mode** where drones automatically correct to their intended launch positions using global GPS coordinates.

### Specific Goals

1. **Add New Execution Mode: `USE_ORIGIN_CORRECTION`**
   - When enabled: Use formation origin for position corrections
   - When disabled: Current behavior (rely on operator placement)
   - Default: **OFF** (don't break existing shows)

2. **Calculate Expected Launch Position**
   - Read formation origin from backend API
   - Calculate expected GPS position for this drone using config.csv offsets
   - Compare with actual launch position
   - Log discrepancies

3. **Apply Position Correction After Initial Climb**
   - During initial climb: Vertical-only (maintain current horizontal position)
   - After initial climb: Move to expected GPS position
   - Smooth transition to avoid abrupt maneuvers

4. **Fallback Mechanisms**
   - If origin not available: Fall back to current behavior
   - If GPS quality poor: Use local NED only
   - If correction distance > threshold: Warn and abort

5. **Clean Up Confusing Parameters**
   - Rename/consolidate redundant parameters
   - Clear documentation of each mode
   - Remove conflicting options

6. **Full Logging and Telemetry**
   - Log expected vs actual positions
   - Report correction distances
   - Send telemetry to GCS for monitoring

### Success Criteria

- [ ] Existing shows run unchanged with `USE_ORIGIN_CORRECTION=False`
- [ ] New mode corrects placement errors up to configurable threshold (e.g., 5m)
- [ ] Formation executes precisely when origin is set correctly
- [ ] No breaking changes to current API or parameters
- [ ] Full test coverage with SITL simulation
- [ ] Documentation updated with new mode explanation

---

## Challenges and Constraints

### Technical Challenges

#### 1. Coordinate Frame Confusion

**Problem:** Multiple coordinate systems with similar names.

**Solutions:**
- Use explicit naming: `formation_origin`, `px4_origin`, `launch_position`
- Document each clearly in code comments
- Never reuse variable names across different coordinate systems

#### 2. Timing of Corrections

**Problem:** When to apply position corrections?

**Constraints:**
- Can't correct during initial climb (drone is climbing vertically)
- Can't correct too late (show already started)
- Must avoid abrupt maneuvers (smooth transition)

**Proposed Approach:**
```
1. Arm at current position (wherever drone is)
2. Initial climb: Vertical only, maintain horizontal position
3. At climb completion: Smooth transition to expected position
4. Execute trajectory from corrected position
```

#### 3. GPS Accuracy and Drift

**Problem:** GPS is not perfectly accurate.

**Considerations:**
- RTK GPS: ~2cm accuracy (best case)
- Standard GPS: ~2-5m accuracy (typical)
- HDOP affects accuracy (lower is better)
- Satellite count matters (more is better)

**Mitigations:**
- Check GPS quality before corrections
- Set minimum satellite count (e.g., 8 sats)
- Set maximum HDOP threshold (e.g., 2.0)
- Allow operator override

#### 4. Safety Thresholds

**Problem:** Large corrections could be dangerous.

**Requirements:**
- Maximum correction distance (e.g., 10m)
- If exceeded: Log error and abort
- Pre-flight validation of expected positions
- Geofence checks

**Implementation:**
```python
MAX_CORRECTION_DISTANCE = 10.0  # meters

correction_distance = sqrt(error_north² + error_east²)

if correction_distance > MAX_CORRECTION_DISTANCE:
    logger.error(f"Correction distance {correction_distance:.2f}m exceeds "
                 f"maximum {MAX_CORRECTION_DISTANCE}m. Aborting.")
    raise ValueError("Position correction too large - likely config error")
```

#### 5. Backwards Compatibility

**Problem:** Can't break existing shows.

**Requirements:**
- Default behavior unchanged
- New mode opt-in only
- Existing parameter files work
- Graceful fallback if origin not available

### Operational Constraints

#### 1. Field Workflow

**Current Workflow:**
```
1. Deploy drones on ground in formation
2. Operator visually places each drone at correct position
3. Power on drones
4. Launch show
```

**New Workflow (Optional):**
```
1. Set formation origin (once, from GCS)
2. Deploy drones roughly in formation (doesn't need to be perfect)
3. Power on drones
4. System auto-calculates corrections
5. Monitor position deviations in UI
6. Launch show (drones auto-correct during initial climb)
```

#### 2. Internet Connectivity

**Problem:** Drones in field may not have reliable internet.

**Solutions:**
- Origin can be pre-loaded to `origin.json` file
- Drones read from local file, not API
- API only for real-time monitoring (optional)

#### 3. Multi-Show Operation

**Problem:** Different shows, different origins.

**Solutions:**
- Origin stored per-show or per-location
- Load correct origin file before launch
- UI shows which origin is active

### Code Quality Constraints

#### 1. Don't Break drone_show.py Execution

**Critical Rule:** The execution loop in `perform_trajectory()` is battle-tested. Don't change core flight logic unless absolutely necessary.

**Allowed Changes:**
- Add new optional correction logic
- Enhance logging
- Improve comments

**Forbidden Changes:**
- Modify core offboard mode handling
- Change timing or waypoint execution
- Alter safety mechanisms

#### 2. Clean Up Redundancies

**Current Redundant Concepts:**
```
- PX4 origin vs formation origin (both called "origin")
- launch_position vs initial_position vs home_position
- auto_launch_position vs ENABLE_INITIAL_POSITION_CORRECTION
- USE_GLOBAL_SETPOINTS vs USE_ORIGIN_CORRECTION (new)
```

**Goal:** Clear, distinct terms for each concept.

#### 3. Documentation Requirements

Every function dealing with coordinates must document:
- Which coordinate system it uses
- What reference frame (PX4 origin? Formation origin?)
- Units (meters? degrees?)
- Example values

**Template:**
```python
def calculate_expected_position(config_north: float, config_east: float,
                                formation_origin: dict) -> dict:
    """
    Calculate expected GPS position from formation-relative coordinates.

    Coordinate System: Uses formation origin as (0,0,0) reference.

    Args:
        config_north (float): North offset in meters from formation origin
        config_east (float): East offset in meters from formation origin
        formation_origin (dict): Formation origin with 'lat', 'lon', 'alt' keys
                                in WGS84 coordinates (degrees, meters MSL)

    Returns:
        dict: Expected GPS position with keys:
            - 'lat': Latitude in degrees (WGS84)
            - 'lon': Longitude in degrees (WGS84)
            - 'alt': Altitude in meters MSL

    Example:
        config_north = 10.5  # 10.5m north of origin
        config_east = 5.2    # 5.2m east of origin
        origin = {'lat': 37.7749, 'lon': -122.4194, 'alt': 45.5}

        expected = calculate_expected_position(config_north, config_east, origin)
        # Returns: {'lat': 37.774995, 'lon': -122.419334, 'alt': 45.5}
    """
```

---

## Technical Architecture

### System Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        OPERATOR (GCS)                            │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ Dashboard UI (React)                                        │ │
│  │  ├─ OriginModal: Set formation origin (lat/lon/alt)        │ │
│  │  ├─ LaunchPlot: Visualize formation layout                 │ │
│  │  └─ DeviationView: Monitor real-time positions             │ │
│  └────────────────────────────────────────────────────────────┘ │
│                            ↓ HTTP API                            │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ GCS Server (Flask Python)                                   │ │
│  │  ├─ /set-origin: Save formation origin                     │ │
│  │  ├─ /get-origin: Retrieve formation origin                 │ │
│  │  ├─ /get-desired-launch-positions: Calculate GPS coords    │ │
│  │  └─ /get-position-deviations: Monitor deviations           │ │
│  │                                                              │ │
│  │  Data Store: origin.json (formation origin)                │ │
│  │              config.csv (drone offsets)                     │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                            ↓ WiFi/Network
┌─────────────────────────────────────────────────────────────────┐
│                    DRONE (Raspberry Pi)                          │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ drone_show.py (Python)                          [PHASE 2]  │ │
│  │  ├─ Read origin.json (formation origin)         [NEW]     │ │
│  │  ├─ Read config.csv (this drone's offsets)                 │ │
│  │  ├─ Calculate expected GPS position              [NEW]     │ │
│  │  ├─ Capture actual GPS position                            │ │
│  │  ├─ Calculate correction vector                  [NEW]     │ │
│  │  └─ Execute trajectory with corrections          [NEW]     │ │
│  └────────────────────────────────────────────────────────────┘ │
│                            ↓ MAVLink                             │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ MAVSDK Server (gRPC ↔ MAVLink bridge)                      │ │
│  │  ├─ Telemetry: GPS position, altitude, heading            │ │
│  │  ├─ Offboard: Send position/velocity setpoints            │ │
│  │  └─ Action: Arm, disarm, land                              │ │
│  └────────────────────────────────────────────────────────────┘ │
│                            ↓ MAVLink                             │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ PX4 Autopilot (Flight Controller)                          │ │
│  │  ├─ GPS: Provides position, altitude, quality             │ │
│  │  ├─ EKF: Fuses GPS + IMU + baro for state estimate        │ │
│  │  ├─ Position Controller: Tracks setpoints                 │ │
│  │  └─ Sets GPS origin automatically at arming               │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow: Position Correction Mode

```
┌──────────────────────────────────────────────────────────────────┐
│ STEP 1: Initialization (Before Flight)                           │
└──────────────────────────────────────────────────────────────────┘
  Operator sets formation origin via OriginModal:
    origin = {lat: 37.7749, lon: -122.4194, alt: 45.5}
  Saved to: gcs-server/origin.json

  ↓

┌──────────────────────────────────────────────────────────────────┐
│ STEP 2: Drone Startup (drone_show.py)                            │
└──────────────────────────────────────────────────────────────────┘
  Read config.csv for this drone (HW_ID=1):
    config_north = 10.5m  (x column)
    config_east = 5.2m    (y column)

  Read origin.json:
    origin_lat = 37.7749
    origin_lon = -122.4194
    origin_alt = 45.5

  Calculate expected GPS position:
    expected_lat, expected_lon, expected_alt = ned2geodetic(
      10.5, 5.2, 0,
      37.7749, -122.4194, 45.5
    )
    → expected_lat = 37.774995
    → expected_lon = -122.419334
    → expected_alt = 45.5

  ↓

┌──────────────────────────────────────────────────────────────────┐
│ STEP 3: Pre-Flight (before arming)                               │
└──────────────────────────────────────────────────────────────────┘
  Wait for GPS lock (pre_flight_checks)

  Capture actual launch position:
    launch_lat = 37.774990  (drone is 5m south of expected)
    launch_lon = -122.419330
    launch_alt = 46.2

  Calculate position error:
    error_north, error_east, error_down = geodetic2ned(
      37.774990, -122.419330, 46.2,
      37.774995, -122.419334, 45.5
    )
    → error_north = -5.0m  (5m south of expected)
    → error_east = -0.4m   (0.4m west of expected)
    → error_down = 0.7m    (0.7m above expected)

  Calculate correction distance:
    correction_distance = sqrt(5.0² + 0.4²) = 5.02m

  Check safety threshold:
    if correction_distance > MAX_CORRECTION_DISTANCE:
      ABORT (config error or wrong origin)
    else:
      LOG: "Position correction required: 5.02m"

  ↓

┌──────────────────────────────────────────────────────────────────┐
│ STEP 4: Arming and Initial Climb                                 │
└──────────────────────────────────────────────────────────────────┘
  Arm drone at current position
  PX4 sets its GPS origin = launch_lat/lon/alt

  Initial climb (vertical only):
    - Maintain horizontal position (current north/east)
    - Climb to INITIAL_CLIMB_ALTITUDE_THRESHOLD (e.g., 5m)
    - Use LOCAL_NED mode for climb

  ↓

┌──────────────────────────────────────────────────────────────────┐
│ STEP 5: Position Correction (after initial climb)                │
└──────────────────────────────────────────────────────────────────┘
  Calculate correction waypoint:
    If USE_ORIGIN_CORRECTION=True:
      target_lat = expected_lat
      target_lon = expected_lon
      target_alt = expected_alt

  Smooth transition to corrected position:
    - Use GLOBAL setpoint mode for correction
    - Move horizontally at safe speed (e.g., 2 m/s)
    - Maintain altitude during transition

  Wait until position reached (tolerance: 1m)

  ↓

┌──────────────────────────────────────────────────────────────────┐
│ STEP 6: Trajectory Execution (from corrected position)           │
└──────────────────────────────────────────────────────────────────┘
  Now at expected position, execute trajectory:
    - All CSV waypoints are relative to (0,0,0)
    - (0,0,0) now corresponds to expected GPS position
    - Formation executes correctly

  If USE_GLOBAL_SETPOINTS=True:
    Convert each NED waypoint to GPS:
      waypoint_lat, waypoint_lon, waypoint_alt = ned2geodetic(
        csv_north, csv_east, csv_down,
        expected_lat, expected_lon, expected_alt  ← Use expected, not launch
      )

  Execute show...
```

### File Structure

```
mavsdk_drone_show/
├── drone_show.py                 # Main execution script [PHASE 2 CHANGES]
├── config.csv                    # Drone configuration (x=North, y=East)
│
├── gcs-server/                   # Ground Control Server
│   ├── app.py                    # Flask server
│   ├── routes.py                 # API endpoints [PHASE 1 COMPLETE]
│   ├── origin.py                 # Origin management [PHASE 1 COMPLETE]
│   └── origin.json               # Formation origin storage
│
├── app/dashboard/drone-dashboard/  # React UI
│   ├── src/
│   │   ├── components/
│   │   │   ├── OriginModal.js       # Set origin [PHASE 1 COMPLETE]
│   │   │   ├── PositionTabs.js      # Tab interface [PHASE 1 COMPLETE]
│   │   │   ├── DeviationView.js     # Position monitoring [PHASE 1 COMPLETE]
│   │   │   └── InitialLaunchPlot.js # Formation plot
│   │   ├── pages/
│   │   │   └── MissionConfig.js     # Main config page [PHASE 1 COMPLETE]
│   │   └── styles/
│   │       ├── PositionTabs.css     # [PHASE 1 COMPLETE]
│   │       └── DeviationView.css    # [PHASE 1 COMPLETE]
│
├── src/
│   ├── params.py                 # Configuration parameters [PHASE 2 CHANGES]
│   ├── led_controller.py
│   └── ...
│
├── shapes/                       # Trajectory CSV files
│   └── swarm/processed/          # Per-drone trajectories
│       └── Drone 1.csv           # px=North, py=East, pz=Down (NED)
│
└── docs/
    └── ORIGIN_SYSTEM_IMPLEMENTATION_GUIDE.md  # This document
```

---

## API Reference

### Backend Endpoints (Phase 1 Complete)

#### POST /set-origin

Set the formation origin coordinates.

**Request Body:**
```json
{
  "lat": 37.7749,
  "lon": -122.4194,
  "alt": 45.5,
  "alt_source": "drone_telemetry"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Origin saved successfully"
}
```

#### GET /get-origin

Retrieve the current formation origin.

**Response:**
```json
{
  "lat": 37.7749,
  "lon": -122.4194,
  "alt": 45.5,
  "alt_source": "drone_telemetry",
  "timestamp": "2025-11-03T10:30:45.123456",
  "version": 2
}
```

#### GET /get-desired-launch-positions

Calculate GPS coordinates for all drone launch positions.

**Query Parameters:**
- `heading` (optional): Formation rotation in degrees (0-359)

**Response:**
```json
{
  "success": true,
  "origin": {
    "lat": 37.7749,
    "lon": -122.4194,
    "alt": 45.5,
    "source": "drone_telemetry"
  },
  "positions": [
    {
      "hw_id": "1",
      "pos_id": "1",
      "config_north": 10.5,
      "config_east": 5.2,
      "desired_lat": 37.774995,
      "desired_lon": -122.419334,
      "desired_alt": 45.5
    }
  ],
  "formation_stats": {
    "total_drones": 10,
    "extent_north_south": 25.3,
    "extent_east_west": 18.7,
    "max_distance_from_origin": 31.2,
    "formation_diameter": 62.4
  },
  "heading": 0
}
```

#### GET /get-position-deviations

Monitor real-time position deviations.

**Response:** See Phase 1 implementation section for full structure.

---

## Testing Strategy

### Phase 2 Testing Checklist

#### 1. SITL Simulation Testing

**Setup:**
```bash
# Start SITL simulation for 10 drones
./multiple_sitl/multiple_sitl.sh 10

# Start GCS server
cd gcs-server && python app.py

# Start dashboard
cd app/dashboard/drone-dashboard && npm start
```

**Test Cases:**

**TC-1: Origin Not Set (Fallback Mode)**
```
- Condition: origin.json does not exist
- Expected: Drone executes using current behavior
- Verify: Show runs without errors
```

**TC-2: Origin Set, Correction Disabled**
```
- Condition: origin.json exists, USE_ORIGIN_CORRECTION=False
- Expected: Drone ignores origin, uses current behavior
- Verify: Show runs as before
```

**TC-3: Origin Set, Perfect Placement**
```
- Condition: origin.json exists, USE_ORIGIN_CORRECTION=True
- Drones placed exactly at expected positions
- Expected: Correction distance ~0m, no correction applied
- Verify: Show executes normally
```

**TC-4: Origin Set, Small Placement Error**
```
- Condition: origin.json exists, USE_ORIGIN_CORRECTION=True
- Simulate 2m east offset for drone 1
- Expected:
  - Log shows "Position correction required: 2.0m"
  - Drone corrects after initial climb
  - Formation executes correctly
- Verify: Final positions match expected within 1m
```

**TC-5: Origin Set, Large Placement Error**
```
- Condition: origin.json exists, USE_ORIGIN_CORRECTION=True
- Simulate 15m offset (exceeds MAX_CORRECTION_DISTANCE)
- Expected: Script aborts with error message
- Verify: Drone does not take off
```

**TC-6: GPS Quality Check**
```
- Condition: Simulate poor GPS (4 satellites, HDOP=6.0)
- Expected: Script warns and falls back to local NED mode
- Verify: Correction not applied due to poor GPS quality
```

#### 2. Field Testing

**Pre-Flight Checklist:**
- [ ] Formation origin set via UI
- [ ] All drones show in DeviationView
- [ ] GPS quality "excellent" or "good" for all drones
- [ ] Position deviations < 5m for all drones
- [ ] No red status indicators

**During Flight Monitoring:**
- [ ] Watch DeviationView in real-time
- [ ] Confirm drones correct to expected positions after climb
- [ ] Monitor GPS quality throughout flight
- [ ] Check for any position drift warnings

**Post-Flight Validation:**
- [ ] Review drone logs for correction distances
- [ ] Verify final formation matched expected layout
- [ ] Check for any GPS quality degradation
- [ ] Analyze max deviation during flight

#### 3. Edge Case Testing

**EC-1: One Drone GPS Lost**
```
- Scenario: Drone 3 loses GPS mid-flight
- Expected:
  - Drone 3 status → "error"
  - Other drones continue normally
  - Drone 3 enters failsafe (hold position or RTL)
```

**EC-2: Origin Updated Mid-Mission**
```
- Scenario: Operator updates origin while show running
- Expected:
  - Running drones ignore update
  - New origin applies to next show only
```

**EC-3: Network Loss**
```
- Scenario: WiFi connection lost during flight
- Expected:
  - Drones continue executing trajectory
  - UI shows last known positions
  - Telemetry resumes when connection restored
```

**EC-4: Config.csv Mismatch**
```
- Scenario: Drone has different HW_ID than expected
- Expected:
  - Pre-flight check fails
  - Error logged clearly
  - Drone does not arm
```

#### 4. Performance Testing

**P-1: Coordinate Conversion Performance**
```python
import time
import pymap3d as pm

# Benchmark ned2geodetic calls
start = time.time()
for i in range(10000):
    lat, lon, alt = pm.ned2geodetic(
        10.5, 5.2, 0,
        37.7749, -122.4194, 45.5
    )
end = time.time()

print(f"10000 conversions: {(end-start)*1000:.2f}ms")
# Expected: < 100ms total (< 0.01ms per conversion)
```

**P-2: API Response Time**
```bash
# Measure /get-position-deviations latency
time curl http://localhost:5000/get-position-deviations

# Expected: < 500ms for 10 drones
```

**P-3: UI Refresh Rate**
```
- DeviationView auto-refresh: 5 seconds
- Expected: No UI lag or freezing
- CPU usage: < 10% during refresh
```

---

## Glossary of Terms

### Coordinate Systems

| Term | Definition | Example |
|------|------------|---------|
| **NED** | North-East-Down coordinate system. Right-handed. X=North (forward), Y=East (right), Z=Down. | (10.5, 5.2, -3.0) = 10.5m north, 5.2m east, 3m up |
| **LLA** | Latitude-Longitude-Altitude (GPS coordinates). WGS84 geodetic. | (37.7749°, -122.4194°, 45.5m MSL) |
| **AMSL** | Above Mean Sea Level. Altitude reference. | 45.5m AMSL = 45.5 meters above sea level |
| **WGS84** | World Geodetic System 1984. Global coordinate reference system. | Standard GPS coordinate system |

### Origins and References

| Term | Definition | Notes |
|------|------------|-------|
| **Formation Origin** | GPS coordinates defining (0,0,0) for the drone formation. Set by operator. | Our new system from Phase 1 |
| **PX4 GPS Origin** | GPS coordinates where PX4 thinks (0,0,0) is. Auto-set at arming/first GPS lock. | **NOT the same as formation origin!** |
| **Launch Position** | Actual GPS coordinates where a drone is physically located at startup. | Captured from telemetry |
| **Expected Position** | GPS coordinates where a drone **should be** based on config.csv offsets. | Calculated from formation origin + offsets |

### Modes and Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `USE_ORIGIN_CORRECTION` | bool | False | [NEW] Enable origin-based position correction |
| `AUTO_LAUNCH_POSITION` | bool | False | Extract launch position from first trajectory waypoint |
| `USE_GLOBAL_SETPOINTS` | bool | False | Send global GPS setpoints vs local NED setpoints |
| `ENABLE_INITIAL_POSITION_CORRECTION` | bool | True | Apply PX4 origin drift correction |
| `REQUIRE_GLOBAL_POSITION` | bool | True | Require GPS lock for pre-flight checks |

### Deviations and Errors

| Term | Definition | Formula |
|------|------------|---------|
| **Horizontal Deviation** | 2D distance between expected and actual position | `sqrt(north_error² + east_error²)` |
| **Vertical Deviation** | Altitude difference | `abs(expected_alt - actual_alt)` |
| **3D Deviation** | Total 3D distance | `sqrt(north_error² + east_error² + down_error²)` |
| **Position Error** | NED vector from expected to actual position | `(error_north, error_east, error_down)` |

### GPS Quality

| Term | Definition | Good Value |
|------|------------|------------|
| **HDOP** | Horizontal Dilution of Precision. Lower is better. | < 2.0 |
| **Satellite Count** | Number of GPS satellites tracked. | ≥ 8 |
| **GPS Quality** | Classification: excellent/good/fair/poor/no_fix | excellent |
| **GPS Lock** | GPS has valid 3D position fix | Required for flight |

### Status Classifications

| Status | Color | Horizontal Deviation | Action |
|--------|-------|---------------------|--------|
| **ok** | Green | < 2.0m | Normal operation |
| **warning** | Orange | 2.0m - 5.0m | Monitor closely |
| **error** | Red | > 5.0m | Investigate/abort |
| **no_telemetry** | Gray | N/A | No data received |

---

## Next Steps for Phase 2 Implementation

### 1. Planning Phase (Think Deep!)

Before writing any code, the next AI should:

1. **Read this entire document thoroughly**
2. **Study drone_show.py execution flow** (lines 542-801)
3. **Understand current coordinate handling** (lines 184-537)
4. **Map out integration points** (where to add new logic)
5. **Identify potential conflicts** (with existing parameters/modes)
6. **Design safety mechanisms** (thresholds, fallbacks, aborts)
7. **Plan testing strategy** (SITL first, then field)

### 2. Design Decisions Needed

**Decision 1: When to Apply Corrections?**
- Option A: During initial climb (gradual correction)
- Option B: After initial climb (separate correction phase) ← RECOMMENDED
- Option C: Continuously during trajectory (real-time correction)

**Decision 2: How to Handle Correction Failures?**
- Option A: Abort mission (safest)
- Option B: Continue without correction (show offset but runs)
- Option C: Operator decision via parameter ← RECOMMENDED

**Decision 3: Parameter Consolidation**
- Which existing parameters can be deprecated?
- How to avoid mode conflicts?
- Clear naming for new parameters?

### 3. Implementation Order

**Phase 2.1: Foundation**
- [ ] Add `USE_ORIGIN_CORRECTION` parameter to `params.py`
- [ ] Create `load_formation_origin()` function
- [ ] Create `calculate_expected_position()` function
- [ ] Create `calculate_position_error()` function
- [ ] Add safety threshold checks

**Phase 2.2: Position Correction Logic**
- [ ] Modify `arming_and_starting_offboard_mode()` to calculate corrections
- [ ] Add correction phase after initial climb in `perform_trajectory()`
- [ ] Implement smooth transition to expected position
- [ ] Add logging for correction distances

**Phase 2.3: Global Setpoint Integration**
- [ ] Update coordinate conversions to use expected position as reference
- [ ] Ensure `USE_GLOBAL_SETPOINTS` works with origin correction
- [ ] Test both modes (local NED + global GPS)

**Phase 2.4: Safety and Fallbacks**
- [ ] Add GPS quality checks before corrections
- [ ] Implement maximum correction distance abort
- [ ] Add origin availability fallback
- [ ] Enhance error messages

**Phase 2.5: Testing and Validation**
- [ ] SITL testing (all test cases)
- [ ] Field testing (small formation first)
- [ ] Performance validation
- [ ] Documentation updates

### 4. Critical Reminders

⚠️ **DO NOT:**
- Change core offboard mode logic unless absolutely necessary
- Break existing shows (default behavior must be unchanged)
- Confuse PX4 GPS origin with formation origin
- Skip safety threshold checks
- Assume GPS is always accurate

✅ **DO:**
- Add extensive logging for debugging
- Document every coordinate transformation
- Test in SITL before field deployment
- Validate against existing shows first
- Get operator feedback on thresholds

### 5. Questions to Answer

Before starting implementation:

1. **Should correction be mandatory or optional when origin is set?**
2. **What's the acceptable correction distance threshold? (5m? 10m?)**
3. **How long should the correction transition take? (5s? 10s?)**
4. **Should we support partial corrections? (e.g., horizontal only)**
5. **How to handle multi-altitude formations? (stairs, slopes)**
6. **Should we log corrections to a separate file for analysis?**
7. **What telemetry should be sent to GCS during corrections?**

### 6. Success Metrics

Phase 2 will be considered successful when:

- [ ] Existing shows run unchanged with origin correction disabled
- [ ] New mode corrects 5m placement errors successfully in SITL
- [ ] Field test shows formation accuracy within 1m with origin correction
- [ ] GPS quality indicators prevent corrections when GPS is poor
- [ ] Safety thresholds abort mission when corrections are too large
- [ ] Documentation is complete and clear
- [ ] Code is clean, well-commented, and follows existing patterns
- [ ] All test cases pass
- [ ] Operator feedback is positive

---

## Appendix: Code Snippets for Phase 2

### A. Load Formation Origin

```python
def load_formation_origin() -> dict:
    """
    Load formation origin from origin.json file.

    Returns:
        dict: Formation origin with keys 'lat', 'lon', 'alt', or None if not available

    Example:
        origin = load_formation_origin()
        if origin:
            print(f"Origin: {origin['lat']}, {origin['lon']}, {origin['alt']}m")
        else:
            print("No origin set - using fallback mode")
    """
    logger = logging.getLogger(__name__)
    origin_file = os.path.join('gcs-server', 'origin.json')

    try:
        if not os.path.exists(origin_file):
            logger.warning(f"Origin file not found: {origin_file}")
            return None

        with open(origin_file, 'r') as f:
            data = json.load(f)

        # Validate required fields
        if 'lat' not in data or 'lon' not in data:
            logger.error("Origin file missing required fields (lat, lon)")
            return None

        origin = {
            'lat': float(data['lat']),
            'lon': float(data['lon']),
            'alt': float(data.get('alt', 0.0)),  # Default to 0 if not present
            'source': data.get('alt_source', 'unknown'),
            'version': data.get('version', 1)
        }

        logger.info(f"Formation origin loaded: lat={origin['lat']:.6f}, "
                   f"lon={origin['lon']:.6f}, alt={origin['alt']:.2f}m "
                   f"(source: {origin['source']})")
        return origin

    except Exception as e:
        logger.exception(f"Error loading formation origin: {e}")
        return None
```

### B. Calculate Expected Position

```python
def calculate_expected_position(config_north: float, config_east: float,
                                formation_origin: dict) -> dict:
    """
    Calculate expected GPS position from formation-relative coordinates.

    Coordinate System: Uses formation origin as (0,0,0) reference.

    Args:
        config_north (float): North offset in meters from formation origin
        config_east (float): East offset in meters from formation origin
        formation_origin (dict): Formation origin with 'lat', 'lon', 'alt' keys

    Returns:
        dict: Expected GPS position with keys 'lat', 'lon', 'alt'

    Example:
        config_north = 10.5  # From config.csv x column
        config_east = 5.2    # From config.csv y column
        origin = {'lat': 37.7749, 'lon': -122.4194, 'alt': 45.5}

        expected = calculate_expected_position(config_north, config_east, origin)
        # Returns: {'lat': 37.774995, 'lon': -122.419334, 'alt': 45.5}
    """
    import pymap3d as pm

    # Convert NED offset to GPS coordinates
    expected_lat, expected_lon, expected_alt = pm.ned2geodetic(
        config_north,              # meters north of origin
        config_east,               # meters east of origin
        0.0,                       # altitude offset (0 = same altitude as origin)
        formation_origin['lat'],   # origin latitude
        formation_origin['lon'],   # origin longitude
        formation_origin['alt']    # origin altitude MSL
    )

    return {
        'lat': expected_lat,
        'lon': expected_lon,
        'alt': expected_alt
    }
```

### C. Calculate Position Error

```python
def calculate_position_error(expected: dict, actual: dict) -> dict:
    """
    Calculate position error in NED coordinates.

    Args:
        expected (dict): Expected GPS position {'lat', 'lon', 'alt'}
        actual (dict): Actual GPS position {'lat', 'lon', 'alt'}

    Returns:
        dict: Position error with keys:
            - 'north': Error in meters (positive = actual is north of expected)
            - 'east': Error in meters (positive = actual is east of expected)
            - 'down': Error in meters (positive = actual is below expected)
            - 'horizontal': 2D distance in meters
            - 'vertical': Altitude difference in meters
            - 'total_3d': 3D distance in meters

    Example:
        expected = {'lat': 37.774995, 'lon': -122.419334, 'alt': 45.5}
        actual = {'lat': 37.774990, 'lon': -122.419330, 'alt': 46.2}

        error = calculate_position_error(expected, actual)
        # Returns: {'north': -5.0, 'east': -0.4, 'down': 0.7,
        #           'horizontal': 5.02, 'vertical': 0.7, 'total_3d': 5.07}
    """
    import pymap3d as pm
    import math

    # Convert from expected to actual in NED coordinates
    error_north, error_east, error_down = pm.geodetic2ned(
        actual['lat'], actual['lon'], actual['alt'],
        expected['lat'], expected['lon'], expected['alt']
    )

    # Calculate derived metrics
    horizontal = math.sqrt(error_north**2 + error_east**2)
    vertical = abs(error_down)
    total_3d = math.sqrt(error_north**2 + error_east**2 + error_down**2)

    return {
        'north': error_north,
        'east': error_east,
        'down': error_down,
        'horizontal': horizontal,
        'vertical': vertical,
        'total_3d': total_3d
    }
```

### D. Safety Check

```python
async def validate_correction_safety(position_error: dict,
                                     gps_quality: dict,
                                     params) -> tuple:
    """
    Validate that position correction is safe to apply.

    Args:
        position_error (dict): Position error from calculate_position_error()
        gps_quality (dict): GPS quality metrics {'satellites', 'hdop'}
        params: Parameters object with safety thresholds

    Returns:
        tuple: (is_safe: bool, message: str)

    Safety Checks:
        1. GPS quality sufficient (satellites >= 8, HDOP <= 2.0)
        2. Correction distance within limits (< MAX_CORRECTION_DISTANCE)
        3. Vertical correction reasonable (< MAX_VERTICAL_CORRECTION)

    Example:
        is_safe, msg = await validate_correction_safety(error, gps, Params)
        if not is_safe:
            logger.error(f"Correction unsafe: {msg}")
            sys.exit(1)
    """
    logger = logging.getLogger(__name__)

    # Check 1: GPS Quality
    min_satellites = params.MIN_GPS_SATELLITES  # e.g., 8
    max_hdop = params.MAX_GPS_HDOP              # e.g., 2.0

    satellites = gps_quality.get('satellites', 0)
    hdop = gps_quality.get('hdop', 99.9)

    if satellites < min_satellites:
        return False, f"Insufficient GPS satellites: {satellites} < {min_satellites}"

    if hdop > max_hdop:
        return False, f"GPS HDOP too high: {hdop} > {max_hdop}"

    # Check 2: Horizontal Correction Distance
    max_horizontal = params.MAX_CORRECTION_DISTANCE  # e.g., 10.0 meters
    horizontal = position_error['horizontal']

    if horizontal > max_horizontal:
        return False, (f"Correction distance too large: {horizontal:.2f}m > "
                      f"{max_horizontal}m (likely config error)")

    # Check 3: Vertical Correction
    max_vertical = params.MAX_VERTICAL_CORRECTION  # e.g., 5.0 meters
    vertical = position_error['vertical']

    if vertical > max_vertical:
        return False, (f"Altitude correction too large: {vertical:.2f}m > "
                      f"{max_vertical}m (check origin altitude)")

    # All checks passed
    logger.info(f"Position correction validated: {horizontal:.2f}m horizontal, "
               f"{vertical:.2f}m vertical, GPS quality OK "
               f"({satellites} sats, HDOP {hdop:.1f})")
    return True, "Correction within safe parameters"
```

---

## See Also

For comprehensive information about the completed Phase 2 implementation and control modes:

- **[Control Modes and Coordinates](../control-modes-and-coordinates.md)** - Complete reference for control modes, coordinate systems, Phase 2 auto-correction implementation, initial climb behavior, time synchronization, and troubleshooting

---

## Final Notes

This guide represents the complete knowledge transfer from Phase 1 (origin system implementation) to Phase 2 (drone_show.py integration). The next AI working on this project should:

1. **Read this entire document before writing any code**
2. **Understand the "why" behind each decision**
3. **Respect the constraints and safety requirements**
4. **Test thoroughly in SITL before field deployment**
5. **Ask questions if anything is unclear** (better to clarify than break things)

The goal is a **robust, safe, well-documented drone show execution system** that works perfectly in both modes:
- **Mode A (Current):** Operator-placed, zero corrections (default, safe)
- **Mode B (New):** Origin-based, automatic corrections (opt-in, powerful)

Good luck with Phase 2! 🚁

---

**Document End**

*Last Updated: November 3, 2025*
*Next Review: Before Phase 2 Implementation*
