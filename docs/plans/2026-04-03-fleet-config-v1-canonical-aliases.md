# Canonical Fleet Config V1 Checkpoint

Date: 2026-04-03
Status: Completed checkpoint
Scope: API modernization phase 4, second GCS canonical route-migration slice

## Summary

- introduced canonical v1 aliases for the fleet configuration surface:
  - `GET /api/v1/config/fleet`
  - `PUT /api/v1/config/fleet`
  - `POST /api/v1/config/fleet/validation`
  - `GET /api/v1/config/fleet/trajectory-start-positions`
  - `GET /api/v1/config/fleet/trajectory-start-positions/{pos_id}`
- kept the legacy compatibility routes mounted:
  - `GET /get-config-data`
  - `POST /save-config-data`
  - `POST /validate-config`
  - `GET /get-drone-positions`
  - `GET /get-trajectory-first-row?pos_id=...`
- migrated the shared frontend GCS service layer onto the canonical fleet-config resource paths
- updated Mission Config trajectory-position hydration so it accepts canonical `x` / `y` and legacy `north` / `east`

## Design Decision

This slice keeps `GET` and `PUT` on the same canonical fleet-config resource path, `/api/v1/config/fleet`, because configuration is a stable resource, not two unrelated operations.

The canonical per-position trajectory-start route uses `x` / `y` on purpose. The collection endpoint for all trajectory start positions already returns `x` / `y`, and the frontend stores those values as `x` / `y`. The old single-position route was the inconsistent outlier using `north` / `east`. The canonical contract removes that drift while leaving the legacy route untouched for compatibility.

## Root Fixes Included In This Slice

- the frontend config service now uses `PUT /api/v1/config/fleet` instead of the legacy `POST /save-config-data`
- the frontend per-slot trajectory-start lookup now uses the canonical path-parameter form instead of the legacy query-string route
- the canonical single-position trajectory-start response now matches the collection route with `x` / `y`, eliminating the mixed axis naming for the same config-derived concept
- route inventory and alias identity tests now enforce the canonical fleet-config surface alongside the legacy compatibility routes

## Tests

Local validation:

- `python3 -m py_compile gcs-server/api_routes/configuration.py tests/test_gcs_configuration_routes.py`
- `python3 -m pytest tests/test_gcs_configuration_routes.py tests/test_gcs_api_http.py::TestConfigurationEndpoints tests/test_gcs_api_http.py::TestAPIV1Aliases tests/test_api_route_inventory.py tests/test_request_logging.py -q`
- result: `27 passed`

Hetzner validation checkout: `/root/mavsdk_drone_show_validation`

- `/root/mavsdk_drone_show_validation/.venv/bin/python -m py_compile gcs-server/api_routes/configuration.py tests/test_gcs_configuration_routes.py tests/test_api_route_inventory.py tests/test_gcs_api_http.py`
- `/root/mavsdk_drone_show_validation/.venv/bin/python -m pytest tests/test_gcs_configuration_routes.py tests/test_gcs_api_http.py::TestConfigurationEndpoints tests/test_gcs_api_http.py::TestAPIV1Aliases tests/test_api_route_inventory.py tests/test_request_logging.py -q`
- result: `27 passed`
- `source ~/.nvm/nvm.sh && cd /root/mavsdk_drone_show_validation/app/dashboard/drone-dashboard && CI=true npm test -- --runInBand --watch=false src/services/gcsApiService.test.js`
- result: `12 passed`
- `source ~/.nvm/nvm.sh && cd /root/mavsdk_drone_show_validation/app/dashboard/drone-dashboard && npm run build`
- result: compiled successfully

## Files

- updated: `CHANGELOG.md`
- updated: `docs/apis/api-modernization-blueprint.md`
- updated: `docs/apis/gcs-api-server.md`
- updated: `gcs-server/api_routes/configuration.py`
- updated: `app/dashboard/drone-dashboard/src/services/gcsApiService.js`
- updated: `app/dashboard/drone-dashboard/src/services/gcsApiService.test.js`
- updated: `app/dashboard/drone-dashboard/src/pages/MissionConfig.js`
- updated: `tests/test_api_route_inventory.py`
- updated: `tests/test_gcs_api_http.py`
- updated: `tests/test_gcs_configuration_routes.py`

## Next

- canonicalize swarm configuration and single-assignment mutation next
- then move to origin after the configuration family semantics are stable and documented
