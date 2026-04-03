# 2026-04-03 Show Legacy Route Retirement

## Scope

This checkpoint retires the remaining GCS show-management verb-style compatibility routes now that all active dashboard/runtime/helper callers have already moved to the canonical `/api/v1/shows/...` surface.

Removed routes:

- `POST /import-show`
- `GET /download-raw-show`
- `GET /download-processed-show`
- `GET /get-show-info`
- `GET /get-custom-show-info`
- `POST /import-custom-show`
- `GET /get-comprehensive-metrics`
- `GET /get-safety-report`
- `POST /validate-trajectory`
- `POST /deploy-show`
- `GET /get-show-plots`
- `GET /get-show-plots/{filename}`
- `GET /get-custom-show-image`

Canonical routes retained:

- `POST /api/v1/shows/skybrush/import`
- `GET /api/v1/shows/skybrush`
- `GET /api/v1/shows/skybrush/archives/raw`
- `GET /api/v1/shows/skybrush/archives/processed`
- `GET /api/v1/shows/skybrush/metrics`
- `GET /api/v1/shows/skybrush/safety-report`
- `GET /api/v1/shows/skybrush/validation`
- `POST /api/v1/shows/skybrush/deployments`
- `GET /api/v1/shows/skybrush/plots`
- `GET /api/v1/shows/skybrush/plots/{filename}`
- `GET /api/v1/shows/custom`
- `POST /api/v1/shows/custom/import`
- `GET /api/v1/shows/custom/preview`

## Why this slice was safe

- Active caller audit found no live non-test consumers of the retired show aliases in `app/`, `src/`, or `tools/`.
- The shared dashboard resolver still knew about those routes, so that pseudo-compatibility was removed in the same slice.
- Active operator/developer docs were updated so the removed show aliases are no longer advertised as current behavior.

## Additional cleanup included

- schema docstrings in `gcs-server/schemas.py` now point at the canonical show endpoints instead of the retired aliases
- `docs/features/drone-show.md` and `docs/apis/gcs-api-server.md` now describe only the canonical show-management contract

## Validation

Local:

- `python3 -m pytest tests/test_gcs_show_management_routes.py tests/test_gcs_api_http.py::TestShowManagementEndpoints tests/test_api_route_inventory.py -q`
- Result: `24 passed`

Hetzner fresh temp validation checkout:

- backend batch:
  - `24 passed`
- shared frontend route-service Jest:
  - `21 passed`
- production dashboard build:
  - passed

Notes:

- The Hetzner validation used a fresh temp copy cloned from `/root/mavsdk_drone_show_main_candidate_runtime_https`, not the older drifted validation tree.
- The production build still reports that the main bundle is larger than recommended. That is an existing frontend optimization concern, not a contract failure introduced by this slice.

## Next boundary

After this checkpoint, the remaining public GCS legacy families to classify and retire deliberately are:

- origin
- command-control
- versionless Swarm Trajectory
