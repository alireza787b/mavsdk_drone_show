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

#### `GET /get-config-data`
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

#### `POST /save-config-data`
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

#### `POST /validate-config`
Validate configuration without saving.

**Request:** Same as `/save-config-data`

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

#### `GET /get-drone-positions`
Get initial positions for all drones from trajectory CSV files.

**Response:**
```json
[
  {
    "hw_id": 1,
    "pos_id": 0,
    "north": 0.0,
    "east": 0.0
  }
]
```

#### `GET /get-trajectory-first-row?pos_id={id}`
Get expected position from trajectory CSV file.

**Parameters:**
- `pos_id` (required): Position ID

**Response:**
```json
{
  "pos_id": 0,
  "north": 0.0,
  "east": 0.0,
  "source": "Drone 0.csv (first waypoint)"
}
```

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

---

### Origin Management

#### `GET /get-origin`
Get current origin coordinates.

**Response:**
```json
{
  "latitude": 35.123456,
  "longitude": -120.654321,
  "altitude": 488.0,
  "timestamp": 1700000000000
}
```

#### `POST /set-origin`
Set origin coordinates manually.

**Request:**
```json
{
  "latitude": 35.123456,
  "longitude": -120.654321,
  "altitude": 488.0
}
```

#### `GET /get-origin-for-drone`
Lightweight endpoint for drones to fetch origin before flight.

**Response:**
```json
{
  "lat": 35.123456,
  "lon": -120.654321,
  "alt": 488.0,
  "timestamp": "2025-11-22T12:00:00",
  "source": "manual"
}
```

#### `GET /get-gps-global-origin`
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

#### `GET /elevation?lat={lat}&lon={lon}`
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

#### `POST /compute-origin`
Compute origin from drone's current position.

**Request:**
```json
{
  "current_lat": 35.123456,
  "current_lon": -120.654321,
  "intended_north": 0.0,
  "intended_east": 0.0
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

#### `GET /get-position-deviations`
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

#### `GET /get-desired-launch-positions?heading={degrees}&format={json|csv|kml}`
Calculate GPS coordinates for each drone's desired launch position.

**Parameters:**
- `heading` (optional): Formation heading (0-359 degrees, default: 0)
- `format` (optional): Output format (json, csv, kml, default: json)

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
      "east": 0.0
    }
  ],
  "total_drones": 10
}
```

---

### Show Management

#### `POST /import-show`
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
  "drones_configured": 10
}
```

#### `GET /get-show-info`
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

#### `GET /download-raw-show`
Download raw show files as ZIP.

**Response:** ZIP file download

#### `GET /download-processed-show`
Download processed show files as ZIP.

**Response:** ZIP file download

#### `GET /get-show-plots`
Get list of all show plot images.

**Response:**
```json
{
  "filenames": ["drone_1_plot.jpg", "drone_2_plot.jpg"],
  "uploadTime": "Fri Nov 22 12:00:00 2025"
}
```

#### `GET /get-show-plots/{filename}`
Get specific show plot image.

**Response:** JPG image file

#### `GET /get-custom-show-image`
Get custom drone show trajectory plot image.

**Response:** PNG image file

#### `GET /get-comprehensive-metrics`
Retrieve comprehensive trajectory analysis metrics.

**Response:**
```json
{
  "safety_metrics": {...},
  "performance_metrics": {...},
  "formation_metrics": {...}
}
```

#### `GET /get-safety-report`
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

#### `POST /validate-trajectory`
Real-time trajectory validation.

**Response:**
```json
{
  "validation_status": "PASS",
  "issues": [],
  "metrics_summary": {...}
}
```

#### `POST /deploy-show`
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

#### `GET /get-swarm-data`
Get swarm configuration.

**Response:**
```json
{
  "hierarchies": {...}
}
```

#### `POST /save-swarm-data?commit={true|false}`
Save swarm configuration.

**Parameters:**
- `commit` (optional): Whether to commit to git

**Request:**
```json
{
  "hierarchies": {...}
}
```

**Response:**
```json
{
  "status": "success",
  "message": "Swarm data saved successfully"
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

#### `POST /submit_command`
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
- `tracking_phase=pending_execution` means delivery/ACKs are complete but the drone has not yet reported execution start.
- Long-running actions such as `TAKE_OFF`, `LAND`, `DRONE_SHOW_FROM_CSV`, `SMART_SWARM`, and `QUICKSCOUT` should be tracked via `GET /command/{command_id}` rather than treated as finished at submission time.
- `tracking_timeout_ms` is the mission-aware lifecycle timeout selected by the backend for this command. It already includes any future trigger delay plus the expected execution/cleanup window, and frontend/background polling should reuse it instead of guessing with a flat client-side timeout.
- tracker timeout budgets are mission-aware instead of one flat timeout: short actions use action-specific budgets, while Drone Show, Custom CSV, and Swarm Trajectory derive longer tracking windows from the active mission assets plus cleanup buffers.
- if `triggerTime` schedules the command in the future, that waiting period is included in `tracking_timeout_ms`; delayed commands should not use a shorter client-side timeout than the server provided.
- duplicate delivery of the same `command_id` to a drone is treated as idempotent while that command is still queued or executing; the drone returns an accepted ACK rather than re-installing the mission.
- `missionType=0` is the dedicated cancel/clear path for shared command control. It clears queued or active mission state without launching a normal mission subprocess.

#### `GET /command/{command_id}`
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

---

### Git Operations

#### `GET /git-status`
Get git status from all drones.

**Response:**
```json
{
  "git_status": {
    "1": {
      "pos_id": 0,
      "status": "synced",
      "current_branch": "main",
      "latest_commit": "abc123"
    }
  },
  "total_drones": 10,
  "synced_count": 8,
  "needs_sync_count": 2,
  "timestamp": 1700000000000
}
```

#### `GET /get-gcs-git-status` *(Deprecated)*
> **Deprecated:** Use `GET /git-status` instead — the `gcs_status` field in the unified response contains the same data.

**Response:**
```json
{
  "branch": "main",
  "status": "clean",
  "commit": "abc123"
}
```

#### `GET /get-drone-git-status/{drone_id}` *(Deprecated)*
> **Deprecated:** Use `GET /git-status` instead — the `git_status` dict contains all drone statuses keyed by `hw_id`.

**Parameters:**
- `drone_id`: Drone ID

**Response:**
```json
{
  "status": "clean",
  "branch": "main",
  "commit": "abc123"
}
```

#### `POST /sync-repos`
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
  "success": true,
  "message": "Sync operation initiated",
  "synced_drones": [0, 1, 2],
  "failed_drones": [],
  "total_attempted": 3
}
```

---

### GCS Configuration

#### `GET /get-gcs-config`
Get GCS server configuration.

**Response:**
```json
{
  "sim_mode": false,
  "gcs_port": 5000,
  "git_auto_push": true,
  "acceptable_deviation": 2.0
}
```

#### `POST /save-gcs-config`
Save GCS server configuration.

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
  "status": "success",
  "message": "GCS configuration saved"
}
```

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
