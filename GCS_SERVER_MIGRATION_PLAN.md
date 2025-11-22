# GCS Server FastAPI Migration - Complete Analysis & Plan

**Generated:** 2025-11-22
**Status:** Pre-Migration Analysis
**Complexity:** HIGH (60+ endpoints, 3 background services, file uploads)
**Risk Level:** MEDIUM (with proper testing)
**Estimated Time:** 2-3 weeks

---

## Executive Summary

The GCS Server is **significantly more complex** than the drone-side server:
- **60+ API endpoints** (vs 10 on drone-side)
- **3 background polling services** (telemetry, git status, heartbeat)
- **Multiple file upload/download endpoints** (ZIP, CSV, KML)
- **Complex origin/GPS calculations** with pymap3d
- **Git operations** integrated into multiple endpoints
- **Advanced logging system** (custom DisplayMode, log throttling)
- **Metrics engine integration** (optional DroneShowMetrics)

### Migration Feasibility: ✅ HIGHLY FEASIBLE

**However, requires meticulous planning due to:**
1. ⚠️ Background polling threads (need lifespan events)
2. ⚠️ Large file uploads (multipart forms - different FastAPI syntax)
3. ⚠️ Thread-safe global dictionaries (need async-safe structures)
4. ⚠️ Complex error handling (custom logging system)
5. ⚠️ Git operations (may block async)

---

## Complete Endpoint Inventory

### Category Breakdown

| Category | Endpoints | Complexity | WebSocket Candidate |
|----------|-----------|------------|-------------------|
| **Telemetry** | 1 | Low | ✅ **YES** (high frequency) |
| **Commands** | 2 | Medium | ❌ No (fire-and-forget) |
| **Configuration** | 8 | Medium-High | ❌ No (CRUD operations) |
| **Swarm Config** | 2 | Low | ❌ No (CRUD operations) |
| **Show Management** | 11 | **HIGH** | 🟡 Partial (progress updates) |
| **Origin/GPS** | 7 | Medium-High | ❌ No (calculations) |
| **GCS Config** | 2 | Low | ❌ No (CRUD operations) |
| **Git Status** | 3 | Low | ✅ **YES** (periodic updates) |
| **Network/Heartbeat** | 3 | Low | ✅ **YES** (real-time) |
| **Leader Election** | 1 | Low | ❌ No (fire-and-forget) |
| **System** | 1 | Low | ❌ No (health check) |
| **Swarm Trajectory** | 14 | **HIGH** | 🟡 Partial (progress) |
| **Static Files** | 2 | Medium | ❌ No (file serving) |

**Total: 57 endpoints** in main routes + **14 endpoints** in swarm trajectory = **71 ENDPOINTS**

---

## Detailed Endpoint Documentation

### 1. TELEMETRY ENDPOINTS (1 endpoint)

#### GET /telemetry
**Description:** Get aggregated telemetry from all drones
**Input:** None
**Output:**
```json
{
  "hw_id_1": {
    "Pos_ID": "1",
    "State": 0,
    "Mission": "IDLE",
    "Position_Lat": 47.397742,
    "Position_Long": 8.545594,
    "Position_Alt": 488.5,
    "Battery_Voltage": 12.6,
    ...
  },
  "hw_id_2": {...}
}
```
**WebSocket Candidate:** ✅ **YES - HIGH PRIORITY**
- **Reason:** Called every 1-2 seconds by dashboard
- **Benefit:** 95% less overhead, real-time push
- **Implementation:** `ws://gcs-ip:5000/ws/telemetry`

---

### 2. COMMAND ENDPOINTS (2 endpoints)

#### POST /submit_command
**Description:** Receive commands from frontend and process asynchronously
**Input:**
```json
{
  "action": "ARM",
  "triggerTime": "1732270300",
  "target_drones": ["1", "2", "3"],  // optional
  "auto_global_origin": true  // Phase 2 feature
}
```
**Output:**
```json
{
  "status": "success",
  "message": "Command received and is being processed."
}
```
**Features:**
- Async processing in separate thread
- Supports selected drones or broadcast to all
- Phase 2: Includes origin data if `auto_global_origin=true`
- Uses `send_commands_to_all()` or `send_commands_to_selected()`

