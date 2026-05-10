# Drone API Server Documentation

**Version:** 5.0 (FastAPI)
**Previous Version:** 1.x (Flask) - Deprecated
**Migration Date:** 2025-11-22
**Status:** ✅ Production Ready

---

## Overview

The Drone API Server is a high-performance FastAPI-based server that runs on each drone, providing both HTTP REST endpoints and WebSocket streaming for real-time telemetry. It handles communication with the Ground Control Station (GCS) and serves drone state information, commands, and configuration data.

## API Evolution Note

As of the 2026-04-04 drone-contract cleanup, the supported HTTP contract is the canonical `/api/v1/...` surface. The old verb-style drone routes were retired instead of being kept as misleading compatibility aliases.

Use [api-modernization-blueprint.md](./api-modernization-blueprint.md) as the planning and migration source of truth.

### Key Features

- ✅ **HTTP REST API** - 10 endpoints for standard operations
- ✅ **WebSocket Streaming** - Real-time telemetry push (95% less overhead)
- ✅ **Auto-Generated Docs** - Interactive API documentation at `/docs`
- ✅ **Type Validation** - Pydantic models ensure data integrity
- ✅ **Async/Await** - Non-blocking I/O for better performance
- ✅ **CORS Enabled** - Accessible from web dashboards
- ✅ **Canonical Contract** - One current route per domain for UI, runtime tooling, and future MCP layers

### Performance Metrics

| Metric | Flask (v1.x) | FastAPI (v2.0) | Improvement |
|--------|--------------|----------------|-------------|
| Requests/sec | ~500 | ~2,000+ | **4x faster** |
| Latency (p50) | 20ms | 5ms | **75% reduction** |
| Memory usage | Baseline | -20% | **More efficient** |
| WebSocket support | ❌ No | ✅ Yes | **New feature** |
| Concurrent connections | 100 | 1,000+ | **10x more** |

---

## Server Configuration

### Default Settings

| Parameter | Value | Description |
|-----------|-------|-------------|
| Host | `0.0.0.0` | Listen on all interfaces |
| Port | `7070` | Default from `MDS_DEFAULT_DRONE_API_PORT`; override per node with `MDS_DRONE_API_PORT` |
| Environment | `development` / `production` | Set via `Params.env_mode` |
| Auto-reload | `False` | Disabled for embedded systems |

### Accessing the Server

The examples below use the default `7070`; replace it with the configured `MDS_DRONE_API_PORT` when a node overrides the port.

**From same network:**
```
http://drone-ip:7070
```

**Interactive API docs:**
```
http://drone-ip:7070/docs
```

**Alternative docs (ReDoc):**
```
http://drone-ip:7070/redoc
```

**OpenAPI schema:**
```
http://drone-ip:7070/openapi.json
```

---

## HTTP REST Endpoints

### 1. Get Drone State

**Endpoint:** `GET /api/v1/drone/state`

**Description:** Retrieve current drone state (snapshot)

**Response:**
```json
{
  "pos_id": 1,
  "detected_pos_id": 1,
  "state": 0,
  "mission": 0,
  "last_mission": 0,
  "position_lat": 47.397742,
  "position_long": 8.545594,
  "position_alt": 488.5,
  "global_position_valid": true,
  "global_position_timestamp_ms": 1732270245000,
  "global_position_age_ms": 100,
  "position_source": "global_position_int",
  "position_unavailable_reason": null,
  "distance_to_home_m": 18.4,
  "velocity_north": 0.0,
  "velocity_east": 0.0,
  "velocity_down": 0.0,
  "yaw": 180.5,
  "battery_voltage": 12.6,
  "follow_mode": "LEADER",
  "update_time": "2025-11-22 10:30:45",
  "timestamp": 1732270245000,
  "flight_mode": 4,
  "base_mode": 81,
  "system_status": 4,
  "is_armed": false,
  "is_ready_to_arm": true,
  "home_position_set": true,
  "readiness_status": "ready",
  "readiness_summary": "Ready to fly",
  "readiness_checks": [
    {
      "id": "px4",
      "label": "PX4 arming report",
      "ready": true,
      "detail": "No active PX4 preflight blockers"
    }
  ],
  "preflight_blockers": [],
  "preflight_warnings": [],
  "status_messages": [],
  "preflight_last_update": 1732270245000,
  "hdop": 0.8,
  "vdop": 1.2,
  "gps_fix_type": 3,
  "gps_raw_valid": true,
  "gps_raw_timestamp_ms": 1732270245000,
  "gps_raw_age_ms": 100,
  "gps_raw_altitude_m": 488.5,
  "satellites_visible": 12,
  "ip": "192.168.1.100"
}
```

