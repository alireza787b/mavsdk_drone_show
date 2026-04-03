# 2026-04-03 Swarm Config V1 Canonical Aliases

## Scope

Phase 4, third GCS canonical route slice:

- `GET /api/v1/config/swarm`
- `PUT /api/v1/config/swarm`
- `PATCH /api/v1/config/swarm/assignments/{hw_id}`

This slice keeps the legacy compatibility routes live:

- `GET /get-swarm-data`
- `POST /save-swarm-data`
- `POST /request-new-leader`

## Contract Decisions

- Canonical swarm-config `GET` returns the typed persisted resource shape:
  - `{ "version": 1, "assignments": [...] }`
- Canonical swarm-config `PUT` accepts the same wrapped resource shape.
- Canonical single-assignment updates use `PATCH /api/v1/config/swarm/assignments/{hw_id}`.
- The patch route is intentionally assignment-scoped, not leader-scoped, because the live mutation surface includes `follow`, `offset_x`, `offset_y`, `offset_z`, and `frame`.

## Caller Migration

- Dashboard shared GCS service layer now uses canonical swarm-config routes.
- `Overview`, `Mission Config`, and `Swarm Design` now unwrap the canonical swarm envelope centrally instead of assuming a raw array from the transport.
- `smart_swarm.py` now refreshes saved swarm config from `GET /api/v1/config/swarm` and notifies failover changes through `PATCH /api/v1/config/swarm/assignments/{hw_id}`.
- `functions/swarm_analyzer.py` now uses the canonical swarm-config fallback route and unwraps the envelope.
- The reusable validation clients touched in this slice now use the canonical swarm-config routes, and the command-validation clients touched here also use canonical command submit/status routes.

## Local Validation

- `python3 -m pytest tests/test_gcs_swarm_routes.py tests/test_gcs_api_http.py::TestSwarmEndpoints tests/test_api_route_inventory.py tests/test_validate_smart_swarm_runtime.py tests/test_validate_swarm_trajectory_runtime.py tests/test_validate_drone_show_runtime.py tests/test_swarm_trajectory_service.py::test_fetch_swarm_data_prefers_local_config -q`
  - result: `60 passed`
- `python3 -m pytest tests/test_gcs_api_http.py::TestAPIV1Aliases -q`
  - result: `10 passed`

## Hetzner Validation

- backend/tooling batch:
  - `71 passed`
- frontend shared GCS service Jest slice:
  - `13 passed`
- production dashboard build:
  - passed

## Notes

- Local frontend Jest was not run in the recovery repo because `node_modules` is intentionally not installed there; the authoritative frontend validation for this slice was run on Hetzner.
- The next clean Phase 4 boundary is origin canonicalization, now that the config-family slices for fleet and swarm are both stabilized.
