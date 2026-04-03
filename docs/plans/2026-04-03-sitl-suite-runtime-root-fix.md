# 2026-04-03 SITL Suite Runtime Root Fix

## Summary

This checkpoint finishes the reusable SITL validation-suite slice that followed the
API contract modernization work.

The new suite and shared validator helpers are now validated locally and on
Hetzner, and the corrected live 3-drone run passed end to end for:

- Drone Show
- Smart Swarm
- Swarm Trajectory

## Root Cause Found During Live Hetzner Run

The first live suite run exposed two separate operational issues:

1. The live GCS `gunicorn` process on port `5000` was still the long-lived
   April 1 worker running inside the `MDS-GCS` tmux session, so it did not yet
   expose the canonical `/api/v1/...` routes that already existed on disk in the
   synced runtime checkout.
2. After that stale worker was replaced, the final Swarm Trajectory slice still
   misbehaved because the validator wrote short validation profiles into the
   temporary validation checkout while the live GCS processed trajectory files
   from the runtime checkout.

That second issue caused the live server to ignore the freshly generated short
profiles and instead process older runtime data with much higher altitude
profiles.

## Fixes Applied

### Hetzner live-service fix

- traced the live listener on `5000` back to the `MDS-GCS` tmux session
- confirmed canonical routes existed on disk in
  `/root/mavsdk_drone_show_main_candidate_runtime_https/gcs-server`
- terminated the stale April 1 `gunicorn` master
- relaunched `gunicorn` from the clean runtime checkout in the same tmux session

### Reusable suite contract fix

`tools/run_sitl_validation_suite.py` now separates:

- `--validator-root`
  - checkout containing the suite script and validator tooling being executed
- `--repo-root`
  - runtime repo root used for host-side SITL resets and validator operations
    that must target the same mission-data tree as the live GCS

The suite now:

- runs reset steps from `repo_root`
- runs validator commands from `validator_root`
- passes `--repo-root` through to validators as the runtime mission-data source
- records both roots in `suite-summary.json`

## Validation

### Local

- `python3 -m pytest tests/test_run_sitl_validation_suite.py tests/test_validate_smart_swarm_runtime.py tests/test_validate_drone_show_runtime.py tests/test_validate_swarm_trajectory_runtime.py tests/test_drone_api_http.py tests/test_drone_setup.py tests/test_gcs_api_http.py tests/test_gcs_api_websocket.py tests/test_api_route_inventory.py tests/test_command_system.py tests/test_command_processing.py tests/test_command_timeout_policy.py tests/test_swarm_trajectory_service.py -q`
- result: `371 passed, 8 skipped`

### Hetzner focused validation checkout

- same focused batch in `/tmp/mds_sitl_suite_validation`
- result: `371 passed, 8 skipped`

### Corrected live Hetzner suite run

Command:

```bash
cd /tmp/mds_sitl_suite_validation
. .venv/bin/activate
python tools/run_sitl_validation_suite.py \
  --base-url http://127.0.0.1:5000 \
  --validator-root /tmp/mds_sitl_suite_validation \
  --repo-root /root/mavsdk_drone_show_main_candidate_runtime_https \
  --drone-ids 1 2 3 \
  --artifact-dir /tmp/mds_sitl_suite_validation/artifacts/sitl-validation/live-3drone-runtime-root
```

Result:

- suite status: `passed`
- artifact summary:
  - `/tmp/mds_sitl_suite_validation/artifacts/sitl-validation/live-3drone-runtime-root/suite-summary.json`
- per-mode results:
  - `drone_show`: passed
  - `smart_swarm`: passed
  - `swarm_trajectory`: passed

Final live-state verification after the corrected run:

- `GET /health`: `ok`
- `GET /api/v1/commands/active`: `total=0`
- drones `1/2/3`: `mission=0`, `state=0`, `armed=false`

## Operator Guidance

When the validator checkout and the live GCS/runtime checkout are different
paths on the same host, always pass both roots explicitly:

- `--validator-root` for the temporary or feature checkout holding the latest
  validator code
- `--repo-root` for the runtime checkout that the live GCS is actually using

Do not assume they are interchangeable for Swarm Trajectory validation.
