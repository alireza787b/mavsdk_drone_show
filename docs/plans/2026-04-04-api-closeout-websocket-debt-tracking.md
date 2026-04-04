# 2026-04-04 API Closeout: WebSocket Contracts and Deferred Debt

## Scope

This checkpoint closes the active API modernization stream for now without
pretending every future API concern is complete. The goal is:

- remove the last low-risk contract drift still hiding inside the cleaned API
- document the remaining work as explicit deferred follow-up instead of hidden debt
- freeze the standards that future API additions must follow

## What Changed

- fixed `WS /ws/heartbeats` so it now streams the normalized heartbeat list
  contract instead of the raw internal heartbeat map
- replaced the old skipped GCS websocket suite with deterministic route-level
  tests for telemetry, heartbeat, and git-status streams
- corrected GCS websocket docs so the examples match the live contracts
- corrected drone websocket docs so they describe the current one-way stream
  honestly and document the no-state sentinel payload
- updated the modernization blueprint so future API work has one explicit ruleset
  and one explicit deferred-follow-up list

## Deferred Follow-Ups

These are intentionally deferred, not forgotten:

- QuickScout / SAR typed success-surface and OpenAPI cleanup
  - Defer until QuickScout mission behavior and UI workflows are more mature.
- Drone websocket event-envelope redesign
  - Current `WS /ws/drone-state` is kept as a one-way state/error stream.
  - Revisit only when a real first-party consumer needs richer event metadata.
- Dormant auth / principal seams
  - Keep auth disabled for current dev/demo workflows.
  - Revisit after the next SITL/system-validation gate and concrete customer auth requirements.

## Rules Going Forward

- New public HTTP business routes go under `/api/v1/...`.
- `/api/logs/*`, `/api/sar/*`, and `/ws/*` remain the only current stable-root exceptions.
- New request and response bodies should be typed whenever practical.
- First-party callers, docs, tests, and route inventory must be updated in the same slice.
- Temporary compatibility aliases must be called out explicitly with a retirement reason.
- Future MCP / AI-agent-facing work must preserve stable IDs, timestamps, actor context, and machine-readable error details.

## Validation

Local focused websocket batch:

- `python3 -m pytest --no-cov tests/test_gcs_api_websocket.py tests/test_gcs_core_routes.py tests/test_gcs_git_routes.py tests/test_drone_api_websocket.py -q`
- result: `19 passed`

Hetzner clean-sync validation:

- checkout: `/root/mavsdk_drone_show_main_candidate_clean_sync`
- `/root/mavsdk_drone_show_validation/.venv/bin/python -m pytest --no-cov tests/test_gcs_api_websocket.py tests/test_gcs_core_routes.py tests/test_gcs_git_routes.py tests/test_drone_api_websocket.py -q`
- result: `19 passed`

## Merge Status

- This closes the active API modernization phase on `main-candidate`.
- It does **not** imply immediate merge to `main`.
- The next major gate before merge is the planned systematic SITL regression pass on top of the cleaned API surface.
