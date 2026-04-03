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
- **100% backward compatibility** with original Flask implementation

## API Evolution Note

Beginning with the 2026-04-03 API modernization stream, canonical routes are being introduced under `/api/v1/...` while legacy compatibility routes remain available during migration.

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

#### `GET /ping`
Health check endpoint.

**Response:**
```json
{
  "status": "ok",
  "timestamp": 1700000000000,
  "version": "5.0"
}
```

#### `GET /health`
Same as `/ping`.

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

#### `GET /telemetry`
Get telemetry from all drones (legacy endpoint).

**Response:**
```json
{
  "1": {
    "pos_id": 0,
    "hw_id": "1",
    "state": 0,
    "mission": 0,
    "last_mission": 0,
    "battery_voltage": 12.6,
    "position_lat": 35.123456,
    "position_long": -120.654321,
    "position_alt": 488.5,
    "is_armed": false,
    "is_ready_to_arm": true,
    "readiness_status": "ready",
    "readiness_summary": "Ready to fly",
    "preflight_blockers": [],
    "preflight_warnings": [],
    "status_messages": [],
    "heartbeat_last_seen": 1700000000000
  }
}
```

#### `GET /api/telemetry`
Get telemetry with the same live payload shape used by the React dashboard.

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

`readiness_status`, `readiness_summary`, `preflight_blockers`, and `status_messages` are the operator-facing fields the dashboard now uses for "Ready to Fly" and live PX4 preflight feedback.

---

### Heartbeat

#### `POST /heartbeat`
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

#### `GET /get-heartbeats`
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

#### `GET /get-network-status`
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
    "assignments": []
  }
}
```

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

#### `GET /api/swarm/leaders`
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

#### `POST /api/swarm/trajectory/upload/{leader_id}`
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

#### `POST /api/swarm/trajectory/process`
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

#### `GET /api/swarm/trajectory/status`
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

#### `GET /api/swarm/trajectory/policy`
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

- `GET /api/swarm/trajectory/recommendation`
- `POST /api/swarm/trajectory/clear`
- `POST /api/swarm/trajectory/clear-leader/{leader_id}`
- `DELETE /api/swarm/trajectory/remove/{leader_id}`
- `POST /api/swarm/trajectory/clear-drone/{drone_id}`
- `GET /api/swarm/trajectory/download-cluster-kml/{leader_id}`
- `POST /api/swarm/trajectory/commit`

#### `POST /api/swarm/trajectory/clear-processed`
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
  "missionType": 10,
  "triggerTime": 0,
  "target_drones": ["1", "2"],
  "takeoff_altitude": 10
}
```

**Response:**
```json
{
  "success": true,
  "command_id": "5c6c136a-0ea2-41ba-a00f-0e632c3c4418",
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
- `target_drones` may contain hardware IDs or position IDs. The response always normalizes `target_drones` to hardware IDs after the target set is resolved.
- malformed JSON, non-object JSON bodies, invalid `target_drones` shapes, and explicit target selections that match no configured drones fail fast with `400` instead of creating an ambiguous zero-target command record.
- `tracking_phase=pending_execution` means delivery/ACKs are complete but the drone has not yet reported execution start.
- Long-running actions such as `TAKE_OFF`, `LAND`, `DRONE_SHOW_FROM_CSV`, `SMART_SWARM`, and `QUICKSCOUT` should be tracked via `GET /api/v1/commands/{command_id}` rather than treated as finished at submission time.
- `tracking_timeout_ms` is the mission-aware lifecycle timeout selected by the backend for this command. It already includes any future trigger delay plus the expected execution/cleanup window, and frontend/background polling should reuse it instead of guessing with a flat client-side timeout.
- tracker timeout budgets are mission-aware instead of one flat timeout: short actions use action-specific budgets, while Drone Show, Custom CSV, and Swarm Trajectory derive longer tracking windows from the active mission assets plus cleanup buffers.
- if `triggerTime` schedules the command in the future, that waiting period is included in `tracking_timeout_ms`; delayed commands should not use a shorter client-side timeout than the server provided.
- duplicate delivery of the same `command_id` to a drone is treated as idempotent while that command is still queued or executing; the drone returns an accepted ACK rather than re-installing the mission.
- `missionType=0` is the dedicated cancel/clear path for shared command control. It clears queued or active mission state without launching a normal mission subprocess.
- `POST /api/v1/commands/{command_id}/cancel` is intentionally fail-closed for now; use `POST /api/v1/commands` with `missionType=0` for live cancellation because that path actually dispatches to drones.

#### `GET /api/v1/commands/{command_id}`
Retrieve the current lifecycle state for a previously submitted command.

**Response:**
```json
{
  "command_id": "5c6c136a-0ea2-41ba-a00f-0e632c3c4418",
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
- strict synchronized offboard missions (`DRONE_SHOW_FROM_CSV`, `CUSTOM_CSV_DRONE_SHOW`, `SWARM_TRAJECTORY`, `HOVER_TEST`) stop GCS-side retries once the safe queue window before `triggerTime - trigger_sooner_seconds - COMMAND_SYNC_DISPATCH_GUARD_SEC` has passed, and the drone runtime aborts if actual mission start slips beyond `SYNCHRONIZED_MISSION_LATE_START_TOLERANCE_SEC`.
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

Canonical git routes are exposed under `/api/v1/...`. Legacy compatibility routes remain mounted during the migration:

- `GET /git-status`
- `POST /sync-repos`

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

---

### Swarm Trajectory Static Assets

#### `GET /api/v1/swarm-trajectories/plots/{filename}`
Serve generated Swarm Trajectory plot images.

---

## WebSocket Endpoints

WebSocket endpoints provide real-time streaming for high-frequency data.

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
      "battery_voltage": 12.6,
      "Position_Lat": 35.123456
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

The WebSocket compatibility path remains `/ws/git-status` in this phase. Canonical HTTP reads are available at `GET /api/v1/git/status`.

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
    "1": {
      "pos_id": 0,
      "status": "synced",
      "current_branch": "main"
    }
  }
}
```

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

---

## Authentication

Currently, no authentication is required. In production deployments, consider adding:
- API key authentication
- JWT tokens
- IP whitelisting

---

## Error Handling

All endpoints return consistent error responses:

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

The FastAPI implementation maintains **100% backward compatibility** with the original Flask server:

### URL Compatibility
All Flask endpoints work identically in FastAPI:
- Same URLs
- Same request/response formats
- Same parameter names

### Migration Steps
1. Install dependencies: `pip install fastapi uvicorn pydantic python-multipart`
2. Start FastAPI server: `uvicorn app_fastapi:app --port 5000`
3. Update UI to use FastAPI (optional, both servers can run in parallel)
4. Gradually migrate features to leverage FastAPI advantages

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

**Last Updated:** 2026-03-22
**Version:** 5.0 (FastAPI)
**Maintainer:** MAVSDK Drone Show Team