**Migration Notes:**
- Convert threading to FastAPI BackgroundTasks
- Preserve async behavior

#### POST /request-new-leader
**Description:** Update leader election (from drone)
**Input:**
```json
{
  "hw_id": "5",
  "follow": "1",
  "offset_n": "5.0",
  "offset_e": "0.0",
  "offset_alt": "0.0",
  "body_coord": "1"
}
```
**Output:**
```json
{
  "status": "success",
  "message": "Leader updated for HW_ID 5"
}
```

---

### 3. CONFIGURATION ENDPOINTS (8 endpoints)

#### GET /get-config-data
**Output:** Array of drone configurations
```json
[
  {
    "hw_id": "1",
    "pos_id": "1",
    "ip": "192.168.1.101"
  }
]
```

#### POST /save-config-data
**Input:** Array of drone configurations
**Output:** Success message + optional git_info

#### POST /validate-config
**Input:** Array of drone configurations
**Output:**
```json
{
  "report": {...},
  "summary": {
    "duplicates_count": 0,
    "missing_trajectories_count": 0,
    "role_swaps_count": 0
  },
  "updated_config": [...]
}
```

#### GET /get-drone-positions
**Output:** Positions from trajectory CSVs
```json
[
  {
    "hw_id": 1,
    "pos_id": 1,
    "x": 0.0,
    "y": 5.0
  }
]
```

#### GET /get-trajectory-first-row
**Query Params:** `pos_id`
**Output:** First waypoint from trajectory CSV
```json
{
  "pos_id": 1,
  "north": 0.0,
  "east": 5.0,
  "source": "Drone 1.csv (first waypoint)"
}
```

#### GET /get-swarm-data
**Output:** Swarm configuration (leader/follower)
```json
[
  {
    "hw_id": "1",
    "follow": "0",
    "offset_n": "0",
    "offset_e": "0",
    "offset_alt": "0",
    "body_coord": "false"
  }
]
```

#### POST /save-swarm-data
**Input:** Swarm configuration array
**Output:** Success + optional git_info
**Query Params:** `commit=true` (override GIT_AUTO_PUSH)

#### GET /ping
**Output:** `{"status": "ok"}`

---

### 4. SHOW MANAGEMENT ENDPOINTS (11 endpoints)

#### POST /import-show
**Description:** Upload and process drone show ZIP file
**Content-Type:** `multipart/form-data`
**Input:** File upload (ZIP)
**Processing Steps:**
1. Clear show directories
2. Save uploaded ZIP
3. Extract to skybrush_dir
4. Call `run_formation_process()`
5. Calculate comprehensive metrics (if available)
6. Git commit/push (if enabled)
7. Verify git tracking

**Output:**
```json
{
  "success": true,
  "message": "Processing output...",
  "git_info": {...},
  "processing_stats": {
    "input_count": 10,
    "processed_count": 10,
    "validation_passed": true
  },
  "git_tracking_stats": {
    "committed_count": 10,
    "ignored_count": 0,
    "tracking_complete": true
  },
  "show_health": {
    "status": "healthy",
    "issues": []
  },
  "comprehensive_metrics": {...}  // if METRICS_AVAILABLE
}
```

**Migration Notes:**
- ⚠️ **CRITICAL:** Large file upload (FastAPI uses different syntax)
- Background processing may take time
- Git operations may block

#### GET /download-raw-show
**Output:** ZIP file of raw skybrush files

#### GET /download-processed-show
**Output:** ZIP file of processed trajectories

#### GET /get-show-info
**Output:**
```json
{
  "drone_count": 10,
  "duration_ms": 180000,
  "duration_minutes": 3.0,
  "duration_seconds": 0.0,
  "max_altitude": 50.0
}
```

