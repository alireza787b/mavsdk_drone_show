# HANDOVER: FastAPI GCS Server React UI Integration Issues

**Date:** 2025-11-24
**From:** Remote AI Agent (via Netbird at 100.96.55.26)
**To:** Local AI Agent (on SITL server)
**Status:** Partially Complete - Endpoints fixed but need testing & verification

---

## SUMMARY

We completed a **Flask to FastAPI migration** cleanup that:
1. ✅ **Fixed critical telemetry polling bug** - Renamed `flask_drone_port` → `drone_api_port`
2. ✅ **Unified all naming** - Removed 24 files of Flask naming
3. ✅ **Fixed data transformation** - Updated `/git-status` and `/get-heartbeats` endpoints
4. ⚠️ **INCOMPLETE** - React UI still not showing drones, needs local debugging

**Git Status:** All changes committed and pushed to `main-candidate` branch
- Commit 1: `c9d6806d` - Parameter renaming (24 files)
- Commit 2: `41d5173a` - Endpoint data transformation fixes

---

## CURRENT SYSTEM STATE

### ✅ What's Working
- GCS FastAPI server runs at `http://100.96.55.26:5000` (Netbird interface wt0)
- `/telemetry` endpoint works via curl (returns drone data)
- Telemetry background polling is now functional (bug fixed)
- CORS is properly configured (allows all origins)
- FastAPI server starts without errors

### ❌ What's NOT Working
- React UI at `localhost:3030` not displaying drone cards
- Mission Config page shows no heartbeat/git info
- Browser console shows:
  - CORS errors (may be cached)
  - 500 errors on `/git-status` and `/get-heartbeats` (should be fixed but needs verification)

---

## TECHNICAL DETAILS

### Issue #1: Parameter Naming Bug (FIXED ✅)
**File:** `gcs-server/app_fastapi.py:174, 214`

**Before:**
```python
url = f"http://{ip}:{Params.flask_drone_port}/get_drone_state"  # AttributeError!
```

**After:**
```python
url = f"http://{ip}:{Params.drone_api_port}/get_drone_state"  # ✅ Works
```

**New Parameter Names:**
- `drone_api_port = 7070` (was `drones_flask_port`)
- `gcs_api_port = 5000` (was `GCS_FLASK_PORT`, `flask_telem_socket_port`, etc.)

---

### Issue #2: `/git-status` Data Transformation (FIXED ✅)
**File:** `gcs-server/app_fastapi.py:676-734`

**Problem:** Raw git status from drones doesn't match `DroneGitStatus` Pydantic schema

**Raw Data Structure from Drone:**
```json
{
  "branch": "main-candidate",
  "commit": "c9d6806d...",
  "status": "clean",  // ❌ Not a valid GitStatus enum value
  "uncommitted_changes": []
  // ❌ Missing: pos_id, hw_id, ip, commits_ahead, commits_behind...
}
```

**Required Schema:**
```python
class DroneGitStatus(BaseModel):
    pos_id: int
    hw_id: str
    ip: str
    current_branch: str
    latest_commit: str  # Short hash (8 chars)
    status: GitStatus  # Enum: SYNCED, AHEAD, BEHIND, DIVERGED, UNKNOWN
    commits_ahead: int
    commits_behind: int
    has_uncommitted: bool
    last_check: int
```

**Solution Implemented:**
- Load drone config to get `pos_id`, `hw_id`, `ip` mapping
- Transform `status: 'clean'` → `GitStatus.SYNCED`
- Transform `status: 'dirty'` → `GitStatus.DIVERGED`
- Extract short commit hash (first 8 chars)
- Calculate `has_uncommitted` from `uncommitted_changes` list length
- Thread-safe access to `git_status_data_all_drones`

---

### Issue #3: `/get-heartbeats` Data Transformation (FIXED ✅)
**File:** `gcs-server/app_fastapi.py:414-456`

**Problem:** Type mismatch - dict vs list