**Use Case:** Get current drone state for polling-based GCS

**Recommended For:** GCS polling, validator tooling, and direct operator diagnostics

Readiness fields:
- `is_ready_to_arm` remains the simple compatibility boolean.
- `readiness_status` and `readiness_summary` are the operator-facing verdict.
- `preflight_blockers`, `preflight_warnings`, and `status_messages` surface live PX4 preflight feedback and recent `STATUSTEXT` messages.
- `gps_raw_valid` is raw GPS evidence from `GPS_RAW_INT`; it does not prove the drone has a usable mappable position.
- `gps_raw_altitude_m` is raw GPS altitude above MSL from `GPS_RAW_INT`. It can be shown as an altitude fallback while map placement remains unavailable.
- `global_position_valid` is true only after PX4 publishes a finite, non-zero `GLOBAL_POSITION_INT` coordinate. If GPS reports a fix but global position is not valid, keep map placement and `distance_to_home_m` unavailable.
- `distance_to_home_m` is the horizontal great-circle distance from current valid LLA to cached home position. It is `null` until current position and home position are both available.

---

### 2. Send Command

**Endpoint:** `POST /api/v1/drone/commands`

**Description:** Receive command from GCS

**Request Body:**
```json
{
  "mission_type": 10,
  "trigger_time": 1732270300,
  "command_id": "5c6c136a-0ea2-41ba-a00f-0e632c3c4418",
  "takeoff_altitude": 10
}
```

**Response:**
```json
{
  "status": "accepted",
  "command_id": "5c6c136a-0ea2-41ba-a00f-0e632c3c4418",
  "hw_id": "1",
  "pos_id": 1,
  "current_state": 0,
  "new_state": 1,
  "mission_type": 10,
  "trigger_time": 1732270300,
  "message": "Command TAKE_OFF accepted for immediate execution",
  "error_code": null,
  "error_detail": null,
  "timestamp": 1732270245000
}
```

The drone API returns structured ACKs for both accepted and rejected commands. A rejected command still uses HTTP 200 and places the reason in `status`, `error_code`, and `error_detail`.

Preferred mission encoding:
- canonical request fields are `mission_type` and `trigger_time`.
- legacy aliases (`missionType`, `triggerTime`) are still accepted at the HTTP edge, but first-party GCS callers now send the canonical snake_case contract.
- GCS-to-drone traffic should stay on numeric mission codes for consistency.

---

### 3. Get Home Position

**Endpoint:** `GET /api/v1/navigation/home`

**Description:** Get drone home position

**Response:**
```json
{
  "latitude": 47.397742,
  "longitude": 8.545594,
  "altitude": 488.0,
  "timestamp": 1732270245000
}
```

---

### 4. Get GPS Global Origin

**Endpoint:** `GET /api/v1/navigation/global-origin`

**Description:** Get GPS global origin from autopilot

**Response:**
```json
{
  "latitude": 47.397742,
  "longitude": 8.545594,
  "altitude": 488.0,
  "origin_time_usec": 1732270245000000,
  "timestamp": 1732270245000
}
```

---

### 5. PX4 Parameters

The drone-side PX4 parameter routes are the vehicle-local MAVSDK facade behind the higher-level GCS workflow. Operators and dashboard clients should use the GCS `px4-params` routes instead of calling these directly.

#### `GET /api/v1/px4-params/policy`
Return the local policy envelope, including docs-link configuration and mutation safety policy.