#### GET /get-comprehensive-metrics
**Output:** Detailed trajectory analysis (if METRICS_AVAILABLE)
```json
{
  "spatial_metrics": {...},
  "temporal_metrics": {...},
  "safety_metrics": {...},
  "performance_metrics": {...},
  "formation_metrics": {...}
}
```

#### GET /get-safety-report
**Output:** Safety analysis with recommendations

#### POST /validate-trajectory
**Output:** Validation status (PASS/WARNING/FAIL)

#### POST /deploy-show
**Input:** `{message: "..."}`
**Output:** Git deployment result

#### GET /get-show-plots
**Output:** List of plot images
```json
{
  "filenames": ["combined_drone_paths.jpg", ...],
  "uploadTime": "..."
}
```

#### GET /get-show-plots/<filename>
**Output:** Image file (JPEG)

#### GET /get-custom-show-image
**Output:** PNG file (trajectory_plot.png)

---

### 5. ORIGIN/GPS ENDPOINTS (7 endpoints)

#### POST /set-origin
**Input:**
```json
{
  "lat": 47.397742,
  "lon": 8.545594,
  "alt": 488.0,  // optional
  "alt_source": "manual"  // "manual" | "drone" | "elevation_api"
}
```
**Output:** Success with saved data

#### GET /get-origin
**Output:** Origin with v2 schema (includes altitude)
```json
{
  "lat": 47.397742,
  "lon": 8.545594,
  "alt": 488.0,
  "alt_source": "manual",
  "timestamp": "2025-11-22T10:30:00",
  "version": 2
}
```

#### GET /get-origin-for-drone
**Output:** Lightweight origin for drone pre-flight
```json
{
  "lat": 47.397742,
  "lon": 8.545594,
  "alt": 488.0,
  "timestamp": "2025-11-22T10:30:00",
  "source": "manual"
}
```

#### GET /get-position-deviations
**Output:** Comprehensive deviation analysis
```json
{
  "status": "success",
  "origin": {...},
  "deviations": {
    "1": {
      "hw_id": "1",
      "pos_id": 1,
      "expected": {
        "lat": 47.397742,
        "lon": 8.545594,
        "north": 0.0,
        "east": 5.0
      },
      "current": {
        "lat": 47.397750,
        "lon": 8.545600,
        "gps_quality": "excellent",
        "satellites": 12,
        "hdop": 0.8
      },
      "deviation": {
        "north": 0.5,
        "east": -0.3,
        "horizontal": 0.58,
        "within_threshold": true
      },
      "status": "ok",
      "message": "Position within acceptable range"
    }
  },
  "summary": {
    "total_drones": 10,
    "online": 8,
    "within_threshold": 7,
    "warnings": 1,
    "errors": 0,
    "average_deviation": 0.45
  }
}
```

#### POST /compute-origin
**Input:**
```json
{
  "current_lat": 47.397742,
  "current_lon": 8.545594,
  "intended_east": 5.0,
  "intended_north": 0.0
}
```
**Output:** Computed origin coordinates

#### GET /get-desired-launch-positions
**Query Params:** `heading=90`, `format=json`
**Output:** GPS coordinates for all drones' launch positions
```json
{
  "status": "success",
  "origin": {...},
  "drones": [
    {
      "hw_id": "1",
      "pos_id": 1,
      "config_north": 0.0,
      "config_east": 5.0,
      "launch_lat": 47.397742,
      "launch_lon": 8.545650,
      "distance_from_origin": 5.0,
      "bearing_from_origin": 90.0
    }
  ],
  "metadata": {
    "total_drones": 10,
    "formation_extent": {...},
    "timestamp": "..."
  }
}
```

#### GET /elevation
**Query Params:** `lat`, `lon`
**Output:** Elevation data from external API

---

### 6. GCS CONFIGURATION ENDPOINTS (2 endpoints)