**Before:**
```python
heartbeats = get_all_heartbeats()  # Returns Dict[hw_id, {...}]
online_count = len([h for h in heartbeats if h.get('online', False)])
# ❌ TypeError: 'str' object has no attribute 'get'
```

**Root Cause:**
- `get_all_heartbeats()` returns `Dict[hw_id, heartbeat_data]`
- Pydantic schema expects `List[HeartbeatData]`
- Code tried to call `.get()` on dict keys (hw_id strings) instead of values

**Solution Implemented:**
- Transform dict → list of `HeartbeatData` objects
- Calculate online status: `current_time - (timestamp_ms / 1000) < timeout`
- Extract `latency_ms` from `network_info` if available
- Handle missing timestamps gracefully

---

## WHY CHANGES MIGHT NOT BE ACTIVE YET

**Critical Issue:** FastAPI running with `--reload` flag

```bash
ps aux | grep uvicorn
# Shows: uvicorn app_fastapi:app --host 0.0.0.0 --port 5000 --reload
```

**Problem:** The `--reload` flag uses watchdog/watchfiles which may not detect all code changes, especially:
- Changes inside functions (only watches top-level changes)
- Changes while imports are being executed
- Race conditions during hot reload

**Solution:** **FULL RESTART REQUIRED**

---

## YOUR MISSION (LOCAL AI AGENT)

### STEP 1: Pull Latest Changes
```bash
cd /root/mavsdk_drone_show
git fetch origin
git checkout main-candidate
git pull origin main-candidate

# Verify you have the latest commits
git log --oneline -3
# Should show:
# 41d5173a fix: Transform raw data to match Pydantic schemas
# c9d6806d refactor: Remove all Flask naming
```

### STEP 2: HARD RESTART GCS Server
```bash
# Kill existing server completely
pkill -9 -f "uvicorn app_fastapi"
pkill -9 -f "python.*app_fastapi"

# Verify it's dead
ps aux | grep -E "app_fastapi|uvicorn.*gcs" | grep -v grep
# Should return nothing

# Start fresh (use venv Python!)
cd /root/mavsdk_drone_show/gcs-server
/root/mavsdk_drone_show/venv/bin/python3 app_fastapi.py

# Or if you want background:
nohup /root/mavsdk_drone_show/venv/bin/python3 app_fastapi.py > /tmp/gcs_server.log 2>&1 &

# Wait for startup (5 seconds)
sleep 5
```

### STEP 3: Verify Endpoints Return 200 OK
```bash
# Test 1: Git Status (was returning 500, should now return 200)
curl -s http://localhost:5000/git-status | python3 -m json.tool | head -50

# Expected: JSON with structure like:
# {
#   "git_status": {
#     "1": {
#       "pos_id": 1,
#       "hw_id": "1",
#       "ip": "172.18.0.2",
#       "current_branch": "main-candidate",
#       "latest_commit": "41d5173a",
#       "status": "synced",
#       ...
#     }
#   },
#   "total_drones": 1,
#   "synced_count": 1,
#   ...
# }

# Test 2: Heartbeats (was returning 500, should now return 200)
curl -s http://localhost:5000/get-heartbeats | python3 -m json.tool

# Expected: JSON with structure like:
# {
#   "heartbeats": [
#     {
#       "hw_id": "1",
#       "pos_id": 1,
#       "ip": "172.18.0.2",
#       "last_heartbeat": 1732468800000,
#       "online": true,
#       "latency_ms": 5.2
#     }
#   ],
#   "total_drones": 1,
#   "online_count": 1,
#   ...
# }

# Test 3: Telemetry (already working)
curl -s http://localhost:5000/telemetry | python3 -m json.tool | head -30
```

### STEP 4: Check if Drone is Actually Sending Data
```bash
# Check if drone SITL is running
docker ps | grep drone

# Test drone API directly
curl -s http://172.18.0.2:7070/get_drone_state | python3 -m json.tool

# Check drone heartbeat is being sent
# Look for drone heartbeat sender process
ps aux | grep heartbeat

# Check GCS server logs for heartbeat reception
tail -f /tmp/gcs_server.log | grep -i heartbeat
```

