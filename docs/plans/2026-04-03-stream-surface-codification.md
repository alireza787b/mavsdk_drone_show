# 2026-04-03 Stream Surface Codification

## Objective

Close the last open GCS API-surface policy question by making the remaining WebSocket stream endpoints explicit canonical transport roots instead of leaving them as versionless leftovers with only implicit status.

## Scope

- codify the intended status of:
  - `WS /ws/telemetry`
  - `WS /ws/heartbeats`
  - `WS /ws/git-status`
- add one shared backend constant surface for those transport routes
- add one shared frontend URL-builder surface for those transport routes
- align operator/developer API docs with the explicit transport-root policy

## Changes

- Added shared WebSocket route constants in `src/gcs_api_routes.py`:
  - `GCS_WS_TELEMETRY_ROUTE`
  - `GCS_WS_HEARTBEATS_ROUTE`
  - `GCS_WS_GIT_STATUS_ROUTE`
- Added shared frontend WebSocket helpers in `app/dashboard/drone-dashboard/src/services/gcsApiService.js`:
  - `GCS_WS_ROUTES`
  - `buildGcsWebSocketUrl(...)`
  - `buildTelemetryWebSocketUrl()`
  - `buildHeartbeatWebSocketUrl()`
  - `buildGitStatusWebSocketUrl()`
- Added focused Jest coverage in `app/dashboard/drone-dashboard/src/services/gcsApiService.test.js` for:
  - canonical route derivation from the configured backend base URL
  - `https://` to `wss://` protocol promotion
  - pass-through of already-absolute WebSocket URLs
- Updated API docs to classify:
  - `/api/logs/*` and `/api/sar/*` as stable subsystem roots
  - `/ws/telemetry`, `/ws/heartbeats`, and `/ws/git-status` as canonical transport roots

## Validation

- Hetzner focused frontend service Jest:
  - `CI=true npm test -- --runInBand --watch=false src/services/gcsApiService.test.js`
  - result: `1 suite passed, 24 tests passed`
- Hetzner dashboard production build:
  - `npm run build`
  - result: passed

## Outcome

After this slice, the public GCS API contract no longer has unresolved route-shape ambiguity:

- canonical HTTP resource/mutation routes live under `/api/v1/...`
- `/api/logs/*` and `/api/sar/*` are stable subsystem roots
- `/ws/telemetry`, `/ws/heartbeats`, and `/ws/git-status` are canonical transport roots

The next best work is no longer more GCS route-surface cleanup. It is repeatable SITL/API regression coverage on top of the cleaned contract, plus any later drone-side internal router extraction if maintainability work is prioritized.
