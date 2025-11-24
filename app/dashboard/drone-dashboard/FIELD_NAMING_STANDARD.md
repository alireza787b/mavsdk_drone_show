# Field Naming Standard - Flask to FastAPI Migration

**Last Updated:** 2025-11-24
**Migration Status:** ✅ Complete
**Backend Standard:** snake_case (FastAPI Pydantic)

---

## Overview

This document defines the official field naming convention for all drone telemetry data after the GCS server migration from Flask to FastAPI. **All React components must use snake_case field names** to match the FastAPI backend response format.

---

## Official Field Names (28 total)

### Identity
- `hw_id` - Hardware ID (string)
- `pos_id` - Position ID (integer, 0-based)
- `detected_pos_id` - Auto-detected position ID
- `ip` - Drone IP address

### Position & Navigation
- `position_lat` - Latitude (degrees)
- `position_long` - Longitude (degrees)
- `position_alt` - Altitude MSL (meters)
- `velocity_north` - Velocity north component (m/s)
- `velocity_east` - Velocity east component (m/s)
- `velocity_down` - Velocity down component (m/s)
- `yaw` - Heading (degrees, 0-360)

### Flight Status
- `flight_mode` - MAVLink flight mode code
- `base_mode` - MAVLink base mode code
- `system_status` - MAVLink system status code
- `is_armed` - Armed status (boolean)
- `is_ready_to_arm` - Pre-arm check status (boolean)

### Mission State
- `state` - Drone show state code
- `mission` - Current mission type
- `last_mission` - Last executed mission
- `trigger_time` - Mission trigger timestamp
- `follow_mode` - Follow mode enabled (boolean)

### Battery & Power
- `battery_voltage` - Battery voltage (volts)

### GPS & Positioning Accuracy
- `gps_fix_type` - GPS fix type (0-6)
- `satellites_visible` - Number of satellites
- `hdop` - Horizontal dilution of precision
- `vdop` - Vertical dilution of precision

### Timestamps
- `timestamp` - Telemetry timestamp (Unix ms)
- `update_time` - Last update time (Unix seconds)
- `heartbeat_last_seen` - Last heartbeat (Unix ms)

---

## Legacy Field Names (DEPRECATED ❌)

These PascalCase names were used in the Flask version and are **no longer supported** in FastAPI:

```javascript
// ❌ DEPRECATED - DO NOT USE
Position_Lat, Position_Long, Position_Alt
Battery_Voltage, Flight_Mode, Base_Mode
System_Status, Is_Armed, Is_Ready_To_Arm
State, Mission, Gps_Fix_Type, Satellites_Visible
Hdop, Vdop, Timestamp, hw_ID, Pos_ID
```

---

## How to Use Field Names in React Components

### Method 1: FIELD_NAMES Constants (Recommended ⭐)

```javascript
import { FIELD_NAMES } from '../constants/fieldMappings';

const DroneComponent = ({ drone }) => {
  const voltage = drone[FIELD_NAMES.BATTERY_VOLTAGE];
  const lat = drone[FIELD_NAMES.POSITION_LAT];
  const isArmed = drone[FIELD_NAMES.IS_ARMED];

  return <div>{voltage}V at {lat}</div>;
};
```

**Benefits:**
- Type-safe with autocomplete
- Easy to refactor
- Self-documenting code
- Single source of truth

### Method 2: Direct snake_case Access

```javascript
const DroneComponent = ({ drone }) => {
  const voltage = drone.battery_voltage;
  const lat = drone.position_lat;
  const isArmed = drone.is_armed;

  return <div>{voltage}V at {lat}</div>;
};
```

**Benefits:**
- Simpler syntax
- Matches backend exactly

### Method 3: useNormalizedTelemetry Hook (Advanced)

```javascript
import useNormalizedTelemetry from '../hooks/useNormalizedTelemetry';

const DroneList = () => {
  const { data, error, loading } = useNormalizedTelemetry('/telemetry', 1000);

  if (loading) return <div>Loading...</div>;

  return Object.values(data).map(drone => (
    <div key={drone.hw_id}>
      Drone {drone.hw_id}: {drone.battery_voltage}V
    </div>
  ));
};
```

**Benefits:**
- Automatic normalization
- Handles legacy data
- Polling built-in

---

## Migration Checklist for New Components

When creating or updating a React component that accesses telemetry:

- [ ] Import `FIELD_NAMES` from `../constants/fieldMappings`
- [ ] Use `drone[FIELD_NAMES.FIELD_NAME]` syntax
- [ ] Never use PascalCase field names
- [ ] Test with live telemetry data
- [ ] Update propTypes/TypeScript types if applicable

---

## Backend API Endpoints

All endpoints return snake_case field names:

| Endpoint | Returns | Format |
|----------|---------|--------|
| `/telemetry` | All drone telemetry | `{ "1": {...}, "2": {...} }` |
| `/get-heartbeats` | Heartbeat status | `{ heartbeats: [...] }` |
| `/git-status` | Git sync status | `{ git_status: {...} }` |

---

## Troubleshooting

### Problem: Drone cards show "N/A" or "undefined"
**Solution:** Check if you're using PascalCase field names. Convert to snake_case.

### Problem: TypeScript errors on field access
**Solution:** Update interface definitions to use snake_case.

### Problem: Old component still works
**Solution:** `normalizeDroneData()` provides backward compatibility, but update to snake_case for best practices.

---

## Files Modified (Reference)

**Frontend:**
- `src/constants/fieldMappings.js` (NEW) - Field mappings utility
- `src/hooks/useNormalizedTelemetry.js` (NEW) - Normalization hook
- `src/pages/Overview.js` - Filter fix
- `src/components/DroneWidget.js` - 15+ field updates
- `src/components/ExpandedDronePortal.js` - Mirror of DroneWidget
- `src/components/DroneDetail.js` - Auto-fixed via script
- `src/pages/GlobeView.js` - Auto-fixed via script
- `src/components/Globe.js` - Auto-fixed via script
- `src/components/OriginModal.js` - Auto-fixed via script
- `src/components/CommandSender.js` - Auto-fixed via script

**Backend:**
- `gcs-server/app_fastapi.py:414-469` - Heartbeat endpoint fix (IP None validation)

---

## Questions?

Contact: MAVSDK Drone Show Team
Documentation: This file
Examples: See `fieldMappings.js` and `DroneWidget.js`

---

**✅ Migration Complete - All Components Now Use snake_case Standard**
