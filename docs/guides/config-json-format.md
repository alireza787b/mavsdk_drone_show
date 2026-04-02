# Config JSON Format Reference

## Overview

MDS uses JSON files for fleet and swarm configuration. The format supports optional and custom fields via Pydantic `extra='allow'`.

## config.json / config_sitl.json

```json
{
  "version": 1,
  "drones": [
    {
      "hw_id": 1,
      "pos_id": 1,
      "ip": "192.168.1.10",
      "mavlink_port": 14551,
      "serial_port": "/dev/ttyS0",
      "baudrate": 57600,
      "callsign": "VIPER-01",
      "notes": "Replaced motor 2 on 2026-02-15"
    }
  ]
}
```

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `hw_id` | int (>=1) | Hardware ID -- unique physical drone identifier |
| `pos_id` | int (>=1) | Position ID -- maps to trajectory `Drone {pos_id}.csv` |
| `ip` | string | IP address (IPv4) |
| `mavlink_port` | int (>=1) | MAVLink UDP port |

### Optional Core Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `serial_port` | string | `""` | Serial port device (empty for SITL) |
| `baudrate` | int | `0` | Serial baudrate (0 for SITL) |
| `callsign` | string | `null` | Optional operator alias shown as secondary metadata in Mission Config |
| `notes` | string | `null` | Operator notes |

### Custom Fields

Any additional fields are preserved. Recommended pattern:
- keep core mission identity in `hw_id` and `pos_id`
- use custom fields only for secondary metadata such as `callsign`, `notes`, `maintenance_tag`, or `payload_type`
- prefer lowercase `snake_case` keys for long-term compatibility

Examples: `"maintenance_tag": "A2"`, `"payload_type": "smoke"`, `"ready_for_show": true`.

## swarm.json / swarm_sitl.json

```json
{
  "version": 1,
  "assignments": [
    {
      "hw_id": 1,
      "follow": 0,
      "offset_x": 0.0,
      "offset_y": 0.0,
      "offset_z": 0.0,
      "frame": "ned"
    }
  ]
}
```

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `hw_id` | int (>=1) | required | Hardware ID |
| `follow` | int (>=0) | `0` | Leader hw_id (0 = independent) |
| `offset_x` | float | `0.0` | X offset in meters (North in NED, Forward in body) |
| `offset_y` | float | `0.0` | Y offset in meters (East in NED, Right in body) |
| `offset_z` | float | `0.0` | Z offset in meters (Up, always positive-up regardless of frame) |
| `frame` | string | `"ned"` | Reference frame: `"ned"` (geographic) or `"body"` (relative to leader heading) |

### Frame Interpretation

| Frame | `offset_x` | `offset_y` | `offset_z` |
|-------|-----------|-----------|-----------|
| `"ned"` | North | East | Up |
| `"body"` | Forward | Right | Up |

## Mode Selection

| Mode | Config File | Swarm File |
|------|-------------|------------|
| Real | `config.json` | `swarm.json` |
| SITL | `config_sitl.json` | `swarm_sitl.json` |

Selected automatically by `src/params.py` based on the presence of `real.mode` file.

## Import/Export

The dashboard supports both JSON (primary) and CSV (legacy) import/export:
- **Export JSON**: Downloads `config.json` with version wrapper
- **Export CSV**: Downloads `config_export.csv` (core 6 fields only; custom fields remain JSON-only)
- **Import**: Accepts `.json` or `.csv`, auto-detects format

### Mission Config UI Behavior

- Mission Config treats `hw_id` and `pos_id` as the only primary identity fields
- Additional JSON fields appear under **Additional Fields**
- `callsign` is promoted as a secondary alias when present
- Editing a drone preserves unknown JSON fields; they are not dropped when saving
- Dense operator surfaces use the compact shorthand `Pn|Hm`
- Example: `P1|H7` means `Position ID 1 | Hardware ID 7`
- Compact shorthand is for dashboards, scopes, clusters, and plots only; edit forms keep the explicit labels `Position ID` and `Hardware ID`

## Validation

Configuration is validated with Pydantic schemas (`gcs-server/schemas.py`):
- `hw_id` and `pos_id` must be >= 1 (1-based)
- `ip` must be valid IPv4
- Duplicate `hw_id` values are rejected
- Duplicate `pos_id` values trigger a collision warning
- Missing trajectory files for a `pos_id` trigger a warning

---

**Last Updated:** 2026-03-16