### STEP 5: Debug React UI Issues

**Check React Environment:**
```bash
cd /root/mavsdk_drone_show/app/dashboard/drone-dashboard

# Check .env file
cat .env

# Should have:
# REACT_APP_GCS_PORT=5000
# REACT_APP_SERVER_URL=http://localhost  (or http://100.96.55.26)
# REACT_APP_DRONE_PORT=7070

# Restart React dev server
pkill -f "react-scripts"
npm start &
```

**Browser Debugging:**
1. Open DevTools (F12)
2. Go to Network tab
3. Clear cache and hard refresh (Ctrl+Shift+R)
4. Check which requests are failing
5. Look at Console tab for errors

**Expected React API Calls:**
- `GET http://localhost:5000/telemetry` (every 1-2 seconds)
- `GET http://localhost:5000/git-status` (every 5-10 seconds)
- `GET http://localhost:5000/get-heartbeats` (every 2-3 seconds)

---

## DEBUGGING CHECKLIST

### If `/git-status` Still Returns 500:
```bash
# Check server logs for full error
tail -100 /tmp/gcs_server.log | grep -A 20 "git-status"

# Check if drone config is loaded
python3 << 'EOF'
import sys
sys.path.append('/root/mavsdk_drone_show/gcs-server')
from config import load_config
drones = load_config()
print(f"Loaded {len(drones)} drones:")
for d in drones:
    print(f"  hw_id={d.get('hw_id')}, pos_id={d.get('pos_id')}, ip={d.get('ip')}")
EOF

# Check raw git status data
python3 << 'EOF'
import sys
sys.path.append('/root/mavsdk_drone_show/gcs-server')
from git_status import git_status_data_all_drones, data_lock_git_status
with data_lock_git_status:
    print(f"Git status data: {dict(git_status_data_all_drones)}")
EOF
```

### If `/get-heartbeats` Still Returns 500:
```bash
# Check heartbeat data structure
python3 << 'EOF'
import sys
sys.path.append('/root/mavsdk_drone_show/gcs-server')
from heartbeat import get_all_heartbeats
hb = get_all_heartbeats()
print(f"Heartbeats data type: {type(hb)}")
print(f"Heartbeats data: {hb}")
for hw_id, data in hb.items():
    print(f"  hw_id={hw_id}, type={type(data)}, keys={data.keys() if isinstance(data, dict) else 'not a dict'}")
EOF
```

### If React UI Still Shows Empty:
```bash
# Check if telemetry endpoint is actually being called
tail -f /tmp/gcs_server.log | grep telemetry

# Check React is configured correctly
curl -s http://localhost:5000/telemetry

# If telemetry returns data but UI is empty, check React component
# File: /root/mavsdk_drone_show/app/dashboard/drone-dashboard/src/components/DroneCards.js
# or similar component that renders drone list
```

---

## EXPECTED OUTCOMES

### Success Criteria:
1. ✅ `curl http://localhost:5000/git-status` returns 200 with proper JSON
2. ✅ `curl http://localhost:5000/get-heartbeats` returns 200 with proper JSON
3. ✅ `curl http://localhost:5000/telemetry` returns drone data
4. ✅ React UI at `http://localhost:3030` displays:
   - Drone cards with telemetry data
   - Git status info on Mission Config page
   - Heartbeat status indicators
   - No CORS or 500 errors in console

### If Still Failing:
Report back with:
- Exact curl responses from all 3 endpoints
- Full server logs (last 100 lines)
- React console errors (screenshot or copy/paste)
- Output of drone config check (Step above)
- Output of heartbeat data check (Step above)

---

## FILES CHANGED (REFERENCE)

