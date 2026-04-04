# 2026-04-04 Swarm Trajectory Typed Contracts

## Objective

Close the next merge-readiness gap after the Phase 6F error-envelope slice by
moving the active Swarm Trajectory success surface onto typed request/response
contracts and OpenAPI metadata instead of leaving it as a large ad hoc dict
domain.

## Scope

- add typed GCS schema models for the active Swarm Trajectory success payloads
- replace the last manual request parsing on `process` and `commit`
- normalize service-layer failure signaling so operational failure does not
  return `200 success=false`
- keep current frontend/operator success semantics stable
- revalidate locally and on Hetzner

## Changes

- Added typed GCS schema models in `gcs-server/schemas.py` for:
  - leader inventory
  - upload result
  - recommendation
  - status and nested cluster/package/session payloads
  - policy
  - process request/response
  - clear/remove mutation responses
  - commit request/success response
- Updated `gcs-server/api_routes/swarm_trajectory.py` to:
  - use `response_model` on the active JSON endpoints
  - return validated model payloads on success instead of raw `JSONResponse`
  - accept typed optional request bodies for `process` and `commit`
- Updated `functions/swarm_trajectory_service.py` so:
  - `process_trajectories_payload(...)` raises `SwarmTrajectoryError` on
    failure instead of returning `success=false`
  - `clear_processed_payload()` raises `SwarmTrajectoryError` on failure
    instead of returning `success=false`
- Updated frontend helpers:
  - `app/dashboard/drone-dashboard/src/services/apiError.js`
  - `app/dashboard/drone-dashboard/src/services/droneApiService.js`
  so structured validation/detail payloads remain readable to operators after
  the typed-route migration
- Strengthened regression coverage in:
  - `tests/test_gcs_swarm_trajectory_routes.py`
  - `tests/test_swarm_trajectory_service.py`
  - `tests/test_gcs_api_http.py`
- Refreshed:
  - `docs/apis/api-modernization-blueprint.md`
  - `docs/apis/gcs-api-server.md`
  - `CHANGELOG.md`

## Validation

- Local focused backend batch:
  - `python3 -m pytest tests/test_gcs_swarm_trajectory_routes.py tests/test_swarm_trajectory_service.py tests/test_gcs_api_http.py -q`
  - result: `108 passed`
- Local frontend note:
  - the recovery checkout does not have dashboard dependencies installed, so
    the frontend Jest slice was validated on Hetzner instead of locally
- Hetzner focused backend batch:
  - `/root/mavsdk_drone_show_validation/.venv/bin/python -m pytest tests/test_gcs_swarm_trajectory_routes.py tests/test_swarm_trajectory_service.py tests/test_gcs_api_http.py -q`
  - result: `108 passed`
- Hetzner frontend validation:
  - `CI=true npm test -- --runInBand --watch=false src/services/droneApiService.test.js`
  - result: `5 passed`
  - `npm run build`
  - result: passed

## Outcome

After this slice, Swarm Trajectory is no longer a partially modernized special
case. Its current success payloads are typed and machine-readable, request-body
parsing is aligned with the shared FastAPI contract, and operational failures
no longer masquerade as `200` transport success.

The remaining merge-readiness debt is now concentrated in:

- QuickScout / SAR success-payload typing and OpenAPI cleanup
- WebSocket/OpenAPI stream-shape drift
- dormant auth/principal seams around privileged mutations
- drone-side error-envelope and typed-stream cleanup