#### `POST /api/v1/px4-params/snapshots/refresh`
Fetch a fresh snapshot directly from the local PX4 vehicle.

**Request:**
```json
{
  "component_id": 1
}
```

#### `GET /api/v1/px4-params/snapshots/current`
Return the most recent locally cached snapshot. Returns `404` if no snapshot has been refreshed yet.

#### `GET /api/v1/px4-params/values/{name}`
Read one PX4 parameter directly from the local vehicle.

#### `PATCH /api/v1/px4-params/values/{name}`
Write one PX4 parameter and optionally verify readback.

**Request:**
```json
{
  "component_id": 1,
  "value_type": "int",
  "value": 4,
  "verify_readback": true
}
```

#### `POST /api/v1/px4-params/patches/apply`
Apply a multi-parameter patch to the local PX4 vehicle.

Notes:
- the default safety policy blocks writes while armed
- docs links are generated from the configured PX4 docs version and the parameter anchor, not from live web scraping
- metadata beyond live name/type/value is best-effort in v1 and may come from component information when available
- these routes exist as the vehicle-local MAVSDK facade; dashboard and operator flows should still go through the GCS `px4-params` routes so snapshots, diffs, imports, and batch jobs stay tracked in one place

---

### 5. Get Git Status

**Endpoint:** `GET /api/v1/git/status`

**Description:** Get current git status of drone repository

**Response:**
```json
{
  "branch": "main-candidate",
  "commit": "29d1ba0abc123...",
  "author_name": "Developer Name",
  "author_email": "dev@example.com",
  "commit_date": "2025-11-22T10:30:00+00:00",
  "commit_message": "refactor: Migrate to FastAPI",
  "remote_url": "git@github.com:alireza787b/mavsdk_drone_show.git",
  "tracking_branch": "origin/main-candidate",
  "status": "clean",
  "uncommitted_changes": [],
  "commits_ahead": 0,
  "commits_behind": 0,
  "mavlink_runtime": {
    "management_mode": "managed",
    "ref": "v3.0.8",
    "router_service_status": "active",
    "desired_config_hash": "9c4d...",
    "applied_config_hash": "9c4d...",
    "config_hash_match": true
  },
  "connectivity_runtime": {
    "backend": "none",
    "ref": "v2.1.9",
    "profile_hash": null,
    "config_hash_match": null
  }
}
```

Notes:
- `tracking_branch` may be empty on detached worktrees or custom local branches
  without an upstream; this is not an error
- `commits_ahead` / `commits_behind` remain `0` when no tracking branch exists
- the drone route now uses the shared Git manager contract, so drone and GCS
  git-status semantics stay aligned
- managed sidecar hash fields are drift markers for Fleet Ops; they do not
  expose profile contents, Wi-Fi secrets, token values, or SSH key paths

---

### 6. Node Environment

#### `GET /api/v1/system/env`

Inspect registry-backed `/etc/mds/local.env` values on the local node. Secret
values are redacted, and the response includes registry metadata, unknown keys,
deprecated keys, and the compact env posture summary also reported in
`GET /api/v1/git/status`.

#### `PUT /api/v1/system/env`

Persist one or more registry-approved node-local env values.

**Request:**
```json
{
  "updates": {
    "MDS_CONNECTIVITY_BACKEND": "smart-wifi-manager"
  },
  "dry_run": false
}
```

Policy:
- only registered node-scope keys are accepted
- raw secrets are never accepted through this API
- `dry_run=true` validates without writing
- the response reports `restart_required` and `apply_actions`; operators should
  restart/reconcile the relevant node service when required
- the normal dashboard path is through the GCS proxy:
  `GET/PUT /api/v1/system/env/fleet/nodes/{hw_id}`

---

### 7. Health

**Primary Endpoint:** `GET /api/v1/system/health`

**Operational Alias:** `GET /ping`

**Description:** Health check endpoint

**Response:**
```json
{
  "status": "ok",
  "timestamp": 1732270245000,
  "version": "5.0.31"
}
```

