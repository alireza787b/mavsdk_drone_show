# 2026-04-04 Command Submit Idempotency

## Objective

Close the remaining replay-safety gap in the cleaned command contract so client/network retries against `POST /api/v1/commands` cannot create duplicate live commands at the GCS layer.

## Scope

- add one canonical replay-safe submit key to the typed command contract
- make command creation atomic across retry/replay paths
- reject conflicting reuse of the same key
- surface replay metadata in typed command responses
- revalidate the touched command/GCS/drone regression surface locally and on Hetzner

## Changes

- Added canonical optional field `idempotency_key` to `SubmitCommandRequest` in `src/command_contract.py`.
- Kept `idempotencyKey`, `client_command_id`, and `clientCommandId` accepted only at the HTTP validation edge for compatibility during migration.
- Added replay-safe tracker primitives in `gcs-server/command_tracker.py`:
  - `CommandCreationResult`
  - `CommandIdempotencyConflictError`
  - `lookup_command_by_idempotency_key(...)`
  - `create_or_replay_command(...)`
- Tracked both `idempotency_key` and a normalized request fingerprint on each `TrackedCommand`, so the tracker can safely distinguish a true retry from an accidental or conflicting resubmission.
- Updated `gcs-server/api_routes/commands.py` so `POST /api/v1/commands` now:
  - returns the original tracked command with `replayed=true` when the same normalized submission is retried
  - returns `409` when the same `idempotency_key` is reused with a different normalized payload
  - includes `idempotency_key` in the submit/status contract
- Expanded command route, HTTP, and tracker tests to cover:
  - idempotent replay
  - conflicting key reuse
  - canonical alias parsing for `idempotency_key`
- Refreshed command-facing API docs and the API-modernization blueprint so the current replay semantics are documented instead of remaining implied by tests only.

## Validation

- Local focused regression batch:
  - `python3 -m pytest tests/test_gcs_api_http.py tests/test_gcs_command_routes.py tests/test_command_system.py tests/test_command_processing.py tests/test_drone_api_http.py tests/test_gcs_git_routes.py tests/test_command_timeout_policy.py -q`
  - result: `249 passed, 1 skipped`
- Hetzner focused regression batch:
  - `/root/mavsdk_drone_show_validation/.venv/bin/python -m pytest tests/test_gcs_api_http.py tests/test_gcs_command_routes.py tests/test_command_system.py tests/test_command_processing.py tests/test_drone_api_http.py tests/test_gcs_git_routes.py tests/test_command_timeout_policy.py -q`
  - result: `249 passed, 1 skipped`

## Outcome

The command surface is now replay-safe for client retries at the GCS boundary. The remaining merge-readiness work is structural rather than route-shape or command-field drift:

- broader typed request/response cleanup for manual-parsing domains
- standardized machine-readable error/problem envelopes
- dormant auth/security seams for future customer deployments
- continued metadata tightening for MCP and agent consumers
