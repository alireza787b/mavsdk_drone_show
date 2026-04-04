# 2026-04-04 GCS Error Envelope And Typed Mutations

## Objective

Close the next merge-readiness gap after command-contract cleanup by making the
cleaned GCS FastAPI surface more machine-readable:

- one shared HTTP error envelope for the canonical router families
- typed request models for the remaining high-value mutation routes
- narrower, truthful docs about which subsystem domains still intentionally
  return specialized operation envelopes

## Scope

- add shared GCS FastAPI error helpers and reusable OpenAPI error metadata
- normalize request-validation, `HTTPException`, and uncaught-server failures
  for the cleaned GCS router families
- replace remaining manual JSON parsing with typed request models for:
  - fleet config
  - GCS config stub writes
  - origin compute
  - swarm config save / assignment patch
  - Drone Show deployment
- refresh docs, changelog, and recovery notes
- revalidate locally and on Hetzner

## Changes

- Added `gcs-server/api_errors.py` with:
  - `DEFAULT_ERROR_RESPONSES`
  - `build_error_payload(...)`
  - `normalize_validation_errors(...)`
- Updated `gcs-server/app_fastapi.py` so the cleaned router families now mount
  with shared error-response metadata and common exception handlers for:
  - `RequestValidationError`
  - `HTTPException`
  - uncaught `Exception`
- Deliberately left the `Swarm Trajectory` and `QuickScout / SAR` routers on
  their route-local operation envelopes for now instead of pretending the whole
  GCS surface is already uniform.
- Added typed request/response models in `gcs-server/schemas.py` for:
  - `FleetConfigEntryPayload`
  - `SwarmConfigSaveResponse`
  - `SwarmAssignmentPatchRequest`
  - `SwarmAssignmentUpdateResponse`
  - `ShowDeploymentRequest`
  - `ShowDeploymentResponse`
  - `OriginComputeRequest`
  - `OriginComputeResponse`
  - `GCSConfigUpdateRequest`
- Migrated route handlers off manual `request.json()` parsing in:
  - `gcs-server/api_routes/configuration.py`
  - `gcs-server/api_routes/management.py`
  - `gcs-server/api_routes/origin.py`
  - `gcs-server/api_routes/show_management.py`
  - `gcs-server/api_routes/swarm.py`
- Tightened the canonical swarm-config resource so reads and writes now return
  normalized assignment objects with defaulted `offset_x`, `offset_y`,
  `offset_z`, and `frame` values instead of mixed sparse payload shapes.
- Refreshed:
  - `docs/apis/gcs-api-server.md`
  - `docs/apis/api-modernization-blueprint.md`
  - `CHANGELOG.md`

## Validation

- Local focused regression batch:
  - `python3 -m pytest tests/test_gcs_api_http.py tests/test_gcs_configuration_routes.py tests/test_gcs_management_routes.py tests/test_gcs_origin_routes.py tests/test_gcs_swarm_routes.py tests/test_gcs_show_management_routes.py tests/test_gcs_command_routes.py tests/test_command_system.py tests/test_command_processing.py tests/test_drone_api_http.py tests/test_gcs_git_routes.py tests/test_command_timeout_policy.py -q`
  - result: `275 passed, 1 skipped`
- Hetzner focused regression batch:
  - `/root/mavsdk_drone_show_validation/.venv/bin/python -m pytest tests/test_gcs_api_http.py tests/test_gcs_configuration_routes.py tests/test_gcs_management_routes.py tests/test_gcs_origin_routes.py tests/test_gcs_swarm_routes.py tests/test_gcs_show_management_routes.py tests/test_gcs_command_routes.py tests/test_command_system.py tests/test_command_processing.py tests/test_drone_api_http.py tests/test_gcs_git_routes.py tests/test_command_timeout_policy.py -q`
  - result: `275 passed, 1 skipped`

## Outcome

After this slice, the cleaned GCS HTTP surface is much closer to being a real
typed contract instead of a mix of manual parsing and framework-default error
behavior. The remaining merge-readiness debt is now narrower and explicit:

- normalize the remaining specialized subsystem error envelopes in Swarm
  Trajectory and QuickScout / SAR
- tighten the WebSocket/OpenAPI contract where live stream payloads still drift
- add clearer dormant auth / principal seams around privileged mutations
- continue drone-side error-envelope and typed-stream cleanup so merge readiness
  is end to end rather than GCS-only
