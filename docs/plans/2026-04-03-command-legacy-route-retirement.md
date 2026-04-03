# 2026-04-03 Command Legacy Route Retirement

## Scope

This checkpoint retires the remaining GCS command-control compatibility routes now that all active dashboard callers, runtime flows, and SITL validation helpers use the canonical `/api/v1/commands...` and `/api/v1/command-reports/...` surface.

Removed routes:

- `POST /submit_command`
- `GET /command/{command_id}`
- `GET /commands/recent`
- `GET /commands/active`
- `GET /commands/statistics`
- `POST /command/{command_id}/cancel`
- `POST /command/execution-start`
- `POST /command/execution-result`

Canonical routes retained:

- `POST /api/v1/commands`
- `GET /api/v1/commands/{command_id}`
- `GET /api/v1/commands/recent`
- `GET /api/v1/commands/active`
- `GET /api/v1/commands/statistics`
- `POST /api/v1/commands/{command_id}/cancel`
- `POST /api/v1/command-reports/execution-start`
- `POST /api/v1/command-reports/execution-result`

## Why this slice was safe

- Active caller audit found no live non-test consumers of the retired command aliases in `app/`, `src/`, or `tools/`.
- The repeatable SITL/runtime helpers already submit and track commands through the canonical `/api/v1/commands` family.
- The remaining legacy references were concentrated in backend compatibility decorators, the shared dashboard route resolver, request-log classification, and docs/tests, so this slice could remove them together without changing live operator behavior.

## Additional cleanup included

- `gcs-server/request_logging.py` no longer treats retired command aliases as routine success paths.
- `gcs-server/schemas.py` command schema docstrings now point at the canonical command resource.
- `docs/apis/gcs-api-server.md` and `docs/features/swarm-trajectory.md` now describe only the canonical command-control surface.

## Validation

Local:

- `python3 -m pytest tests/test_gcs_command_routes.py tests/test_gcs_api_http.py::TestCommandEndpoints tests/test_api_route_inventory.py tests/test_request_logging.py -q`
- Result: `22 passed`

Hetzner fresh temp validation checkout:

- backend batch:
  - same focused pytest batch
  - Result: `22 passed`
- shared frontend route-service Jest:
  - `CI=true npm test -- --runInBand --watch=false src/services/gcsApiService.test.js`
  - Result: `21 passed`
- production dashboard build:
  - `npm run build`
  - Result: passed

Notes:

- Validation used a fresh temp checkout cloned from `/root/mavsdk_drone_show_main_candidate_runtime_https`.
- The initial Hetzner sync attempt accidentally flattened files into the temp checkout root; the final validation was rerun on a new clean temp checkout after correcting the sync method with relative-path preservation.

## Next boundary

After this checkpoint, the remaining public GCS legacy families to retire deliberately are:

- origin
- versionless Swarm Trajectory
