# 2026-04-03 Origin V1 Canonical Aliases

## Scope

Phase 4, fourth GCS canonical route slice:

- `GET /api/v1/origin`
- `PUT /api/v1/origin`
- `GET /api/v1/origin/bootstrap`
- `GET /api/v1/navigation/global-origin`
- `GET /api/v1/origin/elevation`
- `GET /api/v1/origin/deviations`
- `POST /api/v1/origin/compute`
- `GET /api/v1/origin/launch-positions`

This slice keeps the legacy compatibility routes live:

- `GET /get-origin`
- `POST /set-origin`
- `GET /get-origin-for-drone`
- `GET /get-gps-global-origin`
- `GET /elevation`
- `GET /get-position-deviations`
- `POST /compute-origin`
- `GET /get-desired-launch-positions`

## Contract Decisions

- Canonical origin reads use the typed payload:
  - `{ "lat": ..., "lon": ..., "alt": ..., "timestamp": ..., "source": ... }`
- Canonical origin writes use `PUT /api/v1/origin`.
- Canonical origin writes now accept omitted altitude and default it to `0.0` MSL so the API matches the dashboard/manual-origin workflow instead of rejecting a legitimate operator input shape.
- Bootstrap/runtime origin consumers now have a dedicated canonical route at `GET /api/v1/origin/bootstrap` instead of relying on an implicit mapping to the generic origin resource.
- `POST /api/v1/origin/compute` remains compute-only and does not persist origin state.

## Caller Migration

- Dashboard shared GCS service layer now uses canonical origin routes.
- `drone_show.py` fetches origin from `GET /api/v1/origin`.
- `tools/validate_drone_show_runtime.py` now checks launch geometry through `GET /api/v1/origin/deviations`.
- The shared route-key mapping now recognizes the canonical bootstrap and deviation/origin paths.

## Local Validation

- `python3 -m pytest tests/test_gcs_origin_routes.py tests/test_gcs_api_http.py::TestOriginEndpoints tests/test_gcs_api_http.py::TestAPIV1Aliases tests/test_api_route_inventory.py tests/test_validate_drone_show_runtime.py -q`
  - result: `44 passed`

## Hetzner Validation

- backend/tooling batch:
  - `44 passed`
- frontend shared GCS service Jest slice:
  - `14 passed`
- production dashboard build:
  - passed

## Notes

- Local frontend Jest was not run in the recovery repo because `node_modules` is intentionally not installed there; the authoritative frontend validation for this slice was run on Hetzner.
- The next clean Phase 4 boundary is the remaining git/show-management canonicalization work, followed by deliberate compatibility-route retirement only after all active callers and SITL validation paths move fully onto the canonical surface.