#### GET /get-gcs-config
**Output:**
```json
{
  "status": "success",
  "data": {
    "gcs_ip": "100.96.32.75",
    "gcs_flask_port": 5000,
    "git_auto_push": true,
    "git_branch": "main-candidate",
    "simulation_mode": false
  }
}
```

#### POST /save-gcs-config
**Input:** `{gcs_ip: "...", update_env_file: true}`
**Output:** Success with warnings about required restarts
**Features:**
- Updates params.py file
- Optionally updates dashboard .env
- Git commit/push if enabled
- Returns warnings about service restarts

---

### 7. GIT STATUS ENDPOINTS (3 endpoints)

#### GET /get-gcs-git-status
**Output:** GCS git status
```json
{
  "branch": "main-candidate",
  "commit": "abc123...",
  "status": "clean",
  ...
}
```

#### GET /get-drone-git-status/<drone_id>
**Output:** Specific drone git status

#### GET /git-status
**Output:** Consolidated git status for all drones
```json
{
  "1": {
    "branch": "main-candidate",
    "commit": "abc123...",
    "status": "clean"
  },
  "2": {...}
}
```

**WebSocket Candidate:** ✅ **YES - MEDIUM PRIORITY**
- **Reason:** Periodically updated, useful for real-time sync status
- **Implementation:** `ws://gcs-ip:5000/ws/git-status`

---

### 8. NETWORK/HEARTBEAT ENDPOINTS (3 endpoints)

#### GET /get-network-info
**Output:** Network info from heartbeats
```json
[
  {
    "hw_id": "1",
    "wifi": {
      "ssid": "DroneNet",
      "signal_strength_percent": 85
    },
    "ethernet": {
      "interface": "eth0",
      "connection_name": "Wired"
    }
  }
]
```

#### POST /drone-heartbeat
**Input:** Heartbeat data from drone
```json
{
  "hw_id": "1",
  "pos_id": 1,
  "ip": "192.168.1.101",
  "timestamp": 1732270245000,
  "network_info": {
    "wifi": {...},
    "ethernet": {...}
  }
}
```
**Output:** `{"message": "Heartbeat received"}`

#### GET /get-heartbeats
**Output:** All heartbeats
```json
{
  "1": {
    "hw_id": "1",
    "timestamp": 1732270245000,
    "network_info": {...}
  }
}
```

**WebSocket Candidate:** ✅ **YES - LOW PRIORITY**
- **Reason:** Real-time heartbeat updates
- **Benefit:** Instant offline detection
- **Implementation:** `ws://gcs-ip:5000/ws/heartbeats`

---

### 9. SWARM TRAJECTORY ENDPOINTS (14 endpoints)

#### GET /api/swarm/leaders
**Output:** List of top leaders from swarm config
```json
{
  "success": true,
  "leaders": [1, 5, 10],
  "hierarchies": {
    "1": 4,  // leader 1 has 4 followers
    "5": 3,
    "10": 2
  },
  "follower_details": {
    "1": [2, 3, 4, 5],
    ...
  },
  "uploaded_leaders": [1, 5]
}
```

#### POST /api/swarm/trajectory/upload/<leader_id>
**Content-Type:** `multipart/form-data`
**Input:** CSV file
**Output:** Success with filepath

#### POST /api/swarm/trajectory/process
**Input:**
```json
{
  "force_clear": false,
  "auto_reload": true
}
```
**Output:** Processing result with stats

**WebSocket Candidate:** 🟡 **PROGRESS UPDATES**
- **Use Case:** Real-time processing progress
- **Implementation:** Send progress % during processing

#### GET /api/swarm/trajectory/recommendation
**Output:** Smart processing recommendation

#### POST /api/swarm/trajectory/clear-processed
**Output:** Cleared files confirmation

