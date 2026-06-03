# GCS API Server Documentation

**Version:** 5.0 (FastAPI)
**Port:** 5030 (default, configurable with `MDS_GCS_API_PORT`)
**Base URL:** `http://localhost:5030`
**Documentation:** `/docs` (Swagger UI) | `/redoc` (ReDoc)

---

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [API Endpoints](#api-endpoints)
4. [WebSocket Endpoints](#websocket-endpoints)
5. [Authentication](#authentication)
6. [Error Handling](#error-handling)
7. [Migration from Flask](#migration-from-flask)

---

## Overview

The GCS (Ground Control Station) API Server provides comprehensive control and monitoring for drone swarms. Built with FastAPI, it offers:

- **71+ HTTP REST endpoints** for drone configuration, telemetry, and show management
- **3 WebSocket endpoints** for real-time telemetry, git status, and heartbeat streaming
- **Automatic OpenAPI documentation** at `/docs` and `/redoc`
- **Type-safe request/response** validation with Pydantic
- **Background services** for telemetry and git status polling
- **File upload/download** support for show management
- **Canonical `/api/v1/...` business routes** plus a small set of intentionally stable operational roots

## API Evolution Note

As of the 2026-04-03 API modernization checkpoints, the GCS business API source of truth is the canonical `/api/v1/...` surface.

The remaining versionless roots are intentional:
- `/health` and `/ping` remain stable operational health probes
- `/ws/*` remains the stable real-time transport surface
- `/api/logs/*` and `/api/sar/*` remain stable subsystem roots

Use [api-modernization-blueprint.md](./api-modernization-blueprint.md) as the planning and migration source of truth.

---

## Quick Start

### Starting the Server

```bash
# Recommended full launcher for GCS + dashboard in SITL
bash app/linux_dashboard_start.sh --sitl

# Production-style launcher
bash app/linux_dashboard_start.sh --prod --sitl
```

If you only want the backend service without the React dashboard:

```bash
cd gcs-server

# Development backend only
./start_gcs_server.sh development 5030

# Production backend only
./start_gcs_server.sh production 5030
```

Notes:
- `--sitl` starts FastAPI plus the dashboard in development mode.
- `--prod --sitl` builds/serves the React dashboard and runs FastAPI in production mode.
- Production currently stays single-worker on purpose because command tracking, heartbeat state, and background services still rely on in-process memory.

### Interactive API Documentation

Visit `/docs` for Swagger UI or `/redoc` for ReDoc documentation:
- **Swagger UI:** http://localhost:5030/docs
- **ReDoc:** http://localhost:5030/redoc

---

## API Endpoints

### Health & System

#### `GET /api/v1/system/health`
Canonical system health endpoint.

**Response:**
```json
{
  "status": "ok",
  "timestamp": 1700000000000,
  "version": "5.0"
}
```

#### `GET /health`
Stable operational alias for quick liveness probes.

#### `GET /ping`
Stable operational alias for quick liveness probes.

#### SITL Control

The SITL Control subsystem exposes typed routes for local Docker-backed SITL
management.

- In `SITL` mode it allows the full local lifecycle surface.
- In `REAL` mode it drops to cleanup-only: inventory, logs, operations, and
  remove remain available so leftover local SITL containers can be cleaned up
  without switching the GCS back to simulation.

Current routes:

- `GET /api/v1/system/sitl/policy`
- `GET /api/v1/system/sitl/host`
- `GET /api/v1/system/sitl/images`
- `GET /api/v1/system/sitl/instances`
- `GET /api/v1/system/sitl/instances/{instance_name}/logs`
- `POST /api/v1/system/sitl/reconcile`
- `POST /api/v1/system/sitl/instances/{instance_name}/restart`
- `DELETE /api/v1/system/sitl/instances/{instance_name}`
- `GET /api/v1/system/sitl/operations`
- `GET /api/v1/system/sitl/operations/{operation_id}`

Design notes:

- dashboard, validators, and headless automation can all use the same API
- GCS still reuses the canonical `multiple_sitl/create_dockers.sh` launcher
  under the hood rather than introducing a parallel Docker workflow
- operation polling is the intended way to track reconcile/restart/remove
  completion without scraping shell output

Example reconcile request:

```json
{
  "target_count": 3,
  "start_id": 1,
  "start_ip": 2,
  "git_sync_enabled": true,
  "requirements_sync_enabled": true
}
```

---

### PX4 Parameters

The PX4 parameter subsystem is a dedicated GCS-orchestrated workflow. The dashboard should talk only to GCS, and GCS fans out to drone-local MAVSDK param access when a fresh snapshot is needed.

Current routes:

#### `GET /api/v1/px4-params/policy`
Return the live policy envelope for the subsystem, including:
- documentation base/version configuration
- mutation safety policy
- metadata-source expectations

**Response:**
```json
{
  "subsystem": "px4_params",
  "docs": {
    "provider": "px4_parameter_reference",
    "version": "main",
    "base_url": "https://docs.px4.io/main/en/advanced_config/parameter_reference.html",
    "param_anchor_supported": true
  },
  "metadata": {
    "runtime_values": "mavsdk_param",
    "float_metadata": "component_information",
    "docs_links": "px4_parameter_reference",
    "reboot_required": "component_information"
  },
  "mutations": {
    "require_disarmed": true,
    "supports_batch_apply": true,
    "supports_qgc_import": true,
    "supports_mds_profiles": true,
    "supported_component_ids": [1]
  }
}
```

#### `POST /api/v1/px4-params/snapshots`
Request fresh parameter snapshots from one or more configured drones.

**Request:**
```json
{
  "hw_ids": ["1", "2"],
  "component_id": 1
}
```

**Response:**
```json
{
  "snapshots": [
    {
      "snapshot": {
        "snapshot_id": "px4-params-1-1712659200000",
        "hw_id": "1",
        "component_id": 1,
        "px4_docs_version": "main",
        "total_params": 2,
        "created_at": 1712659200000,
        "stale_after_ms": 60000
      },
      "rows": [
        {
          "component_id": 1,
          "name": "MAV_SYS_ID",
          "value_type": "int",
          "value": 1,
          "writable": true,
          "docs_url": "https://docs.px4.io/main/en/advanced_config/parameter_reference.html#MAV_SYS_ID",
          "short_description": null,
          "long_description": null,
          "unit": null,
          "decimal_places": null,
          "default_value": null,
          "min_value": null,
          "max_value": null,
          "reboot_required": null,
          "metadata_sources": ["vehicle", "px4_docs"]
        }
      ]
    }
  ],
  "errors": [],
  "total_targets": 2,
  "timestamp": 1712659200000
}
```

#### `GET /api/v1/px4-params/snapshots/{snapshot_id}`
Return one stored GCS-managed snapshot envelope.

#### `GET /api/v1/px4-params/snapshots/{snapshot_id}/rows`
Return the row collection for a stored snapshot.

#### `POST /api/v1/px4-params/diff`
Compare a desired parameter set against one stored snapshot and return only the rows that would change by default.

**Request:**
```json
{
  "snapshot_id": "px4-params-1-1712659200000",
  "desired_entries": [
    {
      "component_id": 1,
      "name": "GF_MAX_HOR_DIST",
      "value_type": "float",
      "value": 120.0
    }
  ],
  "include_unchanged": false
}
```

#### `POST /api/v1/px4-params/imports/qgc`
Parse a QGroundControl `.params` file into typed patch entries without writing them.

#### `POST /api/v1/px4-params/imports/mds`
Parse a typed MDS JSON patch payload into patch entries without writing them.

#### `POST /api/v1/px4-params/patch-jobs`
Apply one patch set to one or more drones through the GCS.

**Request:**
```json
{
  "hw_ids": ["1", "2"],
  "source": "manual",
  "verify_readback": true,
  "entries": [
    {
      "component_id": 1,
      "name": "GF_MAX_HOR_DIST",
      "value_type": "float",
      "value": 120.0
    }
  ]
}
```

#### `GET /api/v1/px4-params/patch-jobs/{job_id}`
Return the tracked result envelope for one GCS patch job.

Notes:
- full parameter retrieval happens between GCS and drones, not between dashboard and drones
- docs links are generated from the configured PX4 docs version and parameter anchor
- QGC interoperability is supported through import/export helpers, but MDS keeps its own typed patch format for automation and future MCP use
- metadata such as defaults, min/max limits, decimal hints, and reboot-required flags are best-effort and may be null when PX4 does not expose them through the live vehicle/component-information path
- the current dashboard workspace supports single-drone snapshot inspection/editing plus batch patch dispatch; dashboard clients still do not talk directly to drone APIs

---

### Configuration Management

The older verb-style GCS configuration aliases were retired on 2026-04-03. Use the canonical `/api/v1/config/fleet*` routes below.

#### `GET /api/v1/config/fleet`
Get current drone configuration from config.json.

**Response:**
```json
[
  {
    "hw_id": 1,
    "pos_id": 1,
    "ip": "192.168.1.101",
    "mavlink_port": 14551,
    "serial_port": "/dev/ttyS0",
    "baudrate": 57600
  }
]
```

#### `PUT /api/v1/config/fleet`
Save drone configuration to config.json.

**Request:**
```json
[
  {
    "hw_id": 1,
    "pos_id": 1,
    "ip": "192.168.1.101",
    "mavlink_port": 14551,
    "serial_port": "/dev/ttyS0",
    "baudrate": 57600
  }
]
```

**Response:**
```json
{
  "success": true,
  "message": "Configuration saved successfully",
  "updated_count": 1
}
```

Invalid or non-list JSON payloads now return the shared `422 Validation error`
envelope instead of route-local string errors.

#### `POST /api/v1/config/fleet/validation`
Validate configuration without saving.

**Request:** Same as `PUT /api/v1/config/fleet`

**Response:**
```json
{
  "updated_config": [...],
  "summary": {
    "duplicates_count": 0,
    "missing_trajectories_count": 0,
    "role_swaps_count": 0
  }
}
```

Invalid or non-list JSON payloads now return the shared `422 Validation error`
envelope.

#### `GET /api/v1/config/fleet/trajectory-start-positions`
Get initial positions for all drones from trajectory CSV files.

**Response:**
```json
[
  {
    "hw_id": 1,
    "pos_id": 0,
    "x": 0.0,
    "y": 0.0
  }
]
```

#### `GET /api/v1/config/fleet/trajectory-start-positions/{pos_id}`
Get expected position from a single trajectory CSV file using canonical `x` / `y` naming.

**Response:**
```json
{
  "pos_id": 0,
  "x": 0.0,
  "y": 0.0,
  "source": "Drone 0.csv (first waypoint)"
}
```

The older query-string compatibility route was retired. Use the path-parameter form above.

---

### Telemetry

#### `GET /api/v1/fleet/telemetry`
Canonical fleet telemetry snapshot used by the dashboard and validation tooling.

**Response:**
```json
{
  "telemetry": {
    "1": {
      "pos_id": 1,
      "hw_id": "1",
      "state": 0,
      "mission": 0,
      "last_mission": 0,
      "trigger_time": 0,
      "flight_mode": 65536,
      "base_mode": 81,
      "system_status": 4,
      "is_armed": false,
      "is_ready_to_arm": true,
      "readiness_status": "ready",
      "readiness_summary": "Ready to fly",
      "readiness_checks": [],
      "preflight_blockers": [],
      "preflight_warnings": [],
      "status_messages": [],
      "position_lat": 35.123456,
      "position_long": -120.654321,
      "position_alt": 488.5,
      "altitude_display_m": 18.4,
      "altitude_source": "relative_home",
      "relative_altitude_m": 18.4,
      "baro_altitude_m": 17.9,
      "altitude_report": {
        "display_m": 18.4,
        "source": "relative_home",
        "label": "REL",
        "stale": false,
        "sources": {
          "relative_home": {"valid": true, "value_m": 18.4, "fresh": true, "label": "REL"},
          "absolute_msl": {"valid": true, "value_m": 488.5, "fresh": true, "label": "MSL"},
          "local_ned": {"valid": true, "value_m": 18.2, "fresh": true, "label": "LCL"},
          "baro": {"valid": true, "value_m": 17.9, "fresh": true, "label": "BARO"}
        }
      },
      "global_position_valid": true,
      "global_position_timestamp_ms": 1700000000000,
      "global_position_age_ms": 120,
      "position_source": "global_position_int",
      "position_unavailable_reason": null,
      "distance_to_home_m": 18.4,
      "velocity_north": 0.0,
      "velocity_east": 0.0,
      "velocity_down": 0.0,
      "battery_voltage": 12.6,
      "hdop": 0.8,
      "vdop": 1.1,
      "gps_fix_type": 3,
      "gps_raw_valid": true,
      "gps_raw_timestamp_ms": 1700000000000,
      "gps_raw_age_ms": 120,
      "gps_raw_altitude_m": 488.5,
      "satellites_visible": 12,
      "ip": "192.168.1.101",
      "heartbeat_last_seen": 1700000000000,
      "heartbeat_network_info": {},
      "heartbeat_first_seen": 1699999999000,
      "timestamp": 1700000000000
    }
  },
  "total_drones": 10,
  "online_drones": 8,
  "timestamp": 1700000000000
}
```

The older GCS HTTP telemetry aliases were retired on 2026-04-03. Use the canonical route above.

`readiness_status`, `readiness_summary`, `preflight_blockers`, and `status_messages` are the operator-facing fields the dashboard now uses for "Ready to Fly" and live PX4 preflight feedback.

`gps_raw_valid` describes raw GPS fix evidence. `gps_raw_altitude_m` is raw GPS altitude above MSL from `GPS_RAW_INT`; dashboards may show it as an altitude fallback, but must not use it for map placement. `global_position_valid` describes whether PX4 has published a usable mappable global coordinate. These are intentionally separate: a board can have a 3D GPS fix while `position_lat=0` and `position_long=0` because the estimator has not emitted a valid `GLOBAL_POSITION_INT` yet. Dashboards must not map `0,0,0` as a real aircraft position.

`distance_to_home_m` is a nullable horizontal distance from the drone's current valid global position to cached home position; dashboards should show `n/a` until both endpoints are known.

---

### Heartbeat

#### `POST /api/v1/fleet/heartbeats`
Receive heartbeat from drone (fire-and-forget).

**Request:**
```json
{
  "pos_id": 0,
  "hw_id": "1",
  "timestamp": 1700000000000,
  "runtime_mode": "real"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Heartbeat received",
  "server_time": 1700000000000
}
```

Mode-fencing notes:

- Nodes should declare `runtime_mode` as `real` or `sitl`.
- GCS rejects missing, invalid, or mode-mismatched heartbeats at
  intake so SITL and real nodes do not contaminate each other's live state.
- A rejected heartbeat still returns `success: true` because the transport
  request itself succeeded; the operator-facing `message` explains that the
  heartbeat was ignored due to runtime-mode mismatch.

#### `GET /api/v1/fleet/heartbeats`
Get heartbeat status for all drones.

**Response:**
```json
{
  "heartbeats": [
    {
      "pos_id": 0,
      "hw_id": "1",
      "runtime_mode": "real",
      "online": true,
      "last_heartbeat": 1700000000000
    }
  ],
  "total_drones": 10,
  "online_count": 8,
  "timestamp": 1700000000000
}
```

#### `POST /api/v1/fleet/node-boot-status`
Receive a best-effort boot/init status report from a drone node before the
normal coordinator heartbeat is available.

This route is intended for field observability only. It lets Fleet Ops show
states such as git sync, runtime reconcile, restart pending, success, or error
while a board is visible on the network but not yet ready in MDS. A boot-status
report never marks a drone online, commandable, or flight-ready; only accepted
mode-matched heartbeats do that.

**Request:**
```json
{
  "hw_id": "2",
  "pos_id": 2,
  "runtime_mode": "real",
  "status": "running",
  "phase": "fetch",
  "message": "Fetching latest repo state",
  "ip": "198.51.100.12"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Node boot status received",
  "node": {
    "hw_id": "2",
    "phase": "fetch",
    "status": "running",
    "timestamp": 1700000000000,
    "first_seen": 1700000000000
  },
  "server_time": 1700000000000
}
```

#### `GET /api/v1/fleet/node-boot-status`
Get the latest boot/init status reports keyed by hardware ID.

Fleet Ops merges this payload with git status and heartbeat state. If a node has
recent boot status but no accepted heartbeat, the UI may show it as
`Initializing`, but it remains offline for command/readiness decisions.

**Response:**
```json
{
  "nodes": {
    "2": {
      "hw_id": "2",
      "runtime_mode": "real",
      "status": "running",
      "phase": "restart",
      "message": "Restarting coordinator after runtime sync",
      "timestamp": 1700000000000,
      "first_seen": 1700000000000
    }
  },
  "timestamp": 1700000000000
}
```

#### `GET /api/v1/fleet/network-status`
Get network connectivity status for all drones.

**Response:**
```json
{
  "network_status": {
    "1": {
      "pos_id": 0,
      "ip": "192.168.1.101",
      "reachable": true,
      "last_check": 1700000000000
    }
  },
  "total_drones": 10,
  "reachable_count": 8,
  "timestamp": 1700000000000
}
```

#### `GET /api/v1/fleet/network-details`
Get detailed heartbeat-derived per-drone network metadata.

This route is distinct from `GET /api/v1/fleet/network-status`: it exposes detailed interface metadata gathered from live heartbeats instead of only the higher-level reachability summary.

---

### Origin Management

Canonical origin routes are exposed under `/api/v1/...`.

#### `GET /api/v1/origin`
Get current origin coordinates.

**Response:**
```json
{
  "lat": 35.123456,
  "lon": -120.654321,
  "alt": 488.0,
  "timestamp": 1700000000000,
  "source": "manual"
}
```

#### `PUT /api/v1/origin`
Set origin coordinates manually.

**Request:**
```json
{
  "lat": 35.123456,
  "lon": -120.654321,
  "alt": 488.0,
  "alt_source": "manual"
}
```

`alt` is optional on the canonical write path and defaults to `0.0` meters MSL when omitted.

#### `GET /api/v1/origin/bootstrap`
Canonical origin bootstrap payload for runtime consumers that need origin before flight.

**Response:**
```json
{
  "lat": 35.123456,
  "lon": -120.654321,
  "alt": 488.0,
  "timestamp": 1700000000000,
  "source": "manual"
}
```

#### `GET /api/v1/navigation/global-origin`
Get GPS global origin.

**Response:**
```json
{
  "latitude": 35.123456,
  "longitude": -120.654321,
  "altitude": 488.0,
  "has_origin": true
}
```

#### `GET /api/v1/origin/elevation?lat={lat}&lon={lon}`
Get elevation data for coordinates.

**Parameters:**
- `lat` (required): Latitude
- `lon` (required): Longitude

**Response:**
```json
{
  "elevation": 488.0,
  "resolution": "30m"
}
```

#### `POST /api/v1/origin/compute`
Compute origin from drone's current position.

This endpoint is compute-only. It returns the candidate origin and does not persist it. Use `PUT /api/v1/origin` to save the result explicitly.

**Request:**
```json
{
  "current_lat": 35.123456,
  "current_lon": -120.654321,
  "pos_id": 1
}
```

**Response:**
```json
{
  "status": "success",
  "lat": 35.123456,
  "lon": -120.654321
}
```

Malformed JSON or missing/invalid required fields now return the shared
validation envelope instead of route-local `400` parsing errors.

#### `GET /api/v1/origin/deviations`
Calculate position deviations for all drones.

**Response:**
```json
{
  "status": "success",
  "origin": {...},
  "deviations": {
    "1": {
      "hw_id": "1",
      "pos_id": 0,
      "expected": {...},
      "current": {...},
      "deviation": {
        "horizontal": 1.23,
        "within_threshold": true
      },
      "status": "ok"
    }
  },
  "summary": {
    "total_drones": 10,
    "online": 8,
    "within_threshold": 7,
    "average_deviation": 1.45
  }
}
```

#### `GET /api/v1/origin/launch-positions?heading={degrees}&format={json|csv|kml}`
Calculate GPS coordinates for each drone's desired launch position.

**Parameters:**
- `heading` (optional): Formation heading (0-359 degrees, default: 0)
- `format` (optional): Output format (json, csv, kml, default: json)

`heading` is applied before GPS projection. JSON returns the rotated `north` / `east` offsets plus the original trajectory offsets for auditability. `format=csv` and `format=kml` return downloadable attachments.

**Response:**
```json
{
  "origin": {...},
  "positions": [
    {
      "pos_id": 0,
      "hw_id": "1",
      "latitude": 35.123456,
      "longitude": -120.654321,
      "north": 0.0,
      "east": 0.0,
      "trajectory_north": 0.0,
      "trajectory_east": 0.0
    }
  ],
  "total_drones": 10,
  "heading": 0.0
}
```

---

### Show Management

The show domain now exposes canonical v1 routes grouped by workflow:

- standard SkyBrush ZIP import / processing under `/api/v1/shows/skybrush/*`
- custom per-drone local replay CSV import under `/api/v1/shows/custom/*`

The older verb-style show-management aliases were retired on 2026-04-03. Use the canonical routes below.

#### `POST /api/v1/shows/skybrush/import`
Import and process drone show files (multipart file upload).

**Request:**
- Content-Type: `multipart/form-data`
- Field: `file` (ZIP file containing show CSVs)

**Response:**
```json
{
  "success": true,
  "message": "Show imported and processed successfully",
  "show_name": "show.zip",
  "files_processed": 10,
  "drones_configured": 10,
  "raw_files_found": 10,
  "plots_generated": 11,
  "warnings": [],
  "next_steps": [
    "Review launch positions and origin in Mission Config.",
    "Confirm telemetry and readiness in Overview before launch."
  ],
  "git_info": null
}
```

#### `GET /api/v1/shows/skybrush`
Get show metadata (drone count, duration, altitude).

**Response:**
```json
{
  "drone_count": 10,
  "duration_ms": 120000,
  "duration_minutes": 2,
  "duration_seconds": 0,
  "max_altitude": 50.0
}
```

#### `GET /api/v1/shows/skybrush/archives/raw`
Download raw show files as ZIP.

**Response:** ZIP file download

#### `GET /api/v1/shows/skybrush/archives/processed`
Download processed show files as ZIP.

**Response:** ZIP file download

#### `GET /api/v1/shows/custom`
Get metadata for the active custom replay CSV.

**Response:**
```json
{
  "exists": true,
  "filename": "active.csv",
  "row_count": 240,
  "duration_sec": 120.0,
  "max_altitude": 35.0,
  "preview_exists": true,
  "execution_mode": "local per-drone replay",
  "required_columns": ["t", "px", "py", "pz", "vx", "vy", "vz", "ax", "ay", "az", "yaw", "mode"]
}
```

#### `POST /api/v1/shows/custom/import`
Upload, validate, and activate a custom replay CSV.

**Request:**
- Content-Type: `multipart/form-data`
- Field: `file` (CSV file using the custom-show protocol columns)

**Response:**
```json
{
  "success": true,
  "message": "Custom CSV validated and activated successfully",
  "filename": "custom_show.csv",
  "stored_as": "active.csv",
  "row_count": 240,
  "duration_sec": 120.0,
  "max_altitude": 35.0,
  "preview_generated": true,
  "warnings": [],
  "next_steps": [
    "Review the generated preview and confirm the path is correct.",
    "Remember: every drone will execute the same CSV in its own local launch frame.",
    "Use Mission Config and Overview to confirm spacing and readiness before launch."
  ],
  "git_info": null
}
```

#### `GET /api/v1/shows/skybrush/plots`
Get list of all show plot images.

**Response:**
```json
{
  "filenames": ["drone_1_plot.jpg", "drone_2_plot.jpg"],
  "uploadTime": "Fri Nov 22 12:00:00 2025"
}
```

If the plots directory does not exist yet, the response is an empty list with `"uploadTime": "unknown"` instead of creating the directory as a side effect.

#### `GET /api/v1/shows/skybrush/plots/{filename}`
Get specific show plot image.

**Response:** JPG image file

The server now rejects path traversal attempts and only serves files inside the configured show-plots directory.

#### `GET /api/v1/shows/custom/preview`
Get custom drone show trajectory plot image.

**Response:** PNG image file

#### `GET /api/v1/shows/skybrush/metrics`
Retrieve comprehensive trajectory analysis metrics.

**Response:**
```json
{
  "safety_metrics": {...},
  "performance_metrics": {...},
  "formation_metrics": {...}
}
```

#### `GET /api/v1/shows/skybrush/metrics/snapshot`
Read the current cached comprehensive trajectory metrics snapshot without recalculating or writing metrics files. Use this route for MCP/read-only inspections.

**Response with current cache:**
```json
{
  "available": true,
  "snapshot_only": true,
  "cache_current": true,
  "metrics": {
    "safety_metrics": {...},
    "performance_metrics": {...},
    "formation_metrics": {...}
  }
}
```

**Response when no current cache exists:**
```json
{
  "available": false,
  "snapshot_only": true,
  "cache_current": false,
  "detail": "No current cached SkyBrush metrics snapshot is available..."
}
```

The legacy `GET /api/v1/shows/skybrush/metrics` route may refresh cached metrics and is therefore not exposed as a read-only MCP tool.

#### `GET /api/v1/shows/skybrush/safety-report`
Get detailed safety analysis report.

**Response:**
```json
{
  "safety_analysis": {...},
  "recommendations": [
    "Maintain minimum 2m separation between drones"
  ]
}
```

#### `GET /api/v1/shows/skybrush/validation`
Get the current validation snapshot for the processed show package.

**Response:**
```json
{
  "validation_status": "PASS",
  "issues": [],
  "metrics_summary": {...}
}
```

#### `POST /api/v1/shows/skybrush/deployments`
Deploy show changes to git repository for drone fleet.

**Request:**
```json
{
  "message": "Deploy drone show update"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Show deployed successfully to drone fleet",
  "git_info": {...}
}
```

The request body is optional. When provided, it must be a JSON object with an
optional `message` field.

---

### Swarm Management

The older verb-style GCS swarm configuration aliases were retired on 2026-04-03. Use the canonical `/api/v1/config/swarm*` routes below.

#### `GET /api/v1/config/swarm`
Get the canonical swarm configuration resource.

**Response:**
```json
{
  "version": 1,
  "assignments": [
    {
      "hw_id": 1,
      "follow": 0,
      "offset_x": 0,
      "offset_y": 0,
      "offset_z": 0,
      "frame": "ned"
    }
  ]
}
```

#### `PUT /api/v1/config/swarm?commit={true|false}`
Save the canonical swarm configuration resource.

**Parameters:**
- `commit` (optional): Whether to commit to git

**Request:**
```json
{
  "version": 1,
  "assignments": [
    {
      "hw_id": 1,
      "follow": 0,
      "offset_x": 0,
      "offset_y": 0,
      "offset_z": 0,
      "frame": "ned"
    }
  ]
}
```

**Response:**
```json
{
  "status": "success",
  "message": "Swarm configuration saved successfully",
  "config": {
    "version": 1,
    "assignments": [
      {
        "hw_id": 1,
        "follow": 0,
        "offset_x": 0,
        "offset_y": 0,
        "offset_z": 0,
        "frame": "ned"
      }
    ]
  }
}
```

The canonical response returns the normalized assignment resource, including the
defaulted offset fields and frame for each assignment.

#### `PATCH /api/v1/config/swarm/assignments/{hw_id}`
Patch a saved swarm assignment for one hardware drone.

This is the canonical replacement for the older leader-only naming. The live
contract can update `follow`, `offset_x`, `offset_y`, `offset_z`, and `frame`
together for a single saved assignment.

**Request:**
```json
{
  "follow": 1,
  "offset_x": 2.5,
  "offset_y": 0.0,
  "offset_z": 0.0,
  "frame": "body"
}
```

The `hw_id` path parameter owns the target resource. The request body no longer
accepts a second `hw_id` field.

**Response:**
```json
{
  "status": "success",
  "message": "Swarm assignment updated",
  "assignment": {
    "hw_id": 2,
    "follow": 1,
    "offset_x": 2.5,
    "offset_y": 0.0,
    "offset_z": 0.0,
    "frame": "body"
  }
}
```

#### `GET /api/v1/swarm-trajectories/leaders`
Get list of top leaders from swarm configuration.

**Response:**
```json
{
  "success": true,
  "leaders": [1, 5],
  "hierarchies": {"1": 2, "5": 1},
  "follower_details": {"1": [2, 3], "5": [6]},
  "uploaded_leaders": [1],
  "simulation_mode": true
}
```

#### `POST /api/v1/swarm-trajectories/upload/{leader_id}`
Upload CSV trajectory for specific leader.

**Parameters:**
- `leader_id`: Leader drone ID

**Request:**
- Content-Type: `multipart/form-data`
- Field: `file` (CSV trajectory file)

**Response:**
```json
{
  "success": true,
  "message": "Drone 1 trajectory uploaded successfully",
  "filepath": "/path/to/Drone 1.csv"
}
```

#### `POST /api/v1/swarm-trajectories/process`
Smart processing with automatic change detection.

**Request:**
```json
{
  "force_clear": false,
  "auto_reload": true
}
```

**Response:**
```json
{
  "success": true,
  "outcome": "partial",
  "message": "Processed 2/4 drones (1 leaders, 1 followers). Some clusters still need attention before launch.",
  "processed_drones": 2,
  "processed_drone_list": [1, 2],
  "expected_drone_list": [1, 2, 5, 6],
  "skipped_drone_ids": [5, 6],
  "missing_leaders": [5],
  "auto_reloaded": [1],
  "statistics": {
    "leaders": 1,
    "followers": 1,
    "errors": 0
  }
}
```

The dashboard now prefers the asynchronous job API for operator-facing
processing so the UI can show phase/progress/cancel state instead of waiting on
one long request. Keep this synchronous endpoint for compatibility and simple
automation, but do not build new UI flows that can spin indefinitely on it.

#### `POST /api/v1/swarm-trajectories/process/jobs`
Create an asynchronous processing job.

**Request:**
```json
{
  "force_clear": false,
  "auto_reload": true
}
```

**Response:**
```json
{
  "success": true,
  "job_id": "swarm-process-abc123",
  "status": "queued",
  "phase": "queued",
  "progress": 0,
  "message": "Processing job queued",
  "result": null,
  "error": null
}
```

#### `GET /api/v1/swarm-trajectories/process/jobs/{job_id}`
Read processing job state. Terminal states are `succeeded`, `failed`,
`canceled`, and `expired`.

#### `POST /api/v1/swarm-trajectories/process/jobs/{job_id}/cancel`
Request cancellation. If the underlying processor is already in a non-
interruptible operation, the job response reports the safe terminal state and
message instead of pretending cancellation stopped work immediately.

#### `GET /api/v1/swarm-trajectories/status`
Get current processing status and file counts.

**Response:**
```json
{
  "success": true,
  "status": {
    "raw_trajectories": 1,
    "processed_trajectories": 2,
    "generated_plots": 0,
    "has_results": true,
    "expected_top_leaders": [1, 5],
    "uploaded_leaders": [1],
    "missing_uploaded_leaders": [5],
    "orphan_uploaded_leaders": [],
    "cluster_summary": {
      "cluster_count": 2,
      "ready_cluster_count": 0,
      "needs_processing_cluster_count": 0,
      "missing_upload_cluster_count": 1,
      "partial_output_cluster_count": 1,
      "processed_cluster_count": 1,
      "all_clusters_ready": false,
      "overall_state": "partial"
    },
    "clusters": [
      {
        "leader_id": 1,
        "state": "partial_outputs",
        "leader_uploaded": true,
        "leader_processed": true,
        "expected_drone_count": 3,
        "processed_drone_count": 2,
        "missing_follower_ids": [3]
      }
    ]
  }
}
```

#### `GET /api/v1/swarm-trajectories/validate`
Validate the active processed package for commit/transfer/launch review.

**Response:**
```json
{
  "success": true,
  "ready": false,
  "state": "blocked",
  "blockers": [
    {
      "code": "missing_leader_upload",
      "severity": "blocked",
      "message": "Leader 5 has no uploaded route."
    }
  ],
  "warnings": [],
  "advisories": [],
  "processed_drone_ids": [1, 2],
  "expected_drone_ids": [1, 2, 5, 6],
  "missing_drone_ids": [5, 6]
}
```

#### `GET /api/v1/swarm-trajectories/preview`
Return downsampled processed paths and cluster relationships for map preview.
Optional query: `max_points_per_drone` between `10` and `2000`.

#### `POST /api/v1/swarm-trajectories/elevation/batch`
Resolve terrain/elevation for waypoint authoring. Each result reports whether
terrain was available; clients must not silently use a guessed elevation for
AGL waypoint storage.

**Request:**
```json
{
  "points": [
    {"lat": 35.0, "lng": 51.0}
  ]
}
```

#### `GET /api/v1/swarm-trajectories/policy`
Get the operator-facing trajectory planner envelope sourced from backend `Params`.

**Response:**
```json
{
  "success": true,
  "policy": {
    "altitude": {
      "default_msl": 100.0,
      "default_target_agl": 100.0,
      "min_msl": 1.0,
      "max_msl": 10000.0
    },
    "speed": {
      "default_preferred": 8.0,
      "min_preferred": 0.5,
      "optimal_max": 12.0,
      "absolute_max": 20.0
    },
    "timing": {
      "default_route_entry_delay_s": 10.0,
      "default_fallback_leg_duration_s": 10.0,
      "derived_time_step_s": 0.1
    },
    "terrain": {
      "min_safe_clearance_m": 50.0,
      "default_safe_clearance_m": 100.0
    }
  }
}
```

Use this endpoint as the frontend source of truth for Swarm Trajectory planner defaults and operator envelopes instead of maintaining a separate hardcoded policy table.

Additional active Swarm Trajectory endpoints:

- `GET /api/v1/swarm-trajectories/recommendation`
- `POST /api/v1/swarm-trajectories/process/jobs`
- `GET /api/v1/swarm-trajectories/process/jobs/{job_id}`
- `POST /api/v1/swarm-trajectories/process/jobs/{job_id}/cancel`
- `GET /api/v1/swarm-trajectories/validate`
- `GET /api/v1/swarm-trajectories/preview`
- `POST /api/v1/swarm-trajectories/elevation/batch`
- `POST /api/v1/swarm-trajectories/clear`
- `POST /api/v1/swarm-trajectories/clear-leader/{leader_id}`
- `DELETE /api/v1/swarm-trajectories/remove/{leader_id}`
- `POST /api/v1/swarm-trajectories/clear-drone/{drone_id}`
- `GET /api/v1/swarm-trajectories/download-cluster-kml/{leader_id}`
- `POST /api/v1/swarm-trajectories/commit`

The older versionless `/api/swarm/...` compatibility routes for this domain are retired.

Swarm Trajectory failures now use the same shared error envelope as the rest of
the cleaned GCS HTTP surface. Git sync failures on `commit` are surfaced as
operation errors with an explicit HTTP status (`409` or `502`) and a readable
`detail` field instead of route-local `success=false` payloads.

The active Swarm Trajectory success surfaces are now typed in the GCS schema
layer as well, so `/docs` and `/openapi.json` expose the current contract for:

- `GET /api/v1/swarm-trajectories/leaders`
- `GET /api/v1/swarm-trajectories/recommendation`
- `GET /api/v1/swarm-trajectories/status`
- `GET /api/v1/swarm-trajectories/validate`
- `GET /api/v1/swarm-trajectories/preview`
- `POST /api/v1/swarm-trajectories/elevation/batch`
- `GET /api/v1/swarm-trajectories/policy`
- `POST /api/v1/swarm-trajectories/process`
- `POST /api/v1/swarm-trajectories/process/jobs`
- `GET /api/v1/swarm-trajectories/process/jobs/{job_id}`
- `POST /api/v1/swarm-trajectories/process/jobs/{job_id}/cancel`
- `POST /api/v1/swarm-trajectories/clear-processed`
- `POST /api/v1/swarm-trajectories/clear`
- `POST /api/v1/swarm-trajectories/clear-leader/{leader_id}`
- `DELETE /api/v1/swarm-trajectories/remove/{leader_id}`
- `POST /api/v1/swarm-trajectories/clear-drone/{drone_id}`
- `POST /api/v1/swarm-trajectories/commit`

`process` and `commit` now accept optional typed JSON bodies, so schema/body
violations use the standard shared `422 Validation error` envelope instead of
custom route-local parsing behavior.

#### `POST /api/v1/swarm-trajectories/clear-processed`
Explicitly clear all processed data and plots.

**Response:**
```json
{
  "success": true,
  "message": "Processed data cleared"
}
```

---

### Command Execution

#### `POST /api/v1/commands`
Submit a command to drones and immediately return ACK tracking information.

**Request:**
```json
{
  "mission_type": 10,
  "trigger_time": 0,
  "idempotency_key": "launch-wave-001",
  "target_drone_ids": ["1", "2"],
  "operator_label": "Launch all",
  "takeoff_altitude": 10
}
```

**Response:**
```json
{
  "success": true,
  "command_id": "5c6c136a-0ea2-41ba-a00f-0e632c3c4418",
  "idempotency_key": "launch-wave-001",
  "replayed": false,
  "status": "submitted",
  "mission_type": 10,
  "mission_name": "TAKE_OFF",
  "target_drones": ["1", "2"],
  "submitted_count": 2,
  "results_summary": {
    "accepted": 2,
    "offline": 0,
    "rejected": 0,
    "errors": 0
  },
  "tracking_status": "submitted",
  "tracking_phase": "pending_execution",
  "tracking_outcome": null,
  "tracking_timeout_ms": 420000,
  "message": "2 accepted",
  "timestamp": 1700000000000
}
```

Important semantics:
- `success=true` means at least one drone accepted the command.
- canonical request fields are `mission_type`, `trigger_time`, `idempotency_key`, `target_drone_ids`, and `operator_label`.
- `idempotency_key` is the canonical replay-safe client key. Repeating the same submission with the same `idempotency_key` and the same normalized payload returns the existing `command_id` with `replayed=true` instead of creating or dispatching a second command.
- reusing the same `idempotency_key` with a different normalized payload fails with `409 Conflict`.
- legacy request aliases (`missionType`, `triggerTime`, `target_drones`, `targetDrones`, `operatorLabel`, `idempotencyKey`, `client_command_id`, `clientCommandId`) are still accepted at the HTTP edge, but first-party callers and docs now use the canonical snake_case contract.
- `target_drone_ids` may contain hardware IDs or position IDs. The response still normalizes `target_drones` to hardware IDs after the target set is resolved.
- malformed JSON, non-object JSON bodies, invalid `target_drone_ids` shapes, and explicit target selections that match no configured drones fail fast with `400` instead of creating an ambiguous zero-target command record.
- `tracking_phase=pending_execution` means delivery/ACKs are complete but the drone has not yet reported execution start.
- Long-running actions such as `TAKE_OFF`, `LAND`, `DRONE_SHOW_FROM_CSV`, `SMART_SWARM`, and `QUICKSCOUT` should be tracked via `GET /api/v1/commands/{command_id}` rather than treated as finished at submission time.
- `tracking_timeout_ms` is the mission-aware lifecycle timeout selected by the backend for this command. It already includes any future trigger delay plus the expected execution/cleanup window, and frontend/background polling should reuse it instead of guessing with a flat client-side timeout.
- tracker timeout budgets are mission-aware instead of one flat timeout: short actions use action-specific budgets, while Drone Show, Custom CSV, and Swarm Trajectory derive longer tracking windows from the active mission assets plus cleanup buffers.
- if `trigger_time` schedules the command in the future, that waiting period is included in `tracking_timeout_ms`; delayed commands should not use a shorter client-side timeout than the server provided.
- duplicate delivery of the same `command_id` to a drone is treated as idempotent while that command is still queued or executing; the drone returns an accepted ACK rather than re-installing the mission.
- `mission_type=0` is the dedicated cancel/clear path for shared command control. It clears queued or active mission state without launching a normal mission subprocess.
- there is currently no separate command-specific cancel resource. Live cancellation goes through `POST /api/v1/commands` with `mission_type=0` so the cancel action is actually dispatched to drones.

#### `GET /api/v1/commands/{command_id}`
Retrieve the current lifecycle state for a previously submitted command.

**Response:**
```json
{
  "command_id": "5c6c136a-0ea2-41ba-a00f-0e632c3c4418",
  "idempotency_key": "launch-wave-001",
  "mission_type": 10,
  "mission_name": "TAKE_OFF",
  "target_drones": ["1", "2"],
  "status": "executing",
  "phase": "in_progress",
  "outcome": null,
  "acks": {
    "expected": 2,
    "received": 2,
    "accepted": 2,
    "offline": 0,
    "rejected": 0,
    "errors": 0,
    "details": {}
  },
  "executions": {
    "expected": 2,
    "started": 1,
    "active": 1,
    "received": 0,
    "succeeded": 0,
    "failed": 0,
    "details": {}
  },
  "late_reports": {
    "acks": {
      "received": 0,
      "accepted": 0,
      "offline": 0,
      "rejected": 0,
      "errors": 0,
      "details": {}
    },
    "execution_starts": {
      "received": 0,
      "details": {}
    },
    "executions": {
      "received": 0,
      "succeeded": 0,
      "failed": 0,
      "details": {}
    }
  },
  "progress": {
    "stage": "executing",
    "label": "Execution in progress",
    "message": "Execution is active on 1 drone(s).",
    "ack_pending": 0,
    "accepted": 2,
    "execution_pending": 1,
    "active": 1,
    "completed": 0,
    "remaining": 2,
    "scheduled_trigger_time": null
  },
  "created_at": 1700000000000,
  "submitted_at": 1700000000100,
  "execution_started_at": 1700000002000,
  "completed_at": null,
  "updated_at": 1700000002000,
  "error_summary": null
}
```

Important semantics:
- `progress` is the normalized operator-facing lifecycle view and should be preferred for dashboards/toasts over trying to infer meaning from legacy `status` alone.
- `progress.stage=scheduled` means accepted drones are waiting for a future trigger time.
- `progress.stage=pending_execution` means delivery/ACKs are done, but no drone has reported execution start yet.
- `progress.stage=executing` means at least one drone has started and none have reported completion yet.
- `progress.stage=finishing` means some drones already reported terminal execution results while other accepted drones are still active; this is the normal state during long end behaviors such as RTL / land / disarm cleanup.
- command timeout promotion runs continuously in the FastAPI background services, so a command that never reaches terminal execution reporting will still move to a terminal timeout state instead of remaining stuck forever in `submitted` or `executing`.
- drone-side execution-start and execution-result callbacks are now retried through a bounded in-memory queue with backoff and per-command coalescing when GCS is temporarily unreachable; duplicate callback delivery is idempotent, so brief network loss should degrade into delayed tracker updates rather than permanently missing terminal state.
- execution-start and execution-result callbacks also count as authoritative acceptance evidence. If the original GCS->drone HTTP ACK was lost or temporarily marked offline, the tracker upgrades that target to accepted once execution is confirmed.
- once a command already reached `phase=terminal`, later ACK/execution callbacks no longer rewrite its final outcome. They are exposed under `late_reports` as post-terminal evidence for audit/debugging only.
- failed execution reports preserve the first concrete per-drone reason in `error_summary` and the execution `details` object, so dashboards, logs, and assistants should show that reason instead of only saying that all executions failed.
- strict synchronized offboard missions (`DRONE_SHOW_FROM_CSV`, `CUSTOM_CSV_DRONE_SHOW`, `SWARM_TRAJECTORY`, `HOVER_TEST`) stop GCS-side retries once the safe queue window before `trigger_time - trigger_sooner_seconds - COMMAND_SYNC_DISPATCH_GUARD_SEC` has passed, and the drone runtime aborts if actual mission start slips beyond `SYNCHRONIZED_MISSION_LATE_START_TOLERANCE_SEC`.
- standalone actions such as `TAKEOFF` are not treated as strict synchronized choreography. Once accepted, they still use bounded drone-local startup retries, but they do not keep rejoining a missed synchronized timeline after the safe window has passed.

#### `GET /api/v1/commands/recent`
Retrieve recent tracked commands for persistent operator monitoring surfaces.

**Query parameters:**
- `limit` (optional): max commands to return, default `50`
- `status` (optional): filter by terminal or active status name
- `mission_type` (optional): filter by numeric mission type

Use this endpoint for recent command history panels instead of keeping frontend-only command monitor state.

#### `GET /api/v1/commands/active`
Retrieve currently active non-terminal commands.

Use this endpoint to rehydrate command monitors after a dashboard refresh/navigation event so operators do not lose in-flight command context when the page remounts.

#### `GET /api/v1/commands/policy/precision-move`
Retrieve the live runtime defaults and safety envelope for the Precision Move action.

**Response:**
```json
{
  "action": "precision_move",
  "defaults": {
    "speed_m_s": 1.0,
    "position_tolerance_m": 0.15,
    "yaw_tolerance_deg": 5.0,
    "settle_time_sec": 1.0,
    "timeout_sec": 30.0
  },
  "limits": {
    "max_translation_m": 100.0,
    "max_speed_m_s": 5.0,
    "min_position_tolerance_m": 0.05,
    "max_timeout_sec": 180.0,
    "min_airborne_altitude_m": 0.3,
    "control_rate_hz": 10.0
  },
  "execution": {
    "supported_frames": ["body", "ned"],
    "supported_yaw_modes": ["hold_current", "relative_delta", "absolute_heading"],
    "hold_mode": "px4_hold",
    "immediate_only": true,
    "requires_airborne": true,
    "requires_local_position": true
  }
}
```

Use this contract for:
- operator UI defaults and limit hints
- CLI / automation wrappers that want the live backend policy instead of mirrored constants
- future MCP/AI-agent adapters that need to discover whether the action is immediate-only, airborne-only, and local-position dependent

---

### Git Operations

Canonical git routes are exposed under `/api/v1/...`. The old versionless HTTP aliases are retired.

#### `GET /api/v1/git/status`
Get git status from all drones.

**Response:**
```json
{
  "git_status": {
    "1": {
      "pos_id": 1,
      "hw_id": "1",
      "ip": "10.0.0.1",
      "status": "synced",
      "branch": "main-candidate",
      "commit": "abc12345",
      "commit_message": "Phase 4 git cleanup",
      "in_sync_with_gcs": true,
      "commits_ahead": 0,
      "commits_behind": 0,
      "mavlink_runtime": {
        "management_mode": "local",
        "ref": "v3.0.8",
        "router_service_status": "active",
        "dashboard_access_mode": "local_only",
        "desired_config_hash": "9c4d...",
        "applied_config_hash": "9c4d...",
        "config_hash_match": true
      },
      "connectivity_runtime": {
        "backend": "none",
        "ref": "v2.1.9",
        "profile_hash": null,
        "config_hash_match": null
      },
      "last_check": 1700000000000
    }
  },
  "total_drones": 10,
  "synced_count": 8,
  "needs_sync_count": 2,
  "gcs_status": {
    "branch": "main-candidate",
    "commit": "abc12345",
    "status": "clean"
  },
  "sync_in_progress": false,
  "timestamp": 1700000000000
}
```

#### `POST /api/v1/git/sync-operations`
Deprecated compatibility route. It no longer dispatches `UPDATE_CODE`.
Use Fleet Ops dry-run/apply instead.

**Request:**
```json
{
  "pos_ids": [0, 1, 2],
  "force_pull": false
}
```

**Response:**
```json
{
  "success": false,
  "message": "Direct git sync is disabled. Use Fleet Ops /api/v1/fleet/git-sync/dry-run followed by /api/v1/fleet/git-sync/apply.",
  "synced_drones": [],
  "failed_drones": [],
  "total_attempted": 0
}
```

#### `GET /api/v1/fleet/git-sync`
Return Fleet Ops git-sync posture for configured drones.

#### `POST /api/v1/fleet/git-sync/dry-run`
Preview selected sync targets without mutating drones. Mutation-token headers
are required when `MDS_FLEET_OPS_MUTATION_TOKEN` is configured.

#### `POST /api/v1/fleet/git-sync/apply`
Apply a confirmed dry-run by sending `UPDATE_CODE` only to eligible targets.
The request must include the dry-run id and confirmation token returned by the
dry-run response.

Sidecar hashes are compact compliance markers. They are intended for drift
visibility and should not be treated as profile content or credentials.

---

### GCS Configuration

#### `GET /api/v1/system/gcs-config`
Get the GCS runtime configuration resource.

**Response:**
```json
{
  "sim_mode": false,
  "mode": "real",
  "mode_source": "env:MDS_MODE",
  "configured_mode": "real",
  "configured_sim_mode": false,
  "gcs_port": 5030,
  "git_auto_push": true,
  "configured_git_auto_push": true,
  "acceptable_deviation": 2.0,
  "gcs_config_path": "/etc/mds/gcs.env",
  "gcs_config_present": true,
  "restart_required": false
}
```

#### `PUT /api/v1/system/gcs-config`
Update the GCS runtime configuration resource.

The current implementation persists only the safe host-local subset of runtime
settings:

- `mode` / `sim_mode` -> `MDS_MODE` in `/etc/mds/gcs.env`
- `git_auto_push` -> `MDS_GIT_AUTO_PUSH` in `/etc/mds/gcs.env`

Fields such as `gcs_port` and `acceptable_deviation` are deliberately not
persisted here because they belong to broader runtime/fleet config ownership,
not the narrow host-local GCS mode switch surface.

**Request:**
```json
{
  "mode": "sitl",
  "git_auto_push": false
}
```

**Response:**
```json
{
  "success": true,
  "status": "success",
  "message": "Host-local GCS settings were persisted. Restart the GCS runtime to apply them.",
  "persisted": true,
  "config_path": "/etc/mds/gcs.env",
  "updated_keys": [
    "MDS_MODE",
    "MDS_GIT_AUTO_PUSH"
  ],
  "configured_mode": "sitl",
  "configured_git_auto_push": false,
  "restart_required": true,
  "warnings": []
}
```

Malformed/non-object JSON payloads still return the shared `422 Validation
error` envelope. Conflicting `mode` and `sim_mode` values also return `422`
instead of silently guessing which one should win.

#### `POST /api/v1/system/gcs-config/apply`
Apply the persisted host-local runtime configuration by scheduling a controlled
GCS relaunch through the canonical launcher.

This route does not mutate the persisted configuration. It compares the running
process against `/etc/mds/gcs.env`, reports drift, and only schedules a relaunch
when the configured host-local mode or git auto-push posture differs from the
active process.

**Request:**
```json
{}
```

**Response:**
```json
{
  "success": true,
  "status": "scheduled",
  "message": "GCS restart scheduled to apply host-local runtime changes.",
  "configured_mode": "sitl",
  "configured_git_auto_push": false,
  "restart_required": true,
  "scheduled": true,
  "restart_delay_ms": 2000,
  "warnings": [
    "2 SITL instance(s) are still running; mode-tagged heartbeats will be ignored after restart until those instances are stopped or the host returns to SITL mode."
  ]
}
```

If the running process already matches the persisted host-local settings, the
route returns `status: "no_restart_required"` and does not schedule a relaunch.

#### `GET /api/v1/system/runtime-status`
Get the resolved runtime/admin posture for the active GCS process.

This is the operator-facing status surface consumed by GCS Runtime. It
combines:

- running process mode and uptime
- configured host-local mode from `/etc/mds/gcs.env`
- repo/auth health for the current checkout
- local external-tool posture such as managed `mavlink-anywhere` and
  Smart Wi-Fi Manager runtime status
- relevant documentation links for operators and headless automation

Example response excerpt:

```json
{
  "version": "5.2.0",
  "mode": "real",
  "configured_mode": "sitl",
  "git_auto_push": true,
  "configured_git_auto_push": false,
  "restart_required": true,
  "repo_access_mode": "https_token_file",
  "git_auth_health": {
    "status": "healthy"
  },
  "fleet_defaults": {
    "connectivity_backend": "smart-wifi-manager"
  },
  "mavlink_runtime": {
    "dashboard_service_status": "active"
  },
  "connectivity_runtime": {
    "service_status": "active"
  }
}
```

#### `GET /api/v1/fleet/sidecars`
Return Fleet Ops sidecar contract metadata plus Wi-Fi and MAVLink table data.

#### `GET /api/v1/fleet/sidecars/{sidecar}`
Return one sidecar table. `{sidecar}` is `smart-wifi-manager` or
`mavlink-anywhere`.

Each row includes:

- drone identity and last-known presence
- service state and installed ref
- policy mode
- profile source
- desired, local, and applied hashes
- drift state
- profile/endpoint count
- dashboard link metadata
- last apply result
- `profiles` for sanitized Smart Wi-Fi node-local profiles when reported
- `sources` and `endpoints` for sanitized MAVLink node-local input sources and
  route endpoints when reported

#### `GET /api/v1/fleet/sidecars/{sidecar}/baseline`
Return the redacted repo baseline summary and desired hash. Preferred baseline
paths are:

- `config/fleet-profiles/smart-wifi-manager/config.json`
- `config/fleet-profiles/mavlink-anywhere/profile.json`

Legacy deployment paths may be read for compatibility.

Baseline responses include sanitized Smart Wi-Fi `profiles` or MAVLink
`endpoints`. MAVLink baseline endpoints intentionally exclude node hardware
input overlays such as UART devices and PX4 UDP input sources.

#### `GET /api/v1/fleet/sidecars/{sidecar}/nodes/{hw_id}`
Return one node-local redacted profile summary and drift posture. Wi-Fi node
responses may include sanitized `profiles`; MAVLink node responses may include
sanitized `sources` and `endpoints`. Credentials, tokens, private keys,
secret-file paths, and raw profile bodies are not returned.

#### `POST /api/v1/fleet/sidecars/{sidecar}/promote-draft`
Generate a sanitized reference draft from one selected node. This does not
replace the repo baseline and does not mutate the selected node.

#### `POST /api/v1/fleet/sidecars/{sidecar}/reconcile/dry-run`
Build a reconcile plan for selected nodes. No mutation.

**Request:**
```json
{
  "node_ids": ["demo-drone-1"],
  "mode": "fleet-merge"
}
```

#### `POST /api/v1/fleet/sidecars/{sidecar}/reconcile/apply`
Apply a previously generated dry-run plan. Requires explicit confirmation:

```json
{
  "dry_run_id": "dryrun-abc123",
  "confirmation": {
    "operator": "dashboard",
    "acknowledged_risks": true,
    "advanced_strict_ack": false,
    "confirmation_token": "token-from-dry-run"
  }
}
```

#### `POST /api/v1/fleet/sidecars/{sidecar}/policy/dry-run`
Preview policy-mode changes for selected nodes.

#### `POST /api/v1/fleet/sidecars/{sidecar}/policy/apply`
Apply confirmed policy-mode changes. `fleet-strict` requires
`advanced_strict_ack=true`.

#### `GET /api/v1/fleet/sidecars/jobs/{job_id}`
Read job results. Job-read responses omit sidecar confirmation tokens.

Mutation routes require dry-run first and explicit confirmation second. When
`MDS_FLEET_OPS_MUTATION_TOKEN` is configured, callers must send
`X-Fleet-Ops-Token` or `Authorization: Bearer ...`.

---

### QuickScout / SAR Mission Planning

QuickScout keeps the stable `/api/sar/*` subsystem root because it is a mission
subsystem, not a legacy compatibility alias. See
[QuickScout](../quickscout.md) for operator semantics.

#### `POST /api/sar/mission/plan`
Compute a QuickScout package synchronously. Current first-party UI prefers the
job endpoint below for long operations, but this route remains available for
bounded automation and compatibility.

Mission templates:

- `point_dispatch`
- `last_known_point`
- `area_sweep`
- `corridor_search`

Planner safety:

- selected-drone planning rejects missing, stale, invalid, or placeholder
  telemetry positions
- `(0, 0)` is valid only when explicitly supplied as operator geometry
- terrain-following requests fail with a terrain-unavailable error when
  required elevation data cannot be resolved

#### `POST /api/sar/mission/plan/jobs`
Create an asynchronous planning job.

**Response:**
```json
{
  "success": true,
  "job_id": "quickscout-plan-abc123",
  "status": "queued",
  "phase": "queued",
  "progress": 0,
  "message": "Planning job queued",
  "result": null,
  "error": null
}
```

#### `GET /api/sar/mission/plan/jobs/{job_id}`
Read planning job state. Terminal states are `succeeded`, `failed`, `canceled`,
and `expired`.

#### `POST /api/sar/mission/plan/jobs/{job_id}/cancel`
Request cancellation for a planning job.

#### Active QuickScout endpoints

- `GET /api/sar/missions`
- `POST /api/sar/mission/launch`
- `GET /api/sar/mission/{mission_id}/workspace`
- `GET /api/sar/mission/{mission_id}/status`
- `GET /api/sar/mission/{mission_id}/handoff`
- `POST /api/sar/mission/{mission_id}/pause`
- `POST /api/sar/mission/{mission_id}/resume`
- `POST /api/sar/mission/{mission_id}/abort`
- `POST /api/sar/mission/{mission_id}/progress`
- `POST /api/sar/findings`
- `GET /api/sar/findings`
- `PATCH /api/sar/findings/{finding_id}`
- `DELETE /api/sar/findings/{finding_id}`
- `POST /api/sar/elevation/batch`

QuickScout planning job state is in memory. Persisted mission packages,
findings, and handoff data remain in the QuickScout store.

---

### Stable Subsystem Roots

Not every current GCS API domain needs to move under `/api/v1/...`.

- `/api/logs/*` is an intentional stable logging subsystem root shared with drone-side log access and SSE streaming semantics.
- `/api/sar/*` is an intentional QuickScout mission-subsystem root.

The versioning work after the main Phase 4 cleanup is therefore focused on stream-contract policy and route quality, not on renaming these already namespaced subsystem domains for the sake of uniformity alone.

### Stable Transport Roots

The GCS WebSocket surface is also intentional and canonical.

- `/ws/telemetry` is the canonical real-time fleet telemetry stream.
- `/ws/heartbeats` is the canonical real-time heartbeat stream.
- `/ws/git-status` is the canonical real-time git-status stream.

These transport roots stay versionless on purpose. They are long-lived event channels, not leftover HTTP compatibility aliases.

---

### Swarm Trajectory Static Assets

#### `GET /api/v1/swarm-trajectories/plots/{filename}`
Serve generated Swarm Trajectory plot images.

---

## WebSocket Endpoints

WebSocket endpoints provide real-time streaming for high-frequency data.

The three current GCS WebSocket endpoints are intentional canonical transport roots, not temporary compatibility aliases.

FastAPI/OpenAPI does not describe WebSocket contracts. For `/ws/*`, this
section plus [`tests/test_gcs_api_websocket.py`](../../tests/test_gcs_api_websocket.py)
are the source of truth.

### `WS /ws/telemetry`
Real-time telemetry streaming. The default cadence is 1 Hz.

Optional query:
- `interval_ms`: requested stream interval in milliseconds. The server bounds this between 500 ms and 6000 ms so tactical map clients can reduce bandwidth on constrained links without opening a new API surface.

**Connection:**
```javascript
const ws = new WebSocket('ws://localhost:5030/ws/telemetry?interval_ms=1000');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Telemetry:', data);
};
```

**Message Format:**
```json
{
  "type": "telemetry",
  "timestamp": 1700000000000,
  "data": {
    "1": {
      "pos_id": 0,
      "hw_id": 1,
      "battery_voltage": 12.6,
      "position_lat": 35.123456
    }
  }
}
```

**Benefits:**
- 95% less overhead vs HTTP polling
- Real-time updates (1 Hz)
- Automatic reconnection support

### `WS /ws/git-status`
Real-time git status streaming (0.2 Hz).

Canonical HTTP snapshot reads for the same domain remain available at `GET /api/v1/git/status`.

**Connection:**
```javascript
const ws = new WebSocket('ws://localhost:5030/ws/git-status');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Git Status:', data);
};
```

**Message Format:**
```json
{
  "type": "git_status",
  "timestamp": 1700000000000,
  "data": {
    "git_status": {
      "1": {
        "pos_id": 1,
        "hw_id": "1",
        "branch": "main-candidate",
        "status": "synced",
        "in_sync_with_gcs": true
      }
    },
    "total_drones": 1,
    "synced_count": 1,
    "needs_sync_count": 0,
    "gcs_status": {
      "branch": "main-candidate",
      "commit": "abc12345"
    },
    "sync_in_progress": false,
    "timestamp": 1700000000000
  },
  "sync_in_progress": false
}
```

`data` mirrors the canonical `GET /api/v1/git/status` snapshot body. The
top-level `sync_in_progress` is a convenience copy for stream consumers that do
not want to inspect the nested snapshot payload.

### `WS /ws/heartbeats`
Real-time heartbeat monitoring (0.5 Hz).

**Connection:**
```javascript
const ws = new WebSocket('ws://localhost:5030/ws/heartbeats');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Heartbeats:', data);
};
```

**Message Format:**
```json
{
  "type": "heartbeat",
  "timestamp": 1700000000000,
  "data": [
    {
      "pos_id": 0,
      "hw_id": "1",
      "online": true,
      "last_heartbeat": 1700000000000
    }
  ]
}
```

`data` matches the `heartbeats` list from `GET /api/v1/fleet/heartbeats`; it is
not the older raw internal heartbeat map.

---

## Authentication

Authentication is optional and disabled by default for isolated demos and local
development.

Recommended staged production posture:

1. Enable dashboard login with `MDS_AUTH_ENABLED=true`.
2. Keep machine/API auth disabled with `MDS_API_AUTH_ENABLED=false` until drone,
   SITL, AI-agent, and field-script token provisioning has been tested.
3. Enable full bearer-token enforcement only when every machine client can send
   `Authorization: Bearer mds_...`.

Auth management routes:

- `GET /api/v1/auth/status`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`
- `GET /api/v1/auth/users` (admin)
- `POST /api/v1/auth/users` (admin)
- `PATCH /api/v1/auth/users/{username}` (admin)
- `GET /api/v1/auth/tokens` (admin)
- `POST /api/v1/auth/tokens` (admin)
- `POST /api/v1/auth/tokens/{token_id}/revoke` (admin)

When dashboard auth is enabled, `/docs`, `/redoc`, and `/openapi.json` require a
login session or bearer token. Log into the dashboard in the same browser before
opening Swagger UI.

When `MDS_API_AUTH_ENABLED=false`, current companion-node machine endpoints
remain open on the trusted network:

- `GET /api/v1/origin/bootstrap`
- `POST /api/v1/fleet/heartbeats`
- `POST /api/v1/command-reports/execution-start`
- `POST /api/v1/command-reports/execution-result`
- `POST /api/v1/fleet/candidates/announce`

See [GCS Auth Guide](../guides/gcs-auth.md) for bootstrap flags, roles, token
rotation, SSH recovery, and API-auth rollout guidance.

### Fleet Enrollment Runtime Domains

`GET /api/v1/fleet/candidates` defaults to the current GCS runtime mode so SITL
and REAL candidates do not appear in the same operator queue. Use
`runtime_mode=real`, `runtime_mode=sitl`, or `runtime_mode=all` only when
intentionally auditing another domain. Bootstrap announce payloads should include
`runtime_mode`; `tools/mds_node_announce.sh` derives it from
`/etc/mds/node_identity.json`.

### Environment Control Plane

The environment control plane is registry-backed. It is intended for typed
inspection and small repairs, not as a replacement for repo/bootstrap desired
state.

GCS host routes:

- `GET /api/v1/system/env/registry`
- `GET /api/v1/system/env/gcs`
- `PUT /api/v1/system/env/gcs`
- `POST /api/v1/system/env/gcs/apply`

Fleet-node routes through the GCS proxy:

- `POST /api/v1/system/env/fleet/plan`
- `GET /api/v1/system/env/fleet/nodes/{hw_id}`
- `PUT /api/v1/system/env/fleet/nodes/{hw_id}`

Policy:

- raw secret values are redacted and cannot be edited through env APIs
- GCS edits only accept registry-approved GCS keys
- single-node edits only accept registry-approved node keys
- fleet-wide env mutation remains dry-run only; promote stable changes into the
  repo/bootstrap source of truth and let nodes sync/reconcile
- node proxy calls require the drone API to be reachable from the GCS on the
  configured `MDS_DRONE_API_PORT`

### Simurgh Operator MCP Review

Simurgh exposes two separate surfaces on purpose:

- reviewed callable tools: `GET /api/v1/simurgh/tools` and
  `POST /api/v1/simurgh/mcp`
- first-party dashboard assistant turns:
  `POST /api/v1/simurgh/assistant/turns` and
  `POST /api/v1/simurgh/assistant/turns/stream`
- generated review-only candidates: `GET /api/v1/simurgh/tool-candidates`

`GET /api/v1/simurgh/tool-candidates` reads
`docs/agent-context/generated/simurgh-openapi-tool-candidates.yaml`, summarizes
the current OpenAPI-derived candidate set, and reports which candidates already
match curated registry routes. It does not make routes callable.

Useful query parameters:

- `eligible_read_only=true|false`: filter by generator-inferred read-only MCP
  eligibility
- `risk_class=observe|sensitive_observe|operate|admin|...`: filter by inferred
  risk class
- `search=<text>`: filter by candidate id, route, operation id, summary, or tag
- `limit` and `offset`: bounded pagination, with `limit` capped at 200

Promotion remains manual and reviewed:

```text
OpenAPI route
  -> generated non-callable candidate
  -> config/agent_tools.yaml
  -> config/agent_policy.yaml
  -> tests/docs/evals
  -> reviewer approval
  -> MCP tools/list and tools/call
```

This lets FastAPI-MCP, FastMCP, MCPify, or future adapters help with discovery
without replacing the MDS safety boundary.

`POST /api/v1/simurgh/assistant/turns/stream` returns `text/event-stream` for
the dashboard chat UI. It emits `progress`, `delta`, `final`, `done`, and
sanitized `error` events. The `final` payload matches the normal assistant-turn
response shape. This SSE route is not an MCP transport and is not callable from
the generated OpenAPI candidate menu unless a future reviewed registry/policy
promotion explicitly approves it.

For authenticated dashboard/operator sessions with `MDS_AGENT_PROVIDER=openai`,
assistant turns may first execute a policy-approved read-only Simurgh advisory
tool and then ask OpenAI to compose the final text from a bounded
`session.read_only_mds_evidence` context document. The route still reports the
selected local `trace.tool.intent`, does not expose raw prompts in the trace, and
does not allow provider-side tool execution. Unauthenticated local-tool turns
remain deterministic `mds-tools` answers so field-visible GCS deployments do not
turn into an external provider surface.

---

## Error Handling

Current GCS HTTP routes now return one consistent error envelope for non-2xx
failures. Success payloads still vary by subsystem and operation type, but the
error contract is shared.

**Error Response Format:**
```json
{
  "error": "Error message",
  "detail": "Detailed error information",
  "timestamp": 1700000000000,
  "path": "/endpoint-path"
}
```

**Common Status Codes:**
- `200`: Success
- `400`: Bad Request (invalid parameters)
- `401`: Authentication Required
- `403`: Permission Denied
- `404`: Not Found
- `422`: Validation Error
- `500`: Internal Server Error
- `503`: Service Unavailable

---

## Migration from Flask

The FastAPI implementation replaced the earlier Flask server, but the public contract is no longer a blanket one-for-one Flask mirror.

### Current Contract Policy
- Canonical business routes live under `/api/v1/...`
- Stable operational probes remain versionless at `/health` and `/ping`
- Stable real-time transports remain under `/ws/*`
- Legacy verb-style GCS business routes that were migrated during the 2026-04-03 cleanup are retired rather than preserved indefinitely

### Migration Steps
1. Install dependencies: `pip install fastapi uvicorn pydantic python-multipart`
2. Start FastAPI server: `uvicorn app_fastapi:app --port 5030`
3. Use the canonical `/api/v1/...` contract for new integrations
4. Check [api-modernization-blueprint.md](./api-modernization-blueprint.md) before assuming an older route is still supported

### Advantages of FastAPI
- **3-5x faster** response times
- **Automatic OpenAPI docs** at `/docs` and `/redoc`
- **Type safety** with Pydantic validation
- **WebSocket support** for real-time streaming
- **Async/await** for better concurrency
- **Better error messages** with detailed validation errors

---

## Performance Metrics

### HTTP Endpoints
- Average response time: **10-50ms** (vs 30-150ms Flask)
- Throughput: **1000-2000 req/s** (vs 300-500 req/s Flask)
- Memory usage: Similar to Flask

### WebSocket Endpoints
- Connection overhead: **<1ms**
- Message latency: **<5ms**
- Concurrent connections: **1000+**

---

## Support

- **Documentation:** `/docs` (Swagger UI)
- **Issues:** [GitHub Issues](https://github.com/alireza787b/mavsdk_drone_show/issues)
- **Migration Plan:** See `GCS_SERVER_MIGRATION_PLAN.md`

---

**Last Updated:** 2026-05-27
**Version:** 5.5 (FastAPI)
**Maintainer:** MAVSDK Drone Show Team
