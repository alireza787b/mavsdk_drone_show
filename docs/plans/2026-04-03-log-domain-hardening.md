# 2026-04-03 Logging Domain Hardening

## Goal

Harden the logging subsystem internals and bring the GCS log route contract up to the same typed standard as the rest of the cleaned API without renaming the stable `/api/logs/*` namespace.

## Scope Closed

- hardened the shared logging session layer:
  - session IDs are now validated before path resolution
  - session file paths must resolve inside the configured log directory
  - both GCS and drone-side session access inherit that protection because they both use the shared session helpers
- added typed GCS log-route models for:
  - sources response
  - sessions response
  - session content response
  - frontend report request
  - export request
  - config update request
  - status acknowledgements
- kept the public logging contract stable:
  - `GET /api/logs/sources`
  - `GET /api/logs/sessions`
  - `GET /api/logs/sessions/{session_id}`
  - `GET /api/logs/stream`
  - `POST /api/logs/frontend`
  - `POST /api/logs/export`
  - `POST /api/logs/drone/{drone_id}/export`
  - `GET /api/logs/drone/{drone_id}/sessions`
  - `GET /api/logs/drone/{drone_id}/sessions/{session_id}`
  - `GET /api/logs/drone/{drone_id}/stream`
  - `POST /api/logs/config`
- explicitly treated `/api/logs/*` and `/api/sar/*` as stable subsystem roots instead of forcing `/api/v1/...` aliases in this slice
- added traversal-regression coverage and updated the GCS log-route tests for typed validation behavior

## Validation

- local focused backend/logging batch: `43 passed`
- Hetzner focused backend/logging batch: `43 passed`
- frontend/build impact: none in this slice

## Remaining API Debt

- explicit canonical policy for the remaining GCS WebSocket stream surface:
  - `/ws/telemetry`
  - `/ws/heartbeats`
  - `/ws/git-status`
