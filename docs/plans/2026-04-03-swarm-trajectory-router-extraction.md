# Swarm Trajectory Router Extraction Checkpoint

Date: 2026-04-03
Status: Completed checkpoint
Scope: API modernization phase 3, seventh backend route-domain extraction

## Summary

- extracted the full live Swarm Trajectory route surface from `gcs-server/app_fastapi.py` into `gcs-server/api_routes/swarm_trajectory.py`
- preserved the current live routes:
  - `GET /api/swarm/leaders`
  - `POST /api/swarm/trajectory/upload/{leader_id}`
  - `POST /api/swarm/trajectory/process`
  - `GET /api/swarm/trajectory/recommendation`
  - `GET /api/swarm/trajectory/status`
  - `GET /api/swarm/trajectory/policy`
  - `POST /api/swarm/trajectory/clear-processed`
  - `POST /api/swarm/trajectory/clear`
  - `POST /api/swarm/trajectory/clear-leader/{leader_id}`
  - `DELETE /api/swarm/trajectory/remove/{leader_id}`
  - `GET /api/swarm/trajectory/download/{drone_id}`
  - `GET /api/swarm/trajectory/download-kml/{drone_id}`
  - `GET /api/swarm/trajectory/download-cluster-kml/{leader_id}`
  - `POST /api/swarm/trajectory/clear-drone/{drone_id}`
  - `POST /api/swarm/trajectory/commit`
- kept the request-time dependency seam on the live `app_fastapi` module object so existing patch-driven tests and future auth/MCP wrappers still target one current surface
- added focused router-level coverage in `tests/test_gcs_swarm_trajectory_routes.py`
- removed the stale unused Flask-era `gcs-server/swarm_trajectory_routes.py` file so the extracted FastAPI router is now the only current Swarm Trajectory route definition in the repo

## Root Fixes Included In This Slice

- `POST /api/swarm/trajectory/process` now returns `400` for malformed JSON request bodies instead of degrading that client error into a generic `500`
- `POST /api/swarm/trajectory/commit` now returns `400` for malformed JSON and non-object JSON payloads instead of failing later with a generic `500`
- JSON content-type detection for these optional-body routes is now normalized at the route layer instead of depending on exact raw header formatting

## Design Decision

This slice keeps the legacy route names intact and does not start the canonical `/api/v1/...` rename yet.

The extraction deliberately follows the live FastAPI behavior in `app_fastapi.py`, not the stale Flask-era `gcs-server/swarm_trajectory_routes.py` file. That older file had already drifted from the active status/payload contract and would have been the wrong source to preserve.

`/api/swarm/trajectory/status` remains the highest-risk contract in this domain because it gates launch readiness, planner transfer posture, command validation, and runtime verification. This slice preserves that shape and its dependency seam rather than redesigning it prematurely.

## Tests

Local focused validation:

- `python3 -m py_compile gcs-server/app_fastapi.py gcs-server/api_routes/swarm_trajectory.py tests/test_gcs_swarm_trajectory_routes.py`
- `python3 -m pytest tests/test_gcs_swarm_trajectory_routes.py tests/test_gcs_api_http.py tests/test_api_route_inventory.py -q`
- result: focused batch passed

Local full extracted-router backend validation:

- `python3 -m pytest tests/test_gcs_swarm_trajectory_routes.py tests/test_gcs_show_management_routes.py tests/test_gcs_management_routes.py tests/test_gcs_static_assets_routes.py tests/test_gcs_origin_routes.py tests/test_gcs_git_routes.py tests/test_gcs_configuration_routes.py tests/test_gcs_swarm_routes.py tests/test_gcs_core_routes.py tests/test_gcs_api_http.py tests/test_gcs_api_websocket.py tests/test_api_route_inventory.py -q`
- result: `103 passed, 7 skipped`

Local post-cleanup recheck after removing the stale Flask duplicate:

- `python3 -m py_compile gcs-server/app_fastapi.py gcs-server/api_routes/swarm_trajectory.py tests/test_gcs_swarm_trajectory_routes.py`
- `python3 -m pytest tests/test_gcs_swarm_trajectory_routes.py tests/test_gcs_api_http.py::TestSwarmTrajectoryEndpoints::test_swarm_trajectory_routes_registered tests/test_api_route_inventory.py -q`
- result: `10 passed`

Hetzner validation checkout: `/root/mavsdk_drone_show_validation`

- `/root/mavsdk_drone_show_validation/.venv/bin/python -m py_compile gcs-server/app_fastapi.py gcs-server/api_routes/swarm_trajectory.py tests/test_gcs_swarm_trajectory_routes.py`
- `/root/mavsdk_drone_show_validation/.venv/bin/python -m pytest tests/test_gcs_swarm_trajectory_routes.py tests/test_gcs_show_management_routes.py tests/test_gcs_management_routes.py tests/test_gcs_static_assets_routes.py tests/test_gcs_origin_routes.py tests/test_gcs_git_routes.py tests/test_gcs_configuration_routes.py tests/test_gcs_swarm_routes.py tests/test_gcs_core_routes.py tests/test_gcs_api_http.py tests/test_gcs_api_websocket.py tests/test_api_route_inventory.py -q`
- result: `103 passed, 7 skipped`

Hetzner frontend build:

- `source ~/.nvm/nvm.sh && cd /root/mavsdk_drone_show_validation/app/dashboard/drone-dashboard && npm run build`
- result: compiled successfully

## Files

- updated: `CHANGELOG.md`
- updated: `docs/apis/api-modernization-blueprint.md`
- updated: `gcs-server/app_fastapi.py`
- added: `gcs-server/api_routes/swarm_trajectory.py`
- added: `tests/test_gcs_swarm_trajectory_routes.py`
- deleted: `gcs-server/swarm_trajectory_routes.py`

## Next

- extract the remaining Commands surface from `gcs-server/app_fastapi.py`
- then start Phase 4 canonical `/api/v1/...` migration against the now-isolated backend domains
