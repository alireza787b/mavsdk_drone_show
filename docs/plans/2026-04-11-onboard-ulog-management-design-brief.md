# Onboard ULog Management Design Brief

Date: 2026-04-11
Branch target: `main-candidate`
Status: research / design only, no implementation started

## Executive Conclusion

Yes, onboard PX4 ULog management is feasible in MDS, but only if the feature is
scoped correctly.

The correct v1 is:

- list onboard log files for selected drones
- download selected logs
- erase all onboard logs for a selected drone
- show capability and bandwidth limits explicitly

The wrong v1 is:

- promising per-log delete on every PX4 target
- pretending SD-backed and streaming-backed logging are the same workflow
- treating onboard-log retrieval as a slot (`pos_id`) operation instead of a
  hardware (`hw_id`) maintenance operation

## What The Existing Stack Already Gives Us

Current MDS already has:

- a mature dashboard log surface in [LogViewer.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/pages/LogViewer.js)
- a shared dashboard log service in [logService.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/services/logService.js)
- drone-side log session routes in [drone_api_server.py](/tmp/mavsdk_drone_show_resume/src/drone_api_server.py)
- GCS log proxy routes in [log_routes.py](/tmp/mavsdk_drone_show_resume/gcs-server/log_routes.py)
- shared identity doctrine already shown in the log viewer

This means the feature should be integrated into the existing log domain, not
added as a disconnected one-off page unless the UX eventually proves it needs a
separate workspace.

## MAVSDK / MAVLink / PX4 Feasibility

### MAVSDK

The vendored MAVSDK binding in this repo already includes the `LogFiles`
plugin:

- [mavsdk/log_files.py](/tmp/mavsdk_drone_show_resume/mavsdk/log_files.py)

Supported operations:

- `get_entries()`
- `download_log_file(entry, path)`
- `erase_all_log_files()`

Important limitation:

- generic MAVSDK does **not** expose portable “delete one selected log file”
  semantics

This aligns with the MAVLink log microservice and QGC’s own user workflow.

### MAVLink

The standard MAVLink log protocol supports:

- `LOG_REQUEST_LIST`
- `LOG_REQUEST_DATA`
- `LOG_ERASE`
- `LOG_REQUEST_END`

This supports:

- list logs
- request/download log data
- erase all logs

It does **not** define a portable single-log delete operation.

### PX4

PX4 supports two distinct logging modes:

1. file-backed logging, traditionally to SD-backed storage
2. MAVLink log streaming

Critical point:

- file-backed onboard-log management and MAVLink log streaming are not the same
  product feature

For boards with SD-backed PX4 logging:

- onboard file list/download/erase is a good fit

For boards without SD storage:

- streaming/capture-to-GCS may still work if bandwidth is sufficient
- onboard file listing/downloading may not exist at all

## SITL vs Real Hardware

### SITL

Feasible:

- yes, as long as PX4 logger is enabled and files are actually produced during
  flight sessions

Observed in current Hetzner SITL image:

- the PX4 SITL runtime exposes a rootfs log directory
- fresh reset containers do not necessarily have any log files until flights
  have occurred

This means SITL validation is realistic for:

- list after a flown mission
- download selected logs
- erase-all confirmation flow

### Real Hardware

Feasible on PX4 targets with file-backed logging:

- yes

Not guaranteed on every hardware target:

- some targets may rely on MAVLink log streaming rather than local file-backed
  storage
- some companion workflows may want to archive logs from a local mount rather
  than via MAVSDK

Therefore the correct product behavior is capability-driven:

- if onboard file log access is supported, expose list/download/erase-all
- if only streaming is supported, expose that as a different mode
- if neither is available, show `unsupported` clearly instead of faking a
  broken empty list

## Real-World Network/Bandwidth Guidance

### File-backed list/download

- list operation is lightweight and suitable even on modest links
- download is feasible on constrained links, but should be one-at-a-time and
  operator-driven
- download progress must be explicit
- avoid auto-refreshing large lists repeatedly

### MAVLink log streaming

PX4 documents this as requiring roughly `~50KB/s`, using MAVLink 2, and only
one client at a time.

That makes streaming useful for:

- Wi-Fi / NetBird / higher-throughput IP links

That makes streaming a bad default for:

- narrow telemetry links
- multi-client ambiguous operations
- “just fetch the logs later” workflows

## Product Recommendation

### Recommended v1

Ship only the file-backed workflow first:

- list onboard ULogs
- download one or more selected ULogs
- erase all ULogs on a selected drone
- capability banner for unsupported / no-storage / no-logs states

### Explicitly Defer From v1

- single-log delete from onboard storage
- full MAVLink streaming capture workflow
- built-in ULog analysis/review page
- automatic upload to GCS archive after every mission

## UI / UX Recommendation

### Placement

Best default:

- integrate into the existing log domain as a dedicated `Onboard ULog` mode or
  tab inside the current log viewer

Alternative if the feature grows:

- separate `ULog Manager` page under the logs section, still using the same log
  service layer and identity doctrine

