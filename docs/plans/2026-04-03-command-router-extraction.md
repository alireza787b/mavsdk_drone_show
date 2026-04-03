# Commands Router Extraction Checkpoint

Date: 2026-04-03
Status: Completed checkpoint
Scope: API modernization phase 3, eighth backend route-domain extraction

## Summary

- extracted the remaining live Commands route surface from `gcs-server/app_fastapi.py` into `gcs-server/api_routes/commands.py`
- preserved the current live routes:
  - `POST /submit_command`
  - `GET /command/{command_id}`
  - `GET /commands/recent`
  - `GET /commands/active`
  - `GET /commands/statistics`
  - `POST /command/{command_id}/cancel`
  - `POST /command/execution-result`
  - `POST /command/execution-start`
- kept the request-time dependency seam on the live `app_fastapi` module object so existing patch-driven tests and future auth/MCP wrappers still target one current surface
- moved the command-only helper logic for target-telemetry lookup and altitude-budget estimation into the extracted router module instead of leaving it as file-local logic inside `app_fastapi.py`
- added focused router-level coverage in `tests/test_gcs_command_routes.py`
- aligned the helper schemas and public GCS API doc with the live command contract

## Root Fixes Included In This Slice

- `POST /submit_command` now returns `400` for malformed JSON request bodies instead of degrading that client error into a generic `500`
- `POST /submit_command` now returns `400` for non-object JSON bodies instead of failing later with generic server errors
- `POST /submit_command` now returns `400` when `target_drones` is not an array-like identifier list
- `POST /submit_command` now returns `400` when an explicit `target_drones` selection matches no configured drones instead of creating an ambiguous zero-target command record
- `SubmitCommandRequest` and `SubmitCommandResponse` metadata now match the live route behavior:
  - `target_drones` may contain hardware IDs or position IDs on input
  - the response always normalizes `target_drones` to hardware IDs
  - legacy `wait_for_ack`, `ack_timeout_ms`, and `pos_ids` fields are explicitly documented as compatibility-only / ignored by the current route

## Design Decision

This slice keeps the legacy command route names intact and does not start canonical `/api/v1/...` renames yet.

The router extraction deliberately preserves the current live command-tracker, dispatch, and ack behavior instead of redesigning it during the move. That keeps the current operational contract stable while removing the last business route block from the GCS monolith.

After this extraction, `gcs-server/app_fastapi.py` no longer contains business `@app.*` route handlers. On the GCS side it is now infrastructure, shared state, compatibility seams, and router mounting only.

## Tests

Local focused validation:

- `python3 -m py_compile gcs-server/app_fastapi.py gcs-server/api_routes/commands.py tests/test_gcs_command_routes.py gcs-server/schemas.py`
- `python3 -m pytest tests/test_gcs_command_routes.py tests/test_gcs_api_http.py::TestCommandEndpoints tests/test_api_route_inventory.py -q`
- result: focused batch passed

Local schema/doc recheck:

- `python3 -m py_compile gcs-server/app_fastapi.py gcs-server/api_routes/commands.py tests/test_gcs_command_routes.py gcs-server/schemas.py`
- `python3 -m pytest tests/test_gcs_command_routes.py tests/test_gcs_api_http.py::TestCommandEndpoints tests/test_command_system.py::TestSchemas::test_submit_command_request tests/test_command_system.py::TestSchemas::test_submit_command_response -q`
- result: `17 passed`

Local full extracted-router backend validation:

- `python3 -m pytest tests/test_gcs_command_routes.py tests/test_gcs_swarm_trajectory_routes.py tests/test_gcs_show_management_routes.py tests/test_gcs_management_routes.py tests/test_gcs_static_assets_routes.py tests/test_gcs_origin_routes.py tests/test_gcs_git_routes.py tests/test_gcs_configuration_routes.py tests/test_gcs_swarm_routes.py tests/test_gcs_core_routes.py tests/test_gcs_api_http.py tests/test_gcs_api_websocket.py tests/test_api_route_inventory.py -q`
- result: `112 passed, 7 skipped`

Hetzner validation checkout: `/root/mavsdk_drone_show_validation`

- `/root/mavsdk_drone_show_validation/.venv/bin/python -m py_compile gcs-server/app_fastapi.py gcs-server/api_routes/commands.py tests/test_gcs_command_routes.py gcs-server/schemas.py`
- `/root/mavsdk_drone_show_validation/.venv/bin/python -m pytest tests/test_gcs_command_routes.py tests/test_gcs_swarm_trajectory_routes.py tests/test_gcs_show_management_routes.py tests/test_gcs_management_routes.py tests/test_gcs_static_assets_routes.py tests/test_gcs_origin_routes.py tests/test_gcs_git_routes.py tests/test_gcs_configuration_routes.py tests/test_gcs_swarm_routes.py tests/test_gcs_core_routes.py tests/test_gcs_api_http.py tests/test_gcs_api_websocket.py tests/test_api_route_inventory.py -q`
- result: `112 passed, 7 skipped`

Hetzner frontend build:

- `source ~/.nvm/nvm.sh && cd /root/mavsdk_drone_show_validation/app/dashboard/drone-dashboard && npm run build`
- result: compiled successfully

## Files

- updated: `CHANGELOG.md`
- updated: `docs/apis/api-modernization-blueprint.md`
- updated: `docs/apis/gcs-api-server.md`
- updated: `gcs-server/app_fastapi.py`
- updated: `gcs-server/schemas.py`
- updated: `tests/test_gcs_api_http.py`
- added: `gcs-server/api_routes/commands.py`
- added: `tests/test_gcs_command_routes.py`

## Next

- start Phase 4 canonical `/api/v1/...` migration against the now-extracted GCS route domains
- keep the drone-side monolith extraction as a separate follow-on Phase 3 track after the GCS contract migration is stable