---

### 7. Get Position Deviation

**Endpoint:** `GET /api/v1/navigation/position-deviation`

**Description:** Calculate deviation from expected position

**Response:**
```json
{
  "deviation_north": 0.5,
  "deviation_east": -0.3,
  "total_deviation": 0.58,
  "within_acceptable_range": true
}
```

**Use Case:** Verify drone is at correct starting position before mission

---

### 8. Get Network Status

**Endpoint:** `GET /api/v1/network/status`

**Description:** Get current network connectivity information

**Response:**
```json
{
  "wifi": {
    "ssid": "DroneNet5G",
    "signal_strength_percent": 85
  },
  "ethernet": {
    "interface": "eth0",
    "connection_name": "Wired connection 1"
  },
  "timestamp": 1732270245000
}
```

---

### 9. Get Swarm Data

**Endpoint:** `GET /api/v1/swarm/config`

**Description:** Get swarm configuration (leader/follower relationships)

**Response:**
```json
[
  {
    "hw_id": "1",
    "follow": "0",
    "offset_x": "0",
    "offset_y": "0",
    "offset_z": "0",
    "frame": "ned"
  },
  {
    "hw_id": "2",
    "follow": "1",
    "offset_x": "5.0",
    "offset_y": "0.0",
    "offset_z": "0.0",
    "frame": "body"
  }
]
```

---

### 10. Get Local Position NED

**Endpoint:** `GET /api/v1/telemetry/local-position`

**Description:** Get LOCAL_POSITION_NED data from MAVLink

**Response:**
```json
{
  "time_boot_ms": 12345678,
  "x": 0.5,
  "y": -0.3,
  "z": -5.2,
  "vx": 0.0,
  "vy": 0.0,
  "vz": 0.0,
  "timestamp": 1732270245000
}
```

**Coordinate System:** North-East-Down (NED)

---

## WebSocket Endpoint (Real-Time Streaming)

### WebSocket Drone State Stream

**Endpoint:** `WS /ws/drone-state`

**Description:** Real-time drone state streaming (recommended for GCS)

**Advantages over HTTP polling:**
- ✅ **95% less network overhead** (no HTTP headers)
- ✅ **Real-time push** (no polling delay)
- ✅ **One-way monitoring stream** (commands stay on `POST /api/v1/drone/commands`)
- ✅ **More efficient** for GCS monitoring multiple drones
- ✅ **Lower latency** (~5ms vs 20ms with HTTP)

### Connection URL

```
ws://drone-ip:7070/ws/drone-state
```

### Update Frequency

**Default:** 1 Hz (1 message per second)

**Configurable rates:**
- High frequency: 10 Hz (0.1s interval) - For precise monitoring
- Medium frequency: 1 Hz (1s interval) - Recommended default
- Low frequency: 0.5 Hz (2s interval) - For bandwidth-constrained networks

### Current Contract

- When state is available, each WebSocket message uses the same canonical
  payload shape as `GET /api/v1/drone/state`.
- When state is temporarily unavailable, the server sends the sentinel payload
  `{"error": "Drone state not available", "timestamp": ...}`.
- This endpoint is currently a one-way monitoring stream. Command submission
  remains the HTTP route `POST /api/v1/drone/commands`.

To change frequency, modify `asyncio.sleep()` value in endpoint code.

### Data Format

Same as HTTP `/api/v1/drone/state` endpoint - JSON format with all telemetry fields.

### Usage Examples

#### JavaScript (Browser)

```javascript
const ws = new WebSocket('ws://192.168.1.100:7070/ws/drone-state');

ws.onopen = () => {
    console.log('Connected to drone');
};

ws.onmessage = (event) => {
    const droneState = JSON.parse(event.data);
    console.log('Drone state:', droneState);

    // Update UI
    document.getElementById('altitude').textContent = droneState.position_alt;
    document.getElementById('battery').textContent = droneState.battery_voltage;
};

ws.onerror = (error) => {
    console.error('WebSocket error:', error);
};

ws.onclose = () => {
    console.log('Disconnected from drone');
};
```