### Scope model

This should be `hw_id`-oriented.

Why:

- onboard log files belong to the physical aircraft / node
- maintenance/download/erase operations are hardware operations
- slot reassignment must not make operators think a different aircraft now owns
  an old onboard log set

Operator labels should still show compact identity:

- `P12|H101`

But selection authority should remain:

- choose hardware targets

### Interaction model

Default screen should stay minimal:

- drone selector with online/offline and `P|H` label
- capability/status chip
- one table of onboard logs
- actions: `Refresh`, `Download`, `Erase All`

Per-row columns should stay compact:

- date/time
- size
- log id
- maybe source/capability chip if mixed modes ever appear

Do not dump verbose descriptions into every row.

Use:

- icons
- short labels
- a compact detail panel if needed

### Batch behavior

Recommended first step:

- multi-drone list and multi-download
- erase-all only with explicit confirmation per-target summary

Avoid first-wave complexity like:

- many simultaneous downloads over weak links
- blind batch erase with no per-drone result reporting

## API / Architecture Recommendation

### Drone side

Add a drone-local ULog service using MAVSDK `LogFiles`.

Recommended drone routes:

- `GET /api/v1/ulog/policy`
- `GET /api/v1/ulog/files`
- `POST /api/v1/ulog/files/{log_id}/download`
- `POST /api/v1/ulog/erase-all`

Why not direct browser download from drone:

- GCS should remain the operator-facing control surface
- consistent auth/MCP/audit seams belong at GCS

### GCS side

Recommended canonical routes:

- `GET /api/v1/logs/drone/{hw_id}/ulog/policy`
- `GET /api/v1/logs/drone/{hw_id}/ulog/files`
- `POST /api/v1/logs/drone/{hw_id}/ulog/files/{log_id}/download`
- `POST /api/v1/logs/drone/{hw_id}/ulog/erase-all`

The GCS should:

- proxy lightweight list requests
- own background transfer jobs
- stream download progress/status to the UI
- optionally stage downloads under a controlled GCS artifact directory

### MCP / AI friendliness

Expose the operations as explicit tasks, not opaque browser actions:

- list available logs
- fetch metadata for selected drones
- request staged download
- poll transfer status
- confirm erase-all

This is much cleaner for future agent workflows than direct browser-triggered
blob downloads with no job state.

## Storage / Artifact Recommendation

If implemented, downloaded ULogs should have two possible destinations:

1. direct operator/browser download
2. optional staged GCS artifact copy for later export or AI review

Do not silently retain huge staged archives forever.

Need:

- retention policy
- explicit cleanup
- clear separation from JSONL MDS runtime logs

## Hardware / Enrollment Alignment

This feature must align with today’s node-enrollment work:

- operate by `hw_id`
- show `P|H` labels where available
- do not attach onboard logs to slot ownership

Bootstrap/hardware docs should later include:

- logger backend expectations
- SD storage expectations
- MAVLink 2 streaming requirements if streaming mode is added
- how to verify that PX4 is actually producing ULogs on the target platform

## Recommended Implementation Phases

### Phase 1

- add capability probe on drone side
- add file list on drone + GCS routes
- add simple single-drone UI list under logs domain

### Phase 2

- add download jobs with progress and browser download
- add multi-drone list/download support
- add focused SITL validation after real flight steps produce logs

### Phase 3

- add erase-all with strong confirmation and per-drone result reporting
- add staged GCS artifact retention policy
- add operator docs/hardware guidance

### Phase 4

- optional future streaming capture mode for SD-less hardware
- optional future ULog review/analyzer page
- optional MCP tool surface for flight-log audit agents

## What I Recommend We Do Next

Yes, continue with this feature.

But continue with this scope:

- onboard file-backed ULog management first
- streaming as a later separate mode
- no single-log delete promise in v1

That is the cleanest, most robust, and least misleading path.

## Questions To Lock Before Implementation

1. Is `erase all` sufficient for v1, or is single-log delete being treated as a
   hard product requirement?

2. Do you want downloaded ULogs to:
   - go directly to the operator browser only, or
   - also be staged on GCS for later export/review?

3. Should we implement this as:
   - a new tab inside `Log Viewer`, or
   - a separate `ULog Manager` page under the logs section?

## References

- MAVSDK LogFiles API:
  - https://mavsdk.mavlink.io/main/en/cpp/api_reference/classmavsdk_1_1_log_files.html
- MAVSDK LogStreaming API:
  - https://mavsdk.mavlink.io/main/en/cpp/api_reference/classmavsdk_1_1_log_streaming.html
- PX4 Logging:
  - https://docs.px4.io/main/en/dev_log/logging
- MAVLink common log messages:
  - https://mavlink.io/en/messages/common.html
- QGroundControl Log Download:
  - https://docs.qgroundcontrol.com/Stable_V4.3/en/qgc-user-guide/analyze_view/log_download.html
- QGroundControl MAVLink 2 Logging:
  - https://docs.qgroundcontrol.com/master/en/qgc-user-guide/settings_view/telemetry.html
