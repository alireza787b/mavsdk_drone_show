# 2026-04-04 Command Contract Canonicalization

## Objective

Finish the typed command/input-contract slice that remained after the route-shape cleanup, so the current command API is taught, generated, and consumed through one canonical snake_case request envelope instead of mixed-generation field names.

## Scope

- canonicalize the shared command request model on both GCS and drone paths
- keep legacy aliases accepted only at the HTTP validation edge
- migrate active first-party backend, frontend, validator, and mission callers to the canonical request shape
- refresh operator/developer API docs to match the live contract
- revalidate locally and on Hetzner

## Changes

- Tightened the shared request contract in `src/command_contract.py` so the canonical request fields are:
  - `mission_type`
  - `trigger_time`
  - `target_drone_ids`
  - `operator_label`
- Kept legacy command aliases (`missionType`, `triggerTime`, `target_drones`, `targetDrones`, `operatorLabel`) accepted only during request validation instead of continuing to serialize or teach them as the current contract.
- Switched the GCS submit route in `gcs-server/api_routes/commands.py` to serialize canonical snake_case command payloads internally and updated command logging to reflect the canonical field names.
- Normalized the drone command install path in `src/drone_api_server.py` so the typed request model now reaches `drone_communicator.process_command(...)` as canonical snake_case data instead of re-expanding camelCase internally.
- Migrated remaining first-party command producers and helpers to the canonical request shape across:
  - `gcs-server/api_routes/git_status.py`
  - `gcs-server/sar/routes.py`
  - `gcs-server/command_timeout_policy.py`
  - `tools/validate_drone_show_runtime.py`
  - `tools/validate_smart_swarm_runtime.py`
  - `tools/validate_swarm_trajectory_runtime.py`
  - `app/dashboard/drone-dashboard/src/services/gcsApiService.js`
- Refreshed command-facing docs in:
  - `docs/apis/gcs-api-server.md`
  - `docs/apis/drone-api-server.md`
  - `docs/apis/api-modernization-blueprint.md`
- Captured the remaining merge-readiness review debt in the blueprint instead of pretending the API stream is fully done just because field-name drift is fixed.

## Validation

- Local focused regression batch:
  - `python3 -m pytest tests/test_gcs_api_http.py tests/test_gcs_command_routes.py tests/test_command_system.py tests/test_command_processing.py tests/test_drone_api_http.py tests/test_gcs_git_routes.py tests/test_command_timeout_policy.py -q`
  - result: `243 passed, 1 skipped`
- Hetzner focused regression batch:
  - `/root/mavsdk_drone_show_validation/.venv/bin/python -m pytest tests/test_gcs_api_http.py tests/test_gcs_command_routes.py tests/test_command_system.py tests/test_command_processing.py tests/test_drone_api_http.py tests/test_gcs_git_routes.py tests/test_command_timeout_policy.py -q`
  - result: `243 passed, 1 skipped`
- Hetzner frontend shared-service Jest:
  - `CI=true npm test -- --runInBand --watch=false src/services/gcsApiService.test.js`
  - result: `25 passed`
- Hetzner production dashboard build:
  - `npm run build`
  - result: passed

## Outcome

After this slice, command request field-name drift is no longer the main API-modernization debt. The remaining high-signal work is merge-readiness review debt:

- true idempotent submit/replay semantics for command creation
- broader typed request/response cleanup so OpenAPI stays the real contract beyond the cleaned command surface
- standardized machine-readable error/problem envelopes
- dormant auth/security metadata and actor/origin seams for future customer deployments
- continued stream/telemetry metadata tightening for MCP and agent consumers