#### Python (asyncio + websockets)

```python
import asyncio
import websockets
import json

async def monitor_drone(drone_ip):
    uri = f"ws://{drone_ip}:7070/ws/drone-state"

    async with websockets.connect(uri) as websocket:
        print(f"Connected to drone at {drone_ip}")

        while True:
            try:
                message = await websocket.recv()
                state = json.loads(message)

                print(f"Altitude: {state['position_alt']:.2f}m")
                print(f"Battery: {state['battery_voltage']:.1f}V")
                print(f"GPS Fix: {state['gps_fix_type']}")
                print("-" * 40)

            except websockets.exceptions.ConnectionClosed:
                print("Connection closed")
                break

# Run
asyncio.run(monitor_drone("192.168.1.100"))
```

#### Python (websockets library - simpler)

```python
import websockets
import json
import asyncio

async def monitor():
    async with websockets.connect('ws://192.168.1.100:7070/ws/drone-state') as ws:
        async for message in ws:
            state = json.loads(message)
            print(f"Drone {state['pos_id']}: Alt={state['position_alt']:.2f}m")

asyncio.run(monitor())
```

#### Python (Monitoring Multiple Drones)

```python
import asyncio
import websockets
import json

async def monitor_drone(drone_id, drone_ip):
    uri = f"ws://{drone_ip}:7070/ws/drone-state"

    async with websockets.connect(uri) as websocket:
        async for message in websocket:
            state = json.loads(message)
            print(f"[Drone {drone_id}] Alt: {state['position_alt']:.2f}m | "
                  f"Battery: {state['battery_voltage']:.1f}V | "
                  f"Armed: {state['is_armed']}")

async def monitor_swarm(drones):
    """Monitor multiple drones concurrently"""
    tasks = [
        monitor_drone(drone_id, ip)
        for drone_id, ip in drones.items()
    ]
    await asyncio.gather(*tasks)

# Run
drones = {
    1: "192.168.1.101",
    2: "192.168.1.102",
    3: "192.168.1.103"
}

asyncio.run(monitor_swarm(drones))
```

---

## API Authentication

**Current Status:** No authentication required

**Security Note:** Drone API server is designed for private networks only. If exposing to internet, implement:
- VPN (Tailscale, WireGuard)
- Network firewall rules
- Future: JWT token authentication (planned)

---

## Error Handling

### HTTP Errors

| Status Code | Description |
|-------------|-------------|
| 200 | Success |
| 400 | Bad Request (invalid input) |
| 404 | Not Found (data not available) |
| 500 | Internal Server Error |

### Error Response Format

```json
{
  "detail": "Error description"
}
```

### WebSocket Errors

If drone state is unavailable:
```json
{
  "error": "Drone state not available",
  "timestamp": 1732270245000
}
```

---

## Testing the API

### Manual Testing

#### 1. Test HTTP Endpoints

```bash
# Ping
curl http://192.168.1.100:7070/ping

# Get drone state
curl http://192.168.1.100:7070/api/v1/drone/state

# Send command
curl -X POST http://192.168.1.100:7070/api/v1/drone/commands \
  -H "Content-Type: application/json" \
  -d '{"mission_type": 10, "trigger_time": 0}'
```

#### 2. Test WebSocket (websocat tool)

```bash
# Install websocat
# macOS: brew install websocat
# Linux: cargo install websocat

# Connect to WebSocket
websocat ws://192.168.1.100:7070/ws/drone-state
```

#### 3. Interactive API Documentation

Visit `http://drone-ip:7070/docs` in browser:
- Try out all endpoints
- See request/response schemas
- Test with real drone

---

## Migration from Flask (v1.x)

### What Changed

| Feature | Flask (v1.x) | FastAPI (v2.0) |
|---------|-------------|----------------|
| Module name | `flask_handler.py` | `drone_api_server.py` |
| Class name | `FlaskHandler` | `DroneAPIServer` |
| WebSocket | ❌ Not supported | ✅ Supported |
| API docs | ❌ Manual | ✅ Auto-generated at `/docs` |
| Type validation | ❌ Manual | ✅ Pydantic models |
| Async support | ❌ No | ✅ Yes |

