# 2026-04-03 Config/Swarm Legacy Route Retirement

## Scope

This checkpoint retires the remaining GCS configuration and swarm verb-style compatibility routes now that all active dashboard/runtime/tool callers have already moved to the canonical `/api/v1/config/...` surface.

Removed routes:

- `GET /get-config-data`
- `POST /save-config-data`
- `POST /validate-config`
- `GET /get-drone-positions`
- `GET /get-trajectory-first-row`
- `GET /get-swarm-data`
- `POST /save-swarm-data`
- `POST /request-new-leader`

Canonical routes retained:

- `GET /api/v1/config/fleet`
- `PUT /api/v1/config/fleet`
- `POST /api/v1/config/fleet/validation`
- `GET /api/v1/config/fleet/trajectory-start-positions`
- `GET /api/v1/config/fleet/trajectory-start-positions/{pos_id}`
- `GET /api/v1/config/swarm`
- `PUT /api/v1/config/swarm`
- `PATCH /api/v1/config/swarm/assignments/{hw_id}`

## Why this slice was safe

- Active caller audit found no live non-test consumers of the retired GCS config/swarm aliases in `app/`, `src/`, or `tools/`.
- The shared dashboard resolver still knew about those routes, so that pseudo-compatibility was removed in the same slice.
- Active operator/developer docs were updated so the removed routes are no longer advertised as current behavior.

## Additional cleanup included

- `gcs-server/request_logging.py` now classifies canonical `GET /api/v1/config/fleet` as routine success traffic instead of the retired alias.
- Active config/saving comments were updated in:
  - `app/dashboard/drone-dashboard/src/services/logService.js`
  - `app/dashboard/drone-dashboard/src/components/SaveReviewDialog.js`
  - `gcs-server/config.py`
- `docs/configuration_architecture.md` now documents the canonical fleet-config routes and current router module ownership instead of the old `app_fastapi.py` verb-style paths.

## Validation

Local:

- `python3 -m pytest tests/test_gcs_configuration_routes.py tests/test_gcs_swarm_routes.py tests/test_gcs_api_http.py::TestConfigurationEndpoints tests/test_gcs_api_http.py::TestSwarmEndpoints tests/test_gcs_api_http.py::TestErrorHandling tests/test_gcs_api_http.py::TestAPIV1Aliases tests/test_api_route_inventory.py -q`
- Result: `41 passed`

Hetzner fresh temp validation checkout:

- backend batch:
  - `41 passed`
- shared frontend route-service Jest:
  - `21 passed`
- production dashboard build:
  - passed

Notes:

- The Hetzner validation used a fresh temp copy cloned from `/root/mavsdk_drone_show_main_candidate_runtime_https`, not the older drifted validation tree.
- Local frontend Jest was not used for this slice because the recovery repo intentionally avoids heavy local installs; frontend validation ran on Hetzner instead.

## Next boundary

After this checkpoint, the remaining public GCS legacy families to classify and retire deliberately are:

- origin
- show-management
- command-control
- versionless Swarm Trajectory
