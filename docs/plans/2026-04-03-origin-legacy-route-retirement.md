# 2026-04-03 Origin Legacy Route Retirement

## Scope

This checkpoint retires the remaining GCS origin compatibility routes now that all active dashboard callers, runtime flows, and SITL validation helpers use the canonical `/api/v1/origin...` and `/api/v1/navigation/global-origin` surface.

Removed routes:

- `GET /get-origin`
- `POST /set-origin`
- `GET /get-gps-global-origin`
- `GET /elevation`
- `GET /get-origin-for-drone`
- `GET /get-position-deviations`
- `POST /compute-origin`
- `GET /get-desired-launch-positions`

Canonical routes retained:

- `GET /api/v1/origin`
- `PUT /api/v1/origin`
- `GET /api/v1/navigation/global-origin`
- `GET /api/v1/origin/elevation`
- `GET /api/v1/origin/bootstrap`
- `GET /api/v1/origin/deviations`
- `POST /api/v1/origin/compute`
- `GET /api/v1/origin/launch-positions`

## Why this slice was safe

- Active caller audit found no live non-test consumers of the retired origin aliases in `app/`, `src/`, or `tools/`.
- The dashboard shared GCS route service and the runtime tooling already used the canonical origin surface.
- The remaining legacy references were concentrated in backend compatibility decorators, the shared dashboard route resolver, request-log classification, and active docs/tests, so this slice could remove them together without changing live operator behavior.

## Additional cleanup included

- `gcs-server/request_logging.py` now treats `GET /api/v1/origin` as the routine success path instead of the retired `GET /get-origin`.
- `gcs-server/schemas.py` origin schema docstrings now point at the canonical origin resources.
- `docs/apis/gcs-api-server.md`, `docs/features/origin-system.md`, `docs/features/drone-show.md`, and `docs/guides/sitl-comprehensive.md` now describe the canonical origin surface only.

## Validation

Local:

- `python3 -m pytest tests/test_gcs_origin_routes.py tests/test_gcs_api_http.py::TestOriginEndpoints tests/test_gcs_api_http.py::TestShowManagementEndpoints::test_get_position_deviations_supports_string_hw_id_telemetry_keys tests/test_api_route_inventory.py tests/test_request_logging.py -q`
- Result: `25 passed`

Hetzner fresh temp validation checkout:

- backend batch:
  - same focused pytest batch
  - Result: `25 passed`
- shared frontend route-service Jest:
  - `CI=true npm test -- --runInBand --watch=false src/services/gcsApiService.test.js`
  - Result: `21 passed`
- production dashboard build:
  - `npm run build`
  - Result: passed

## Next boundary

After this checkpoint, the remaining public GCS legacy family to retire deliberately is:

- versionless Swarm Trajectory
