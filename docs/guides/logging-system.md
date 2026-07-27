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

logger.info("Server started on port 5030")
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
| `/api/logs/drone/{drone_id}/ulog/files/{log_id}/summary` | GET | Return a derived local PX4 ULog summary without returning raw ULog content |
| `/api/logs/drone/{drone_id}/ulog/files/{log_id}/download` | POST | Create a staged browser-download job for one onboard ULog |
| `/api/logs/drone/{drone_id}/ulog/downloads/{job_id}` | GET | Poll staged onboard-ULog download job state |
| `/api/logs/drone/{drone_id}/ulog/downloads/{job_id}` | DELETE | Drop a staged onboard-ULog download job |
| `/api/logs/drone/{drone_id}/ulog/downloads/{job_id}/content` | GET | Stream staged onboard-ULog content to the browser |
| `/api/logs/drone/{drone_id}/ulog/erase-all` | POST | Erase all file-backed onboard PX4 ULogs on the target drone |
| `/api/logs/ulog/summary` | POST | Summarize one uploaded PX4 ULog locally without storing or returning raw content |
| `/api/logs/frontend` | POST | Receive frontend error reports |
| `/api/logs/export` | POST | Export sessions as JSONL or ZIP |
| `/api/logs/config` | POST | Toggle background pull at runtime |

### Simurgh Read-Only Log Use

Simurgh may use reviewed read-only log tools to summarize per-drone log session
counts, bounded latest-session warning/error lines, onboard PX4 ULog file
metadata, and derived local ULog summaries. The ULog summary path uses the
approved onboard staging policy, parses the selected log locally with `pyulog`,
returns bounded metrics such as duration, topic/sample counts, local-position
envelope, battery range, command/ack counts, and dropout counts, then deletes
the staged job. This path is for operator evidence only: it does not return raw
ULog bytes, raw topic arrays, raw logged-message text, browser download content,
erase logs, expose unrestricted drone-local APIs to MCP clients, or treat
backend API warnings as flight-log evidence.

The semantic routing contract requests evidence depth as structured booleans
(`verify_operation`, `include_unified_logs`, and `analyze_latest_ulog`) rather
than relying on a maintained list of phrases such as "check the flight." Local
code validates these options and still owns target/action-run correlation,
limits, parser policy, and raw-artifact exclusion.

Operators and integrations may also use `POST /api/logs/ulog/summary`
with one uploaded `.ulg` file. The GCS stores the upload only as a temporary
file during parsing, applies `MDS_ULOG_UPLOAD_SUMMARY_MAX_BYTES`, returns the
same derived summary contract, and deletes the temporary file before responding.
This upload route is intentionally not part of the Simurgh/MCP callable registry
in the current slice.

### ULog API and MCP Contract

ULog inventory and summary responses use `schema_version: "1.0"`. The dashboard
assistant and external MCP clients discover the same two read tools from
`config/agent_tools.yaml`:

- `mds.logs.drone_ulog_files.read` lists metadata without staging file content.
- `mds.logs.drone_ulog_summary.read` returns bounded derived metrics and always
  reports `raw_content_included: false`.

The registry owns each tool's input schema, output schema, timeout setting, role,
runtime-mode exposure, and safety notes. A parser limit, malformed file, missing
parser dependency, or timeout is returned as a typed failure instead of a
successful empty summary. Expected HTTP mappings are:

| Status | Meaning |
|--------|---------|
| `429` | Bounded parser workers and queue are currently full; retry later |
| `404` | Drone, ULog id, or staged job is unavailable to this caller |
| `413` | File exceeds the configured analysis or transfer limit |
| `422` | The file exists but is not a valid parseable PX4 ULog |
| `502` | The selected drone/log source could not be reached |
| `503` | The local ULog parser dependency is unavailable |
| `504` | Proxy, transfer, or isolated parser deadline expired |

Parsing runs in a separate child process with wall-clock, address-space, CPU,
output-file, and open-file limits. The child receives a minimal environment
without GCS credentials, cannot create ordinary Python socket/subprocess paths,
and sets Linux `no_new_privs` when available. Parser output is validated against
a closed, finite-value Pydantic schema before it reaches GCS or MCP. The GCS
event loop and drone telemetry loop do not parse `.ulg` files directly. Active
workers and queued requests are both bounded; a full queue returns `429` rather
than growing without limit. `pyulog` remains a pinned trusted parser dependency,
not a general sandbox for arbitrary native code.

MCP text and `structuredContent` share the same response budget. When a route
response exceeds that budget, Simurgh returns bounded text plus truncation
metadata and omits the original structured object so it cannot bypass the
limit.

Raw browser downloads have a separate security and lifecycle path:

- only authenticated `operator` or `admin` actors may create or access jobs;
- the browser receives an opaque, signed, actor-and-drone-bound handle rather
  than the drone-local job id or capability;
- the GCS uses a transient derived capability when calling the trusted
  drone-side raw-content routes;
- the drone stores only a capability hash, and failed, expired, or deleted jobs
  lose their capability state;
- active jobs are never evicted to satisfy retention limits;
- per-file size, aggregate staging size, free-space reserve, idle deadline, and
  total deadline are checked before and during transfer;
- service shutdown cancels and awaits active transfer tasks.

These controls protect raw files. Sanitized summary/list calls remain
viewer-readable and never return raw content.

### ULog Runtime Controls

The environment registry is the canonical configuration source. Shared
deployment settings must be applied consistently to GCS and node env files;
node-only settings live in `/etc/mds/local.env`.

| Setting | Default | Scope |
|---------|---------|-------|
| `MDS_ULOG_PROXY_TIMEOUT_SEC` | `30` | GCS inventory/maintenance proxy |
| `MDS_ULOG_SUMMARY_TIMEOUT_SEC` | `90` | GCS and node parser deadline |
| `MDS_ULOG_SUMMARY_MAX_WORKERS` | `2` | GCS and node parser concurrency |
| `MDS_ULOG_SUMMARY_MAX_QUEUE` | `4` | Queued summaries beyond active workers |
| `MDS_ULOG_SUMMARY_MAX_MEMORY_MB` | `1024` | Per parser child process |
| `MDS_ULOG_SUMMARY_MAX_CPU_SEC` | `60` | Per parser child CPU-time ceiling |
| `MDS_ULOG_SUMMARY_MAX_OUTPUT_BYTES` | `8388608` | Per parser child output-file ceiling |
| `MDS_ULOG_SUMMARY_MAX_OPEN_FILES` | `64` | Per parser child descriptor ceiling |
| `MDS_ULOG_SUMMARY_MAX_BYTES` | `67108864` | Parseable local file size |
| `MDS_ULOG_UPLOAD_SUMMARY_MAX_BYTES` | `67108864` | GCS multipart upload |
| `MDS_ULOG_DOWNLOAD_MAX_BYTES` | `536870912` | One raw transfer |
| `MDS_ULOG_DOWNLOAD_AGGREGATE_MAX_BYTES` | `1073741824` | Node staging total |
| `MDS_ULOG_DOWNLOAD_MIN_FREE_BYTES` | `536870912` | Node disk reserve |
| `MDS_ULOG_DOWNLOAD_TIMEOUT_SEC` | `900` | Total transfer/browser deadline |
| `MDS_ULOG_DOWNLOAD_IDLE_TIMEOUT_SEC` | `60` | Node progress idle deadline |
| `MDS_ULOG_DOWNLOAD_JOB_TTL_SEC` | `1800` | Terminal staged-job retention |
| `MDS_ULOG_DOWNLOAD_MAX_JOBS` | `8` | Retained jobs per node |

Disarm requirements, staging path, and optional PX4 filesystem fallback roots
are also registry-owned through `MDS_ULOG_DOWNLOAD_REQUIRE_DISARMED`,
`MDS_ULOG_ERASE_REQUIRE_DISARMED`, `MDS_ULOG_DOWNLOAD_STAGE_DIR`, and
`MDS_ULOG_FILESYSTEM_FALLBACK_DIRS`.

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

Current behavior:
- maintenance workflow anchored to `hw_id`, while the UI still shows compact
  `Pn|Hm` identity for operator clarity
- supports `list`, on-demand derived analysis, staged `download`, and `erase all`
- the **Analyze** control calls the GCS summary endpoint and shows bounded flight
  duration, local movement/altitude envelope, battery range, and command/ack
  evidence inline; raw ULog content is never rendered
- stages downloads briefly on the drone/GCS path and then hands them off to
  the browser; v1 does not keep a long-lived GCS archive
- designed for file-backed PX4 ULogs only; MAVLink log streaming is a separate
  future feature
- single-file delete is intentionally not exposed in the generic v1 contract

Operational notes:
- the dialog shows policy chips such as `Download requires disarmed` and
  `Erase requires disarmed`
- stock lab/demo nodes with no `MDS_GCS_API_TOKEN_FILE` use explicit
  trusted-network ULog mode and log a warning; this preserves plug-and-play
  operation but must not be exposed to untrusted peers
- when `MDS_GCS_API_TOKEN_FILE` is configured, every GCS-to-node ULog request
  carries a single-use, 15-second `X-MDS-Machine-Credential` bound to the target
  hardware identity and exact ULog operation; the node verifies it from that
  root-readable token, and an unreadable configured path fails closed
