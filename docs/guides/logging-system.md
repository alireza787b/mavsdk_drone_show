# Unified Logging System Guide

> **Package:** `mds_logging/` at repo root
> **Python:** 3.8+ (uses `from __future__ import annotations`)
> **Format:** JSONL (file) + colored text (console)

## Architecture

All MDS components share a single logging contract via the `mds_logging` package:

```
mds_logging/
  __init__.py     # Public API: get_logger(), set_session(), set_source()
  schema.py       # JSONL field definitions and validation
  constants.py    # Environment variable config (MDS_LOG_* prefix)
  formatter.py    # JSONLFormatter (file) + ConsoleFormatter (terminal)
  session.py      # Session lifecycle: create, list, cleanup
  handlers.py     # SessionFileHandler + WatcherHandler
  watcher.py      # In-memory pub/sub for SSE streaming
  registry.py     # Component self-registration
  cli.py          # Shared CLI flags (--verbose, --debug, --quiet, etc.)
  drone.py        # init_drone_logging() — drone-side init
  server.py       # init_server_logging() — GCS server init
```

## Quick Start

### Drone-side component

```python
from mds_logging.drone import init_drone_logging
from mds_logging import get_logger, register_component

register_component("my_component", "drone", "What this component does")
init_drone_logging(drone_id=5)
logger = get_logger("my_component")

logger.info("System ready")
logger.warning("Low battery", extra={"mds_extra": {"voltage": 11.2}})
```

### GCS server component

```python
from mds_logging.server import init_server_logging
from mds_logging import get_logger, register_component

register_component("my_api", "gcs", "REST API endpoints")
init_server_logging()
logger = get_logger("my_api")

logger.info("Server started on port 5000")
```

### Module that doesn't own initialization

```python
from mds_logging import get_logger

logger = get_logger("my_module")
logger.debug("Processing data")
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MDS_LOG_LEVEL` | `INFO` | Console log level (DEBUG, INFO, WARNING, ERROR, CRITICAL) |
| `MDS_LOG_FILE_LEVEL` | `DEBUG` | File log level |
| `MDS_LOG_MAX_SESSIONS` | `10` | Max session files to keep per device |
| `MDS_LOG_MAX_SIZE_MB` | `100` | Max total log size in MB per device |
| `MDS_LOG_DIR` | `logs/sessions` | Session log directory |
| `MDS_LOG_CONSOLE_FORMAT` | `text` | Console format: `text` (colored) or `json` |
| `MDS_LOG_FLUSH` | `true` | Flush file handler after every line |

Launcher defaults:
- Dashboard/GCS launchers default console logging to `INFO` in both development and production.
- Dashboard/GCS launchers set that console level through `MDS_GCS_CONSOLE_LOG_LEVEL`, so inherited shell state does not silently change first-run/operator behavior.
- If you want deeper live GCS console traces, set `MDS_GCS_CONSOLE_LOG_LEVEL=DEBUG` before launch.
- SITL drone containers default console logging to `INFO`, or `DEBUG` when started with `startup_sitl.sh --verbose`.
- File/session logging stays at `DEBUG` by default in all modes so historical analysis still has full detail.

### Deprecated (still supported via shim)

| Old Variable | Maps To |
|-------------|---------|
| `DRONE_LOG_LEVEL` | `MDS_LOG_LEVEL` |
| `DRONE_LOG_FILE` | `MDS_LOG_DIR` |

## CLI Flags

Add to any argparse-based script:

```python
from mds_logging.cli import add_log_arguments, apply_log_args

parser = argparse.ArgumentParser()
add_log_arguments(parser)
args = parser.parse_args()
apply_log_args(args)
```

Available flags:
- `--verbose` / `--debug` — Set console level to DEBUG
- `--quiet` — Set console level to WARNING
- `--log-dir PATH` — Override log directory
- `--log-json` — Output JSON to console instead of colored text

## Session Management

Sessions are named `s_YYYYMMDD_HHMMSS` and stored as `.jsonl` files.

```python
from mds_logging.session import create_session, list_sessions, cleanup_sessions

# Create a new session
session_id = create_session("logs/sessions")  # Returns "s_20260319_140000"

# List sessions (newest first)
sessions = list_sessions("logs/sessions")
# [{"session_id": "s_20260319_140000", "size_bytes": 1024, "modified": 1742...}, ...]

# Cleanup old sessions (hybrid: count + size)
cleanup_sessions("logs/sessions", max_sessions=10, max_size_mb=100)
```

## JSONL Schema

Every log line follows this schema:

```json
{
  "ts": "2026-03-19T14:00:00.123Z",
  "level": "INFO",
  "component": "coordinator",
  "source": "drone",
  "drone_id": 5,
  "session_id": "s_20260319_140000",
  "msg": "Armed successfully",
  "extra": {"mode": "OFFBOARD", "battery": 12.4}
}
```

| Field | Type | Description |
|-------|------|-------------|
| `ts` | string | ISO 8601 UTC timestamp with milliseconds |
| `level` | string | DEBUG, INFO, WARNING, ERROR, CRITICAL |
| `component` | string | Logical component name |
| `source` | string | drone, gcs, frontend, infra |
| `drone_id` | int/null | Drone identifier (null for GCS) |
| `session_id` | string | Current session ID |
| `msg` | string | Human-readable message |
| `extra` | object/null | Structured metadata |

## Console Output

Colored text format for terminals:

```
14:00:00.123 INFO  [coordinator] Armed successfully (mode=OFFBOARD)
14:00:00.456 ERROR [telemetry] Connection lost (drone_id=5)
```

## Component Registry

Components self-register at startup for auto-discovery:

```python
from mds_logging import register_component, get_registry

register_component("coordinator", "drone", "System initialization")
register_component("api", "gcs", "FastAPI server")

# GCS exposes this via GET /api/logs/sources
registry = get_registry()
```

## Log API Endpoints

### Drone-Side Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/logs/sessions` | GET | List available log sessions |
| `/api/logs/sessions/{session_id}` | GET | Retrieve session JSONL (supports `?level=`, `?component=`, `?limit=`, `?offset=`) |
| `/api/logs/stream` | GET (SSE) | Real-time log stream via Server-Sent Events |

### GCS-Side Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/logs/sources` | GET | List registered log components |
| `/api/logs/sessions` | GET | List GCS sessions |
| `/api/logs/sessions/{session_id}` | GET | Retrieve GCS session content |
| `/api/logs/stream` | GET (SSE) | Real-time GCS log stream via SSE |
| `/api/logs/drone/{drone_id}/sessions` | GET | List sessions on a drone (proxied) |
| `/api/logs/drone/{drone_id}/sessions/{session_id}` | GET | Retrieve drone session content (proxied) |
| `/api/logs/drone/{drone_id}/stream` | GET (SSE) | Proxy real-time drone log stream |
| `/api/logs/drone/{drone_id}/ulog/policy` | GET | Onboard ULog maintenance policy and capability summary |
| `/api/logs/drone/{drone_id}/ulog/files` | GET | List file-backed onboard PX4 ULogs |
| `/api/logs/drone/{drone_id}/ulog/files/{log_id}/download` | POST | Create a staged browser-download job for one onboard ULog |
| `/api/logs/drone/{drone_id}/ulog/downloads/{job_id}` | GET | Poll staged onboard-ULog download job state |
| `/api/logs/drone/{drone_id}/ulog/downloads/{job_id}` | DELETE | Drop a staged onboard-ULog download job |
| `/api/logs/drone/{drone_id}/ulog/downloads/{job_id}/content` | GET | Stream staged onboard-ULog content to the browser |
| `/api/logs/drone/{drone_id}/ulog/erase-all` | POST | Erase all file-backed onboard PX4 ULogs on the target drone |
| `/api/logs/frontend` | POST | Receive frontend error reports |
| `/api/logs/export` | POST | Export sessions as JSONL or ZIP |
| `/api/logs/config` | POST | Toggle background pull at runtime |

### SSE Stream Usage

Connect via `EventSource` (browser) or any SSE client:

```javascript
const source = new EventSource('/api/logs/stream?level=WARNING');
source.onmessage = (event) => {
  const entry = JSON.parse(event.data);
  console.log(`[${entry.level}] ${entry.component}: ${entry.msg}`);
};
```

Query parameters for filtering:
- `level` — minimum log level (e.g., `WARNING` shows WARNING, ERROR, CRITICAL)
- `component` — filter by component name
- `source` — filter by source type (`drone`, `gcs`, `frontend`, `infra`)
- `drone_id` — filter by drone ID

### Session Export

```bash
# Single session as JSONL
curl -X POST /api/logs/export -H 'Content-Type: application/json' \
  -d '{"session_ids": ["s_20260319_140000"], "format": "jsonl"}' -o session.jsonl

# Multiple sessions as ZIP
curl -X POST /api/logs/export -H 'Content-Type: application/json' \
  -d '{"session_ids": ["s_20260319_140000", "s_20260319_150000"], "format": "zip"}' -o logs.zip
```