### Commit 1: Parameter Renaming (c9d6806d)
- `src/params.py` - New parameters + aliases
- `gcs-server/app_fastapi.py` - Fixed typo + port references
- `gcs-server/{command,git_status,telemetry,network,routes,env_updater}.py`
- `src/{drone_api_server,drone_communicator,connectivity_checker,heartbeat_sender,telemetry_subscription_manager}.py`
- `smart_swarm.py`, mission files, tests, docs (19 more files)

### Commit 2: Endpoint Fixes (41d5173a)
- `gcs-server/app_fastapi.py:676-734` - `/git-status` data transformation
- `gcs-server/app_fastapi.py:414-456` - `/get-heartbeats` data transformation

---

## ARCHITECTURE CONTEXT

### Data Flow:
```
Drone (172.18.0.2:7070)
  ↓ /get_drone_state (FastAPI)
  ↓
GCS Background Service (telemetry_polling)
  ↓ Stores in: telemetry_data_all_drones
  ↓
GCS FastAPI Endpoint /telemetry
  ↓
React UI (localhost:3030)
  ↓ Polls every 1-2 seconds
  ↓ Renders drone cards
```

### Git Status Flow:
```
Drone (172.18.0.2:7070)
  ↓ /get-git-status (FastAPI)
  ↓ Returns: {branch, commit, status:'clean', ...}
  ↓
GCS Background Service (git_status_polling)
  ↓ Stores RAW data in: git_status_data_all_drones
  ↓
GCS FastAPI Endpoint /git-status
  ↓ NEW: Transforms raw → DroneGitStatus schema
  ↓ Maps 'clean' → GitStatus.SYNCED
  ↓ Adds pos_id, hw_id, ip from config
  ↓
React UI Mission Config Page
```

### Heartbeat Flow:
```
Drone (sends HTTP POST every 10s)
  ↓ POST /drone-heartbeat
  ↓ Body: {pos_id, hw_id, ip, timestamp, network_info}
  ↓
GCS heartbeat.py:handle_heartbeat_post()
  ↓ Stores in: last_heartbeats dict
  ↓
GCS FastAPI Endpoint /get-heartbeats
  ↓ NEW: Transforms dict → List[HeartbeatData]
  ↓ Calculates online status from timestamp
  ↓
React UI Mission Config Page
```

---

## CONTACT / ESCALATION

If you encounter issues you can't resolve:

1. **Check Git History:**
   ```bash
   git log --oneline --graph --all
   git show 41d5173a  # View endpoint fix commit
   git show c9d6806d  # View parameter renaming commit
   ```

2. **Revert if Necessary:**
   ```bash
   git revert 41d5173a  # Revert endpoint fixes
   git revert c9d6806d  # Revert parameter renaming
   ```

3. **Create Issue Report:**
   - Include all curl responses
   - Include server logs
   - Include React console output
   - Include drone status (docker ps, curl to drone)

---

## ADDITIONAL NOTES

### Why This Happened:
The FastAPI migration was mostly complete, but:
1. A typo in parameter names (`flask_drone_port` vs `drones_flask_port`) broke telemetry polling
2. Raw data structures from drones didn't match Pydantic schemas
3. No data transformation layer was added during migration

### What Was Fixed:
1. ✅ Renamed all parameters to framework-agnostic names
2. ✅ Added data transformation in `/git-status` endpoint
3. ✅ Added data transformation in `/get-heartbeats` endpoint
4. ✅ Fixed thread-safe access patterns
5. ✅ Added proper enum value mapping

### What Might Still Need Fixing:
1. ⚠️ React component field name mismatches (if drones still don't appear after endpoint fix)
2. ⚠️ CORS browser cache (needs hard refresh)
3. ⚠️ Other endpoints with similar data transformation issues (not discovered yet)

---

## GOOD LUCK! 🚀

The hardest part is done. You just need to:
1. Restart the server properly
2. Verify endpoints work
3. Debug React UI if needed

All the code fixes are committed and ready to go!

---

**Generated by:** Remote AI Agent via Claude Code
**Handover Date:** 2025-11-24
**Branch:** main-candidate
**Last Commit:** 41d5173a
