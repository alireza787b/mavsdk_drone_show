# Control Modes and Coordinate Systems

## Overview

This document provides a comprehensive reference for the MAVSDK Drone Show control modes, coordinate systems, and origin handling strategies. It is intended for AI agents, developers, and operators who need to understand the precise behavior of different control configurations.

## Table of Contents

1. [Coordinate Systems](#coordinate-systems)
2. [Control Modes](#control-modes)
3. [Phase 2 Auto Global Origin Correction](#phase-2-auto-global-origin-correction)
4. [Initial Climb Behavior](#initial-climb-behavior)
5. [Time Synchronization](#time-synchronization)
6. [Launch Position Sources](#launch-position-sources)
7. [Best Practices](#best-practices)

---

## Coordinate Systems

### NED (North-East-Down)

**Standard aerospace coordinate frame used throughout the system:**
- **X-axis**: North (positive = north)
- **Y-axis**: East (positive = east)
- **Z-axis**: Down (positive = down)

All CSV trajectory files use NED coordinates. Altitude is negative (e.g., z=-30.0 means 30 meters above origin).

### Blender NWU (North-West-Up)

**Animation software coordinate frame (converted to NED during processing):**
- **X-axis**: North (positive = north)
- **Y-axis**: West (positive = west)
- **Z-axis**: Up (positive = up)

**Conversion to NED:**
```python
# X (north) => X (north) : unchanged
# Y (west)  => Y (east)  : multiply by -1
# Z (up)    => Z (down)  : multiply by -1
df['y [m]'] = -df['y [m]']
df['z [m]'] = -df['z [m]']
```

### GPS Coordinates (LLA)

**Global positioning using:**
- **Latitude**: Degrees (positive = north of equator)
- **Longitude**: Degrees (positive = east of prime meridian)
- **Altitude**: Meters AMSL (Above Mean Sea Level)

### LOCAL_POSITION_NED

**PX4's local frame relative to arming position:**
- Origin: GPS position where drone was armed
- Frame: NED coordinates
- Used for local position setpoints

### Shared Origin (Phase 2)

**Fixed GPS reference point provided by GCS for swarm coordination:**
- All drones use the same origin for GPS conversion
- Allows drones to be placed with ±5-10m tolerance
- Automatic position correction during mission start

---

## Control Modes

### LOCAL Mode (use_global_setpoints = False)

**Position setpoints in local NED frame:**
- **Origin**: Drone's arming position (LOCAL_POSITION_NED)
- **Setpoints**: NED offsets from arming position
- **Launch Position Source**: CSV first row
- **Waypoint Adjustment**: Auto-extract from CSV (`auto_launch_position=True`)
- **Use Case**: Single drone or manual placement
- **Precision**: Relative to arming position

**Example:**
```python
# Drone armed at GPS (35.123456, -120.654321, 100m)
# CSV first row: (0.0, -5.0, 2.5, -5.0)
# Extracted launch: NED(-5.0, 2.5, -5.0) from arming position
# All waypoints adjusted relative to this launch position
```

### GLOBAL Manual Mode (use_global_setpoints = True, auto_origin_mode = False)

**Position setpoints in GPS LLA:**
- **Origin**: Drone's arming position
- **Setpoints**: Converted from NED to GPS using arming origin
- **Launch Position Source**: CSV first row
- **Waypoint Adjustment**: Auto-extract from CSV (`auto_launch_position=True`)
- **Use Case**: Multi-drone with precise manual placement
- **Precision**: GPS-based, drift-independent

**Example:**
```python
# Drone armed at GPS (35.123456, -120.654321, 100m)
# CSV first row: (0.0, -5.0, 2.5, -5.0)
# Waypoints converted to GPS using arming position as origin
# Each drone uses its own arming position as origin
```

### GLOBAL Phase 2 Auto Mode (use_global_setpoints = True, auto_origin_mode = True)

**Position setpoints in GPS LLA with shared origin:**
- **Origin**: Shared GPS position from GCS (fixed for all drones)
- **Setpoints**: Converted from NED to GPS using shared origin
- **Launch Position Source**: Telemetry (current GPS position)
- **Waypoint Adjustment**: NONE - absolute waypoints (`initial_x=0.0, initial_y=0.0`)
- **Initial Climb**: BODY_VELOCITY mode (forced)
- **Blending**: 3-second LLA interpolation after climb
- **Use Case**: Swarm deployment with placement tolerance (±5-10m)
- **Precision**: GPS-based, drift-independent, swarm-synchronized

**Key Difference:**
In Phase 2, waypoints are **absolute NED offsets from shared origin**, not adjusted per drone. The shared origin is the reference point for the entire swarm formation.

**Example:**
```python
# Shared origin: GPS (35.123456, -120.654321, 100m)
# Drone 1 placed at: GPS (35.123400, -120.654350, 100m) [~5m south, ~2.5m east]
# CSV first row: (0.0, -5.0, 2.5, -5.0)

# Phase 2 behavior:
# 1. Initial climb: BODY_VELOCITY (vx=0, vy=0, vz=-1.0)
# 2. After 5s/5m: Blend from current GPS to target GPS
#    - Current: GPS (35.123400, -120.654350, 105m)
#    - Target: shared_origin + CSV_waypoint[-5.0, 2.5, -5.0]
#    - Target GPS: (35.123411, -120.654296, 95m)
# 3. 3-second interpolation: current_gps -> target_gps
# 4. Continue with GPS setpoints from shared origin
```

---

## Phase 2 Auto Global Origin Correction

### Purpose

Allow operators to place drones with **±5-10 meter tolerance** without compromising formation precision. The system automatically corrects position errors during mission start.

### Requirements for Phase 2

1. **use_global_setpoints = True** (GPS mode)
2. **auto_origin_mode = True** (Phase 2 enabled)
3. **Shared origin configured** (GPS from GCS)
4. **Initial climb enabled** (required for blending)

### Technical Implementation

#### 1. Waypoint Loading Strategy

```python
if effective_auto_origin_mode:
    # Phase 2: NO adjustment (absolute waypoints)
    waypoints = read_trajectory_file(
        filename=trajectory_filename,
        auto_launch_position=False,
        initial_x=0.0,  # Pass zeros to prevent subtraction
        initial_y=0.0
    )
else:
    # Manual modes: Use config offsets or auto_launch
    waypoints = read_trajectory_file(
        filename=trajectory_filename,
        auto_launch_position=effective_auto_launch,
        initial_x=drone_config.initial_x,
        initial_y=drone_config.initial_y
    )
```

**Why zeros in Phase 2?**
Passing `initial_x=0.0, initial_y=0.0` prevents `adjust_waypoints()` from subtracting offsets. This ensures CSV waypoints remain as absolute NED offsets from the shared origin.

#### 2. Initial Climb (BODY_VELOCITY)

**Phase 2 forces BODY_VELOCITY mode:**
```python
# Always use body velocity in Phase 2
if effective_auto_origin_mode:
    logger.info("Phase 2: Forcing BODY_VELOCITY initial climb mode")
    initial_climb_mode = "BODY_VELOCITY"
```

**Body velocity setpoints:**
```python
vx_body = 0.0      # No forward/back movement
vy_body = 0.0      # No left/right movement
vz_climb = -1.0    # Climb at 1 m/s (DOWN=-1 means UP)
yaw_deg = 0.0      # Face north
```

**Why BODY_VELOCITY?**
- Prevents horizontal drift during climb
- Drone climbs vertically from current position
- Ignores CSV horizontal positions during climb
- Ensures clean separation from ground for blending

#### 3. Waypoint Index Advancement During Climb

```python
# Keep waypoint_index advancing for swarm synchronization
# Setpoints overridden with climb commands, but timeline continues
waypoint_index += 1
continue
```

**Critical for synchronization:**
- Timeline continues even during climb override
- All drones stay synchronized at same waypoint index
- After 5s climb at 100Hz, waypoint_index ≈ 500
- Blend target is waypoints[500], not waypoints[0]

#### 4. Blend Target Selection

```python
# PHASE 2 FIX: Use CURRENT waypoint as blend target
# waypoint_index has advanced during climb to maintain timeline sync
current_waypoint = waypoints[waypoint_index]
(t_wp_0, px_0, py_0, pz_0, vx_0, vy_0, vz_0, ...) = current_waypoint
```

**Why current waypoint?**
After 5 seconds of climb, the timeline is at ~5 seconds. The CSV waypoint at t=5s might be 30m altitude (drone climbed from 0→30m in show). Using waypoints[0] (t=0s, z=0m) would pull drone back down.

#### 5. Position Blending (3-Second LLA Interpolation)

```python
# Get current GPS position
current_lla = drone_lla

# Target GPS from shared origin + CSV NED
target_lla = convert_ned_to_lla(
    north=px_0,
    east=py_0,
    down=pz_0,
    origin_lat=origin_lat_deg,
    origin_lon=origin_lon_deg,
    origin_alt=origin_alt_m
)

# Interpolate over 3 seconds
for blend_t in range(0, 3000, 50):  # 50ms steps
    alpha = blend_t / 3000.0  # 0.0 -> 1.0
    blended_lat = current_lla.lat + alpha * (target_lla.lat - current_lla.lat)
    blended_lon = current_lla.lon + alpha * (target_lla.lon - current_lla.lon)
    blended_alt = current_lla.alt + alpha * (target_lla.alt - current_lla.alt)

    await drone.offboard.set_position_global(
        PositionGlobalYaw(blended_lat, blended_lon, blended_alt, yaw_deg)
    )
```

**Why 3 seconds?**
- Smooth transition prevents abrupt jerks
- GPS setpoints have higher latency than local
- Formation geometry preserved during blend
- All drones converge to correct positions simultaneously

### Phase 2 Summary

**Key Principles:**
1. Waypoints are **absolute offsets from shared origin** (no adjustment)
2. Initial climb is **vertical from current position** (BODY_VELOCITY)
3. Timeline **advances during climb** (swarm synchronization)
4. Blend target is **current timeline waypoint** (not first waypoint)
5. Blending is **smooth GPS interpolation** (3-second transition)

---

## Initial Climb Behavior

### Purpose

Provide safe vertical separation from ground before starting horizontal maneuvers. Ensures drones clear obstacles and reach stable altitude.

### Completion Criteria (Dual Check)

```python
actual_alt = -pz  # Current waypoint altitude
under_alt = actual_alt < Params.INITIAL_CLIMB_ALTITUDE_THRESHOLD  # Default: 5.0m
under_time = time_in_climb < Params.INITIAL_CLIMB_TIME_THRESHOLD   # Default: 5.0s
in_initial_climb = under_alt or under_time  # BOTH must be satisfied
```

**Climb continues until:**
- Altitude ≥ 5.0 meters **AND**
- Time ≥ 5.0 seconds

**Why dual check?**
- Altitude-only: Drone might reach 5m in 2s, but swarm needs 5s
- Time-only: Drone might be at 3m after 5s (underpowered/heavy)
- Both: Ensures minimum time AND minimum altitude

### Climb Modes

#### BODY_VELOCITY Mode (Forced in Phase 2)

```python
await drone.offboard.set_velocity_body(
    VelocityBodyYawspeed(
        forward_m_s=0.0,   # vx_body
        right_m_s=0.0,     # vy_body
        down_m_s=-1.0,     # vz_climb (negative = up)
        yawspeed_deg_s=0.0
    )
)
```

**Characteristics:**
- Body-frame velocity commands
- Vertical climb only (no horizontal drift)
- Ignores CSV trajectory during climb
- Most predictable for Phase 2 blending

#### LOCAL_NED Mode (Optional in Manual Modes)

```python
await drone.offboard.set_velocity_ned(
    VelocityNedYaw(
        north_m_s=0.0,     # vx_climb
        east_m_s=0.0,      # vy_climb
        down_m_s=-1.0,     # vz_climb
        yaw_deg=yaw_deg
    )
)
```

**Characteristics:**
- Local-frame velocity commands
- Can include horizontal trajectory during climb
- Uses CSV vx, vy values
- Alternative for manual modes

### Critical Bug Fix: Climb Speed

**Problem (Fixed in commit feaee038):**
```python
# WRONG: CSV vz values contain numerical noise
vz_climb = vz if abs(vz) > 1e-6 else Params.INITIAL_CLIMB_VZ_DEFAULT
# CSV had vz=0.0026 -> treated as valid -> drone didn't climb
```

**Solution:**
```python
# CORRECT: Always use configured climb speed
vz_climb = Params.INITIAL_CLIMB_VZ_DEFAULT  # Unconditional
```

**Why this happened:**
- CSV export from Blender includes floating-point noise
- Threshold 1e-6 (0.000001) was too sensitive
- Value 0.0026 > 1e-6, so system used it
- Result: vz=-0.00 m/s (essentially zero climb)

### Critical Bug Fix: Timeline Synchronization

**Problem (Fixed in commit feaee038):**
```python
# WRONG: Timeline frozen during climb
await asyncio.sleep(0.05)
continue  # Skips waypoint_index increment
```

**Solution:**
```python
# CORRECT: Timeline advances during climb
waypoint_index += 1
continue  # Increments before continuing
```

**Why this matters:**
- Swarm must stay synchronized at same timeline position
- After 5s at 100Hz (csv_step=0.01s), waypoint_index should be ~500
- Frozen index breaks formation timing
- All drones must advance timeline identically

---

## Time Synchronization

### Overview

Precise time synchronization is **critical** for swarm formations. All drones must execute waypoints at exactly the same timeline position, regardless of performance variations.

### Drift Detection

**Drift calculation:**
```python
elapsed = time.time() - mission_start_time  # Actual time elapsed
drift_delta = elapsed - t_wp                 # Drift from timeline
```

**Drift states:**
- `drift_delta > 0`: **Behind schedule** (need to catch up)
- `drift_delta < 0`: **Ahead of schedule** (need to wait)
- `drift_delta = 0`: **On time** (perfect sync)

### Case A: Behind Schedule (Waypoint Skipping)

```python
if drift_delta >= 0:
    # Limit catchup to prevent excessive skipping
    safe_drift = min(drift_delta, Params.DRIFT_CATCHUP_MAX_SEC)  # Default: 0.5s

    # Calculate skip count (limited to prevent formation breaks)
    skip_count = int(safe_drift / csv_step)
    skip_count = min(skip_count, Params.MAX_WAYPOINT_SKIP_PER_ITERATION)  # Max: 5

    if skip_count > 0:
        logger.warning(
            f"⚠️ DRIFT CATCHUP: Skipping {skip_count} waypoints "
            f"(drift={drift_delta:.2f}s, from WP{waypoint_index} "
            f"to WP{waypoint_index+skip_count})"
        )
        waypoint_index = min(waypoint_index + skip_count, total_waypoints - 1)
        drift_stats['skip_events'] += 1
        drift_stats['total_waypoints_skipped'] += skip_count
```

**Key parameters:**
- **DRIFT_CATCHUP_MAX_SEC** (0.5s): Maximum drift to catch up per iteration
- **MAX_WAYPOINT_SKIP_PER_ITERATION** (5): Maximum waypoints to skip at once
- **csv_step** (0.01s): Time between waypoints (100Hz)

**Why limit skipping?**
- Skipping 50 waypoints (0.5s) in one iteration can break formation
- Limit to 5 waypoints provides gradual catchup
- Prevents sudden position jumps
- Maintains smooth trajectory

### Case B: Ahead of Schedule (Sleep)

```python
else:  # drift_delta < 0
    sleep_duration = t_wp - elapsed  # How much ahead
    if sleep_duration > 0:
        await asyncio.sleep(min(sleep_duration, Params.AHEAD_SLEEP_STEP_SEC))
```

**Key parameters:**
- **AHEAD_SLEEP_STEP_SEC** (0.05s): Maximum sleep duration per iteration

**Why limit sleep?**
- Prevents blocking too long
- Allows responsive control loop
- Smooth waiting instead of sudden stops

### Severe Drift Detection

```python
# Detect severe drift (production alert)
if drift_delta > Params.SEVERE_DRIFT_THRESHOLD:
    logger.error(
        f"🚨 SEVERE DRIFT: {drift_delta:.2f}s behind timeline "
        f"(threshold={Params.SEVERE_DRIFT_THRESHOLD}s) - "
        f"Performance insufficient for real-time execution!"
    )
    drift_stats['severe_drift_events'] += 1
```

**Key parameters:**
- **SEVERE_DRIFT_THRESHOLD** (2.0s): Alert threshold for critical drift

**Why alert?**
- Indicates system cannot maintain real-time performance
- Operator needs to know if hardware is insufficient
- May require mission abort or parameter adjustment

### Drift Statistics

```python
drift_stats = {
    'max_drift_behind': 0.0,
    'max_drift_ahead': 0.0,
    'skip_events': 0,
    'total_waypoints_skipped': 0,
    'severe_drift_events': 0,
    'ahead_wait_events': 0
}

# Update during mission
if drift_delta > 0:
    drift_stats['max_drift_behind'] = max(drift_stats['max_drift_behind'], drift_delta)
else:
    drift_stats['max_drift_ahead'] = max(drift_stats['max_drift_ahead'], abs(drift_delta))

# Log at end
logger.info(
    f"📊 DRIFT STATISTICS:\n"
    f"  Max Behind: {drift_stats['max_drift_behind']:.3f}s\n"
    f"  Max Ahead: {drift_stats['max_drift_ahead']:.3f}s\n"
    f"  Skip Events: {drift_stats['skip_events']}\n"
    f"  Waypoints Skipped: {drift_stats['total_waypoints_skipped']}\n"
    f"  Severe Drift Events: {drift_stats['severe_drift_events']}\n"
    f"  Ahead Wait Events: {drift_stats['ahead_wait_events']}"
)
```

**Benefits:**
- Post-mission analysis
- Performance tuning
- Hardware validation
- Production monitoring

### Timeline Sync Verification

```python
# After initial climb, verify timeline synchronization
if just_finished_climb:
    expected_index = int(time_in_climb / csv_step)
    actual_index = waypoint_index
    sync_error = abs(actual_index - expected_index)

    if sync_error > 10:  # More than 0.1s error
        logger.warning(
            f"⚠️ TIMELINE SYNC WARNING: After initial climb, "
            f"waypoint_index={actual_index} but expected ~{expected_index} "
            f"(error={sync_error} waypoints = {sync_error*csv_step:.2f}s)"
        )
    else:
        logger.info(
            f"✅ TIMELINE SYNC VERIFIED: waypoint_index={actual_index}, "
            f"expected={expected_index} (error={sync_error} waypoints)"
        )
```

**Purpose:**
- Verify climb didn't break synchronization
- Catch timeline bugs early
- Ensure Phase 2 blending uses correct target

### Best Practices

1. **Monitor drift statistics** after every mission
2. **Alert on severe drift** (>2.0s) - indicates hardware issues
3. **Limit waypoint skipping** (max 5 per iteration) - prevents formation breaks
4. **Use small sleep steps** (50ms) - maintains responsive control
5. **Verify timeline sync** after initial climb - catches synchronization bugs
6. **Log skip events** - provides visibility for operators
7. **Track skip counts** - identify problematic missions

---

## Launch Position Sources

### Overview

The launch position (where the drone starts in the formation) can be determined from two sources:
1. **CSV first row** (trajectory file)
2. **config.csv values** (drone_config.initial_x, initial_y)

Different control modes use different sources.

### Source Selection Logic

```python
if not effective_use_global_setpoints:
    # LOCAL mode: Extract from CSV first row
    effective_auto_launch = True
    logger.info("LOCAL mode: Extracting launch position from trajectory CSV first row")

elif effective_auto_origin_mode:
    # GLOBAL Phase 2: NO adjustment (absolute waypoints)
    effective_auto_launch = False
    logger.info("GLOBAL Phase 2 mode: Using absolute waypoints, no adjustment")

else:
    # GLOBAL manual: Extract from CSV first row
    effective_auto_launch = True
    logger.info("GLOBAL manual: Extracting launch position from trajectory CSV first row")
```

### Mode-by-Mode Behavior

| Mode | Source | auto_launch_position | initial_x/y |
|------|--------|---------------------|-------------|
| LOCAL | CSV first row | True | Ignored |
| GLOBAL Manual | CSV first row | True | Ignored |
| GLOBAL Phase 2 | Telemetry (current GPS) | False | 0.0, 0.0 |

### Why CSV First Row for Manual Modes?

**Problem with config.csv values:**
- Operators manually place drones at expected positions
- config.csv might have old/incorrect values from previous setup
- CSV first row contains actual formation launch position

**Example scenario:**
```python
# config.csv (old values from previous show)
drone_config.initial_x = 10.0  # Old position
drone_config.initial_y = 5.0

# Current show CSV first row
# t,  px,    py,    pz
# 0.0, -5.0, 2.5, 0.0  # New formation position

# OLD BEHAVIOR (WRONG):
# Used initial_x=10.0, initial_y=5.0 from config.csv
# Subtracted from waypoints: (-5.0-10.0, 2.5-5.0) = (-15.0, -2.5)
# Drone went to wrong position!

# NEW BEHAVIOR (CORRECT):
# Extracted (-5.0, 2.5) from CSV first row
# Subtracted from waypoints: (-5.0-(-5.0), 2.5-2.5) = (0.0, 0.0)
# Drone stays at current position (correct launch)
```

### Critical Bug Fix: Launch Position Source

**Problem (Fixed in commit 84f0ae75):**
```python
# WRONG: Using config.csv values for manual modes
effective_auto_launch = False  # Uses drone_config.initial_x/y
```

**Solution:**
```python
# CORRECT: Extract from CSV first row for manual modes
effective_auto_launch = True  # Extracts from CSV first row
```

**Why this matters:**
- Manual placement relies on CSV formation data
- config.csv values might be outdated
- CSV first row is source of truth for current show
- Prevents position errors from stale configuration

---

## Best Practices

### For Operators

1. **Choose the right mode:**
   - **LOCAL**: Single drone or simple testing
   - **GLOBAL Manual**: Multi-drone with precise manual placement (±0.5m)
   - **GLOBAL Phase 2**: Multi-drone with relaxed placement (±5-10m)

2. **Phase 2 deployment:**
   - Place drones within ±5-10m of expected positions
   - Ensure GPS lock before arming (HDOP < 1.5)
   - Verify shared origin is configured in GCS
   - Allow 3-second blend after initial climb

3. **Monitor drift statistics:**
   - Check logs after mission for severe drift events
   - Max drift behind should be < 0.5s
   - Skip events should be minimal (< 10 per mission)

4. **Time synchronization:**
   - Ensure all drones start within 1 second
   - Use NTP or GPS time sync for multi-swarm
   - Monitor for severe drift warnings (>2.0s)

### For Developers

1. **Coordinate conversions:**
   - Always verify NED orientation (X=North, Y=East, Z=Down)
   - Check sign conventions (negative altitude = up)
   - Test GPS conversion with known coordinates

2. **Timeline synchronization:**
   - Never block the control loop during climb
   - Always advance waypoint_index to maintain sync
   - Use current waypoint for blend targets, not first

3. **Waypoint adjustment:**
   - Phase 2: Pass (0.0, 0.0) to prevent adjustment
   - Manual modes: Use auto_launch_position=True
   - Verify adjustment logic with test trajectories

4. **Initial climb:**
   - Always use configured climb speed (ignore CSV vz)
   - Implement dual check (altitude AND time)
   - Force BODY_VELOCITY in Phase 2

5. **Drift handling:**
   - Limit waypoint skipping (max 5 per iteration)
   - Log all skip events for visibility
   - Alert on severe drift (>2.0s)
   - Track drift statistics for analysis

### For AI Agents

1. **When debugging position errors:**
   - Check coordinate frame (NED vs GPS vs LOCAL)
   - Verify origin source (arming vs shared)
   - Confirm waypoint adjustment logic
   - Review launch position source

2. **When debugging synchronization:**
   - Check waypoint_index advancement during climb
   - Verify blend target uses current waypoint
   - Review drift handling parameters
   - Check timeline sync after climb

3. **When implementing new features:**
   - Preserve timeline advancement (never block control loop)
   - Maintain coordinate frame consistency
   - Add appropriate logging for debugging
   - Update drift statistics tracking

---

## Troubleshooting

### Issue: Drone goes to (0,0) origin instead of launch position

**Likely cause:** Phase 2 waypoint adjustment bug

**Check:**
```python
# In drone_show.py, around line 2022-2037
if effective_auto_origin_mode:
    # Should pass zeros to prevent adjustment
    initial_x=0.0,
    initial_y=0.0
```

**Fix:** Ensure Phase 2 passes (0.0, 0.0) to read_trajectory_file()

### Issue: Drone doesn't climb during initial climb

**Likely cause:** CSV vz value used instead of climb speed

**Check:**
```python
# In drone_show.py, around line 749-751
# Should be unconditional
vz_climb = Params.INITIAL_CLIMB_VZ_DEFAULT
```

**Fix:** Always use configured climb speed, ignore CSV vz during initial climb

### Issue: Swarm desynchronized after initial climb

**Likely cause:** Timeline frozen during climb

**Check:**
```python
# In drone_show.py, around line 763-766
# Should increment before continue
waypoint_index += 1
continue
```

**Fix:** Ensure waypoint_index advances during climb to maintain timeline sync

### Issue: Drone goes to wrong position after manual placement

**Likely cause:** Using config.csv values instead of CSV first row

**Check:**
```python
# In drone_show.py, around line 2015-2027
if not effective_use_global_setpoints:
    effective_auto_launch = True  # Extract from CSV
```

**Fix:** Use auto_launch_position=True for LOCAL and GLOBAL manual modes

### Issue: Severe drift warnings (>2.0s behind)

**Likely cause:** Hardware insufficient for real-time execution

**Check:**
- CPU usage during mission (should be < 80%)
- Loop rate (should be ~100Hz = 0.01s per iteration)
- Network latency to drone (should be < 50ms)

**Fix:**
- Reduce CSV frequency (e.g., 50Hz instead of 100Hz)
- Upgrade flight computer (more CPU/RAM)
- Optimize control loop (remove unnecessary logging)

---

## References

### Related Documentation

- **Origin System**: `docs/features/origin-system.md`
- **SITL Demo**: `docs/sitl_demo_docker.md`
- **Main Guide**: `README.md`

### Key Parameters (src/params.py)

**Initial Climb:**
- `INITIAL_CLIMB_ALTITUDE_THRESHOLD = 5.0` (meters)
- `INITIAL_CLIMB_TIME_THRESHOLD = 5.0` (seconds)
- `INITIAL_CLIMB_VZ_DEFAULT = -1.0` (m/s, negative = up)

**Time Synchronization:**
- `DRIFT_CATCHUP_MAX_SEC = 0.5` (maximum drift to catch up)
- `MAX_WAYPOINT_SKIP_PER_ITERATION = 5` (maximum waypoints to skip)
- `SEVERE_DRIFT_THRESHOLD = 2.0` (alert threshold)
- `AHEAD_SLEEP_STEP_SEC = 0.05` (maximum sleep duration)

**Coordinate Conversion:**
- `EARTH_RADIUS = 6371000.0` (meters)

### Key Code Locations (drone_show.py)

- **Mode selection**: Lines 1990-2010
- **Launch position source**: Lines 2015-2027
- **Waypoint loading**: Lines 2022-2037
- **Initial climb**: Lines 671-766
- **Time drift handling**: Lines 640-920
- **Phase 2 blending**: Lines 690-705

---

## Version History

- **v1.0** (2025-01-08): Initial documentation
  - Comprehensive control modes guide
  - Coordinate systems reference
  - Phase 2 implementation details
  - Time synchronization best practices
  - Launch position source clarification
  - Troubleshooting guide

---

*This document is maintained as part of the MAVSDK Drone Show project.*
*For questions or updates, refer to the project repository.*
