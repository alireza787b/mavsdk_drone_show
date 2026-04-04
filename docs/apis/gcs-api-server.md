# GCS API Server Documentation

**Version:** 5.0 (FastAPI)
**Port:** 5000 (default)
**Base URL:** `http://localhost:5000`
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
./start_gcs_server.sh development fastapi 5000

# Production backend only
./start_gcs_server.sh production fastapi 5000
```

Notes:
- `--sitl` starts FastAPI plus the dashboard in development mode.
- `--prod --sitl` builds/serves the React dashboard and runs FastAPI in production mode.
- Production currently stays single-worker on purpose because command tracking, heartbeat state, and background services still rely on in-process memory.

### Interactive API Documentation

Visit `/docs` for Swagger UI or `/redoc` for ReDoc documentation:
- **Swagger UI:** http://localhost:5000/docs
- **ReDoc:** http://localhost:5000/redoc

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
      "pos_id": 0,
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
      "velocity_north": 0.0,
      "velocity_east": 0.0,
      "velocity_down": 0.0,
      "battery_voltage": 12.6,
      "hdop": 0.8,
      "vdop": 1.1,
      "gps_fix_type": 3,
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

---

### Heartbeat

#### `POST /api/v1/fleet/heartbeats`
Receive heartbeat from drone (fire-and-forget).

**Request:**
```json
{
  "pos_id": 0,
  "hw_id": "1",
  "timestamp": 1700000000000
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

#### `GET /api/v1/fleet/heartbeats`
Get heartbeat status for all drones.

**Response:**
```json
{
  "heartbeats": [
    {
      "pos_id": 0,
      "hw_id": "1",
      "online": true,
      "last_heartbeat": 1700000000000
    }
  ],
  "total_drones": 10,
  "online_count": 8,
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
      "latency_ms": 12.5
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
- `GET /api/v1/swarm-trajectories/policy`
- `POST /api/v1/swarm-trajectories/process`
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
Sync git repositories on target drones.

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
  "message": "Sync partially verified: 2 of 3 drones updated; 1 failed or timed out",
  "synced_drones": [1, 2],
  "failed_drones": [3],
  "total_attempted": 3
}
```

This route is synchronous from the API caller perspective: it dispatches the repo update, verifies convergence, and then returns the verified result. That is why the canonical path is modeled as a sync operation, not a background job resource.

---

### GCS Configuration

#### `GET /api/v1/system/gcs-config`
Get the GCS runtime configuration resource.

**Response:**
```json
{
  "sim_mode": false,
  "gcs_port": 5000,
  "git_auto_push": true,
  "acceptable_deviation": 2.0
}
```

#### `PUT /api/v1/system/gcs-config`
Update the GCS runtime configuration resource.

The current implementation is an explicit stub acknowledgement. It validates the payload shape and returns a truthful non-persisted acknowledgement while the full persistence path remains deferred.

**Request:**
```json
{
  "sim_mode": false,
  "git_auto_push": true
}
```

**Response:**
```json
{
  "success": true,
  "status": "success",
  "persisted": false,
  "warnings": [
    "Persistence is not implemented in the FastAPI compatibility layer yet."
  ]
}
```

The current implementation still does not persist config, but malformed or
non-object JSON payloads now return the shared `422 Validation error` envelope
instead of route-local string errors.

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
Real-time telemetry streaming (1 Hz).

**Connection:**
```javascript
const ws = new WebSocket('ws://localhost:5000/ws/telemetry');

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
const ws = new WebSocket('ws://localhost:5000/ws/git-status');

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
const ws = new WebSocket('ws://localhost:5000/ws/heartbeats');

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

Currently, no authentication is required. In production deployments, consider adding:
- API key authentication
- JWT tokens
- IP whitelisting

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
2. Start FastAPI server: `uvicorn app_fastapi:app --port 5000`
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

**Last Updated:** 2026-04-03
**Version:** 5.0 (FastAPI)
**Maintainer:** MAVSDK Drone Show Team
