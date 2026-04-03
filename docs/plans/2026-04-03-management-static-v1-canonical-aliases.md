# 2026-04-03 Management and Static V1 Canonical Aliases

## Scope

Phase 4, eighth GCS canonical route slice:

- `GET /api/v1/system/gcs-config`
- `PUT /api/v1/system/gcs-config`
- `GET /api/v1/fleet/network-details`
- `GET /api/v1/swarm-trajectories/plots/{filename}`

This slice keeps the legacy compatibility routes live:

- `GET /get-gcs-config`
- `POST /save-gcs-config`
- `GET /get-network-info`
- `GET /static/plots/{filename}`

## Contract Decisions

- GCS runtime configuration is modeled as a system resource, so the canonical surface is `/api/v1/system/gcs-config` instead of preserving the older action-style naming.
- The canonical write uses `PUT` because the route represents replacement/update semantics for one configuration resource even though persistence still remains an explicit stub during this phase.
- Per-drone network metadata is modeled as detailed fleet network state at `GET /api/v1/fleet/network-details`, keeping it distinct from the higher-level reachability summary at `GET /api/v1/fleet/network-status`.
- Swarm Trajectory-generated plot assets now live under `/api/v1/swarm-trajectories/plots/{filename}` instead of a generic `/static/*` namespace so the resource ownership is explicit for future auth/MCP policy layers.

## Caller Migration

- The shared dashboard GCS service layer now uses the canonical management/static routes for:
  - GCS configuration reads
  - GCS configuration writes
  - detailed network metadata reads
  - direct Swarm Trajectory plot URLs
- Dead frontend compatibility helpers for the deprecated one-off git routes were removed from `utilities.js` because they are unrouted, unreferenced, and superseded by the shared GCS service layer.

## Local Validation

- `python3 -m pytest tests/test_gcs_management_routes.py tests/test_gcs_static_assets_routes.py tests/test_gcs_api_http.py::TestGCSManagementEndpoints tests/test_api_route_inventory.py -q`
  - result: `18 passed`

## Hetzner Validation

- backend/tooling batch:
  - `18 passed`
- frontend shared GCS service Jest slice:
  - `17 passed`
- production dashboard build:
  - passed

## Notes

- Legacy routes remain mounted and explicitly covered by alias tests in this phase.
- This is not the final API slice. After this checkpoint, the remaining work is the public compatibility-retirement classification and the deliberate removal/migration of the still-mounted legacy routes that are no longer justified.