#### GET /api/swarm/trajectory/status
**Output:** Current processing status
```json
{
  "success": true,
  "status": {
    "raw_trajectories": 3,
    "processed_trajectories": 9,
    "generated_plots": 9,
    "processed_drones": [1, 2, 3, ...],
    "processed_leaders": [1, 5, 10],
    "processed_followers": [2, 3, 4, ...],
    "has_results": true
  }
}
```

#### POST /api/swarm/trajectory/clear
**Output:** All cleared directories

#### POST /api/swarm/trajectory/clear-leader/<leader_id>
**Output:** Cleared leader and followers

#### DELETE /api/swarm/trajectory/remove/<leader_id>
**Output:** Removed files list

#### GET /api/swarm/trajectory/download/<drone_id>
**Output:** CSV file download

#### GET /api/swarm/trajectory/download-kml/<drone_id>
**Output:** KML file (generated on-demand)

#### GET /api/swarm/trajectory/download-cluster-kml/<leader_id>
**Output:** Cluster KML with all drones

#### POST /api/swarm/trajectory/clear-drone/<drone_id>
**Output:** Cleared individual drone

#### POST /api/swarm/trajectory/commit
**Input:** `{message: "..."}`
**Output:** Git commit result

---

### 10. STATIC FILE SERVING (2 endpoints)

#### GET /static/plots/<filename>
**Output:** Plot image files

---

## Background Services Analysis

### 1. Telemetry Polling (`telemetry.py`)

**Current Implementation:**
- One thread per drone
- Polling interval: 1 second
- Thread-safe dictionary with locks
- Professional logging with throttling
- Stale data purging
- Success/failure statistics

**FastAPI Migration:**
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    tasks = []
    for drone in drones:
        task = asyncio.create_task(poll_telemetry_async(drone))
        tasks.append(task)

    yield  # Server running

    # Shutdown
    for task in tasks:
        task.cancel()
```

**Data Structure Migration:**
- Replace `threading.Lock()` with `asyncio.Lock()`
- Keep global dictionary (FastAPI can use Starlette state)

---

### 2. Git Status Polling (`git_status.py`)

**Current Implementation:**
- One thread per drone
- Polling interval: Configurable
- Thread-safe dictionary
- Tracks branch, commit, status

**FastAPI Migration:** Same as telemetry (use lifespan events)

---

### 3. Heartbeat System (`heartbeat.py`)

**Current Implementation:**
- Receives POST /drone-heartbeat from drones
- Stores in-memory with thread locks
- Provides GET /get-heartbeats

**FastAPI Migration:**
- Keep existing logic (no background thread)
- Just replace Flask routes with FastAPI

---

## WebSocket Recommendations

### ✅ HIGH PRIORITY WebSockets

1. **GET /telemetry → WS /ws/telemetry**
   - **Benefit:** 95% less overhead
   - **Frequency:** Every 1-2 seconds
   - **Payload:** All drone telemetry
   - **Impact:** Huge performance improvement

### ✅ MEDIUM PRIORITY WebSockets

2. **GET /git-status → WS /ws/git-status**
   - **Benefit:** Real-time sync monitoring
   - **Frequency:** Every 10-30 seconds
   - **Payload:** Git status for all drones

### ✅ LOW PRIORITY WebSockets

3. **GET /get-heartbeats → WS /ws/heartbeats**
   - **Benefit:** Instant offline detection
   - **Frequency:** Every 10 seconds
   - **Payload:** Heartbeat data

### 🟡 PROGRESS UPDATES (New Feature)

4. **WS /ws/show-processing**
   - **Use Case:** Real-time show upload/processing progress
   - **Frequency:** During upload/processing only
   - **Payload:** Progress percentage, status messages

---

## Migration Strategy

### Phase 1: Preparation (Week 1)
- [ ] Create comprehensive test suite for Flask endpoints
- [ ] Set up FastAPI project structure
- [ ] Create all Pydantic models
- [ ] Test file upload with FastAPI

### Phase 2: Core Endpoints (Week 2)
- [ ] Migrate simple GET endpoints (config, swarm, git, ping)
- [ ] Migrate POST endpoints (commands, config save)
- [ ] Migrate origin/GPS endpoints
- [ ] Test all migrated endpoints

### Phase 3: Complex Features (Week 3)
- [ ] Migrate show management endpoints (file uploads!)
- [ ] Migrate swarm trajectory endpoints
- [ ] Convert background services to lifespan events
- [ ] Add WebSocket endpoints (telemetry, git-status)

### Phase 4: Testing (Week 4)
- [ ] Integration testing with real dashboard
- [ ] SITL testing
- [ ] Performance benchmarking
- [ ] Parallel deployment (Flask + FastAPI)

### Phase 5: Deployment
- [ ] Switch dashboard to FastAPI endpoints
- [ ] Monitor for 1 week
- [ ] Deprecate Flask

---

## Critical Migration Points

### ⚠️ File Uploads

**Flask:**
```python
file = request.files.get('file')
file.save(filepath)
```

**FastAPI:**
```python
from fastapi import UploadFile, File

