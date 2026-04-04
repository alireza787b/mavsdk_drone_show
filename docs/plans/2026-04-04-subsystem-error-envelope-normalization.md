# 2026-04-04 Subsystem Error Envelope Normalization

## Objective

Close the remaining GCS subsystem error-contract outlier after the Phase 6E
shared-envelope cleanup by normalizing Swarm Trajectory failures and aligning
QuickScout / SAR router metadata with the same contract.

## Scope

- normalize Swarm Trajectory non-2xx failures onto the shared `ErrorResponse`
  envelope
- keep current success payloads stable for the validated frontend and runtime
  consumers
- expose shared OpenAPI error-response metadata directly on the Swarm
  Trajectory and QuickScout routers
- strengthen subsystem contract tests

## Changes

- Updated `gcs-server/api_routes/swarm_trajectory.py` so the route family now
  returns the shared `ErrorResponse` envelope for:
  - service-layer `SwarmTrajectoryError` failures
  - malformed / non-object JSON request bodies
  - operator-facing git commit/push failures
  - unexpected server exceptions
- Stopped leaking raw Python exception text from the Swarm Trajectory router on
  generic `500` paths. Those errors are now logged server-side and returned to
  clients through the shared problem envelope.
- Mapped Swarm Trajectory git operation failures to explicit operator-meaningful
  statuses:
  - `409` for divergence/conflict-style failures
  - `502` for network/auth/timeout-style upstream git failures
- Added shared router-level OpenAPI error metadata in:
  - `gcs-server/api_routes/swarm_trajectory.py`
  - `gcs-server/sar/routes.py`
- Strengthened regression coverage in:
  - `tests/test_gcs_swarm_trajectory_routes.py`
  - `tests/test_gcs_api_http.py`
  - `tests/test_sar_api.py`
- Refreshed:
  - `docs/apis/gcs-api-server.md`
  - `docs/apis/api-modernization-blueprint.md`
  - `CHANGELOG.md`

## Validation

- Local focused subsystem batch:
  - `python3 -m pytest tests/test_gcs_swarm_trajectory_routes.py tests/test_gcs_sar_routes.py tests/test_sar_api.py tests/test_gcs_api_http.py tests/test_api_route_inventory.py -q`
  - result: `114 passed`
- Hetzner focused subsystem batch:
  - `/root/mavsdk_drone_show_validation/.venv/bin/python -m pytest tests/test_gcs_swarm_trajectory_routes.py tests/test_gcs_sar_routes.py tests/test_sar_api.py tests/test_gcs_api_http.py tests/test_api_route_inventory.py -q`
  - result: `114 passed`

## Outcome

After this slice, the GCS-side error contract is materially more uniform:
Swarm Trajectory no longer behaves like a custom error island, and QuickScout /
SAR now documents the same shared error surface at the router boundary.

The remaining merge-readiness debt is no longer route-family error-envelope
sprawl. It is:

- typed request/response and OpenAPI cleanup for the larger Swarm Trajectory
  and QuickScout success-payload surfaces
- WebSocket/OpenAPI schema drift
- dormant auth/principal seams around privileged mutations
- drone-side error-envelope and typed-stream cleanup
