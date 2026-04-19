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
      "marker_color": "#00d4ff",
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
| `marker_color` | string | `null` | Optional `#RGB` or `#RRGGBB` map/globe marker color override |
| `notes` | string | `null` | Operator notes |

### Custom Fields

Any additional fields are preserved. Recommended pattern:
- keep core mission identity in `hw_id` and `pos_id`
- use custom fields only for secondary metadata such as `callsign`, `marker_color`, `notes`, `role_hint`, `maintenance_tag`, or `payload_type`
- prefer lowercase `snake_case` keys for long-term compatibility

Examples: `"maintenance_tag": "A2"`, `"payload_type": "smoke"`, `"marker_color": "#ff9800"`, `"ready_for_show": true`.

Mission Config includes predefined optional-field templates for common fields:

| Template | Saved key | Type | Purpose |
|----------|-----------|------|---------|
| Callsign | `callsign` | text | Operator alias shown in dense cards, maps, and reports |
| Marker Color | `marker_color` | color | `#RGB` or `#RRGGBB` map/globe marker color override |
| Notes | `notes` | text | Short operator maintenance or test note |
| Role Hint | `role_hint` | text | Human planning hint only; does not override mission/swarm logic |

Use **Custom field** only when the predefined templates do not cover the metadata you need.

Marker asset note:

- `marker_color` is the supported lightweight visual override today
- uploaded custom 2D/3D marker assets should use a managed asset library rather
  than arbitrary paths in `config.json`, so operators can validate, reuse, and
  delete assets safely

## Identity And Targeting Doctrine

MDS intentionally keeps three different identity concepts separate:

- `hw_id`: persistent physical/node identity
- `pos_id`: assigned mission/show slot identity
- `mav_sys_id`: MAVLink transport identity

Current production doctrine:

- maintenance, enrollment, PX4 parameter management, telemetry ownership, git
  sync, and low-level command dispatch are `hw_id`-anchored
- mission/show authoring and role/slot displays are `pos_id`-anchored
- high-level mission planners may accept `pos_id` selection in the UI, then
  resolve that to the currently assigned `hw_id` set before launch

Practical examples:

- Drone Show trajectories are resolved by `pos_id`
- QuickScout planning may select assigned slots, then resolve to current
  hardware at launch
- Smart Swarm follow chains remain `hw_id`-based today

Operational scenario rule:

- swapping two already-enrolled drones between slots is a Mission Config role
  change (`pos_id` update)
- replacing a failed airframe with a different spare is a Fleet Enrollment
  replacement workflow, not a manual slot edit
- Smart Swarm follow chains are rewritten by the dedicated replacement flow,
  not by ordinary slot reassignments

Dense operator surfaces use the compact shorthand `Pn|Hm` to show both without
losing context.

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
- Deliberate slot reassignments belong in Mission Config: changing `pos_id` changes which
  show / trajectory slot a physical drone flies
- Spare replacement belongs in Fleet Enrollment: the replacement workflow keeps
  the target `pos_id` and moves that slot onto new hardware while preserving the
  physical maintenance identity model

## Validation

Configuration is validated with Pydantic schemas (`gcs-server/schemas.py`):
- `hw_id` and `pos_id` must be >= 1 (1-based)
- `ip` must be valid IPv4
- Duplicate `hw_id` values are rejected
- Duplicate `pos_id` values trigger a collision warning
- Missing trajectory files for a `pos_id` trigger a warning

---

**Last Updated:** 2026-03-16