@app.post("/import-show")
async def import_show(file: UploadFile = File(...)):
    contents = await file.read()
    with open(filepath, 'wb') as f:
        f.write(contents)
```

### ⚠️ Background Processing

**Flask (threading):**
```python
thread = threading.Thread(target=process_command_async, args=(drones, command_data))
thread.start()
```

**FastAPI (BackgroundTasks):**
```python
from fastapi import BackgroundTasks

@app.post("/submit_command")
async def submit_command(
    command: CommandRequest,
    background_tasks: BackgroundTasks
):
    background_tasks.add_task(process_command_async, drones, command.dict())
    return {"status": "success"}
```

### ⚠️ Thread-Safe Dictionaries

**Current:**
```python
from threading import Lock

data_lock = Lock()

with data_lock:
    telemetry_data = telemetry_data_all_drones.copy()
```

**FastAPI:**
```python
import asyncio

data_lock = asyncio.Lock()

async with data_lock:
    telemetry_data = telemetry_data_all_drones.copy()
```

---

## Testing Strategy

### Unit Tests (pytest)

```python
@pytest.mark.asyncio
async def test_get_telemetry(test_client):
    response = await test_client.get("/telemetry")
    assert response.status_code == 200
    assert isinstance(response.json(), dict)

@pytest.mark.asyncio
async def test_import_show(test_client):
    files = {'file': ('test.zip', zip_content, 'application/zip')}
    response = await test_client.post("/import-show", files=files)
    assert response.status_code == 200
    assert response.json()['success'] is True
```

### WebSocket Tests

```python
@pytest.mark.asyncio
async def test_websocket_telemetry(test_client):
    async with test_client.websocket_connect("/ws/telemetry") as websocket:
        data = await websocket.receive_json()
        assert isinstance(data, dict)
        assert len(data) > 0  # Has drone data
```

---

## Risk Mitigation

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| File upload breaks | High | Low | Test with various ZIP sizes |
| Background tasks fail | High | Medium | Thorough async conversion |
| WebSocket connection drops | Medium | Medium | Auto-reconnect in dashboard |
| Git operations block | Medium | Medium | Use asyncio.subprocess |
| Performance regression | Medium | Low | Benchmarking, load testing |
| Data race conditions | High | Medium | Replace locks with async locks |

---

## Estimated Timeline

**Total: 3-4 weeks**

- Week 1: Preparation, testing setup, Pydantic models
- Week 2: Core endpoints migration
- Week 3: Complex features (file uploads, background services, WebSockets)
- Week 4: Testing, parallel deployment, monitoring

---

## Success Criteria

✅ All 71 endpoints migrated
✅ 100% API compatibility maintained
✅ WebSocket telemetry working
✅ File uploads/downloads working
✅ Background polling working
✅ All tests passing
✅ Dashboard requires ZERO changes
✅ Performance improved 4-10x

---

**Next Steps:** Review this plan, approve, and begin Phase 1!