### What Stayed the Same

- ✅ Default port number (`7070`, configurable through `MDS_DRONE_API_PORT`)
- ✅ WebSocket route (`/ws/drone-state`)
- ✅ CORS configuration
- ✅ Core request/response payload shapes preserved while routes were canonicalized

### Backward Compatibility

The `DroneAPIServer` class includes a `FlaskHandler` alias for backward compatibility:

```python
FlaskHandler = DroneAPIServer  # Backward compatibility alias
```

---

## Performance Tuning

### WebSocket Update Rate

**Location:** `src/drone_api_server.py:473`

```python
await asyncio.sleep(1.0)  # 1 Hz (default)
```

**Recommendations:**

| Use Case | Update Rate | Sleep Value |
|----------|-------------|-------------|
| Precision flight monitoring | 10 Hz | `0.1` |
| Standard telemetry | 1 Hz | `1.0` |
| Bandwidth-constrained | 0.5 Hz | `2.0` |
| Low-priority monitoring | 0.2 Hz | `5.0` |

### Concurrent Connections

FastAPI can handle 1,000+ concurrent WebSocket connections per drone. For GCS monitoring 100 drones:
- Each drone can have 10+ simultaneous connections
- Total system capacity: 100,000+ connections

---

## Troubleshooting

### Common Issues

#### 1. Connection Refused

**Symptom:** `Connection refused` error

**Solutions:**
- Verify server is running: `ps aux | grep drone_api_server`
- Check firewall: `sudo ufw status`
- Verify port: `netstat -tulpn | grep "${MDS_DRONE_API_PORT:-7070}"`

#### 2. WebSocket Connection Drops

**Symptom:** WebSocket disconnects frequently

**Solutions:**
- Check network stability
- Increase TCP timeout
- Add reconnection logic in client
- Check drone CPU usage

#### 3. State Data Not Updating

**Symptom:** `/api/v1/drone/state` returns stale data

**Solutions:**
- Verify DroneCommunicator is running
- Check MAVLink connection
- Review coordinator.py logs

---

## Related Documentation

### Internal Docs
- [Backend Analysis Report](../../BACKEND_ANALYSIS_REPORT.md) - Complete backend architecture
- [GCS Server API](./gcs-api-server.md) - Ground Control Station API
- [Swarm Trajectory](../features/swarm-trajectory.md) - Swarm mission coordination

### Auto-Generated Docs
- **Interactive API Docs:** `http://drone-ip:7070/docs` (Swagger UI)
- **Alternative Docs:** `http://drone-ip:7070/redoc` (ReDoc)
- **OpenAPI Schema:** `http://drone-ip:7070/openapi.json`

### External Resources
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [WebSocket Protocol](https://datatracker.ietf.org/doc/html/rfc6455)
- [Pydantic Models](https://docs.pydantic.dev/)

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 2.0.0 | 2025-11-22 | ✅ Migrated to FastAPI, added WebSocket support |
| 1.x | 2024-2025 | Flask-based implementation (deprecated) |

---

## Future Enhancements

### Planned Features
- [ ] JWT authentication for secure access
- [ ] GraphQL endpoint for flexible queries
- [ ] Binary protocol option (MessagePack/Protobuf)
- [ ] Command acknowledgment via WebSocket
- [ ] Multi-stream WebSocket (telemetry + video)
- [ ] Compression support for bandwidth optimization

### Performance Goals
- Target: 5,000 req/s per drone
- Target: 10,000 concurrent WebSocket connections
- Target: Sub-1ms latency for local requests

---

## Support

**Issues:** Report at [GitHub Issues](https://github.com/alireza787b/mavsdk_drone_show/issues)

**Questions:** See `/help` in main README

---

**Last Updated:** 2026-04-04
**Maintainer:** MAVSDK Drone Show Team
**License:** Same as main project
