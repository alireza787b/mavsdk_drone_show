# Canonical Command V1 Checkpoint

Date: 2026-04-03
Status: Completed checkpoint
Scope: API modernization phase 4, first GCS canonical route-migration slice

## Summary

- introduced canonical v1 aliases for the extracted Commands domain:
  - `POST /api/v1/commands`
  - `GET /api/v1/commands/{command_id}`
  - `GET /api/v1/commands/recent`
  - `GET /api/v1/commands/active`
  - `GET /api/v1/commands/statistics`
  - `POST /api/v1/commands/{command_id}/cancel`
  - `POST /api/v1/command-reports/execution-start`
  - `POST /api/v1/command-reports/execution-result`
- kept the legacy command routes mounted as compatibility aliases:
  - `POST /submit_command`
  - `GET /command/{command_id}`
  - `GET /commands/recent`
  - `GET /commands/active`
  - `GET /commands/statistics`
  - `POST /command/{command_id}/cancel`
  - `POST /command/execution-start`
  - `POST /command/execution-result`
- migrated the shared frontend GCS service layer onto the canonical v1 command submit/status/recent/active paths
- updated request logging so canonical v1 command monitoring and callback traffic is classified consistently with the legacy command polling paths
- refreshed the public GCS API doc to present the canonical command surface first

## Design Decision

This slice uses `POST /api/v1/commands` for command submission, but it keeps the collection read path as `GET /api/v1/commands/recent` instead of overloading `GET /api/v1/commands`.

That is deliberate. The current frontend route-key layer and request-log classifier are path-oriented rather than method-aware. Reusing the same path for both submit and recent-list traffic would have created ambiguous semantic keys and noisier logging behavior in the middle of migration.

The separate canonical callback namespace under `/api/v1/command-reports/*` is also intentional. It keeps operator command control under `/api/v1/commands/...` while separating drone-to-GCS execution evidence into a machine-readable report channel that will be easier to expose cleanly through future MCP or auth policy layers.

## Root Fixes Included In This Slice

- the shared frontend command service no longer points at legacy `/submit_command`, `/command/{id}`, `/commands/recent`, or `/commands/active`
- route inventory and alias-identity tests now enforce the canonical v1 command aliases alongside the legacy compatibility paths
- request logging now recognizes the canonical command monitor/callback paths, so successful v1 monitoring traffic remains `DEBUG` instead of being promoted as operator noise
- the fail-closed cancel endpoint message now points callers at `POST /api/v1/commands` as the canonical live cancellation submission path, with the legacy route called out explicitly

## Tests

Local validation:

- `python3 -m py_compile gcs-server/api_routes/commands.py gcs-server/app_fastapi.py gcs-server/request_logging.py tests/test_gcs_command_routes.py tests/test_api_route_inventory.py tests/test_gcs_api_http.py tests/test_request_logging.py`
- `python3 -m pytest tests/test_gcs_command_routes.py tests/test_api_route_inventory.py tests/test_gcs_api_http.py::TestAPIV1Aliases tests/test_request_logging.py -q`
- result: `20 passed`

Local frontend note:

- `CI=true npm test -- --runInBand --watch=false src/services/gcsApiService.test.js`
- result: not runnable in the clean recovery checkout because `react-scripts` is not installed there; frontend validation for this slice was run on Hetzner instead of installing heavy dependencies locally

Hetzner validation checkout: `/root/mavsdk_drone_show_validation`

- `/root/mavsdk_drone_show_validation/.venv/bin/python -m py_compile gcs-server/api_routes/commands.py gcs-server/app_fastapi.py gcs-server/request_logging.py tests/test_gcs_command_routes.py tests/test_api_route_inventory.py tests/test_gcs_api_http.py tests/test_request_logging.py`
- `/root/mavsdk_drone_show_validation/.venv/bin/python -m pytest tests/test_gcs_command_routes.py tests/test_api_route_inventory.py tests/test_gcs_api_http.py::TestAPIV1Aliases tests/test_request_logging.py -q`
- result: `20 passed`
- `source ~/.nvm/nvm.sh && cd /root/mavsdk_drone_show_validation/app/dashboard/drone-dashboard && CI=true npm test -- --runInBand --watch=false src/services/gcsApiService.test.js && npm run build`
- result: frontend service test passed and production build compiled successfully

## Files

- updated: `CHANGELOG.md`
- updated: `docs/apis/api-modernization-blueprint.md`
- updated: `docs/apis/gcs-api-server.md`
- updated: `gcs-server/api_routes/commands.py`
- updated: `gcs-server/request_logging.py`
- updated: `app/dashboard/drone-dashboard/src/services/gcsApiService.js`
- updated: `app/dashboard/drone-dashboard/src/services/gcsApiService.test.js`
- updated: `tests/test_api_route_inventory.py`
- updated: `tests/test_gcs_api_http.py`
- updated: `tests/test_gcs_command_routes.py`
- updated: `tests/test_request_logging.py`

## Next

- migrate the configuration family next:
  - fleet config first
  - swarm config / assignment second
  - origin after that
- keep legacy compatibility aliases until frontend callers, runtime tooling, and SITL validation flows are migrated and reconfirmed
