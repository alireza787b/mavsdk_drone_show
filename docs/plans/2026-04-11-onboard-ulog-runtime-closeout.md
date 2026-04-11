# Onboard ULog Runtime Closeout

Date: 2026-04-11
Branch: `main-candidate`

## Scope Closed

This closes v1 onboard PX4 ULog management for the dashboard log domain:

- list file-backed onboard PX4 ULogs for a selected drone
- staged browser download with progress polling
- erase-all onboard ULogs
- reusable SITL runtime validator and checked-in plan

This does not add:

- MAVLink log streaming
- single-file delete
- long-lived GCS archive storage
- onboard ULog analysis/review UI

## Final Contract

Drone-side:

- `GET /api/v1/ulog/policy`
- `GET /api/v1/ulog/files`
- `POST /api/v1/ulog/files/{log_id}/download`
- `GET /api/v1/ulog/downloads/{job_id}`
- `DELETE /api/v1/ulog/downloads/{job_id}`
- `GET /api/v1/ulog/downloads/{job_id}/content`
- `POST /api/v1/ulog/erase-all`

GCS log-domain proxy:

- `GET /api/logs/drone/{drone_id}/ulog/policy`
- `GET /api/logs/drone/{drone_id}/ulog/files`
- `POST /api/logs/drone/{drone_id}/ulog/files/{log_id}/download`
- `GET /api/logs/drone/{drone_id}/ulog/downloads/{job_id}`
- `DELETE /api/logs/drone/{drone_id}/ulog/downloads/{job_id}`
- `GET /api/logs/drone/{drone_id}/ulog/downloads/{job_id}/content`
- `POST /api/logs/drone/{drone_id}/ulog/erase-all`

## Runtime Design

- Operator entrypoint stays inside `Log Viewer` as `Onboard ULog`, not a
  parallel standalone tool.
- Workflow is `hw_id`-anchored maintenance with visible compact `Pn|Hm`
  identity in the UI.
- Downloads are staged briefly and then transferred to the browser.
- Download filenames include slot when known, hardware id, PX4 timestamp when
  available, and log identifier.

Example:

- `mds-ulog_P12_H5_20260411T102233Z_L7.ulg`

## SITL/Runtime Hardening

The runtime proof required two concrete fixes:

1. Fresh SITL images must keep PX4 ULog file logging enabled.
   - default SITL override now uses `SDLOG_MODE=0`

2. Drone-local log enumeration cannot rely solely on MAVSDK `log_files`.
   - when MAVSDK log enumeration is unavailable but `.ulg` files are locally
     present on the companion, the drone-side service falls back to configured
     filesystem roots
   - after erase, an empty fallback directory is treated as an empty catalog,
     not as a server error

## Validation

Local:

- `python3 -m pytest --no-cov tests/test_ulog_service.py tests/test_drone_api_http.py tests/test_api_route_inventory.py tests/test_gcs_api_http.py tests/test_mds_logging/test_log_routes_gcs.py -q`
- result: `159 passed`

Hetzner runtime:

- frontend log-surface batch: passed
- frontend production build: passed
- `ulog_runtime` SITL plan: passed

Artifact:

- `/root/mds_ulog_validation/artifacts/sitl-validation/20260411T085513Z`

## Browser Handoff Expectation

When the browser stack is up on the synced runtime tree:

1. open `Log Viewer`
2. select a single drone scope
3. open `Onboard ULog`
4. verify:
   - file list loads
   - policy chips load
   - download job shows progress and then triggers browser download
   - erase-all clears the list after confirmation

## Deferred

- long-lived GCS-side ULog storage/retention management
- per-log delete where the underlying platform guarantees it
- onboard ULog review/analyzer UI
- MAVLink log streaming capture/management for SD-less platforms