### Background Pull

Optional periodic pull of WARNING+ logs from drones to GCS. Disabled by default.

| Variable | Default | Description |
|----------|---------|-------------|
| `MDS_LOG_BACKGROUND_PULL` | `false` | Enable periodic log collection |
| `MDS_LOG_PULL_INTERVAL_SEC` | `30` | Pull interval in seconds |
| `MDS_LOG_PULL_LEVEL` | `WARNING` | Minimum level to collect |
| `MDS_LOG_PULL_MAX_DRONES` | `10` | Max concurrent drone pulls |

Toggle at runtime: `POST /api/logs/config` with `{"background_pull": true}`.

## Troubleshooting

**No log output?**
Call `init_drone_logging()` or `init_server_logging()` before `get_logger()`. The init functions set up handlers on the root logger.

**Duplicate log lines?**
Ensure init is called only once per process. The init functions call `root.handlers.clear()` to prevent duplicates.

**Old env vars not working?**
`DRONE_LOG_LEVEL` and `DRONE_LOG_FILE` are supported via deprecation shim with a warning. Migrate to `MDS_LOG_*` prefix.

**Where are log files?**
Default: `logs/sessions/s_YYYYMMDD_HHMMSS.jsonl`. Override with `MDS_LOG_DIR` env var or `--log-dir` CLI flag.

---

## Log Viewer UI

### Accessing the Log Viewer

Navigate to `/logs` in the dashboard sidebar (under "System" section).

### Modes

**Operations Mode** (default):
- Shows WARNING and ERROR entries only
- Health bar: GCS status, live drone availability, error/warning drill-down counts
- Live event feed with auto-scroll
- One-click drill-down into warnings or errors from the health bar
- Ideal for field operators during missions

**Developer Mode**:
- All log levels (DEBUG through CRITICAL)
- Component source tree for filtering
- Full-text search across log messages
- Scope switcher for `GCS` vs `Drone #N` live and historical browsing
- Human-readable session labels in UTC, clearly marked as UTC
- Session selector for historical log browsing
- Time focus controls: relative live windows, absolute start/end range for historical sessions
- Active filter chips with one-click removal and a `Clear All Filters` action
- MUI DataGrid with virtual scroll for large datasets
- Export to JSONL or ZIP

### Empty States

The Log Viewer explains why the table is empty instead of silently showing a blank grid:
- waiting for live GCS logs
- waiting for live drone logs
- no entries in the selected session view
- no logs matching the current search or filter set

### Real-Time Streaming

The Log Viewer uses Server-Sent Events (SSE) for real-time streaming:
- 200ms batch interval prevents UI thrashing
- 5000-line ring buffer prevents memory bloat
- Auto-reconnect on connection loss
- Pause/resume button to freeze the view without losing data

### Export

In Developer mode, click the Export button to:
- Select one or more sessions
- Choose JSONL (machine-readable) or ZIP
- Export the current scope (`GCS` or the selected drone)

### Onboard ULog

When a single drone scope is selected, the toolbar exposes a compact `ULog`
action that opens the `Onboard ULog` dialog for file-backed PX4 flight logs
stored on that vehicle.

Current v1 behavior:
- maintenance workflow anchored to `hw_id`, while the UI still shows compact
  `Pn|Hm` identity for operator clarity
- supports `list`, staged `download`, and `erase all`
- stages downloads briefly on the drone/GCS path and then hands them off to
  the browser; v1 does not keep a long-lived GCS archive
- designed for file-backed PX4 ULogs only; MAVLink log streaming is a separate
  future feature
- single-file delete is intentionally not exposed in the generic v1 contract

Operational notes:
- the dialog shows policy chips such as `Download requires disarmed` and
  `Erase requires disarmed`
- download progress is polled and surfaced as a compact job-status card before
  the browser transfer starts
- download filenames are normalized to include slot when known, hardware id,
  PX4 log timestamp when available, and the PX4/MDS log identifier, for example
  `mds-ulog_P12_H5_20260411T102233Z_L7.ulg`
- in SITL or companion deployments where MAVSDK log listing is unavailable but
  PX4 `.ulg` files are locally accessible, MDS may fall back to the configured
  local ULog directories instead of failing the entire workflow

### Error Boundary

The app is wrapped in an `ErrorBoundary` component that:
- Catches React render errors anywhere in the component tree
- Automatically reports the error to `POST /api/logs/frontend`
- Shows a fallback UI with a "Try Again" button
- The error appears in the Log Viewer under the `frontend` source