- the GCS issues hardened credentials only from an active `drone`-scoped API
  token; full API auth or a configured SITL token path prevents unauthenticated
  proxy fallback
- SITL launchers read the host path from `MDS_SITL_GCS_API_TOKEN_FILE`, mount it
  read-only at `/run/secrets/mds_gcs_api_token`, and expose only that mounted
  path to the container as `MDS_GCS_API_TOKEN_FILE`
- download progress is polled and surfaced as a compact job-status card before
  the browser transfer starts
- raw job handles are opaque and bound to the authenticated operator and target
  drone; copying a handle to another session does not grant access
- the GCS handle and the node-local `X-MDS-ULog-Job-Token` are separate
  capabilities; neither raw token is returned in assistant evidence or normal
  dashboard payloads
- staged downloads intentionally re-fetch the current MAVSDK log entry inside
  the background worker before downloading; this keeps asynchronous browser
  jobs aligned with MAVSDK's `get_entries` then `download_log_file` flow and
  avoids stale reconstructed entries being rejected by PX4/MAVSDK
- Simurgh and the Logs API share the same 30-second ULog inventory/maintenance
  proxy timeout; ULog parsing uses the separately bounded
  `MDS_ULOG_SUMMARY_TIMEOUT_SEC` setting
- Simurgh scopes drone-log/ULog review to an explicit target, the most recent
  command targets, or fresh heartbeat/telemetry presence before using the
  configured fallback scan. `MDS_SIMURGH_DRONE_LOG_MAX_DRONES` bounds that
  fallback and `MDS_SIMURGH_ULOG_SUMMARY_MAX_DRONES` bounds expensive parsing
- base per-drone session, latest-warning, and ULog inventory reads fan out with
  at most `MDS_SIMURGH_DRONE_LOG_MAX_WORKERS` workers and share one
  `MDS_SIMURGH_DRONE_LOG_EVIDENCE_DEADLINE_SEC` wall-clock budget; a slow or
  offline node becomes explicit unavailable evidence instead of serially
  delaying the complete fleet answer
- unavailable or timed-out log sources are reported as `unknown`, not as zero
  sessions, zero ULogs, or zero warnings; partial fleet coverage and parser caps
  remain visible in the summary
- a ULog is described as correlated with an action only when target identity,
  the action time window/reference, and the matching command IDs are all
  present in local evidence; file recency alone is not proof of association
- staged-analysis cleanup is part of the evidence result: a failed or missing
  staged-job deletion is reported explicitly rather than silently treated as
  successful cleanup
- blocking drone log and ULog proxy work runs outside the async assistant event
  loop, so one slow onboard log cannot freeze unrelated chat/status requests
- ULog parsing runs in a killable resource-bounded child process; timeout,
  malformed input, oversize input, and missing-parser outcomes remain distinct
- direct parser and filesystem-fallback summaries are both validated against
  the same strict versioned response schema before GCS, MCP, or Simurgh can use
  them
- an open raw-content response holds a lease on the securely opened staged file;
  job deletion and retention expiry return a conflict or defer cleanup until the
  stream closes
- download filenames are normalized to include slot when known, hardware id,
  PX4 log timestamp when available, and the PX4/MDS log identifier, for example
  `mds-ulog_P12_H5_20260411T102233Z_L7.ulg`
- in SITL or companion deployments where MAVSDK log listing is unavailable but
  PX4 `.ulg` files are locally accessible, MDS may fall back to the configured
  local ULog directories instead of failing the entire workflow
- drone health and ULog policy responses include `ulog_capability`, including
  `mavsdk_server_present`, executable/path state, and configured filesystem
  fallback paths
- if `mavsdk_server` is missing or not executable and no filesystem fallback is
  available, ULog list/download/erase routes return an actionable dependency
  error instead of a generic server failure

ULog-specific failures remain typed across node and GCS boundaries:

| Status | Meaning |
|--------|---------|
| `401` | A required machine/job credential is missing, expired, replayed, or invalid |
| `403` | Authenticated actor lacks the required operator/admin role |
| `409` | Vehicle/runtime conflict or an active leased transfer |
| `413` | File or parser input exceeds a configured limit |
| `503` | Machine authentication or a required ULog dependency is unavailable |
| `507` | Staging quota or disk reserve cannot safely accept the file |

### Error Boundary

The app is wrapped in an `ErrorBoundary` component that:
- Catches React render errors anywhere in the component tree
- Automatically reports the error to `POST /api/logs/frontend`
- Shows a fallback UI with a "Try Again" button
- The error appears in the Log Viewer under the `frontend` source
